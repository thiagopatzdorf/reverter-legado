"""CLI do rea-lab. Tudo determinístico: mesma entrada, mesmos bytes."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import fonte, medir, wad


def _escrever(dados, destino: str | None) -> None:
    texto = json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if destino:
        Path(destino).write_text(texto, encoding="utf-8")
    else:
        sys.stdout.write(texto)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rea_lab")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gabarito", help="funções e literais do fonte (o lado verdade)")
    g.add_argument("caso", help="caso.json com a lista de arquivos do alvo")
    g.add_argument("fonte", help="pasta que contém a raiz do fonte descrita no caso")
    g.add_argument("-o", "--saida")
    c = sub.add_parser("compactar", help="respostas MCP do REA (list_procedures, list_strings) -> evidência compacta")
    c.add_argument("procedimentos")
    c.add_argument("textos")
    c.add_argument("pasta")
    m = sub.add_parser("medir", help="evidência compacta x gabarito -> números")
    m.add_argument("pasta", help="pasta com procedimentos.json e textos.json")
    m.add_argument("gabarito")
    m.add_argument("-o", "--saida")
    w = sub.add_parser("wad", help="resumo de um WAD lido pelo formato tirado do binário")
    w.add_argument("arquivo")
    w.add_argument("-o", "--saida")
    a = p.parse_args(argv)
    if a.cmd == "compactar":
        def _normalizado(arq):
            r = json.loads(Path(arq).read_text(encoding="utf-8"))
            return r["result"]["structuredContent"]["normalized_result"]
        destino = Path(a.pasta)
        destino.mkdir(parents=True, exist_ok=True)
        _escrever(medir.compactar_procedimentos(_normalizado(a.procedimentos)), str(destino / "procedimentos.json"))
        _escrever(medir.compactar_textos(_normalizado(a.textos)), str(destino / "textos.json"))
    elif a.cmd == "medir":
        pasta = Path(a.pasta)
        _escrever(medir.medir(json.loads((pasta / "procedimentos.json").read_text(encoding="utf-8")),
                              json.loads((pasta / "textos.json").read_text(encoding="utf-8")),
                              json.loads(Path(a.gabarito).read_text(encoding="utf-8"))), a.saida)
    elif a.cmd == "wad":
        _escrever(wad.resumo(Path(a.arquivo)), a.saida)
    elif a.cmd == "gabarito":
        caso = json.loads(Path(a.caso).read_text(encoding="utf-8"))
        raiz = Path(a.fonte) / caso["fonte"]["raiz"]
        _escrever(fonte.gabarito(raiz, caso["fonte"]["arquivos"]), a.saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
