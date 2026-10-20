"""Gabarito do fonte C: funções definidas e literais de texto, por arquivo e linha.

É o lado "verdade" da medição. Lê só o fonte (texto); o executável nunca passa
por aqui. O leitor é tolerante, não é compilador: `#if` não é avaliado (os dois
ramos entram) e macro que gera função não é expandida. Por isso a contagem do
fonte é um TETO do que pode estar no binário: o linker ainda descarta objeto
não usado e o -O2 embute (inline) função `static` pequena.
"""
from __future__ import annotations

import re
from pathlib import Path

# Palavras que aparecem antes de `(` num cabeçalho e não são nome de função.
_NAO_NOME = {"if", "for", "while", "switch", "return", "sizeof", "__attribute__", "defined"}
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "'": "'", "a": "\a", "b": "\b"}


def _limpar(texto: str) -> tuple[str, list[tuple[int, str]]]:
    """Troca comentário, literal e diretiva de pré-processador por espaço, preservando as quebras
    de linha (para o número da linha continuar certo). Devolve o texto limpo e os literais
    de texto como (linha, valor sem escape)."""
    saida: list[str] = []
    literais: list[tuple[int, str]] = []
    i, n, linha = 0, len(texto), 1
    inicio_de_linha = True
    while i < n:
        c = texto[i]
        if c == "\n":
            saida.append(c)
            linha += 1
            inicio_de_linha = True
            i += 1
            continue
        if inicio_de_linha and c == "#":
            # diretiva até o fim da linha, com continuação por barra invertida
            while i < n and texto[i] != "\n":
                if texto[i] == "\\" and i + 1 < n and texto[i + 1] == "\n":
                    saida.append("\n")
                    linha += 1
                    i += 2
                    continue
                i += 1
            continue
        if c in " \t\r":
            saida.append(c)
            i += 1
            continue
        inicio_de_linha = False
        if texto.startswith("//", i):
            while i < n and texto[i] != "\n":
                i += 1
            continue
        if texto.startswith("/*", i):
            fim = texto.find("*/", i + 2)
            fim = n if fim < 0 else fim + 2
            pedaco = texto[i:fim]
            saida.append("\n" * pedaco.count("\n") or " ")
            linha += pedaco.count("\n")
            i = fim
            continue
        if c in "\"'":
            j, valor = i + 1, []
            while j < n and texto[j] != c:
                if texto[j] == "\\" and j + 1 < n:
                    valor.append(_ESCAPES.get(texto[j + 1], texto[j + 1]))
                    j += 2
                    continue
                if texto[j] == "\n":  # literal sem fecho: para na linha
                    break
                valor.append(texto[j])
                j += 1
            if c == '"':
                literais.append((linha, "".join(valor)))
            saida.append(" ")
            i = j + 1
            continue
        saida.append(c)
        i += 1
    return "".join(saida), literais


def _nome_da_funcao(cabecalho: str) -> tuple[str, int] | None:
    """(nome, posição no cabeçalho) de `tipo nome(args)`, ou None se não for definição de função."""
    cab = cabecalho.rstrip()
    if not cab.endswith(")") or "=" in cab.split("(", 1)[0]:
        return None
    # primeiro `(` cujo identificador anterior não é palavra reservada
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", cab):
        if m.group(1) not in _NAO_NOME:
            if not cab[: m.start()].strip():  # sem tipo de retorno: macro solta, não definição
                return None
            return m.group(1), m.start()
    return None


def ler_arquivo(caminho: Path, rotulo: str) -> dict:
    texto = Path(caminho).read_text(encoding="utf-8", errors="replace")
    limpo, literais = _limpar(texto)
    funcoes = []
    profundidade = 0
    inicio_cab, linha_cab = 0, 1
    linha = 1
    for i, c in enumerate(limpo):
        if c == "\n":
            linha += 1
        elif c == "{":
            if profundidade == 0:
                cab = limpo[inicio_cab:i]
                achado = _nome_da_funcao(cab)
                if achado:
                    nome, pos = achado
                    funcoes.append({
                        "nome": nome,
                        "arquivo": rotulo,
                        "linha": linha_cab + cab[:pos].count("\n"),
                        "static": bool(re.search(r"\bstatic\b", cab[:pos])),
                    })
            profundidade += 1
        elif c == "}":
            profundidade = max(0, profundidade - 1)
            if profundidade == 0:
                inicio_cab, linha_cab = i + 1, linha
        elif c == ";" and profundidade == 0:
            inicio_cab, linha_cab = i + 1, linha
    return {
        "funcoes": funcoes,
        "literais": [{"arquivo": rotulo, "linha": ln, "texto": v} for ln, v in literais],
    }


def gabarito(raiz: Path, arquivos: list[str]) -> dict:
    """Junta `arquivos` (relativos a `raiz`, na ordem dada) num gabarito determinístico."""
    raiz = Path(raiz)
    funcoes, literais, faltando = [], [], []
    for rel in arquivos:
        p = raiz / rel
        if not p.is_file():
            faltando.append(rel)
            continue
        r = ler_arquivo(p, rel)
        funcoes += r["funcoes"]
        literais += r["literais"]
    nomes = sorted({f["nome"] for f in funcoes})
    return {
        "arquivos": len(arquivos) - len(faltando),
        "faltando": faltando,
        "funcoes": funcoes,
        "funcoes_total": len(funcoes),
        "funcoes_nomes_distintos": len(nomes),
        "funcoes_static": sum(1 for f in funcoes if f["static"]),
        "literais": literais,
        "literais_total": len(literais),
    }
