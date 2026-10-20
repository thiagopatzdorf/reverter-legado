"""Executável × fonte: o contrato tirado do binário é o mesmo que o tirado do código?

É a prova de que dá para trabalhar só com o .exe quando o fonte se perdeu: onde os
dois existem, as telas têm de bater componente por componente, propriedade por
propriedade e evento por evento. O que só um lado tem vira lista, com o motivo
quando o binário sabe dizer (tela embutida cuja classe o linker removeu).
"""
from __future__ import annotations

import json


def _assinatura(f: dict) -> tuple:
    componentes = sorted((c["nome"], c["classe"], json.dumps(c.get("propriedades", {}), sort_keys=True))
                         for c in f["componentes"])
    eventos = sorted((e["componente"], e["evento"], e["handler"]) for e in f["eventos"])
    props = json.dumps(f.get("propriedades", {}), sort_keys=True)
    return componentes, eventos, props


def comparar(do_exe: dict, do_fonte: dict) -> dict:
    exe = {f["classe"].lower(): f for f in do_exe["formularios"]}
    fonte = {f["classe"].lower(): f for f in do_fonte["formularios"]}
    comuns = sorted(set(exe) & set(fonte))
    diferentes = []
    for k in comuns:
        a, b = _assinatura(exe[k]), _assinatura(fonte[k])
        if a != b:
            diferentes.append({
                "tela": fonte[k]["classe"],
                "componentes": len(set(a[0]) ^ set(b[0])), "eventos": len(set(a[1]) ^ set(b[1])),
                "propriedades_da_tela": a[2] != b[2],
            })
    mortas = {p["onde"].rsplit("/", 1)[-1].lower() for p in do_exe["pendencias"] if p["tipo"] == "tela_sem_codigo"}
    return {
        "telas_exe": len(exe), "telas_fonte": len(fonte), "telas_em_comum": len(comuns),
        "telas_identicas": len(comuns) - len(diferentes), "diferentes": diferentes,
        "so_no_exe": [{"tela": exe[k]["classe"], "classe_no_codigo": k not in mortas} for k in sorted(set(exe) - set(fonte))],
        "so_no_fonte": [fonte[k]["classe"] for k in sorted(set(fonte) - set(exe))],
        "telas_sem_codigo_no_exe": sorted(exe[k]["classe"] for k in exe if k in mortas),
        "componentes_em_comum": sum(len(fonte[k]["componentes"]) for k in comuns),
        "eventos_em_comum": sum(len(fonte[k]["eventos"]) for k in comuns),
    }
