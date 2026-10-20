"""Contrato -> projeto FastAPI que roda sozinho.

Arquivos gerados (todos a partir do contrato; o fonte PHP não é lido aqui):

    main.py            app FastAPI: monta o runtime e inclui as rotas
    rotas.py           uma função por rota, middleware como Depends
    modelos.py         SQLAlchemy (Table) de cada tabela das migrations
    validacoes.py      Pydantic de cada FormRequest com regras literais (vai para o OpenAPI)
    app_traduzido.py   as classes do app traduzidas (controllers, models, resources...)
    config_app.py      config/*.php, cada chave avaliada sozinha
    dados.py           rotas, traduções, middleware, políticas e voláteis do contrato
    laravel_compat/    o runtime (cópia), para o app não depender deste repositório
    cobertura.json     por rota: coberta ou não, e o porquê

"Coberta" quer dizer: tudo que a rota alcança pelo nome (controller, FormRequest,
resource, model, middleware, providers, handler) traduziu sem pendência
bloqueante. É estimativa estática; quem diz se responde igual é o diferencial.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import laravel_compat as lv

from . import php as _php
from .transpilar import ENTRADAS_FRAMEWORK, Transpilador, py_metodo

RUNTIME = Path(__file__).resolve().parent / "runtime" / "laravel_compat"
# Problema que não impede a rota de responder: o trecho só roda num caminho que a API não usa.
AVISOS = {"traco_sem_traducao"}
TIPOS_SA = {"bigint": "sa.BigInteger", "integer": "sa.Integer", "string": "sa.String", "text": "sa.Text",
            "boolean": "sa.Boolean", "datetime": "sa.DateTime", "date": "sa.Date", "time": "sa.Time",
            "json": "sa.JSON", "decimal": "sa.Numeric", "float": "sa.Float", "binary": "sa.LargeBinary"}
REQUIREMENTS = """fastapi==0.149.0
starlette==1.9.0
pydantic==2.14.1
SQLAlchemy==2.1.5
uvicorn==0.54.0
bcrypt==5.0.0
regex==2026.9.29
"""


def _ident(nome: str) -> str:
    s = re.sub(r"\W", "_", nome)
    return s if not s[:1].isdigit() else "_" + s


# --------------------------------------------------------------------------- modelos
def modelos_py(contrato: dict) -> str:
    linhas = ['"""Tabelas do banco, das migrations do app (gerado)."""', "import sqlalchemy as sa", "",
              "metadata = sa.MetaData()", ""]
    for nome, t in sorted(contrato["tabelas"].items()):
        cols = []
        auto = False
        for c in t["colunas"]:
            tipo = TIPOS_SA.get(c["tipo"], "sa.String")
            if c.get("auto"):
                tipo, auto = "sa.Integer", True
            elif c["tipo"] == "string" and c.get("tamanho"):
                tipo += f"({c['tamanho']})"
            args = [repr(c["nome"]), tipo]
            ref = c.get("ref")
            if ref and ref.get("tabela"):
                ao_apagar = (ref.get("ao_apagar") or "").upper() or None
                args.append(f"sa.ForeignKey({(ref['tabela'] + '.' + (ref.get('coluna') or 'id'))!r}"
                            + (f", ondelete={ao_apagar!r})" if ao_apagar else ")"))
            kw = []
            if c.get("primaria"):
                kw.append("primary_key=True")
                if c.get("auto"):
                    kw.append("autoincrement=True")
            else:
                kw.append(f"nullable={bool(c.get('nulo'))}")
            if "padrao" in c and c["padrao"] is not None:
                padrao = c["padrao"]
                texto = "'" + padrao.replace("'", "''") + "'" if isinstance(padrao, str) else str(int(padrao) if isinstance(padrao, bool) else padrao)
                kw.append(f"server_default=sa.text({texto!r})")
            cols.append(f"    sa.Column({', '.join(args + kw)}),")
        for u in t.get("unicos", []):
            cols.append(f"    sa.UniqueConstraint({', '.join(repr(x) for x in u)}),")
        if t.get("primaria"):
            cols.append(f"    sa.PrimaryKeyConstraint({', '.join(repr(x) for x in t['primaria'])}),")
        # sqlite_autoincrement: o Laravel cria "integer primary key autoincrement".
        corpo = cols + (["    sqlite_autoincrement=True,"] if auto else [])
        linhas.append(f"{_ident(nome)} = sa.Table(\n    {nome!r}, metadata,\n" + "\n".join(corpo) + "\n)\n")
    linhas.append("MODELOS = {")
    for fq, m in sorted(contrato["models"].items()):
        if m["tabela"] in contrato["tabelas"]:
            linhas.append(f"    {fq!r}: {_ident(m['tabela'])},")
    linhas.append("}")
    return "\n".join(linhas) + "\n"


# --------------------------------------------------------------------------- pydantic
TIPOS_REGRA = {"integer": "int", "numeric": "float", "boolean": "bool", "array": "list", "string": "str",
               "email": "str", "url": "str"}


def validacoes_py(contrato: dict) -> tuple[str, dict]:
    linhas = ['"""Corpo de cada FormRequest com regras literais, em Pydantic (gerado).',
              "",
              "Documenta o corpo no OpenAPI. Quem decide 422 é o validador do laravel_compat,",
              'que repete as regras e as mensagens do Laravel."""',
              "from typing import Any, Optional", "", "from pydantic import BaseModel, ConfigDict", ""]
    mapa = {}
    for fq, v in sorted(contrato["validacoes"].items()):
        if v["abstrata"] or not v["regras"]:
            continue
        nome = "Corpo" + fq.rsplit("\\", 1)[-1]
        campos = []
        for campo, regras in v["regras"].items():
            if "." in campo or not re.fullmatch(r"[A-Za-z_]\w*", campo):
                continue
            nomes = [r.split(":")[0] for r in regras if isinstance(r, str)]
            tipo = next((TIPOS_REGRA[n] for n in nomes if n in TIPOS_REGRA), "Any")
            obrigatorio = "required" in nomes and "sometimes" not in nomes
            campos.append(f"    {campo}: {tipo}" if obrigatorio else f"    {campo}: Optional[{tipo}] = None")
        linhas.append(f"class {nome}(BaseModel):")
        linhas.append("    model_config = ConfigDict(extra='allow')")
        linhas += campos or ["    pass"]
        linhas.append("")
        if v.get("dados_em"):
            externo = nome + "Envelope"
            linhas.append(f"class {externo}(BaseModel):")
            linhas.append(f"    {v['dados_em']}: {nome}")
            linhas.append("")
            nome = externo
        mapa[fq] = nome
    return "\n".join(linhas) + "\n", mapa


# --------------------------------------------------------------------------- rotas
def rotas_py(contrato: dict, corpos: dict) -> str:
    linhas = ['"""Uma função por rota do contrato, na mesma ordem do Laravel (gerado)."""', "# ruff: noqa",
              "from fastapi import APIRouter, Depends", "", "from laravel_compat import fastapi_glue as glue",
              "from laravel_compat.http import Request", "", "import validacoes", "from dados import DADOS", "",
              "router = APIRouter()", 'R = DADOS["rotas"]', "", "",
              "def esquema(modelo):",
              '    """Schema do Pydantic com as $defs embutidas (o OpenAPI não lê $defs soltas)."""',
              "    s = modelo.model_json_schema()",
              '    defs = s.pop("$defs", {})',
              "    def trocar(x):",
              "        if isinstance(x, dict):",
              '            if "$ref" in x:',
              '                return trocar(defs[x["$ref"].rsplit("/", 1)[-1]])',
              "            return {k: trocar(v) for k, v in x.items()}",
              "        if isinstance(x, list):",
              "            return [trocar(v) for v in x]",
              "        return x",
              "    return trocar(s)", "", ""]
    for i, r in enumerate(contrato["rotas"]):
        acao = r["acao"]
        sufixo = _ident(acao.get("classe", "x").rsplit("\\", 1)[-1] + "_" + str(acao.get("metodo", ""))) if acao.get("tipo") == "controller" else acao.get("tipo", "x")
        params = [p["nome"] for p in r["parametros"]]
        caminho = re.sub(r"\{(\w+)\?\}", r"{\1}", r["caminho"])
        extra = ""
        if acao.get("tipo") == "controller":
            cls = contrato["classes"].get(acao["classe"], {})
            m = cls.get("metodos", {}).get(acao["metodo"], {})
            for p in m.get("params", []):
                if p.get("tipo") in corpos:
                    extra = (f', openapi_extra={{"requestBody": {{"content": {{"application/json": '
                             f'{{"schema": esquema(validacoes.{corpos[p["tipo"]]})}}}}}}}}')
        assinatura = ", ".join([f"{_ident(p)}: str" for p in params] + ["req: Request = Depends(glue.requisicao)"])
        valores = "{" + ", ".join(f"{p!r}: {_ident(p)}" for p in params) + "}"
        linhas.append(f"@router.api_route({caminho!r}, methods={r['metodos']!r}, name={r.get('nome')!r}, "
                      f"dependencies=[Depends(glue.middleware(R[{i}]))]{extra})")
        linhas.append(f"def rota_{i}_{sufixo}({assinatura}):")
        linhas.append(f"    return glue.executar(R[{i}], req, {valores})")
        linhas.append("")
    return "\n".join(linhas) + "\n"


# --------------------------------------------------------------------------- config
def config_py(contrato: dict, t: Transpilador) -> tuple[str, list]:
    """Cada chave de topo de config/*.php vira uma função: uma chave intraduzível não leva o arquivo junto."""
    linhas = ['"""config/*.php do app, avaliado na hora como o Laravel faz com env() (gerado)."""', "# ruff: noqa",
              "import laravel_compat as lv", "from laravel_compat import php", "from app_traduzido import *", "",
              "f_env = lv.funcao('env')", ""]
    problemas = []
    entradas = []
    for nome, ir in sorted(contrato["config"].items()):
        if ir is None or ir[0] != "arr" or any(it[0] is None or it[0][0] != "lit" for it in ir[1]):
            fonte, prob = t.config(nome, ir)
            linhas.append(fonte)
            entradas.append(f"    {nome!r}: config_{_ident(nome)},")
            problemas += prob
            continue
        chaves = []
        for it in ir[1]:
            chave = it[0][1]
            fonte, prob = t.config(f"{nome}_{chave}", it[1])
            problemas += prob
            linhas.append(fonte)
            chaves.append(f"        {chave!r}: config_{_ident(nome + '_' + str(chave))},")
        linhas.append(f"def config_{_ident(nome)}():")
        linhas.append("    return php_config({")
        linhas += chaves
        linhas.append("    })")
        entradas.append(f"    {nome!r}: config_{_ident(nome)},")
    linhas += ["", "def php_config(chaves):",
               '    """Avalia chave por chave; a que falha fica de fora e vira aviso na partida."""',
               "    saida = {}",
               "    for k, fn in chaves.items():",
               "        try:",
               "            saida[k] = fn()",
               "        except Exception as e:",
               "            import sys",
               "            print(f'[laravel_compat] aviso: config {k}: {e}', file=sys.stderr)",
               "    return saida", "", "", "CONFIG = {"] + entradas + ["}"]
    preambulo = [f"{a} = lv.funcao({n!r})" for n, a in sorted(t.funcoes.items())] + \
                [f"{a} = lv.classe({fq!r})" for fq, a in sorted(t.framework.items(), key=lambda x: x[1])]
    linhas[6:6] = preambulo
    return "\n".join(linhas) + "\n", problemas


# --------------------------------------------------------------------------- cobertura
def alcancaveis(t: Transpilador, inicio: set) -> set:
    """Fecho por nome, com a classe do receptor estimada.

    Nós: (classe, método); (classe, '*') = a classe entrou em uso (new, ::class,
    chamada estática, tipo de parâmetro); ('?', nome) = método chamado num objeto
    de tipo desconhecido; ('fn', nome) = função de helpers.php. Um ('?', nome) só
    puxa o método das classes que já entraram em uso: em app grande, puxar de
    todas fazia toda rota alcançar LDAP e console (medido no BookStack).
    """
    vistos, fila = set(), list(inicio)
    em_uso: set = set()
    nomes_pendentes: set = set()
    while fila:
        no = fila.pop()
        if no in vistos:
            continue
        vistos.add(no)
        cls, nome = no
        if cls == "fn":
            fila += list(t.refs.get(f"fn::{nome}", ()))
            continue
        if cls == "?":
            nomes_pendentes.add(nome)
            fila += [(fq, nome) for fq in em_uso if t.metodo_app(fq, nome)[0] is not None]
            continue
        if cls not in t.classes:
            continue
        if nome == "*":
            atual = cls
            while atual in t.classes:
                if atual not in em_uso:
                    em_uso.add(atual)
                    fila += list(t.refs.get(f"{atual}::*", ()))
                    fila += [(atual, n) for n in nomes_pendentes if n in t.classes[atual]["metodos"]]
                for m in t.classes[atual]["metodos"]:
                    if m in ENTRADAS_FRAMEWORK or "\\Policies\\" in atual:
                        fila.append((atual, m))
                fila += [(tr, "*") for tr in t.classes[atual].get("tracos", []) if tr in t.classes]
                atual = t.classes[atual].get("pai")
            continue
        fila.append((cls, "*"))
        dono, m = t.metodo_app(cls, nome)
        if dono is None:
            continue
        fila += list(t.refs.get(f"{dono}::{nome}", ()))
        fila += [(p["tipo"], "*") for p in m["params"] if p.get("tipo") in t.classes]
    return vistos


def cobertura(contrato: dict, t: Transpilador) -> dict:
    problemas_por_metodo: dict[str, list] = {}
    for p in t.problemas:
        problemas_por_metodo.setdefault(p["onde"], []).append(p)
    # O "onde" do problema é arquivo:linha Classe::metodo; indexa por (FQCN, método).
    indice = {}
    for fq, c in t.classes.items():
        for m_nome, m in c["metodos"].items():
            indice[(fq, m_nome)] = f"{c['arquivo']}:{m['linha']} {t.nomes[fq]}::{m_nome}"
        indice[(fq, "*")] = f"{c['arquivo']}:{c['linha']} {t.nomes[fq]}"
    for nome, f in contrato.get("funcoes", {}).items():
        indice[("fn", nome)] = f"{f['arquivo']}:{f['linha']} fn {nome}"
    globais = set()
    for nome in ("App\\Exceptions\\Handler",):
        if nome in t.classes:
            globais.add((nome, "*"))
    ok, provedores = _php.avaliar_literal(_achar_chave(contrato["config"].get("app"), "providers"))
    for p in (provedores or []) if ok else []:
        if p in t.classes:
            globais.add((p, "*"))
    if any("\\Policies\\" in fq for fq in t.classes):
        globais |= {(fq, "*") for fq in t.classes if "\\Policies\\" in fq}
    apelidos = (contrato.get("middleware") or {}).get("apelidos") or {}
    grupos = (contrato.get("middleware") or {}).get("grupos") or {}

    def expandir(ms):
        for m in ms:
            if m in grupos:
                yield from expandir(grupos[m])
            else:
                yield m

    saida = []
    for i, r in enumerate(contrato["rotas"]):
        motivos = []
        acao = r["acao"]
        inicio = set(globais)
        if acao.get("tipo") != "controller":
            motivos.append({"tipo": "acao_" + str(acao.get("tipo")), "onde": r["arquivo"]})
        else:
            dono, m = t.metodo_app(acao["classe"], acao["metodo"])
            if m is None:
                motivos.append({"tipo": "metodo_ausente", "onde": f"{acao['classe']}::{acao['metodo']}"})
            else:
                inicio.add((dono, acao["metodo"]))
                inicio.add((acao["classe"], "*"))
                for p in m["params"]:
                    if p.get("tipo") in t.classes:
                        inicio.add((p["tipo"], "*"))
        for mw in expandir(r["middleware"]):
            nome = mw.split(":")[0]
            alvo = apelidos.get(nome, nome)
            if alvo in t.classes:
                inicio.add((alvo, "*"))
            elif not lv.tem_classe(alvo):
                motivos.append({"tipo": "middleware_sem_traducao", "onde": mw})
        for no in sorted(alcancaveis(t, inicio)):
            for p in problemas_por_metodo.get(indice.get(no, ""), []):
                if p["tipo"] not in AVISOS and p not in motivos:
                    motivos.append(p)
        saida.append({"rota": f"{' '.join(m for m in r['metodos'] if m != 'HEAD')} {r['caminho']}",
                      "coberta": not motivos, "motivos": motivos})
    return {"rotas": len(saida), "cobertas": sum(1 for x in saida if x["coberta"]), "por_rota": saida,
            "problemas_traducao": len(t.problemas),
            "problemas_por_tipo": {k: sum(1 for p in t.problemas if p["tipo"] == k) for k in sorted({p["tipo"] for p in t.problemas})}}


def _achar_chave(ir, chave):
    if not ir or ir[0] != "arr":
        return None
    for it in ir[1]:
        if it[0] is not None and it[0] == ["lit", chave]:
            return it[1]
    return None


# --------------------------------------------------------------------------- tudo
def gerar(contrato: dict, saida: Path) -> dict:
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    t = Transpilador(contrato)
    app_src = t.modulo()
    cfg_src, cfg_prob = config_py(contrato, t)
    # Os aliases de função/classe que a config pediu ficam também no módulo do app.
    val_src, corpos = validacoes_py(contrato)
    dados = {k: contrato[k] for k in ("rotas", "traducoes", "politicas", "middleware", "volateis", "models")}
    arquivos = {
        "app_traduzido.py": app_src,
        "config_app.py": cfg_src,
        "modelos.py": modelos_py(contrato),
        "validacoes.py": val_src,
        "rotas.py": rotas_py(contrato, corpos),
        "dados.py": '"""Dados do contrato que o runtime consulta (gerado)."""\nimport json\n\nDADOS = json.loads(' + repr(json.dumps(dados, ensure_ascii=False, sort_keys=True)) + ")\n",
        "main.py": MAIN,
        "requirements.txt": REQUIREMENTS,
    }
    for nome, conteudo in arquivos.items():
        (saida / nome).write_text(conteudo, encoding="utf-8")
    destino_rt = saida / "laravel_compat"
    if destino_rt.exists():
        shutil.rmtree(destino_rt)
    shutil.copytree(RUNTIME, destino_rt, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cob = cobertura(contrato, t)
    cob["avisos_config"] = len(cfg_prob)
    (saida / "cobertura.json").write_text(json.dumps(cob, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return cob


MAIN = '''"""App FastAPI gerado do contrato Laravel. Rodar: DATABASE_URL=sqlite:///banco.sqlite uvicorn main:app"""
from fastapi import FastAPI

import laravel_compat as lv
from laravel_compat import fastapi_glue
from laravel_compat.eloquent import registrar_tabelas

import app_traduzido  # noqa: F401 - registra as classes do app
from config_app import CONFIG
from dados import DADOS
from modelos import metadata
from rotas import router

registrar_tabelas(metadata)
aplicacao = lv.Aplicacao(DADOS, CONFIG)
app = FastAPI(title="API traduzida de Laravel", version="1")
fastapi_glue.montar(app)
app.include_router(router)
aplicacao.iniciar()
'''


__all__ = ["gerar", "cobertura", "py_metodo"]
