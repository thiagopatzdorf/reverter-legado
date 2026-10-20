"""Leitor de WAD (o arquivo de dados do Doom) escrito a partir do BINÁRIO, não do fonte.

Cada campo abaixo cita o endereço no `chocolate-doom.exe` 3.1.1 onde o REA/Ghidra mostrou
o acesso (evidência em `casos/chocolate-doom/evidencia/`). O fonte (`w_wad.h`) só entra
depois, como gabarito: o teste e o README dizem se bateu.

É um parser de arquivo de dados do jogo, não de estrutura do executável: o executável
continua sendo lido só pelo REA.
"""
from __future__ import annotations

import hashlib
import re
import struct
from pathlib import Path

# Cabeçalho: W_AddFile (FUN_140023170) lê 12 bytes do offset 0 (0x1400231e4..f4: EDX=0, R9D=0xc).
CABECALHO = [
    # (campo, offset, tamanho, tipo, de onde saiu no binário)
    ("identificacao", 0, 4, "ascii", "strncmp(local_44,\"IWAD\",4) e \"PWAD\" logo após a 1a leitura"),
    ("numlumps", 4, 4, "int32 LE", "local_40, usado como contagem (local_40 << 4 bytes de diretório)"),
    ("infotableofs", 8, 4, "int32 LE", "0x140023260: MOV EDX,[RSP+0x2c] = cabeçalho+8 vira o offset da 2a leitura"),
]
TAMANHO_CABECALHO = 12

# Entrada do diretório: passo de 0x10 no laço de W_AddFile; nome copiado com strncpy(...,8).
ENTRADA = [
    ("filepos", 0, 4, "int32 LE", "*(_Source - 8) -> lumpinfo+0x10"),
    ("size", 4, 4, "int32 LE", "*(_Source - 4) -> lumpinfo+0x14"),
    ("name", 8, 8, "ascii, NUL à direita", "strncpy(lumpinfo, _Source, 8)"),
]
TAMANHO_ENTRADA = 16

# Limite do vanilla que o binário impõe a PWAD: `0xfce < numlumps` -> I_Error (4046 lumps).
LIMITE_LUMPS_PWAD = 0xFCE

_MAPA = re.compile(r"^(E[1-9]M[1-9]|MAP[0-9][0-9])$")


class WadInvalido(ValueError):
    pass


def ler(dados: bytes) -> dict:
    """Cabeçalho + diretório. Recusa o que o próprio jogo recusaria (identificação errada)."""
    if len(dados) < TAMANHO_CABECALHO:
        raise WadInvalido("arquivo menor que o cabeçalho de 12 bytes")
    ident = dados[0:4]
    if ident not in (b"IWAD", b"PWAD"):
        raise WadInvalido(f"identificação {ident!r}: o jogo para com \"doesn't have IWAD or PWAD id\"")
    numlumps, infotableofs = struct.unpack_from("<ii", dados, 4)
    fim_dir = infotableofs + numlumps * TAMANHO_ENTRADA
    if numlumps < 0 or infotableofs < 0 or fim_dir > len(dados):
        raise WadInvalido(f"diretório fora do arquivo ({infotableofs}+{numlumps}*16 > {len(dados)})")
    lumps = []
    for i in range(numlumps):
        pos, tam, nome = struct.unpack_from("<ii8s", dados, infotableofs + i * TAMANHO_ENTRADA)
        lumps.append({"i": i, "nome": nome.split(b"\0", 1)[0].decode("ascii", "replace"),
                      "filepos": pos, "size": tam})
    return {"identificacao": ident.decode(), "numlumps": numlumps, "infotableofs": infotableofs,
            "lumps": lumps}


def resumo(caminho: Path) -> dict:
    dados = Path(caminho).read_bytes()
    w = ler(dados)
    fora = [l["nome"] for l in w["lumps"] if l["size"] and l["filepos"] + l["size"] > len(dados)]
    mapas = [l["nome"] for l in w["lumps"] if _MAPA.match(l["nome"])]
    return {
        "arquivo": Path(caminho).name,
        "bytes": len(dados),
        "sha256": hashlib.sha256(dados).hexdigest(),
        "identificacao": w["identificacao"],
        "numlumps": w["numlumps"],
        "infotableofs": w["infotableofs"],
        "diretorio_termina_no_fim_do_arquivo": w["infotableofs"] + w["numlumps"] * TAMANHO_ENTRADA == len(dados),
        "lumps_vazios": sum(1 for l in w["lumps"] if l["size"] == 0),
        "lumps_fora_do_arquivo": fora,
        "mapas": mapas,
        "acima_do_limite_vanilla_de_pwad": w["identificacao"] == "PWAD" and w["numlumps"] > LIMITE_LUMPS_PWAD,
        "primeiros": [l["nome"] for l in w["lumps"][:5]],
        "maiores": [f'{l["nome"]}:{l["size"]}' for l in sorted(w["lumps"], key=lambda l: (-l["size"], l["i"]))[:5]],
    }


# Cabeçalho do save (.dsg), também tirado do binário: escrito por FUN_14003c8f0 e lido por
# FUN_14003ca00 (os dois referenciam o texto "version %i"). Documentado, não lido de save real.
SAVE_CABECALHO = [
    ("descricao", 0, 24, "texto, completado com NUL", "laço até 0x18 com FUN_14003c4d0(0)"),
    ("versao", 24, 16, "texto \"version N\"", "snprintf(buf,0x10,\"version %i\",FUN_14002dd40()); leitura compara com strcmp"),
    ("gameskill", 40, 1, "byte", "1o byte após a versão (DAT_140149b68)"),
    ("gameepisode", 41, 1, "byte", "DAT_140149b60"),
    ("gamemap", 42, 1, "byte", "DAT_140149b5c"),
    ("playeringame", 43, 4, "4 bytes (um por jogador)", "laço DAT_140149b20..b30 (4 ints, 1 byte cada)"),
    ("leveltime", 47, 3, "24 bits big-endian", "b2*0x10000 + b3*0x100 + b4"),
]
TAMANHO_SAVE_CABECALHO = 50


def versao_do_save(gameversion: int) -> int:
    """FUN_14002dd40: `gameversion + 0x68` se `gameversion - 2 <= 2` (sem sinal), senão 0x6d (109)."""
    return gameversion + 0x68 if 0 <= gameversion - 2 <= 2 else 0x6D
