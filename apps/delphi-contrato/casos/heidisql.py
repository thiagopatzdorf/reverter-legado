"""Caso real: HeidiSQL 12.21 (Delphi, GPL-2.0) do executável oficial até a web.

Gera os dados da página /caso-delphi da Genesis, sem número digitado à mão:

    python3 apps/delphi-contrato/casos/heidisql.py --zip <HeidiSQL_12.21_64_Portable.zip> \\
        --dpr <checkout do HeidiSQL em effb854>/packages/Delphi12.3/heidisql.dpr \\
        --saida apps/genesis-site/fonte/caso-delphi

O zip é o da release oficial (URL abaixo); o .exe é lido de dentro dele como bytes,
nunca extraído para disco nem executado. O fonte é o commit da master marcado
"Bump version for v12.21 release": a tag v12.21 aponta para o port em Lazarus,
e o executável 12.21 é Delphi (assinatura Embarcadero/VCL no binário).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delphi_contrato import comparar, contrato, web  # noqa: E402

PRODUTO = {
    "nome": "HeidiSQL",
    "versao": "12.21",
    "licenca": "GPL-2.0",
    "autor": "Ansgar Becker e colaboradores",
    "site": "https://www.heidisql.com/",
    "binario_url": "https://github.com/HeidiSQL/HeidiSQL/releases/download/v12.21/HeidiSQL_12.21_64_Portable.zip",
    "fonte_repo": "https://github.com/HeidiSQL/HeidiSQL",
    "fonte_commit": "effb854",
    "fonte_commit_titulo": "Bump version for v12.21 release",
}
TELA_DESTAQUE = "connform"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--zip", type=Path, required=True)
    p.add_argument("--dpr", type=Path, required=True)
    p.add_argument("--saida", type=Path, required=True)
    a = p.parse_args(argv)

    bruto_zip = a.zip.read_bytes()
    exe_bytes = zipfile.ZipFile(a.zip).read("heidisql.exe")
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp, "heidisql.exe")
        exe.write_bytes(exe_bytes)
        t0 = time.perf_counter()
        do_exe = contrato.extrair(exe)
        segundos_exe = time.perf_counter() - t0
        telas = web.telas(exe, do_exe)
    do_fonte = contrato.extrair(a.dpr)
    faltando = web.conferir(telas, do_exe)
    if faltando:
        print("\n".join(faltando[:20]), file=sys.stderr)
        return 1

    destaque = next(t for t in telas["telas"] if t["n"].lower() == TELA_DESTAQUE)
    caso = {
        "produto": PRODUTO,
        "binario": {"zip_sha256": hashlib.sha256(bruto_zip).hexdigest(), "exe_sha256": hashlib.sha256(exe_bytes).hexdigest(),
                    "exe_bytes": len(exe_bytes), "extracao_segundos": round(segundos_exe, 1)},
        "exe": do_exe["cobertura"],
        "fonte": do_fonte["cobertura"],
        "comparacao": comparar.comparar(do_exe, do_fonte),
        "pendencias_exe": sorted({p["tipo"] for p in do_exe["pendencias"]}),
        "sql_dinamico_fonte": sum(p["tipo"] == "sql_dinamico" for p in do_fonte["pendencias"]),
        "web": {"telas": len(telas["telas"]), "faltando": 0, "destaque": destaque["n"]},
    }
    a.saida.mkdir(parents=True, exist_ok=True)
    (a.saida / "caso.json").write_text(json.dumps(caso, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (a.saida / "telas.json").write_text(web.serializar(telas), encoding="utf-8")
    print(f"caso em {a.saida}: {caso['exe']['formularios']} telas, {caso['comparacao']['telas_identicas']}"
          f"/{caso['comparacao']['telas_em_comum']} idênticas ao fonte, versão web completa")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
