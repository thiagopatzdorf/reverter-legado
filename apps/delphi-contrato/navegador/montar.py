"""Monta a página do extrator no navegador numa pasta pronta para servir, sem servidor de aplicação.

    python3 apps/delphi-contrato/navegador/montar.py <destino> [--prefixo /experimente/]

O destino sai autossuficiente: a página, o MESMO pacote `delphi_contrato` da CLI (copiado
do fonte, nunca reescrito), o Pyodide fixado em `pyodide.json` (baixado uma vez do npm,
conferido por sha256 e guardado em cache), dois exemplos e o `manifesto.json` com o sha256
de cada arquivo. O Pyodide não vai para o Git: são 13,5 MB de binário que o repo não carrega.

Mesma entrada, mesmos bytes: os exemplos e o manifesto não têm data.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
sys.path.insert(0, str(APP / "tests"))

PIN = json.loads((AQUI / "pyodide.json").read_text(encoding="utf-8"))
PASTA_PYODIDE = f"pyodide-{PIN['versao']}"
PAGINA = ("index.html", "app.mjs", "motor.mjs", "trabalhador.mjs", "agentes.mjs", "estilo.css")
# 'wasm-unsafe-eval' é o mínimo para compilar WebAssembly; sem ele o Python não sobe. Não libera eval de JS.
CSP = ("default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; "
       "style-src 'self'; img-src 'self' data: blob:; font-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'none'")


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def cache_padrao() -> Path:
    return Path(os.environ.get("DELPHI_PYODIDE_CACHE") or AQUI / ".cache") / PASTA_PYODIDE


def pyodide(cache: Path | None = None) -> Path:
    """Os arquivos do Pyodide fixado, conferidos. Baixa o pacote do npm só se o cache não bater."""
    cache = cache or cache_padrao()

    def confere() -> bool:
        return all((cache / n).is_file() and _sha((cache / n).read_bytes()) == a["sha256"]
                   for n, a in PIN["arquivos"].items())

    if confere():
        return cache
    with urllib.request.urlopen(PIN["pacote"], timeout=120) as r:  # URL fixa do pin, conferida por sha256 abaixo
        pacote = r.read()
    if _sha(pacote) != PIN["pacote_sha256"]:
        raise SystemExit(f"pacote do Pyodide com sha256 {_sha(pacote)}, esperado {PIN['pacote_sha256']}: nada gravado")
    cache.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(pacote), mode="r:gz") as t:
        for nome, a in PIN["arquivos"].items():
            dados = t.extractfile(f"package/{nome}").read()
            if _sha(dados) != a["sha256"]:
                raise SystemExit(f"{nome} do Pyodide não confere com pyodide.json")
            (cache / nome).write_bytes(dados)
    return cache


def _zip_deterministico(raiz: Path, prefixo: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(raiz.rglob("*"), key=lambda p: p.relative_to(raiz).as_posix()):
            if p.is_file():
                info = zipfile.ZipInfo(f"{prefixo}/{p.relative_to(raiz).as_posix()}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, p.read_bytes())
    return buf.getvalue()


def exemplos() -> dict[str, bytes]:
    """O projeto de exemplo zipado (como o usuário mandaria) e o mesmo projeto como executável sintético."""
    from sintetico import CADASTRO, cadastro_exe
    return {"exemplos/cadastro.zip": _zip_deterministico(CADASTRO, "cadastro"),
            "exemplos/Cadastro.exe": cadastro_exe()}


def arquivos(cache: Path | None = None, *, com_pyodide: bool = True) -> dict[str, bytes]:
    saida = {nome: (AQUI / nome).read_bytes() for nome in PAGINA}
    saida["tela/tela.mjs"] = (APP / "web" / "tela.mjs").read_bytes()
    saida["tela/tela.css"] = (APP / "web" / "tela.css").read_bytes()
    saida["py/ponte.py"] = (AQUI / "ponte.py").read_bytes()
    for p in sorted((APP / "delphi_contrato").glob("*.py")):
        saida[f"py/delphi_contrato/{p.name}"] = p.read_bytes()
    lista = sorted(n[len("py/"):] for n in saida if n.startswith("py/"))
    saida["py/arquivos.json"] = (json.dumps(lista, indent=1) + "\n").encode()
    saida.update(exemplos())
    if com_pyodide:
        origem = pyodide(cache)
        for nome in PIN["arquivos"]:
            saida[f"{PASTA_PYODIDE}/{nome}"] = (origem / nome).read_bytes()
        saida[f"{PASTA_PYODIDE}/LEIAME.txt"] = (
            f"Pyodide {PIN['versao']} (Python {PIN['python']}), licença {PIN['licenca']}.\n"
            f"Arquivos sem alteração do pacote {PIN['pacote']}\n"
            "Fonte: https://github.com/pyodide/pyodide\n").encode()
    return saida


def headers(prefixo: str) -> bytes:
    p = "/" + prefixo.strip("/") + "/" if prefixo.strip("/") else "/"
    return (f"{p}*\n  Content-Security-Policy: {CSP}\n  X-Content-Type-Options: nosniff\n"
            f"  Referrer-Policy: no-referrer\n  Permissions-Policy: tools=(self)\n"
            f"{p}{PASTA_PYODIDE}/*\n  Cache-Control: public, max-age=31536000, immutable\n").encode()


def montar(destino: Path, prefixo: str = "/", cache: Path | None = None, *, com_pyodide: bool = True) -> dict:
    tudo = arquivos(cache, com_pyodide=com_pyodide)
    tudo["_headers"] = headers(prefixo)
    manifesto = {
        "pyodide": PIN["versao"], "csp": CSP,
        "arquivos": {n: {"bytes": len(d), "sha256": _sha(d)} for n, d in sorted(tudo.items())},
    }
    manifesto["total_bytes"] = sum(a["bytes"] for a in manifesto["arquivos"].values())
    tudo["manifesto.json"] = (json.dumps(manifesto, indent=1, sort_keys=True) + "\n").encode()
    if destino.exists():
        shutil.rmtree(destino)
    for nome, dados in tudo.items():
        (destino / nome).parent.mkdir(parents=True, exist_ok=True)
        (destino / nome).write_bytes(dados)
    return manifesto


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("destino", type=Path)
    a.add_argument("--prefixo", default="/", help="caminho onde a pasta será servida (para o _headers)")
    a.add_argument("--cache", type=Path, help="pasta do Pyodide baixado (padrão: navegador/.cache ou $DELPHI_PYODIDE_CACHE)")
    x = a.parse_args()
    m = montar(x.destino, x.prefixo, x.cache)
    print(f"{len(m['arquivos'])} arquivos, {m['total_bytes'] / 1e6:.1f} MB em {x.destino}")
