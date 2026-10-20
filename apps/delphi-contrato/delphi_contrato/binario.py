"""Executável Delphi (.exe/.dll/.bpl) -> contrato, sem o fonte e sem rodar nada.

O Delphi grava cada formulário dentro do executável como recurso RCDATA no
mesmo formato TPF0 do .dfm binário, com o nome da classe. Então as telas, os
componentes, as ligações de dados, o SQL dos componentes e os eventos saem
exatos do binário. O que o binário não dá é o corpo das rotinas: por isso a
ligação clique -> SQL vira pendência explícita, e o REA (Ghidra) é o passo
seguinte para quem precisar dela.

Só biblioteca padrão. O arquivo é lido como bytes; nada é carregado nem executado.
"""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path

from . import contrato, dfm, pascal

RT_RCDATA = 10
EXTENSOES = {".exe", ".dll", ".bpl", ".ocx"}
_ASCII = re.compile(rb"[\x20-\x7e\t\r\n]{12,}")
_UTF16 = re.compile(rb"(?:[\x20-\x7e\t\r\n]\x00){12,}")
_VERBO = re.compile(r"^\s*(" + "|".join(pascal.VERBOS_SQL) + r")\s", re.I)


class BinarioInvalido(ValueError):
    pass


def _u16(d: bytes, i: int) -> int:
    return struct.unpack_from("<H", d, i)[0]


def _u32(d: bytes, i: int) -> int:
    return struct.unpack_from("<I", d, i)[0]


def secoes(d: bytes) -> tuple[str, list[dict], tuple[int, int]]:
    """Formato (PE32/PE32+), seções e o diretório de recursos (RVA, tamanho)."""
    if d[:2] != b"MZ":
        raise BinarioInvalido("não é executável Windows (sem 'MZ')")
    pe = _u32(d, 0x3C)
    if d[pe:pe + 4] != b"PE\0\0":
        raise BinarioInvalido("cabeçalho PE ausente")
    coff = pe + 4
    nsec, tam_opt = _u16(d, coff + 2), _u16(d, coff + 16)
    opt = coff + 20
    magic = _u16(d, opt)
    if magic not in (0x10B, 0x20B):
        raise BinarioInvalido(f"optional header desconhecido {magic:#x}")
    diretorios = opt + (96 if magic == 0x10B else 112)
    recursos = (0, 0)
    if _u32(d, diretorios - 4) > 2:
        recursos = (_u32(d, diretorios + 16), _u32(d, diretorios + 20))
    lista = []
    for k in range(nsec):
        h = opt + tam_opt + 40 * k
        lista.append({
            "nome": d[h:h + 8].rstrip(b"\0").decode("latin-1"),
            "rva": _u32(d, h + 12), "tam_virtual": _u32(d, h + 8),
            "tam_bruto": _u32(d, h + 16), "ptr_bruto": _u32(d, h + 20),
        })
    return ("PE32" if magic == 0x10B else "PE32+"), lista, recursos


def _offset(lista: list[dict], rva: int) -> int:
    for s in lista:
        if s["rva"] <= rva < s["rva"] + max(s["tam_virtual"], s["tam_bruto"]):
            return s["ptr_bruto"] + rva - s["rva"]
    raise BinarioInvalido(f"RVA {rva:#x} fora das seções")


def recursos_rcdata(d: bytes) -> list[tuple[str, bytes]]:
    """(nome, bytes) de cada recurso RCDATA. Nome é a classe do formulário (TFRMCLIENTES)."""
    _, lista, (rva, tam) = secoes(d)
    if not rva:
        return []
    base = _offset(lista, rva)

    def entradas(off: int):
        n = _u16(d, base + off + 12) + _u16(d, base + off + 14)
        for k in range(n):
            e = base + off + 16 + 8 * k
            yield _u32(d, e), _u32(d, e + 4)

    def nome(valor: int) -> str:
        if valor & 0x80000000:
            p = base + (valor & 0x7FFFFFFF)
            return d[p + 2:p + 2 + 2 * _u16(d, p)].decode("utf-16-le")
        return f"#{valor}"

    saida = []
    for tipo, sub in entradas(0):
        if tipo != RT_RCDATA or not sub & 0x80000000:
            continue
        for nm, sub2 in entradas(sub & 0x7FFFFFFF):
            if not sub2 & 0x80000000:
                continue
            for _, folha in entradas(sub2 & 0x7FFFFFFF):
                if folha & 0x80000000:
                    continue
                dado_rva, dado_tam = _u32(d, base + folha), _u32(d, base + folha + 4)
                inicio = _offset(lista, dado_rva)
                saida.append((nome(nm), d[inicio:inicio + dado_tam]))
                break
    return sorted(saida)


def _fora_dos_recursos(d: bytes, lista: list[dict], recursos: tuple[int, int]) -> list[tuple[int, bytes]]:
    """Bytes de cada seção que não é a de recursos: o SQL dos .dfm já sai dos formulários."""
    pedacos = []
    for s in lista:
        if recursos[0] and s["rva"] <= recursos[0] < s["rva"] + max(s["tam_virtual"], s["tam_bruto"]):
            continue
        pedacos.append((s["ptr_bruto"], d[s["ptr_bruto"]:s["ptr_bruto"] + s["tam_bruto"]]))
    return pedacos


def sql_nas_strings(d: bytes, lista: list[dict], recursos: tuple[int, int], nome: str) -> list[dict]:
    """Constantes de texto que começam com verbo SQL, em ANSI ou UTF-16 (Delphi 2009+)."""
    saida = []
    for base, bloco in _fora_dos_recursos(d, lista, recursos):
        for regex, cod in ((_ASCII, "latin-1"), (_UTF16, "utf-16-le")):
            for m in regex.finditer(bloco):
                texto = m.group(0).decode(cod)
                if _VERBO.match(texto):
                    s = pascal.descrever_sql(texto, f"{nome}:{base + m.start():#010x}")
                    s["codificacao"] = "ansi" if cod == "latin-1" else "utf-16"
                    saida.append(s)
    return saida


def metodo_publicado(blocos: list[bytes], nome: str) -> bool:
    """O handler está na tabela de métodos publicados? Lá o nome é ShortString (tamanho + texto).

    Sem essa entrada o Delphi nem carrega o formulário ("Method X not found"), então
    a presença é a melhor prova de implementação que o binário oferece sem desmontar código.
    """
    alvo = bytes([len(nome)]) + nome.encode("latin-1", "replace")
    return any(alvo in b for b in blocos)


def extrair(caminho: Path) -> dict:
    d = Path(caminho).read_bytes()
    nome = Path(caminho).name
    formato, lista, recursos = secoes(d)
    blocos = [b for _, b in _fora_dos_recursos(d, lista, recursos)]
    formularios, sql, pendencias, ignorados = [], [], [], 0

    for recurso, dados in recursos_rcdata(d):
        if not dados.startswith(b"TPF0"):
            ignorados += 1  # ícone, imagem, versão: RCDATA que não é formulário
            continue
        rel = f"{nome}:RCDATA/{recurso}"
        try:
            arvore = dfm.ler_binario(dados)
        except dfm.DfmInvalido as erro:
            pendencias.append({"tipo": "arquivo_ilegivel", "onde": rel, "detalhe": str(erro)})
            continue
        form = contrato.formulario(rel, arvore, None)
        # Classe ausente do código: a unit foi linkada (o recurso veio junto), mas nada
        # instancia a tela e o linker tirou a classe. Medido no HeidiSQL 12.21 (TfrmSyncDB):
        # uma pendência para a tela, não uma por handler.
        viva = metodo_publicado(blocos, arvore["classe"])
        form["classe_no_binario"] = viva
        if not viva:
            pendencias.append({"tipo": "tela_sem_codigo", "onde": rel,
                               "detalhe": f"classe {arvore['classe']} não está no código compilado: a tela foi embutida, "
                                          "mas nada a abre e o linker removeu a classe e os handlers"})
        for e in form["eventos"]:
            e["implementado"] = viva and metodo_publicado(blocos, e["handler"])
            if viva and not e["implementado"]:
                pendencias.append({"tipo": "evento_sem_implementacao", "onde": f"{rel}:{e['componente']}.{e['evento']}",
                                   "detalhe": f"{e['rotina']} (ausente da tabela de métodos publicados)"})
        formularios.append(form)
        contrato._sql_do_dfm(arvore, rel, sql)

    sql += sql_nas_strings(d, lista, recursos, nome)
    if formularios:
        pendencias.append({"tipo": "sem_fonte", "onde": nome,
                           "detalhe": "o binário não traz o corpo das rotinas: clique -> SQL exige o fonte ou a evidência do REA"})

    operacoes = [{
        "id": f"{f['nome']}.{e['componente']}.{e['evento']}", "formulario": f["nome"],
        "gatilho": f"{e['componente']}.{e['evento']}", "rotina": e["rotina"], "implementado": e["implementado"],
        "chama": [], "sql": [], "tabelas": [], "parametros": [],
    } for f in formularios for e in f["eventos"]]

    tabelas: dict[str, list[str]] = {}
    for s in sql:
        for t in s["tabelas"]:
            tabelas.setdefault(t, []).append(s["origem"])

    c = {
        "versao": contrato.VERSAO,
        "origem": {"tipo": "binario", "formato": formato,
                   "arquivos": [{"caminho": nome, "sha256": hashlib.sha256(d).hexdigest()}]},
        "unidades": [], "classes": [],
        "formularios": sorted(formularios, key=lambda f: f["arquivo"]),
        "sql": sorted(sql, key=lambda s: s["origem"]),
        "tabelas": {t: sorted(set(o)) for t, o in sorted(tabelas.items())},
        "operacoes": sorted(operacoes, key=lambda o: o["id"]),
        "pendencias": sorted(pendencias, key=lambda p: (p["tipo"], p["onde"], p["detalhe"])),
    }
    c["cobertura"] = {
        "arquivos": 1, "unidades": 0, "formularios": len(formularios),
        "componentes": sum(len(f["componentes"]) for f in formularios),
        "eventos": len(operacoes), "eventos_implementados": sum(o["implementado"] for o in operacoes),
        "sql": len(sql), "tabelas": len(tabelas), "operacoes": len(operacoes), "pendencias": len(pendencias),
        "rcdata_nao_formulario": ignorados,
    }
    return c
