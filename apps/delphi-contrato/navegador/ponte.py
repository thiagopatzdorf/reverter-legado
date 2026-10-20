"""Ponte entre a página e o pacote delphi_contrato, rodando dentro do Pyodide.

A regra continua toda em `delphi_contrato` (o mesmo código da CLI). Aqui só fica o que
a CLI resolve com o sistema de arquivos e a página não tem: arquivos soltos e .zip
viram a mesma pasta que o usuário passaria para `python3 -m delphi_contrato extrair`.
Por isso o contrato do navegador é byte a byte o da CLI:

| a página recebe                    | equivale a                                    |
|------------------------------------|-----------------------------------------------|
| um .exe/.dll/.bpl/.ocx             | `extrair Sistema.exe`                         |
| um .zip só com binário (1 .exe)    | `extrair Sistema.exe` (lido de dentro do zip) |
| .zip do projeto ou .dfm/.pas soltos| `extrair <pasta>` (a pasta única do zip vira a raiz) |
| + `projeto="X.dpr"`                | `extrair <pasta>/X.dpr`                       |

Roda igual no CPython: o teste prova a equivalência sem navegador.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import struct
import time
import zipfile
from pathlib import Path, PurePosixPath

from delphi_contrato import binario, comparar as _comparar, contrato, web

FONTE = {".pas", ".dpr", ".dpk", ".dfm"}
# Zip-bomba: limites bem acima de um projeto Delphi real (HeidiSQL inteiro: ~40 MB de fonte).
MAX_ZIP_BYTES = 512 * 1024 * 1024
MAX_ZIP_ITENS = 50_000


class EntradaInvalida(ValueError):
    pass


def _nome_seguro(nome: str) -> str:
    base = PurePosixPath(nome.replace("\\", "/")).name
    if not base or base in (".", ".."):
        raise EntradaInvalida(f"nome de arquivo inválido: {nome!r}")
    return base


def _membros(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    itens = [i for i in z.infolist() if not i.is_dir()]
    if len(itens) > MAX_ZIP_ITENS or sum(i.file_size for i in itens) > MAX_ZIP_BYTES:
        raise EntradaInvalida("zip grande demais para abrir no navegador")
    saida = []
    for i in itens:
        partes = PurePosixPath(i.filename.replace("\\", "/")).parts
        if not partes or partes[0] == "__MACOSX" or partes[-1].startswith("._"):
            continue  # lixo do Finder do macOS, não é do projeto
        if i.filename.startswith("/") or ".." in partes or ":" in partes[0]:
            raise EntradaInvalida(f"caminho fora do zip: {i.filename!r}")
        saida.append(i)
    return saida


def _binarios_com_telas(z: zipfile.ZipFile, membros: list[zipfile.ZipInfo]) -> list[tuple[str, bytes]]:
    """Binários do zip que trazem formulário Delphi (RCDATA TPF0). O zip "portable" de um sistema
    traz o .exe junto com DLLs de terceiros e utilitários (no HeidiSQL, 34 binários): só o do
    sistema tem tela Delphi, e é ele que a CLI receberia."""
    saida = []
    for m in membros:
        if PurePosixPath(m.filename).suffix.lower() not in binario.EXTENSOES:
            continue
        dados = z.read(m)
        try:
            if any(b.startswith(b"TPF0") for _, b in binario.recursos_rcdata(dados)):
                saida.append((m.filename, dados))
        except (binario.BinarioInvalido, struct.error, IndexError, ValueError):
            continue  # binário que não é PE ou está truncado: não é o sistema
    return saida


def preparar(entradas: list[Path], area: Path) -> dict:
    """Arquivos recebidos -> o alvo que a CLI receberia. Devolve {alvo, tipo, projetos}."""
    if area.exists():
        shutil.rmtree(area)
    pasta = area / "fonte"
    pasta.mkdir(parents=True)
    if not entradas:
        raise EntradaInvalida("nenhum arquivo")
    if len(entradas) == 1 and entradas[0].suffix.lower() in binario.EXTENSOES:
        alvo = area / _nome_seguro(entradas[0].name)
        shutil.copyfile(entradas[0], alvo)
        return {"alvo": alvo, "tipo": "executavel", "projetos": []}
    for e in entradas:
        if e.suffix.lower() == ".zip":
            with zipfile.ZipFile(e) as z:
                membros = _membros(z)
                if not any(PurePosixPath(m.filename).suffix.lower() in FONTE for m in membros):
                    com_telas = _binarios_com_telas(z, membros)
                    if len(entradas) == 1 and len(com_telas) == 1:
                        nome, dados = com_telas[0]
                        alvo = area / _nome_seguro(nome)
                        alvo.write_bytes(dados)
                        return {"alvo": alvo, "tipo": "executavel", "projetos": []}
                    achados = ", ".join(n for n, _ in com_telas) or "nenhum"
                    raise EntradaInvalida("o zip não tem .pas, .dfm nem .dpr, e não tem exatamente um executável "
                                          f"com telas Delphi (achados: {achados}); arraste o executável sozinho")
                for m in membros:
                    destino = pasta.joinpath(*PurePosixPath(m.filename.replace("\\", "/")).parts)
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    destino.write_bytes(z.read(m))
        elif e.suffix.lower() in binario.EXTENSOES:
            raise EntradaInvalida("executável vai sozinho: um arquivo por vez")
        else:
            shutil.copyfile(e, pasta / _nome_seguro(e.name))
    raiz = pasta
    # Zip de uma pasta (o normal: "Compactar cadastro/") tem uma pasta só no topo; ela é a raiz.
    while True:
        filhos = list(raiz.iterdir())
        if len(filhos) == 1 and filhos[0].is_dir():
            raiz = filhos[0]
        else:
            break
    projetos = sorted((p.relative_to(raiz).as_posix() for p in raiz.rglob("*")
                       if p.is_file() and p.suffix.lower() in (".dpr", ".dpk")), key=str.lower)
    return {"alvo": raiz, "tipo": "pasta", "projetos": projetos}


def _resolver(entradas: list[Path], area: Path, projeto: str | None) -> dict:
    p = preparar(entradas, area)
    if projeto:
        if projeto not in p["projetos"]:
            raise EntradaInvalida(f"projeto {projeto!r} não está entre {p['projetos']}")
        p["alvo"] = p["alvo"] / projeto
        p["tipo"] = "projeto"
    return p


def extrair(entradas: list[Path], area: Path, projeto: str | None = None) -> dict:
    """O que a página mostra: contrato (texto exato da CLI), relatório, telas e a medida de tempo."""
    p = _resolver(entradas, area, projeto)
    t0 = time.perf_counter()
    c = contrato.extrair(p["alvo"])
    texto = contrato.serializar(c)
    ms = round((time.perf_counter() - t0) * 1000)
    t = web.telas(p["alvo"], c)
    return {
        "contrato": texto,
        "contrato_sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "relatorio": contrato.relatorio(c),
        "telas": json.loads(web.serializar(t)),
        "faltando_na_web": web.conferir(t, c),
        "tipo": p["tipo"], "projetos": p["projetos"], "projeto": projeto,
        "extracao_ms": ms,
    }


def comparar(executavel: list[Path], fonte: list[Path], area: Path, projeto: str | None = None) -> dict:
    """`python3 -m delphi_contrato comparar Sistema.exe <fonte>`: as telas do .exe batem com as do fonte?"""
    a = _resolver(executavel, area / "exe", None)
    if a["tipo"] != "executavel":
        raise EntradaInvalida("o primeiro arquivo tem de ser o executável (.exe/.dll/.bpl) ou um zip com um .exe")
    b = _resolver(fonte, area / "src", projeto)
    if b["tipo"] == "executavel":
        raise EntradaInvalida("o segundo arquivo tem de ser o fonte (.zip do projeto ou .dfm/.pas)")
    r = _comparar.comparar(contrato.extrair(a["alvo"]), contrato.extrair(b["alvo"]))
    r["confere"] = r["telas_identicas"] == r["telas_em_comum"]
    r["projetos"] = b["projetos"]
    return r


def chamar(acao: str, pedido_json: str) -> str:
    """Entrada única do trabalhador JS: pedido e resposta em JSON, erro do usuário como mensagem."""
    pedido = json.loads(pedido_json)
    area = Path(pedido.get("area", "/area"))
    try:
        if acao == "extrair":
            r = extrair([Path(x) for x in pedido["entradas"]], area, pedido.get("projeto"))
        elif acao == "comparar":
            r = comparar([Path(x) for x in pedido["executavel"]], [Path(x) for x in pedido["fonte"]], area,
                         pedido.get("projeto"))
        else:
            raise EntradaInvalida(f"ação desconhecida: {acao}")
        return json.dumps({"ok": True, "resultado": r}, ensure_ascii=False)
    except (EntradaInvalida, binario.BinarioInvalido, zipfile.BadZipFile) as erro:
        return json.dumps({"ok": False, "erro": str(erro)}, ensure_ascii=False)
