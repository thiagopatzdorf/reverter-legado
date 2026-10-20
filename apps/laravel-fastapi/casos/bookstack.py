"""Medida em app grande: o contrato e a cobertura estática do BookStack.

BookStack (https://github.com/BookStackApp/BookStack, MIT), tag v26.09.1, commit
31d94dd8b98e3334dc01b66bed6d514719a2f85d. Serve para medir o leitor numa base
grande (502 classes) e para mostrar onde o gerador para. O diferencial roda no
RealWorld, não aqui: a API do BookStack passa por repositórios e permissões
próprias (`apiListingResponse`, `joint_permissions`) e o fecho por nome não
cobre nenhuma rota dela nesta versão; as causas saem em `motivos`.

    python3 apps/laravel-fastapi/casos/bookstack.py --fonte <checkout em v26.09.1> --saida <dir>
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from laravel_fastapi import contrato, gerar  # noqa: E402

PRODUTO = {"nome": "BookStack", "repo": "https://github.com/BookStackApp/BookStack", "tag": "v26.09.1",
           "commit": "31d94dd8b98e3334dc01b66bed6d514719a2f85d", "licenca": "MIT"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--fonte", type=Path, required=True)
    p.add_argument("--saida", type=Path, required=True)
    a = p.parse_args(argv)
    c = json.loads(contrato.serializar(contrato.extrair(a.fonte)))
    with tempfile.TemporaryDirectory() as tmp:
        cob = gerar.gerar(c, Path(tmp))
    api = [r for r in cob["por_rota"] if " /api/" in r["rota"]]
    causas = collections.Counter()
    for r in api:
        for k in {(m["tipo"], m.get("detalhe", "")) for m in r["motivos"]}:
            causas[k] += 1
    medida = {
        "produto": PRODUTO,
        "contrato": c["cobertura"],
        "rotas_api": len(api),
        "gerador": {"rotas": cob["rotas"], "cobertas": cob["cobertas"], "api_cobertas": sum(r["coberta"] for r in api),
                    "problemas_traducao": cob["problemas_traducao"], "problemas_por_tipo": cob["problemas_por_tipo"]},
        "causas_mais_comuns_na_api": [{"tipo": t, "detalhe": d, "rotas": n} for (t, d), n in causas.most_common(10)],
    }
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "bookstack.json").write_text(json.dumps(medida, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rotas": c["cobertura"]["rotas"], "api": len(api), "cobertas": cob["cobertas"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
