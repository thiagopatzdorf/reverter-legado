"""Monta a página de conceito e protótipo a partir do contrato real do exemplo.

Nenhum número da página é digitado: o modelo recebe o contrato que o extrator
gera de tests/fixtures/cadastro e o fonte lido, e o teste confere que a página
versionada é exatamente o que este script produz.

    python3 apps/delphi-contrato/prototipo/montar.py   # regrava prototipo/index.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
sys.path.insert(0, str(APP))

from delphi_contrato import contrato  # noqa: E402

FONTE = APP / "tests" / "fixtures" / "cadastro"
MODELO = AQUI / "modelo.html"
SAIDA = AQUI / "index.html"
MARCA = "/*__DADOS__*/null"


def montar() -> str:
    c = json.loads(contrato.serializar(contrato.extrair(FONTE)))
    arquivos = {a["caminho"]: (FONTE / a["caminho"]).read_text(encoding="utf-8") for a in c["origem"]["arquivos"]}
    dados = json.dumps({"contrato": c, "arquivos": arquivos}, ensure_ascii=False, sort_keys=True)
    # "</script>" dentro de um texto do fonte fecharia o bloco de script da página.
    dados = dados.replace("</", "<\\/")
    modelo = MODELO.read_text(encoding="utf-8")
    if modelo.count(MARCA) != 1:
        raise SystemExit(f"o modelo tem de ter a marca {MARCA} exatamente uma vez")
    return modelo.replace(MARCA, dados)


if __name__ == "__main__":
    SAIDA.write_text(montar(), encoding="utf-8")
    print(f"{SAIDA.relative_to(APP)}: {SAIDA.stat().st_size} bytes")
