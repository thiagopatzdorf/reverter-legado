"""Formulários Delphi (.dfm), em texto ou binário (TPF0), na mesma árvore de dados.

O binário importa porque projeto antigo costuma ter .dfm binário, e executável
sem fonte guarda o formulário assim nos recursos. Os dois leitores devolvem a
mesma árvore; o teste prova isso convertendo um no outro.
"""
from __future__ import annotations

import re
import struct


class Ident(str):
    """Identificador (OnClick = BtnSalvarClick), diferente de string ('Salvar')."""


class Colecao(list):
    """Lista de itens `<item ... end>` (Columns, Parameters)."""


class Conjunto(list):
    """Conjunto `[akLeft, akTop]`."""


class Binario(bytes):
    """Dado binário `{ ... }` (ícone, imagem): fica só o tamanho no contrato."""


class DfmInvalido(ValueError):
    pass


# ---------------------------------------------------------------- texto

_TOKEN = re.compile(
    r"""(?P<esp>\s+)
      | (?P<str>(?:'(?:[^']|'')*'|\#\d+)+)
      | (?P<bin>\{[0-9A-Fa-f\s]*\})
      | (?P<num>-?(?:\$[0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?))
      | (?P<id>[A-Za-z_][\w.]*)
      | (?P<sim>[=:<>()\[\],+])
    """,
    re.X,
)


def _lexar(texto: str) -> list[tuple[str, str, int]]:
    tokens, linha, i = [], 1, 0
    while i < len(texto):
        m = _TOKEN.match(texto, i)
        if not m:
            raise DfmInvalido(f"linha {linha}: caractere inesperado {texto[i]!r}")
        tipo = m.lastgroup
        if tipo != "esp":
            tokens.append((tipo, m.group(0), linha))
        linha += m.group(0).count("\n")
        i = m.end()
    return tokens


def _string(bruto: str) -> str:
    partes = []
    for m in re.finditer(r"'((?:[^']|'')*)'|#(\d+)", bruto):
        partes.append(m.group(1).replace("''", "'") if m.group(1) is not None else chr(int(m.group(2))))
    return "".join(partes)


class _Texto:
    def __init__(self, texto: str):
        self.t = _lexar(texto)
        self.i = 0

    def olhar(self, k: int = 0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else (None, None, -1)

    def andar(self):
        tok = self.olhar()
        if tok[0] is None:
            raise DfmInvalido("fim inesperado do .dfm")
        self.i += 1
        return tok

    def esperar(self, valor: str):
        tok = self.andar()
        if tok[1] != valor:
            raise DfmInvalido(f"linha {tok[2]}: esperava {valor!r}, veio {tok[1]!r}")

    def objeto(self) -> dict:
        _, palavra, linha = self.andar()
        if palavra.lower() not in ("object", "inherited", "inline"):
            raise DfmInvalido(f"linha {linha}: esperava object/inherited/inline, veio {palavra!r}")
        nome, classe = "", ""
        primeiro = self.andar()[1]
        if self.olhar()[1] == ":":
            self.andar()
            nome, classe = primeiro, self.andar()[1]
        else:
            classe = primeiro
        if self.olhar()[1] == "[":
            while self.andar()[1] != "]":
                pass
        no = {"nome": nome, "classe": classe, "tipo": palavra.lower(), "propriedades": {}, "filhos": []}
        while True:
            tipo, valor, _ = self.olhar()
            if tipo is None:
                raise DfmInvalido(f"objeto {nome or classe} sem end")
            if tipo == "id" and valor.lower() == "end":
                self.andar()
                return no
            if tipo == "id" and valor.lower() in ("object", "inherited", "inline"):
                no["filhos"].append(self.objeto())
                continue
            self.andar()
            self.esperar("=")
            no["propriedades"][valor] = self.valor()

    def valor(self):
        tipo, bruto, linha = self.andar()
        if tipo == "str":
            texto = _string(bruto)
            while self.olhar()[1] == "+":
                self.andar()
                texto += _string(self.andar()[1])
            return texto
        if tipo == "num":
            if bruto.startswith("$") or bruto.startswith("-$"):
                return int(bruto.replace("$", "0x"), 16)
            return float(bruto) if any(c in bruto for c in ".eE") else int(bruto)
        if tipo == "bin":
            return Binario(bytes.fromhex(re.sub(r"[{}\s]", "", bruto)))
        if tipo == "id":
            if bruto.lower() in ("true", "false"):
                return bruto.lower() == "true"
            return Ident(bruto)
        if bruto == "(":
            itens = []
            while self.olhar()[1] != ")":
                itens.append(self.valor())
            self.andar()
            return itens
        if bruto == "[":
            itens = Conjunto()
            while self.olhar()[1] != "]":
                tok = self.andar()
                if tok[1] != ",":
                    itens.append(tok[1])
            self.andar()
            return itens
        if bruto == "<":
            itens = Colecao()
            while self.olhar()[1] != ">":
                palavra = self.andar()[1]
                if palavra.lower() != "item":
                    raise DfmInvalido(f"linha {linha}: coleção sem 'item'")
                if self.olhar()[1] == "[":  # item [3]
                    while self.andar()[1] != "]":
                        pass
                props = {}
                while not (self.olhar()[0] == "id" and self.olhar()[1].lower() == "end"):
                    nome = self.andar()[1]
                    self.esperar("=")
                    props[nome] = self.valor()
                self.andar()
                itens.append(props)
            self.andar()
            return itens
        raise DfmInvalido(f"linha {linha}: valor inesperado {bruto!r}")


def ler_texto(texto: str) -> dict:
    leitor = _Texto(texto)
    raiz = leitor.objeto()
    if leitor.olhar()[0] is not None:
        raise DfmInvalido(f"sobrou conteúdo depois do objeto raiz (linha {leitor.olhar()[2]})")
    return raiz


# ---------------------------------------------------------------- binário (TPF0)

# TValueType de Classes.pas.
VA_NULL, VA_LIST, VA_INT8, VA_INT16, VA_INT32, VA_EXTENDED, VA_STRING, VA_IDENT = range(8)
VA_FALSE, VA_TRUE, VA_BINARY, VA_SET, VA_LSTRING, VA_NIL, VA_COLLECTION = range(8, 15)
VA_SINGLE, VA_CURRENCY, VA_DATE, VA_WSTRING, VA_INT64, VA_UTF8STRING, VA_DOUBLE = range(15, 22)


class _Binario:
    def __init__(self, dados: bytes):
        self.d = dados
        self.i = 0

    def ler(self, n: int) -> bytes:
        if self.i + n > len(self.d):
            raise DfmInvalido(f"TPF0 truncado no byte {self.i}")
        b = self.d[self.i:self.i + n]
        self.i += n
        return b

    def byte(self) -> int:
        return self.ler(1)[0]

    def curta(self) -> str:
        return self.ler(self.byte()).decode("latin-1")

    def objeto(self) -> dict:
        tipo = "object"
        if self.d[self.i] & 0xF0 == 0xF0:  # prefixo: ffInherited=1, ffChildPos=2, ffInline=4
            flags = self.byte() & 0x0F
            tipo = "inherited" if flags & 1 else "inline" if flags & 4 else "object"
            if flags & 2:
                self.valor(self.byte())
        classe = self.curta()
        nome = self.curta()
        no = {"nome": nome, "classe": classe, "tipo": tipo, "propriedades": {}, "filhos": []}
        while self.d[self.i] != 0:
            prop = self.curta()
            no["propriedades"][prop] = self.valor(self.byte())
        self.i += 1
        while self.d[self.i] != 0:
            no["filhos"].append(self.objeto())
        self.i += 1
        return no

    def valor(self, va: int):
        if va == VA_LIST:
            itens = []
            while self.d[self.i] != VA_NULL:
                itens.append(self.valor(self.byte()))
            self.i += 1
            return itens
        if va == VA_INT8:
            return struct.unpack("<b", self.ler(1))[0]
        if va == VA_INT16:
            return struct.unpack("<h", self.ler(2))[0]
        if va == VA_INT32:
            return struct.unpack("<i", self.ler(4))[0]
        if va == VA_INT64:
            return struct.unpack("<q", self.ler(8))[0]
        if va == VA_EXTENDED:
            mant, se = struct.unpack("<QH", self.ler(10))
            sinal = -1 if se & 0x8000 else 1
            exp = se & 0x7FFF
            return 0.0 if exp == 0 and mant == 0 else sinal * mant * 2.0 ** (exp - 16383 - 63)
        if va == VA_SINGLE:
            return struct.unpack("<f", self.ler(4))[0]
        if va in (VA_DOUBLE, VA_DATE):
            return struct.unpack("<d", self.ler(8))[0]
        if va == VA_CURRENCY:
            return struct.unpack("<q", self.ler(8))[0] / 10000
        if va == VA_STRING:
            return self.curta()
        if va == VA_LSTRING:
            return self.ler(struct.unpack("<I", self.ler(4))[0]).decode("latin-1")
        if va == VA_UTF8STRING:
            return self.ler(struct.unpack("<I", self.ler(4))[0]).decode("utf-8")
        if va == VA_WSTRING:
            return self.ler(2 * struct.unpack("<I", self.ler(4))[0]).decode("utf-16-le")
        if va == VA_IDENT:
            return Ident(self.curta())
        if va == VA_FALSE:
            return False
        if va == VA_TRUE:
            return True
        if va == VA_NIL:
            return Ident("nil")
        if va == VA_NULL:
            return Ident("Null")
        if va == VA_BINARY:
            return Binario(self.ler(struct.unpack("<I", self.ler(4))[0]))
        if va == VA_SET:
            itens = Conjunto()
            while True:
                nome = self.curta()
                if not nome:
                    return itens
                itens.append(nome)
        if va == VA_COLLECTION:
            itens = Colecao()
            # Como o TReader.ReadCollection: [índice opcional] vaList propriedades vaNull.
            while self.d[self.i] != VA_NULL:
                if self.d[self.i] in (VA_INT8, VA_INT16, VA_INT32):
                    self.valor(self.byte())  # índice do item: não é contrato
                if self.byte() != VA_LIST:
                    raise DfmInvalido(f"item de coleção sem vaList no byte {self.i - 1}")
                props = {}
                while self.d[self.i] != 0:
                    prop = self.curta()
                    props[prop] = self.valor(self.byte())
                self.i += 1
                itens.append(props)
            self.i += 1
            return itens
        raise DfmInvalido(f"tipo de valor TPF0 desconhecido {va} no byte {self.i - 1}")


def ler_binario(dados: bytes) -> dict:
    if not dados.startswith(b"TPF0"):
        raise DfmInvalido("binário sem assinatura TPF0")
    leitor = _Binario(dados)
    leitor.i = 4
    return leitor.objeto()


def ler(dados: bytes) -> dict:
    """Detecta o formato pelo conteúdo, não pela extensão."""
    if dados.startswith(b"TPF0"):
        return ler_binario(dados)
    if dados.startswith(b"\xff\x0a\x00"):  # .dfm binário com cabeçalho de recurso RT_RCDATA
        fim = dados.find(b"TPF0")
        if fim < 0:
            raise DfmInvalido("cabeçalho de recurso sem TPF0")
        return ler_binario(dados[fim:])
    for cod in ("utf-8-sig", "cp1252"):
        try:
            return ler_texto(dados.decode(cod))
        except UnicodeDecodeError:
            continue
    raise DfmInvalido("codificação desconhecida")
