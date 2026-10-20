"""Leitor de Object Pascal (Delphi) que extrai o que um sistema novo precisa honrar.

Não é um compilador: é tolerante. O que ele não entende vira pendência no
contrato, nunca silêncio, porque contrato com buraco escondido é pior que
contrato curto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

VISIBILIDADES = {"private", "protected", "public", "published", "automated"}
ROTINAS = {"procedure", "function", "constructor", "destructor"}
# Diretivas que seguem a assinatura de um método ("procedure X; virtual; abstract;").
DIRETIVAS = {
    "virtual", "override", "abstract", "overload", "reintroduce", "dynamic", "static",
    "stdcall", "cdecl", "pascal", "register", "safecall", "inline", "final", "message",
    "deprecated", "platform", "export", "external", "forward", "assembler", "far", "near",
}
VERBOS_SQL = ("SELECT", "INSERT", "UPDATE", "DELETE", "MERGE", "WITH", "EXEC", "EXECUTE", "CREATE", "ALTER", "DROP")
_RE_TABELA = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([A-Za-z_][\w.\"\[\]]*)", re.I)
_RE_PARAM_SQL = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


@dataclass
class Token:
    tipo: str  # id, num, str, sim
    valor: str
    linha: int

    @property
    def baixo(self) -> str:
        return self.valor.lower() if self.tipo == "id" else self.valor


def lexar(texto: str) -> list[Token]:
    """Tokens sem comentários. Diretivas {$...} somem junto: não são contrato."""
    tokens: list[Token] = []
    i, n, linha = 0, len(texto), 1
    while i < n:
        c = texto[i]
        if c == "\n":
            linha += 1
            i += 1
        elif c.isspace():
            i += 1
        elif texto.startswith("//", i):
            fim = texto.find("\n", i)
            i = n if fim < 0 else fim
        elif c == "{":
            fim = texto.find("}", i)
            fim = n if fim < 0 else fim + 1
            linha += texto.count("\n", i, fim)
            i = fim
        elif texto.startswith("(*", i):
            fim = texto.find("*)", i)
            fim = n if fim < 0 else fim + 2
            linha += texto.count("\n", i, fim)
            i = fim
        elif c == "'" or c == "#":
            # Literal Pascal: 'abc''d' e #13#10 colados formam uma string só.
            partes, inicio = [], linha
            while i < n and texto[i] in "'#":
                if texto[i] == "'":
                    j = i + 1
                    while j < n:
                        if texto[j] == "'":
                            if j + 1 < n and texto[j + 1] == "'":
                                partes.append("'")
                                j += 2
                                continue
                            break
                        partes.append(texto[j])
                        j += 1
                    i = j + 1
                else:
                    m = re.match(r"#(\$[0-9A-Fa-f]+|\d+)", texto[i:])
                    if not m:
                        break
                    num = m.group(1)
                    partes.append(chr(int(num[1:], 16) if num.startswith("$") else int(num)))
                    i += m.end()
            tokens.append(Token("str", "".join(partes), inicio))
        elif c.isalpha() or c == "_" or c == "&":
            m = re.match(r"&?[A-Za-z_]\w*", texto[i:])
            tokens.append(Token("id", m.group(0).lstrip("&"), linha))
            i += m.end()
        elif c.isdigit() or c == "$":
            m = re.match(r"\$[0-9A-Fa-f]+|\d+(\.\d+)?([eE][+-]?\d+)?", texto[i:])
            tokens.append(Token("num", m.group(0), linha))
            i += max(m.end(), 1)
        else:
            dois = texto[i:i + 2]
            if dois in (":=", "<=", ">=", "<>", ".."):
                tokens.append(Token("sim", dois, linha))
                i += 2
            else:
                tokens.append(Token("sim", c, linha))
                i += 1
    return tokens


class Leitor:
    def __init__(self, tokens: list[Token]):
        self.t = tokens
        self.i = 0

    def olhar(self, k: int = 0) -> Token | None:
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def eh(self, *valores: str, k: int = 0) -> bool:
        tok = self.olhar(k)
        return tok is not None and tok.baixo in valores

    def andar(self) -> Token:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def ate(self, *valores: str) -> list[Token]:
        """Consome até (e incluindo) o primeiro token em `valores`, no nível 0 de parênteses."""
        saida, nivel = [], 0
        while self.i < len(self.t):
            tok = self.andar()
            # O terminador vem antes do parêntese: ate(")") tem que parar no ")" de fora.
            if nivel == 0 and tok.tipo != "str" and tok.baixo in valores:
                return saida
            if tok.tipo == "sim" and tok.valor in ("(", "["):
                nivel += 1
            elif tok.tipo == "sim" and tok.valor in (")", "]"):
                nivel -= 1
            saida.append(tok)
        return saida


def _texto(tokens: list[Token]) -> str:
    saida = ""
    for tok in tokens:
        # Volta a ser Pascal válido: aspa dentro da string é dobrada de novo.
        v = "'" + tok.valor.replace("'", "''") + "'" if tok.tipo == "str" else tok.valor
        if saida and (tok.tipo in ("id", "num", "str") and saida[-1].isalnum() or v[0].isalnum() and saida[-1] in ",:;="):
            saida += " "
        saida += v
    return saida


def _parametros(tokens: list[Token]) -> list[dict]:
    """`const A, B: Integer; var C: string = ''` -> lista de parâmetros nomeados."""
    grupos, atual = [], []
    for tok in tokens:
        if tok.valor == ";":
            grupos.append(atual)
            atual = []
        else:
            atual.append(tok)
    if atual:
        grupos.append(atual)
    saida = []
    for g in grupos:
        modo = ""
        if g and g[0].baixo in ("const", "var", "out", "constref"):
            modo = g[0].baixo
            g = g[1:]
        nomes, resto = [], []
        for k, tok in enumerate(g):
            if tok.valor == ":":
                resto = g[k + 1:]
                break
            if tok.tipo == "id":
                nomes.append(tok.valor)
        tipo, padrao = resto, None
        for k, tok in enumerate(resto):
            if tok.valor == "=":
                tipo, padrao = resto[:k], _texto(resto[k + 1:])
                break
        for nome in nomes:
            p = {"nome": nome, "tipo": _texto(tipo) or None, "modo": modo or None}
            if padrao is not None:
                p["padrao"] = padrao
            saida.append(p)
    return saida


def _assinatura(ler: Leitor) -> dict:
    """Lê `procedure Nome(...)[: Tipo]; [diretivas;]*` a partir da palavra-chave."""
    tipo = ler.andar().baixo
    nome_partes = [ler.andar().valor]
    while ler.eh("."):
        ler.andar()
        nome_partes.append(ler.andar().valor)
    params: list[dict] = []
    if ler.eh("("):
        ler.andar()
        params = _parametros(ler.ate(")"))
    retorno = None
    if ler.eh(":"):
        ler.andar()
        retorno = _texto(ler.ate(";")) or None
    else:
        ler.ate(";")
    diretivas = []
    while ler.olhar() and ler.olhar().baixo in DIRETIVAS:
        diretivas.append(ler.andar().baixo)
        ler.ate(";")
    r = {"tipo": tipo, "nome": ".".join(nome_partes), "parametros": params}
    if retorno:
        r["retorno"] = retorno
    if diretivas:
        r["diretivas"] = sorted(set(diretivas))
    return r


def _classe(ler: Leitor, nome: str) -> dict:
    """Corpo de `Nome = class(Pai) ... end;`. Seção sem rótulo é published (padrão do Delphi com $M+)."""
    herda = []
    if ler.eh("("):
        ler.andar()
        herda = [t.valor for t in ler.ate(")") if t.tipo == "id"]
    classe = {"nome": nome, "herda": herda, "campos": [], "metodos": [], "propriedades": []}
    vis = "published"
    while ler.olhar() is not None and not ler.eh("end"):
        if ler.eh("strict"):
            ler.andar()
            continue
        if ler.olhar().baixo in VISIBILIDADES:
            vis = ler.andar().baixo
            continue
        if ler.eh("class") and ler.olhar(1) and ler.olhar(1).baixo in ROTINAS | {"property", "var"}:
            ler.andar()
            continue
        if ler.olhar().baixo in ROTINAS:
            m = _assinatura(ler)
            m["visibilidade"] = vis
            classe["metodos"].append(m)
        elif ler.eh("property"):
            ler.andar()
            pnome = ler.andar().valor
            corpo = ler.ate(";")
            tipo = None
            for k, tok in enumerate(corpo):
                if tok.valor == ":":
                    tipo = corpo[k + 1].valor if k + 1 < len(corpo) else None
                    break
            leitura = [corpo[k + 1].valor for k, tok in enumerate(corpo) if tok.baixo == "read" and k + 1 < len(corpo)]
            escrita = [corpo[k + 1].valor for k, tok in enumerate(corpo) if tok.baixo == "write" and k + 1 < len(corpo)]
            classe["propriedades"].append({
                "nome": pnome, "tipo": tipo, "visibilidade": vis,
                "le": leitura[0] if leitura else None, "escreve": escrita[0] if escrita else None,
            })
            while ler.eh("default", "stored"):
                ler.ate(";")
        elif ler.eh("type", "const", "var"):
            ler.andar()
        else:
            decl = ler.ate(";")
            nomes, tipo = [], []
            for k, tok in enumerate(decl):
                if tok.valor == ":":
                    tipo = decl[k + 1:]
                    break
                if tok.tipo == "id":
                    nomes.append(tok.valor)
            for n in nomes:
                classe["campos"].append({"nome": n, "tipo": _texto(tipo) or None, "visibilidade": vis})
            _pular_diretivas(ler)
    if ler.olhar() is not None:
        ler.andar()  # end
        ler.ate(";")
    return classe


def _record(ler: Leitor, nome: str) -> dict:
    campos, nivel = [], 1
    while ler.olhar() is not None and nivel:
        if ler.eh("end"):
            nivel -= 1
            ler.andar()
            continue
        if ler.eh("case", "record"):
            nivel += ler.eh("record")
            ler.andar()
            continue
        decl = ler.ate(";", "end")
        if ler.t[ler.i - 1].baixo == "end":
            nivel -= 1
        nomes, tipo = [], []
        for k, tok in enumerate(decl):
            if tok.valor == ":":
                tipo = decl[k + 1:]
                break
            if tok.tipo == "id":
                nomes.append(tok.valor)
        if tipo:
            campos += [{"nome": n, "tipo": _texto(tipo)} for n in nomes]
    ler.ate(";")
    return {"nome": nome, "campos": campos}


def _secao_tipos(ler: Leitor, unidade: dict) -> None:
    """Depois de `type`: lê declarações `Nome = ...;` até outra seção."""
    while ler.olhar() is not None and ler.olhar().tipo == "id" and ler.eh("=", k=1):
        nome = ler.andar().valor
        ler.andar()
        if ler.eh("packed"):
            ler.andar()
        if ler.eh("class") and not ler.eh("of", k=1):
            ler.andar()
            if ler.eh(";"):  # declaração antecipada
                ler.andar()
                continue
            if ler.eh("(") and _fecha_em_ponto_e_virgula(ler):
                ler.ate(";")  # TFoo = class(TBar); sem corpo
                unidade["classes"].append({"nome": nome, "herda": [], "campos": [], "metodos": [], "propriedades": []})
                continue
            unidade["classes"].append(_classe(ler, nome))
        elif ler.eh("object"):
            ler.andar()  # object do Turbo Pascal: mesmo corpo que class
            unidade["classes"].append(_classe(ler, nome))
        elif ler.eh("interface", "dispinterface") and not ler.eh(";", k=1):
            # Sem isto os métodos de uma interface COM viravam rotinas soltas da unit
            # e cada um gerava uma pendência falsa de "rotina sem corpo".
            ler.andar()
            if ler.eh("("):
                ler.andar()
                ler.ate(")")
            if ler.eh("["):
                ler.andar()
                ler.ate("]")
            corpo = _classe(ler, nome)
            unidade["interfaces"].append({"nome": nome, "metodos": corpo["metodos"], "propriedades": corpo["propriedades"]})
        elif ler.eh("record"):
            ler.andar()
            unidade["registros"].append(_record(ler, nome))
        elif ler.eh("("):
            ler.andar()
            valores = [t.valor for t in ler.ate(")") if t.tipo == "id"]
            ler.ate(";")
            unidade["enumeracoes"].append({"nome": nome, "valores": valores})
        else:
            ler.ate(";")
            _pular_diretivas(ler)


def _pular_diretivas(ler: Leitor) -> None:
    """`TCb = procedure(...); cdecl;`: a diretiva depois do `;` ainda é da declaração.

    Sem isto o `cdecl` encerrava a seção type e as classes seguintes viravam
    rotinas soltas (medido no HeidiSQL, dbstructures.sqlite.pas e gnugettext.pas).
    """
    while ler.olhar() is not None and ler.olhar().baixo in DIRETIVAS:
        ler.andar()
        ler.ate(";")


def _fecha_em_ponto_e_virgula(ler: Leitor) -> bool:
    nivel, k = 0, 0
    while True:
        tok = ler.olhar(k)
        if tok is None:
            return False
        if tok.valor == "(":
            nivel += 1
        elif tok.valor == ")":
            nivel -= 1
            if nivel == 0:
                prox = ler.olhar(k + 1)
                return prox is not None and prox.valor == ";"
        k += 1


def _uses(ler: Leitor) -> list[dict]:
    ler.andar()
    saida = []
    for grupo in _dividir(ler.ate(";"), ","):
        ids = [t.valor for t in grupo if t.tipo == "id"]
        if not ids:
            continue
        item = {"unidade": ids[0] if "in" not in [t.baixo for t in grupo] else ids[0]}
        strs = [t.valor for t in grupo if t.tipo == "str"]
        if strs:
            item["arquivo"] = strs[0]
        saida.append(item)
    return saida


def _dividir(tokens: list[Token], sep: str) -> list[list[Token]]:
    grupos, atual = [], []
    for tok in tokens:
        if tok.valor == sep:
            grupos.append(atual)
            atual = []
        else:
            atual.append(tok)
    grupos.append(atual)
    return grupos


def _sql_do_corpo(tokens: list[Token], dono: str) -> tuple[list[dict], list[str]]:
    """SQL embutido num corpo de rotina, mais os nomes lidos por FieldByName.

    SQL em Delphi se monta em pedaços (`SQL.Add('...')`, `'a' + 'b'`, `SQL.Text :=`).
    Um grupo começa num literal que abre com verbo SQL e recebe os literais seguintes
    que são argumento de Add, continuação de `+` ou atribuição; acaba em Open,
    ExecSQL, Clear ou num novo verbo. Concatenação com variável marca o SQL como
    dinâmico: a tabela real só aparece em tempo de execução.
    """
    grupos: list[dict] = []
    campos: list[str] = []
    atual: dict | None = None
    for k, tok in enumerate(tokens):
        ant = tokens[k - 1] if k else None
        ant2 = tokens[k - 2] if k > 1 else None
        if tok.tipo == "id" and tok.baixo in ("open", "execsql", "clear", "active") and atual:
            grupos.append(atual)
            atual = None
            continue
        if tok.tipo != "str":
            if atual and tok.tipo == "id" and ant is not None and ant.valor == "+":
                atual["dinamico"] = True
            continue
        if ant2 is not None and ant2.baixo in ("parambyname", "fieldbyname", "findfield") and ant.valor == "(":
            if ant2.baixo != "parambyname":
                campos.append(tok.valor)
            continue
        texto = tok.valor.strip()
        construtor = ant is not None and (ant.valor in ("+", ":=") or (ant.valor == "(" and ant2 is not None and ant2.baixo == "add"))
        if texto.upper().startswith(VERBOS_SQL):
            if atual:
                grupos.append(atual)
            atual = {"partes": [texto], "linha": tok.linha, "dinamico": False}
            nxt = tokens[k + 1] if k + 1 < len(tokens) else None
            if nxt is not None and nxt.valor == "+" and k + 2 < len(tokens) and tokens[k + 2].tipo == "id":
                atual["dinamico"] = True
        elif atual and construtor:
            atual["partes"].append(texto)
            nxt = tokens[k + 1] if k + 1 < len(tokens) else None
            if nxt is not None and nxt.valor == "+" and k + 2 < len(tokens) and tokens[k + 2].tipo == "id":
                atual["dinamico"] = True
    if atual:
        grupos.append(atual)
    return [descrever_sql(" ".join(g["partes"]), f"{dono}:{g['linha']}", g["dinamico"]) for g in grupos], campos


def descrever_sql(texto: str, origem: str, dinamico: bool = False) -> dict:
    texto = re.sub(r"\s+", " ", texto).strip()
    tabelas = sorted({m.group(1).strip('"[]').upper() for m in _RE_TABELA.finditer(texto)})
    verbo = texto.split(" ", 1)[0].upper()
    d = {
        "origem": origem,
        "operacao": verbo,
        "texto": texto,
        "tabelas": tabelas,
        "parametros": sorted(set(m.group(1).upper() for m in _RE_PARAM_SQL.finditer(texto))),
    }
    if dinamico:
        d["dinamico"] = True
    return d


def ler_unidade(texto: str, arquivo: str) -> dict:
    """Uma unit (.pas) ou programa (.dpr) inteira, em forma de dados."""
    ler = Leitor(lexar(texto))
    unidade = {
        "nome": None, "arquivo": arquivo, "tipo": None, "usa": [], "classes": [], "registros": [],
        "enumeracoes": [], "rotinas": [], "implementadas": [], "sql": [], "campos_lidos": [],
        "corpos": {}, "interfaces": [],
    }
    if ler.eh("unit", "program", "library", "package"):
        unidade["tipo"] = ler.andar().baixo
        partes = [ler.andar().valor]
        while ler.eh("."):
            ler.andar()
            partes.append(ler.andar().valor)
        unidade["nome"] = ".".join(partes)
        ler.ate(";")
    secao = "interface" if unidade["tipo"] == "unit" else "implementation"
    while ler.olhar() is not None:
        if ler.eh("interface"):
            secao = "interface"
            ler.andar()
        elif ler.eh("implementation"):
            secao = "implementation"
            ler.andar()
        elif ler.eh("uses"):
            usa = _uses(ler)
            for u in usa:
                u["secao"] = secao
            unidade["usa"] += usa
        elif ler.eh("type"):
            ler.andar()
            _secao_tipos(ler, unidade)
        elif _inicia_rotina(ler) or (ler.eh("class") and ler.olhar(1) and ler.olhar(1).baixo in ROTINAS):
            if ler.eh("class"):
                ler.andar()
            assinatura = _assinatura(ler)
            if secao == "interface":
                unidade["rotinas"].append(assinatura)
            elif "forward" not in assinatura.get("diretivas", []) and "external" not in assinatura.get("diretivas", []):
                corpo = _corpo(ler)
                unidade["implementadas"].append(assinatura["nome"])
                unidade["corpos"][assinatura["nome"]] = _alcance(corpo)
                sql, campos = _sql_do_corpo(corpo, arquivo)
                for s in sql:
                    s["rotina"] = assinatura["nome"]
                unidade["sql"] += sql
                unidade["campos_lidos"] += campos
        elif ler.eh("begin") and unidade["tipo"] != "unit":
            ler.andar()
            corpo = _ate_end_casado(ler)
            sql, campos = _sql_do_corpo(corpo, arquivo)
            unidade["sql"] += sql
        else:
            ler.andar()
    unidade["campos_lidos"] = sorted(set(c.upper() for c in unidade["campos_lidos"]))
    return unidade


def _alcance(corpo: list[Token]) -> dict:
    """O que um corpo toca: identificadores (para achar chamadas) e datasets que ele abre.

    `DmDados.QryClientes.Open` abre QryClientes; o SQL dela está no .dfm, e sem
    esta ligação o clique pareceria não falar com o banco.
    """
    abre = set()
    for k, tok in enumerate(corpo):
        if tok.baixo in ("open", "execsql", "active") and k >= 2 and corpo[k - 1].valor == "." and corpo[k - 2].tipo == "id":
            abre.add(corpo[k - 2].valor)
    return {"ids": sorted({t.baixo for t in corpo if t.tipo == "id"}), "abre": sorted(abre)}


def _inicia_rotina(ler: Leitor) -> bool:
    """`procedure Nome` abre uma rotina; `X: procedure(...)` é só um tipo procedural.

    Medido no HeidiSQL (apphelpers.pas): uma variável `procedure(p1, p2); stdcall`
    era lida como rotina aninhada e o leitor perdia as 72 rotinas seguintes.
    """
    tok, prox = ler.olhar(), ler.olhar(1)
    # `procedure of object` também é tipo (medido no gnugettext.pas do HeidiSQL).
    return tok is not None and tok.baixo in ROTINAS and prox is not None and prox.tipo == "id" and prox.baixo != "of"


def _corpo(ler: Leitor) -> list[Token]:
    """Seções locais (var/const/rotinas aninhadas) e o bloco begin..end; da rotina."""
    corpo: list[Token] = []
    while ler.olhar() is not None and not ler.eh("begin", "asm"):
        if _inicia_rotina(ler):
            _assinatura(ler)
            corpo += _corpo(ler)
            continue
        corpo.append(ler.andar())
    if ler.olhar() is None:
        return corpo
    ler.andar()
    corpo += _ate_end_casado(ler)
    if ler.eh(";"):
        ler.andar()
    return corpo


def _ate_end_casado(ler: Leitor) -> list[Token]:
    nivel, saida = 1, []
    while ler.olhar() is not None:
        tok = ler.andar()
        if tok.baixo in ("begin", "case", "try", "asm"):
            nivel += 1
        elif tok.baixo == "record" and saida and saida[-1].valor in (":", "="):
            nivel += 1
        elif tok.baixo == "end":
            nivel -= 1
            if nivel == 0:
                return saida
        saida.append(tok)
    return saida
