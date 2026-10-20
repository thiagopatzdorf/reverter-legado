"""Artefatos Delphi sintéticos para teste: .dfm binário (TPF0) e executável PE com recursos.

Nada aqui roda nem vai para produção: só monta bytes no formato que o Delphi grava,
para os leitores serem provados sem commitar um .exe de verdade.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delphi_contrato import dfm  # noqa: E402


def tpf0(no: dict) -> bytes:
    """Escritor TPF0 mínimo: o teste prova que os dois leitores concordam e monta o .exe sintético."""
    def curta(s):
        b = s.encode("latin-1")
        return bytes([len(b)]) + b

    def valor(v):
        if isinstance(v, bool):
            return bytes([dfm.VA_TRUE if v else dfm.VA_FALSE])
        if isinstance(v, int):
            return bytes([dfm.VA_INT16]) + struct.pack("<h", v) if -32768 <= v < 32768 else bytes([dfm.VA_INT32]) + struct.pack("<i", v)
        if isinstance(v, dfm.Ident):
            return bytes([dfm.VA_IDENT]) + curta(v)
        if isinstance(v, str):
            try:
                return bytes([dfm.VA_STRING]) + curta(v)
            except UnicodeEncodeError:
                b = v.encode("utf-16-le")
                return bytes([dfm.VA_WSTRING]) + struct.pack("<I", len(b) // 2) + b
        if isinstance(v, dfm.Conjunto):
            return bytes([dfm.VA_SET]) + b"".join(curta(x) for x in v) + b"\x00"
        if isinstance(v, dfm.Colecao):
            corpo = b"".join(bytes([dfm.VA_LIST]) + b"".join(curta(k) + valor(x) for k, x in item.items()) + b"\x00" for item in v)
            return bytes([dfm.VA_COLLECTION]) + corpo + b"\x00"
        if isinstance(v, list):
            return bytes([dfm.VA_LIST]) + b"".join(valor(x) for x in v) + b"\x00"
        raise TypeError(type(v))

    def obj(n):
        props = b"".join(curta(k) + valor(v) for k, v in n["propriedades"].items())
        return curta(n["classe"]) + curta(n["nome"]) + props + b"\x00" + b"".join(obj(f) for f in n["filhos"]) + b"\x00"

    return b"TPF0" + obj(no)


def _alinhar(b: bytes, n: int) -> bytes:
    return b + b"\0" * (-len(b) % n)


def pe(rcdata: dict[str, bytes], codigo: bytes) -> bytes:
    """PE32 com duas seções: .text (`codigo`) e .rsrc (cada item de `rcdata` como RT_RCDATA/nome/0409)."""
    rva_text, rva_rsrc = 0x1000, 0x1000 + ((len(codigo) + 0xFFF) & ~0xFFF)
    nomes = sorted(rcdata)
    n = len(nomes)
    # Layout: raiz, nível 2 (nomes), um nível 3 por nome, entradas de dado, strings de nome, dados.
    o_l2 = 16 + 8
    o_l3 = o_l2 + 16 + 8 * n
    o_dado = o_l3 + n * (16 + 8)
    o_str = o_dado + 16 * n
    strs, o_nomes = b"", []
    for nm in nomes:
        o_nomes.append(o_str + len(strs))
        strs += struct.pack("<H", len(nm)) + nm.encode("utf-16-le")
    o_bytes = (o_str + len(strs) + 3) & ~3
    dirx = lambda nid: struct.pack("<IIHHHH", 0, 0, 0, 0, 0, nid)  # noqa: E731
    dirn = lambda nn: struct.pack("<IIHHHH", 0, 0, 0, 0, nn, 0)  # noqa: E731
    r = dirx(1) + struct.pack("<II", 10, 0x80000000 | o_l2)
    r += dirn(n) + b"".join(struct.pack("<II", 0x80000000 | o_nomes[k], 0x80000000 | (o_l3 + 24 * k)) for k in range(n))
    r += b"".join(dirx(1) + struct.pack("<II", 0x0409, o_dado + 16 * k) for k in range(n))
    dados, pos = b"", []
    for nm in nomes:
        pos.append(o_bytes + len(dados))
        dados = _alinhar(dados + rcdata[nm], 4)
    r += b"".join(struct.pack("<IIII", rva_rsrc + pos[k], len(rcdata[nomes[k]]), 0, 0) for k in range(n))
    r = _alinhar(r + strs, 4)
    assert len(r) == o_bytes
    rsrc = r + dados

    cab = bytearray(0x200)
    cab[0:2] = b"MZ"
    struct.pack_into("<I", cab, 0x3C, 0x40)
    cab[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", cab, 0x44, 0x14C, 2, 0, 0, 0, 224, 0x0102)
    opt = 0x58
    struct.pack_into("<H", cab, opt, 0x10B)
    struct.pack_into("<I", cab, opt + 92, 16)
    struct.pack_into("<II", cab, opt + 96 + 16, rva_rsrc, len(rsrc))
    texto_bruto = _alinhar(codigo, 0x200)
    sec = opt + 224
    for k, (nome, rva, bruto, ptr) in enumerate([(b".text", rva_text, texto_bruto, 0x200),
                                                  (b".rsrc", rva_rsrc, _alinhar(rsrc, 0x200), 0x200 + len(texto_bruto))]):
        struct.pack_into("<8sIIII", cab, sec + 40 * k, nome, len(bruto), rva, len(bruto), ptr)
    return bytes(cab) + texto_bruto + _alinhar(rsrc, 0x200)


CADASTRO = Path(__file__).resolve().parent / "fixtures" / "cadastro"
METODOS_CADASTRO = ("TFrmClientes", "TDmDados", "FormShow", "BtnSalvarClick")


def cadastro_exe(metodos=METODOS_CADASTRO) -> bytes:
    """O exemplo `cadastro` "compilado": as duas telas como RCDATA, a tabela de métodos publicados
    com `metodos` e dois SQL soltos no código (UTF-16 e ANSI). Os testes e o exemplo da página do
    navegador usam este mesmo executável, então provam a mesma coisa."""
    rcdata = {classe: tpf0(dfm.ler((CADASTRO / arquivo).read_bytes()))
              for classe, arquivo in (("TFRMCLIENTES", "UClientes.dfm"), ("TDMDADOS", "UDados.dfm"))}
    rcdata["PACKAGEINFO"] = b"\x00\x01nao e formulario"
    codigo = b"\x90" * 16 + b"".join(bytes([len(m)]) + m.encode() for m in metodos) + b"\x00" * 8
    codigo += "INSERT INTO CLIENTES (CODIGO, NOME, CPF) VALUES (:CODIGO, :NOME, :CPF)".encode("utf-16-le") + b"\x00\x00"
    codigo += b"\x00SELECT MAX(CODIGO) AS ULTIMO FROM \x00curto\x00"
    return pe(rcdata, codigo)
