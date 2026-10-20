"""Ponte para o REA (github.com/morluto/rea, MIT) quando só existe o executável.

O fonte é o caminho principal: dá contrato exato. Sem fonte, o REA abre o .exe
pelo Ghidra (ele reconhece o quadro de exceção Borland/Delphi) e devolve
Evidence em JSON. Aqui o REA é ferramenta externa, não dependência: versão
fixada, simulação por padrão, e o que ele devolve entra no contrato só como
arquivo com sha256, nunca como texto copiado.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Callable

# Uma só fonte para a versão: a fita (factory.manifest.json, papel `reverso`)
# repete este número e o teste reprova se os dois divergirem.
PACOTE = "rea-agents"
VERSAO_REA = "6.7.0"


def comandos(executavel: Path) -> list[tuple[str, list[str]]]:
    """(arquivo de saída, argv) de cada passo. Lista fechada: nada vem de entrada livre."""
    alvo = str(Path(executavel).resolve())
    base = ["npx", "-y", f"{PACOTE}@{VERSAO_REA}"]
    return [
        ("rea-analyze.json", base + ["analyze", alvo, "--provider", "ghidra", "--json"]),
        ("rea-busca-tform.json", base + ["search", alvo, "TForm", "--provider", "ghidra", "--json"]),
    ]


def executar(executavel: Path, saida: Path, *, aplicar: bool = False,
             rodar: Callable[[list[str]], subprocess.CompletedProcess] | None = None) -> dict:
    """Sem `aplicar`, só devolve o plano. Com `aplicar`, roda e registra a prova pelo arquivo gerado."""
    plano = {"pacote": f"{PACOTE}@{VERSAO_REA}", "alvo": Path(executavel).name, "passos": []}
    if not Path(executavel).is_file():
        raise FileNotFoundError(f"executável não existe: {executavel}")
    plano["alvo_sha256"] = hashlib.sha256(Path(executavel).read_bytes()).hexdigest()
    for nome, argv in comandos(executavel):
        plano["passos"].append({"saida": nome, "argv": argv})
    if not aplicar:
        plano["aplicado"] = False
        return plano
    rodar = rodar or (lambda argv: subprocess.run(argv, capture_output=True, timeout=3600))
    saida.mkdir(parents=True, exist_ok=True)
    for passo in plano["passos"]:
        r = rodar(passo["argv"])
        passo["codigo"] = r.returncode
        if r.returncode != 0:
            passo["erro"] = (r.stderr or b"")[-2000:].decode("utf-8", "replace")
            continue
        try:
            json.loads(r.stdout)
        except ValueError:
            # exit 0 com stdout que não é JSON não é evidência: "enviado" não é "entregue".
            passo["codigo"] = -1
            passo["erro"] = "REA terminou sem erro, mas a saída não é JSON"
            continue
        destino = saida / passo["saida"]
        destino.write_bytes(r.stdout)
        passo["sha256"] = hashlib.sha256(destino.read_bytes()).hexdigest()
        passo["bytes"] = destino.stat().st_size
    plano["aplicado"] = True
    plano["ok"] = all(p.get("codigo") == 0 for p in plano["passos"])
    (saida / "rea-evidencia.json").write_text(json.dumps(plano, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                              encoding="utf-8")
    return plano
