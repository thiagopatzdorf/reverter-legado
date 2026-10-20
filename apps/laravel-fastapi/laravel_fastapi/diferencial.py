"""Avaliador diferencial: o mesmo cenário no Laravel original e no FastAPI gerado.

Os dois lados começam de cópias idênticas do mesmo banco semeado. Cada passo do
cenário vai aos dois; compara-se status, corpo JSON e o efeito no banco (todas as
tabelas, linhas ordenadas). Só os campos voláteis declarados no contrato são
normalizados, e mesmo eles têm o formato conferido: uma data vira "<data>" só
se tiver cara de data nos dois lados.

Placar: um endpoint (rota do contrato) "responde igual" quando todos os passos
que o exercitam bateram. Só biblioteca padrão: roda em qualquer máquina com
Python 3, sem instalar nada.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request

DATA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
TABELAS_IGNORADAS = {"migrations", "sqlite_sequence"}


# --------------------------------------------------------------------------- HTTP
def enviar(base: str, passo: dict, fichas: dict, tempo=30) -> dict:
    caminho = passo["caminho"]
    headers = {"Accept": "application/json"}
    headers.update(passo.get("headers", {}))
    corpo = None
    if "corpo" in passo:
        corpo = json.dumps(passo["corpo"]).encode()
        headers["Content-Type"] = "application/json"
    if passo.get("ficha"):
        valor = fichas.get(passo["ficha"])
        headers["Authorization"] = f"Token {valor if valor is not None else 'ficha-ausente'}"
    req = urllib.request.Request(base.rstrip("/") + caminho, data=corpo, method=passo["metodo"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r:
            status, bruto, tipo = r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status, bruto, tipo = e.code, e.read(), e.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return {"status": None, "erro": str(e)}
    try:
        json_ = json.loads(bruto.decode("utf-8")) if bruto else None
        eh_json = True
    except (ValueError, UnicodeDecodeError):
        json_, eh_json = bruto[:200].decode("utf-8", "replace"), False
    return {"status": status, "json": json_, "eh_json": eh_json, "tipo": tipo.split(";")[0]}


def pegar(dados, caminho: str):
    for parte in caminho.split("."):
        if isinstance(dados, dict):
            dados = dados.get(parte)
        elif isinstance(dados, list) and parte.isdigit() and int(parte) < len(dados):
            dados = dados[int(parte)]
        else:
            return None
    return dados


# --------------------------------------------------------------------------- normalização
def normalizar(valor, volateis: set):
    if isinstance(valor, dict):
        return {k: (_volatil(v) if k in volateis else normalizar(v, volateis)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [normalizar(v, volateis) for v in valor]
    return valor


def _volatil(v):
    if v is None:
        return None
    if isinstance(v, str) and DATA.match(v):
        return "<data>"
    if isinstance(v, str):
        return "<texto>"
    return f"<{type(v).__name__}>"


def foto_banco(caminho: str, colunas_volateis: set) -> dict:
    """Todas as tabelas, linhas ordenadas; coluna volátil vira só "presente/nula"."""
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        saida = {}
        tabelas = [r[0] for r in con.execute("select name from sqlite_master where type='table' order by name")]
        for t in tabelas:
            if t in TABELAS_IGNORADAS:
                continue
            cur = con.execute(f'select * from "{t}"')
            cols = [d[0] for d in cur.description]
            linhas = []
            for r in cur.fetchall():
                linha = {c: (("<presente>" if v is not None else None) if c in colunas_volateis else v) for c, v in zip(cols, r)}
                linhas.append(json.dumps(linha, sort_keys=True, default=str))
            saida[t] = sorted(linhas)
        return saida
    finally:
        con.close()


def diferenca_banco(a: dict, b: dict) -> list[str]:
    difs = []
    for t in sorted(set(a) | set(b)):
        la, lb = a.get(t), b.get(t)
        if la is None or lb is None:
            difs.append(f"tabela {t} só existe de um lado")
        elif la != lb:
            so_a = [x for x in la if x not in lb]
            so_b = [x for x in lb if x not in la]
            difs.append(f"{t}: {len(so_a)} linha(s) só no Laravel, {len(so_b)} só no FastAPI"
                        + (f"; ex. Laravel {so_a[0][:160]}" if so_a else "") + (f"; ex. FastAPI {so_b[0][:160]}" if so_b else ""))
    return difs


def diferenca_json(a, b, caminho="$", saida=None, limite=5) -> list[str]:
    saida = [] if saida is None else saida
    if len(saida) >= limite:
        return saida
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        saida.append(f"{caminho}: {json.dumps(a, ensure_ascii=False)[:80]} != {json.dumps(b, ensure_ascii=False)[:80]}")
    elif isinstance(a, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in b:
                saida.append(f"{caminho}.{k}: só no Laravel")
            elif k not in a:
                saida.append(f"{caminho}.{k}: só no FastAPI")
            else:
                diferenca_json(a[k], b[k], f"{caminho}.{k}", saida, limite)
    elif isinstance(a, list):
        if len(a) != len(b):
            saida.append(f"{caminho}: {len(a)} itens != {len(b)} itens")
        for i, (x, y) in enumerate(zip(a, b)):
            diferenca_json(x, y, f"{caminho}[{i}]", saida, limite)
    elif a != b:
        saida.append(f"{caminho}: {json.dumps(a, ensure_ascii=False)[:80]} != {json.dumps(b, ensure_ascii=False)[:80]}")
    return saida


# --------------------------------------------------------------------------- execução
def rodar(cenario: dict, contrato_volateis: dict, laravel: dict, fastapi: dict, pausa=1.1, registro=None) -> dict:
    """`laravel`/`fastapi`: {"base": URL, "banco": caminho do SQLite daquele lado}."""
    vol_resp = set(contrato_volateis.get("resposta", [])) | set(cenario.get("volateis_extra", []))
    vol_col = set(contrato_volateis.get("colunas", []))
    fichas = {"laravel": {}, "fastapi": {}}
    passos = []
    for passo in cenario["passos"]:
        inicio = time.monotonic()
        ra = enviar(laravel["base"], passo, fichas["laravel"])
        rb = enviar(fastapi["base"], passo, fichas["fastapi"])
        for nome, caminho in passo.get("capturar", {}).items():
            fichas["laravel"][nome] = pegar(ra.get("json"), caminho)
            fichas["fastapi"][nome] = pegar(rb.get("json"), caminho)
        motivos = []
        if ra.get("status") != rb.get("status"):
            motivos.append(f"status {ra.get('status')} != {rb.get('status')}")
        ja = normalizar(ra.get("json"), vol_resp)
        jb = normalizar(rb.get("json"), vol_resp)
        if ra.get("eh_json") != rb.get("eh_json"):
            motivos.append("um lado respondeu JSON e o outro não")
        elif ja != jb:
            motivos += ["corpo " + d for d in diferenca_json(ja, jb)]
        fa = foto_banco(laravel["banco"], vol_col)
        fb = foto_banco(fastapi["banco"], vol_col)
        motivos += ["banco " + d for d in diferenca_banco(fa, fb)]
        item = {"id": passo["id"], "rota": passo["rota"], "pedido": f"{passo['metodo']} {passo['caminho']}",
                "status": [ra.get("status"), rb.get("status")], "igual": not motivos, "motivos": motivos}
        passos.append(item)
        if registro:
            registro(item)
        resto = pausa - (time.monotonic() - inicio)
        if resto > 0:
            time.sleep(resto)
    return placar(passos, cenario)


def placar(passos: list, cenario: dict) -> dict:
    """X de Y: Y são as rotas do contrato; passo de framework (404, 405) fica à parte."""
    rotas = list(cenario.get("rotas", []))
    por_rota: dict[str, dict] = {r: {"passos": 0, "iguais": 0, "motivos": []} for r in rotas}
    fora: dict[str, dict] = {}
    for p in passos:
        alvo = por_rota if p["rota"] in por_rota else fora
        r = alvo.setdefault(p["rota"], {"passos": 0, "iguais": 0, "motivos": []})
        r["passos"] += 1
        r["iguais"] += int(p["igual"])
        r["motivos"] += [f"{p['id']}: {m}" for m in p["motivos"]]
    iguais = [k for k, v in por_rota.items() if v["passos"] and v["iguais"] == v["passos"]]
    return {
        "endpoints": len(rotas), "endpoints_exercitados": sum(1 for v in por_rota.values() if v["passos"]),
        "endpoints_iguais": len(iguais),
        "passos": len(passos), "passos_iguais": sum(p["igual"] for p in passos),
        "por_endpoint": {k: {"igual": k in iguais, **v} for k, v in sorted(por_rota.items())},
        "fora_do_contrato": {k: {"igual": v["iguais"] == v["passos"], **v} for k, v in sorted(fora.items())},
        "por_passo": passos,
    }


def esquema_sqlite(caminho: str) -> dict:
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        saida = {}
        for (t,) in con.execute("select name from sqlite_master where type='table' order by name"):
            if t in TABELAS_IGNORADAS:
                continue
            cols = con.execute(f'pragma table_info("{t}")').fetchall()
            saida[t] = {c[1]: {"nulo": not c[3], "pk": bool(c[5])} for c in cols}
        return saida
    finally:
        con.close()


def comparar_esquema(laravel: str, gerado: str) -> dict:
    """Banco que o Laravel migrou × banco que o SQLAlchemy gerado cria: colunas, nulo, chave."""
    a, b = esquema_sqlite(laravel), esquema_sqlite(gerado)
    difs = []
    for t in sorted(set(a) | set(b)):
        if t not in a or t not in b:
            difs.append(f"tabela {t} só {'no Laravel' if t in a else 'no gerado'}")
            continue
        for c in sorted(set(a[t]) | set(b[t])):
            if a[t].get(c) != b[t].get(c):
                difs.append(f"{t}.{c}: {a[t].get(c)} != {b[t].get(c)}")
    colunas = sum(len(x) for x in a.values())
    return {"tabelas": len(a), "colunas": colunas, "diferencas": difs}
