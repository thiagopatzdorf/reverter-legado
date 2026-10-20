"""Caso real, segundo passo: o que cada botão do HeidiSQL 12.21 faz, lido do binário pelo REA.

O primeiro passo (heidisql.py) tira do .exe as telas e diz se cada handler existe; o corpo
do handler o executável não entrega. Aqui o REA (Ghidra) decompila cinco handlers achados
por um texto que só aquele handler usa no fonte, e o resultado é medido contra o fonte:

    python3 apps/delphi-contrato/casos/heidisql_rea.py \\
        [--exe <heidisql.exe>] --saida apps/genesis-site/fonte/caso-delphi/rea.json

Sem --exe, a conferência da tabela de métodos vem da evidência gravada; com --exe ela é
refeita lendo o binário (só bytes, nada é executado). O veredito de cada handler sai das
marcas (marcas.json): fato do fonte -> texto que ele deixa no pseudo-código.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

CASO = Path(__file__).resolve().parent / "heidisql-rea"
EVIDENCIA = CASO / "evidencia"
EXE_SHA256 = "d4bc6b81906832aeed79e054ed094f5e15449c8fa91285538173d4a7f90db113"
# Prefixo de cada pedido na fila da sessão MCP: busca, xrefs, procedimento que contém.
ROTEIRO = {"TfrmPreferences.btnRestoreDefaultsClick": "restore", "TAboutBox.btnDonatedOKClick": "donated",
           "TfrmDataSorting.btnAddColClick": "sortcol", "TfrmReformatter.btnOkClick": "reformat",
           "TfrmTextEditor.menuFormatCodeOnceClick": "formaterr"}


def respostas() -> dict:
    return json.loads(gzip.decompress((EVIDENCIA / "respostas.json.gz").read_bytes()))


def _resposta(todas: dict, prefixo: str, chave: str):
    nome = next((n for n in todas if n.split("-", 1)[0].isdigit() and n.startswith(prefixo) and n.endswith(f"-{chave}.json")), None)
    return todas[nome]["resultado"] if nome else None


def tabela_de_metodos(exe: Path, handlers: list[str]) -> dict:
    """Endereço que a tabela de métodos publicados do Delphi x64 dá a cada handler.

    Entrada da tabela: tamanho (word), endereço do código (8 bytes) e o nome em ShortString.
    É o que o Delphi usa para ligar o evento do .dfm ao código, então é a identidade do handler.
    """
    d = exe.read_bytes()
    if hashlib.sha256(d).hexdigest() != EXE_SHA256:
        raise SystemExit("heidisql.exe não é o da release 12.21 (sha256 diverge)")
    saida = {}
    for handler in handlers:
        nome = handler.split(".", 1)[1]
        alvo = bytes([len(nome)]) + nome.encode("ascii")
        achados, i = set(), d.find(alvo)
        while i >= 0:
            if struct.unpack_from("<H", d, i - 10)[0] == 2 + 8 + len(alvo):
                achados.add(hex(struct.unpack_from("<Q", d, i - 8)[0]))
            i = d.find(alvo, i + 1)
        saida[handler] = sorted(achados)
    return saida


def medir(tabela: dict) -> dict:
    marcas = json.loads((CASO / "marcas.json").read_text(encoding="utf-8"))["handlers"]
    todas = respostas()
    linhas = []
    for h in marcas:
        pseudo = (EVIDENCIA / "pseudo" / f"{h['handler']}.c.txt").read_text(encoding="utf-8")
        p = ROTEIRO[h["handler"]]
        busca = _resposta(todas, "1", f"busca-{p}") or []
        xrefs = _resposta(todas, "2", f"xref-{p}") or []
        contem = _resposta(todas, "3", f"cont-{p}")
        procedimento = pseudo.split("FUN_", 1)[1].split("(", 1)[0]
        normais = [m for m in h["marcas"] if m["tipo"] == "normal"]
        excecao = [m for m in h["marcas"] if m["tipo"] == "excecao"]
        presentes = [m["fato"] for m in normais if m["pseudo"] in pseudo]
        excecao_vista = [m["fato"] for m in excecao if m["pseudo"] in pseudo]
        if len(presentes) < len(normais):
            veredito = "diverge"
        elif excecao and len(excecao_vista) < len(excecao):
            veredito = "sem_tratamento_de_erro"
        else:
            veredito = "igual"
        endereco = "0x" + procedimento.lstrip("0").lower()
        linhas.append({
            "handler": h["handler"], "tela": h["tela"], "botao": h["botao"], "faz": h["faz"],
            "isca": h["isca"], "isca_endereco": busca[0]["address"] if busca else None,
            "referencias": xrefs, "achado_pelo_texto": bool(contem and contem.get("found")),
            "procedimento": endereco, "tabela_de_metodos": tabela.get(h["handler"], []),
            "confere_com_a_tabela": endereco in tabela.get(h["handler"], []),
            "marcas_normais": len(normais), "marcas_normais_vistas": len(presentes),
            "marcas_excecao": len(excecao), "marcas_excecao_vistas": len(excecao_vista),
            "faltou": [m["fato"] for m in h["marcas"] if m["pseudo"] not in pseudo],
            "veredito": veredito,
        })
    consultas = [r["segundos"] for n, r in todas.items() if not n.startswith(("00-", "01-"))]
    return {
        "exe_sha256": EXE_SHA256,
        "rea": {"versao": "6.7.0", "provedor": "Ghidra 12.1.4"},
        "analise_inicial_segundos": round(todas["01-overview.json"]["segundos"]),
        "consulta_max_segundos": round(max(consultas), 1),
        "consultas": len(consultas),
        "handlers": linhas,
        "resumo": {
            "handlers": len(linhas),
            "achados_pelo_texto": sum(x["achado_pelo_texto"] for x in linhas),
            "confere_com_a_tabela": sum(x["confere_com_a_tabela"] for x in linhas),
            "iguais": sum(x["veredito"] == "igual" for x in linhas),
            "sem_tratamento_de_erro": sum(x["veredito"] == "sem_tratamento_de_erro" for x in linhas),
            "divergem": sum(x["veredito"] == "diverge" for x in linhas),
            "marcas_normais": sum(x["marcas_normais"] for x in linhas),
            "marcas_normais_vistas": sum(x["marcas_normais_vistas"] for x in linhas),
            "marcas_excecao": sum(x["marcas_excecao"] for x in linhas),
            "marcas_excecao_vistas": sum(x["marcas_excecao_vistas"] for x in linhas),
        },
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--exe", type=Path)
    p.add_argument("--saida", type=Path, required=True)
    a = p.parse_args(argv)
    gravada = EVIDENCIA / "tabela-de-metodos.json"
    if a.exe:
        handlers = [h["handler"] for h in json.loads((CASO / "marcas.json").read_text(encoding="utf-8"))["handlers"]]
        tabela = tabela_de_metodos(a.exe, handlers)
        gravada.write_text(json.dumps(tabela, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tabela = json.loads(gravada.read_text(encoding="utf-8"))
    medida = medir(tabela)
    a.saida.write_text(json.dumps(medida, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    r = medida["resumo"]
    print(f"{r['handlers']} handlers: {r['iguais']} iguais ao fonte, {r['sem_tratamento_de_erro']} sem o bloco except,"
          f" {r['divergem']} divergem; {r['confere_com_a_tabela']} conferem com a tabela de métodos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
