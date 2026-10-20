"""python -m delphi_contrato {extrair|verificar|relatorio|rea} ..."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import comparar, contrato, rea, web


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="delphi_contrato", description="Sistema Delphi -> contrato verificável.")
    sub = p.add_subparsers(dest="acao", required=True)
    e = sub.add_parser("extrair", help="lê o projeto Delphi (pasta) ou o executável (.exe/.dll/.bpl) e escreve o contrato JSON")
    e.add_argument("fonte", type=Path)
    e.add_argument("-o", "--saida", type=Path, help="padrão: imprime na saída")
    v = sub.add_parser("verificar", help="o contrato ainda é o do fonte? (sai 1 se não)")
    v.add_argument("contrato", type=Path)
    v.add_argument("fonte", type=Path)
    v.add_argument("--estrito", action="store_true", help="pendência em aberto também reprova")
    r = sub.add_parser("relatorio", help="contrato em Markdown, para gente ler")
    r.add_argument("contrato", type=Path)
    r.add_argument("-o", "--saida", type=Path)
    cp = sub.add_parser("comparar", help="contrato do executável × contrato do fonte: as telas batem?")
    cp.add_argument("executavel", type=Path)
    cp.add_argument("fonte", type=Path, help="pasta, .dpr ou .dpk")
    w = sub.add_parser("web", help="telas para a web (JSON do desenhador tela.mjs), conferidas contra o contrato")
    w.add_argument("fonte", type=Path)
    w.add_argument("-o", "--saida", type=Path, required=True)
    x = sub.add_parser("rea", help="sem fonte: roda o REA no executável (seco sem --aplicar)")
    x.add_argument("executavel", type=Path)
    x.add_argument("--saida", type=Path, default=Path("rea-evidencia"))
    x.add_argument("--aplicar", action="store_true")
    a = p.parse_args(argv)

    if a.acao == "extrair":
        texto = contrato.serializar(contrato.extrair(a.fonte))
        if a.saida:
            a.saida.write_text(texto, encoding="utf-8")
            c = json.loads(texto)["cobertura"]
            print(f"contrato em {a.saida}: " + ", ".join(f"{k}={v}" for k, v in c.items()))
        else:
            sys.stdout.write(texto)
        return 0
    if a.acao == "verificar":
        problemas = contrato.verificar(json.loads(a.contrato.read_text(encoding="utf-8")), a.fonte, estrito=a.estrito)
        for item in problemas:
            print(f"  - {item}")
        print("contrato confere com a origem" if not problemas else f"{len(problemas)} problema(s)")
        return 1 if problemas else 0
    if a.acao == "relatorio":
        texto = contrato.relatorio(json.loads(a.contrato.read_text(encoding="utf-8")))
        if a.saida:
            a.saida.write_text(texto, encoding="utf-8")
        else:
            sys.stdout.write(texto)
        return 0
    if a.acao == "comparar":
        r = comparar.comparar(contrato.extrair(a.executavel), contrato.extrair(a.fonte))
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["telas_identicas"] == r["telas_em_comum"] else 1
    if a.acao == "web":
        c = contrato.extrair(a.fonte)
        t = web.telas(a.fonte, c)
        faltando = web.conferir(t, c)
        for item in faltando[:20]:
            print(f"  - {item}")
        if faltando:
            print(f"{len(faltando)} item(ns) do contrato fora da versão web; nada foi gravado")
            return 1
        a.saida.write_text(web.serializar(t), encoding="utf-8")
        print(f"{len(t['telas'])} telas em {a.saida}; contrato inteiro presente na versão web")
        return 0
    plano = rea.executar(a.executavel, a.saida, aplicar=a.aplicar)
    print(json.dumps(plano, ensure_ascii=False, indent=2))
    if not a.aplicar:
        print("\n(nada executado: falta --aplicar)")
        return 0
    return 0 if plano["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
