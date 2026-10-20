"""Linha de comando: extrair, verificar, gerar, diferencial."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import contrato


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="laravel_fastapi", description="Laravel -> contrato -> FastAPI, com avaliador diferencial")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extrair", help="lê o fonte Laravel e escreve o contrato")
    e.add_argument("projeto", type=Path)
    e.add_argument("-o", "--saida", type=Path)
    v = sub.add_parser("verificar", help="sai 1 se o contrato não for mais o do fonte")
    v.add_argument("contrato", type=Path)
    v.add_argument("projeto", type=Path)
    v.add_argument("--estrito", action="store_true", help="pendência aberta também reprova")
    g = sub.add_parser("gerar", help="gera o app FastAPI a partir do contrato")
    g.add_argument("contrato", type=Path)
    g.add_argument("-o", "--saida", type=Path, required=True)
    d = sub.add_parser("diferencial", help="mesmo cenário nos dois apps; placar por endpoint")
    d.add_argument("--cenario", type=Path, required=True)
    d.add_argument("--contrato", type=Path, required=True)
    d.add_argument("--laravel", required=True, help="URL,caminho-do-sqlite")
    d.add_argument("--fastapi", required=True, help="URL,caminho-do-sqlite")
    d.add_argument("-o", "--saida", type=Path, required=True)
    d.add_argument("--pausa", type=float, default=1.1, help="segundos entre passos (o throttle:api do Laravel é 60/min)")
    a = p.parse_args(argv)

    if a.cmd == "extrair":
        texto = contrato.serializar(contrato.extrair(a.projeto))
        if a.saida:
            a.saida.write_text(texto, encoding="utf-8")
            c = json.loads(texto)["cobertura"]
            print(f"{c['rotas']} rotas, {c['tabelas']} tabelas, {c['models']} models, {c['form_requests']} FormRequests, "
                  f"{c['recursos']} resources, {c['pendencias']} pendências")
        else:
            sys.stdout.write(texto)
        return 0
    if a.cmd == "verificar":
        erros = contrato.verificar(json.loads(a.contrato.read_text(encoding="utf-8")), a.projeto, a.estrito)
        for x in erros:
            print(x)
        return 1 if erros else 0
    if a.cmd == "gerar":
        from . import gerar

        cob = gerar.gerar(json.loads(a.contrato.read_text(encoding="utf-8")), a.saida)
        print(f"{cob['cobertas']} de {cob['rotas']} rotas cobertas pelo gerador; detalhe em {a.saida / 'cobertura.json'}")
        return 0
    from . import diferencial

    cen = json.loads(a.cenario.read_text(encoding="utf-8"))
    vol = json.loads(a.contrato.read_text(encoding="utf-8")).get("volateis", {})
    lb, lc = a.laravel.split(",", 1)
    fb, fc = a.fastapi.split(",", 1)
    res = diferencial.rodar(cen, vol, {"base": lb, "banco": lc}, {"base": fb, "banco": fc}, a.pausa)
    a.saida.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{res['endpoints_iguais']} de {res['endpoints']} endpoints respondem igual ({res['passos_iguais']} de {res['passos']} passos)")
    return 0 if res["endpoints_iguais"] == res["endpoints"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
