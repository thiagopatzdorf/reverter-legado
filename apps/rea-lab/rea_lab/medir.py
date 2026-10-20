"""Mede o que o REA devolveu contra o gabarito do fonte. Só números, nenhuma opinião.

Entradas são a evidência compacta (o que o REA listou) e o gabarito (`fonte.gabarito`).
"""
from __future__ import annotations

import re

_GENERICO = re.compile(r"^(FUN|thunk_FUN|LAB|SUB|entry)_?[0-9a-fA-F]*$|^thunk_FUN_[0-9a-fA-F]+$")
TAMANHO_MINIMO_LITERAL = 6  # literal curto ("%d", "wad") casa por acaso em qualquer texto


def compactar_procedimentos(normalized: list[dict]) -> list[dict]:
    """Lista do `list_procedures` do REA -> [{endereco, nome, externo, thunk}], ordenada por endereço."""
    saida = []
    for p in normalized:
        info = p.get("procedure") or {}
        saida.append({"endereco": p["address"], "nome": p["value"],
                      "externo": bool(info.get("external")), "thunk": bool(info.get("thunk"))})
    return sorted(saida, key=lambda x: (x["externo"], x["endereco"]))


def compactar_textos(normalized: list[dict]) -> list[dict]:
    """Lista do `list_strings` do REA -> [{endereco, texto}], ordenada por endereço."""
    return sorted(({"endereco": s["address"], "texto": s["value"]} for s in normalized),
                  key=lambda x: x["endereco"])


def medir(procedimentos: list[dict], textos: list[dict], gabarito: dict) -> dict:
    internos = [p for p in procedimentos if not p["externo"]]
    proprios = [p for p in internos if not p["thunk"]]
    nomeados = [p for p in proprios if not _GENERICO.match(p["nome"])]
    nomes_fonte = {f["nome"] for f in gabarito["funcoes"]}
    nomes_batem = sorted({p["nome"] for p in nomeados} & nomes_fonte)

    # Literal do fonte "recuperado" = aparece inteiro dentro de algum texto que o REA listou.
    # Literais adjacentes do C ("a" "b") viram um texto só no binário; o pedaço ainda casa por substring.
    corpus = "\x00".join(t["texto"] for t in textos)
    unicos = sorted({lit["texto"].strip() for lit in gabarito["literais"]
                     if len(lit["texto"].strip()) >= TAMANHO_MINIMO_LITERAL})
    achados = [u for u in unicos if u in corpus]
    return {
        "rea_procedimentos_total": len(procedimentos),
        "rea_procedimentos_externos": len(procedimentos) - len(internos),
        "rea_procedimentos_internos": len(internos),
        "rea_procedimentos_thunk": len(internos) - len(proprios),
        "rea_procedimentos_proprios": len(proprios),
        "rea_procedimentos_com_nome": len(nomeados),
        "rea_nomes_que_batem_com_o_fonte": len(nomes_batem),
        "rea_nomes_que_batem_exemplos": nomes_batem[:20],
        "rea_textos_total": len(textos),
        "fonte_funcoes_teto": gabarito["funcoes_total"],
        "fonte_funcoes_static": gabarito["funcoes_static"],
        "fonte_literais_unicos_min6": len(unicos),
        "fonte_literais_achados_no_binario": len(achados),
        "fonte_literais_cobertura": round(len(achados) / len(unicos), 4) if unicos else 0.0,
        "razao_funcoes_rea_sobre_fonte": round(len(proprios) / gabarito["funcoes_total"], 4)
        if gabarito["funcoes_total"] else 0.0,
    }
