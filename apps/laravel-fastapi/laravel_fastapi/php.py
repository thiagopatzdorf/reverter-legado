"""PHP -> IR: a árvore do tree-sitter-php vira listas JSON pequenas e estáveis.

O contrato guarda o corpo de cada método nesta forma, e não o texto do PHP, por
dois motivos: o gerador trabalha só com o contrato (não precisa do fonte), e o
que o leitor não entende fica marcado como nó `?` com o tipo e a linha, em vez de
sumir. Cada `?` vira pendência; nada é traduzido "mais ou menos".

Nomes de classe saem resolvidos (namespace + `use`), sem a barra inicial, para o
gerador não ter de repetir a regra de resolução do PHP.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter as ts
import tree_sitter_php as tsp

_PARSER = ts.Parser(ts.Language(tsp.language_php()))

# Tipos que o PHP trata como palavra-chave, não como classe: não se resolvem por `use`.
ESCALARES = {"string", "int", "integer", "float", "bool", "boolean", "array", "mixed", "callable",
             "iterable", "object", "void", "null", "static", "self", "parent", "false", "true", "never"}


def parse(fonte: bytes) -> ts.Tree:
    return _PARSER.parse(fonte)


@dataclass
class Escopo:
    namespace: str = ""
    usos: dict = field(default_factory=dict)  # apelido -> FQCN

    def resolver(self, nome: str) -> str:
        """Regra do PHP para nome de classe: absoluto, apelido de `use`, ou relativo ao namespace."""
        if nome.startswith("\\"):
            return nome[1:]
        if nome.lower() in ESCALARES:
            return nome.lower()
        primeiro, _, resto = nome.partition("\\")
        if primeiro in self.usos:
            return self.usos[primeiro] + ("\\" + resto if resto else "")
        return f"{self.namespace}\\{nome}" if self.namespace else nome


def _txt(n) -> str:
    return n.text.decode("utf-8")


def _filhos(n):
    return [c for c in n.named_children if c.type != "comment"]


class Leitor:
    """Converte um arquivo PHP. `problemas` junta os nós que ficaram como `?`."""

    def __init__(self, fonte: bytes, arquivo: str):
        self.fonte = fonte
        self.arquivo = arquivo
        self.arvore = parse(fonte)
        self.escopo = Escopo()
        self.problemas: list[dict] = []

    # ---------------------------------------------------------------- nomes
    def _ler_usos(self, raiz) -> None:
        for n in raiz.named_children:
            if n.type == "namespace_definition":
                nome = n.child_by_field_name("name")
                self.escopo.namespace = _txt(nome) if nome else ""
            elif n.type == "namespace_use_declaration":
                prefixo = ""
                grupo = None
                for c in n.named_children:
                    if c.type == "namespace_name":
                        prefixo = _txt(c)
                    elif c.type == "namespace_use_group":
                        grupo = c
                clausulas = grupo.named_children if grupo else [c for c in n.named_children if c.type == "namespace_use_clause"]
                for cl in clausulas:
                    if cl.type != "namespace_use_clause":
                        continue
                    partes = [c for c in cl.named_children if c.type in ("qualified_name", "name", "namespace_name")]
                    alias = cl.child_by_field_name("alias")
                    alvo = _txt(partes[0]) if partes else _txt(cl)
                    if prefixo:
                        alvo = prefixo + "\\" + alvo
                    alvo = alvo.lstrip("\\")
                    apelido = _txt(alias) if alias else alvo.rsplit("\\", 1)[-1]
                    self.escopo.usos[apelido] = alvo

    def _classe(self, n) -> str:
        if n.type in ("name", "qualified_name", "named_type"):
            return self.escopo.resolver(_txt(n))
        if n.type == "relative_scope":
            return _txt(n).lower()
        return _txt(n)

    # ---------------------------------------------------------------- arquivo
    def ler(self) -> dict:
        raiz = self.arvore.root_node
        self._ler_usos(raiz)
        classes, retorno, funcoes = [], None, {}
        for n in self._percorrer_topo(raiz):
            if n.type in ("class_declaration", "trait_declaration", "interface_declaration", "enum_declaration"):
                classes.append(self.classe(n))
            elif n.type == "function_definition":
                funcoes[_txt(n.child_by_field_name("name"))] = {
                    "params": self.params(n.child_by_field_name("parameters")),
                    "corpo": self.bloco(n.child_by_field_name("body")), "linha": n.start_point[0] + 1,
                    "arquivo": self.arquivo, "static": True, "visibilidade": "public",
                }
            elif n.type == "if_statement":
                # helpers.php costuma embrulhar cada função em `if (!function_exists(...))`.
                for c in n.named_children:
                    alvo = c if c.type == "compound_statement" else None
                    for f in (alvo.named_children if alvo else []):
                        if f.type == "function_definition":
                            funcoes[_txt(f.child_by_field_name("name"))] = {
                                "params": self.params(f.child_by_field_name("parameters")),
                                "corpo": self.bloco(f.child_by_field_name("body")), "linha": f.start_point[0] + 1,
                                "arquivo": self.arquivo, "static": True, "visibilidade": "public",
                            }
            elif n.type == "return_statement":
                filhos = _filhos(n)
                retorno = self.expr(filhos[0]) if filhos else None
        corpo_topo = []
        for n in self._percorrer_topo(raiz):
            if n.type in ("expression_statement",):
                corpo_topo.append(self.stmt(n))
        return {"namespace": self.escopo.namespace, "classes": classes, "retorno": retorno, "topo": corpo_topo,
                "funcoes": funcoes}

    def _percorrer_topo(self, raiz):
        for n in raiz.named_children:
            if n.type == "namespace_definition" and n.child_by_field_name("body"):
                yield from n.child_by_field_name("body").named_children
            else:
                yield n

    def classe(self, n) -> dict:
        no_nome = n.child_by_field_name("name")
        nome = _txt(no_nome) if no_nome else f"anonima@{self.arquivo}:{n.start_point[0] + 1}"
        fq = f"{self.escopo.namespace}\\{nome}" if self.escopo.namespace and no_nome else nome
        pai, interfaces, tracos = None, [], []
        for c in n.named_children:
            if c.type == "base_clause":
                pai = self._classe(_filhos(c)[0])
            elif c.type == "class_interface_clause":
                interfaces = [self._classe(x) for x in _filhos(c)]
        modificadores = [_txt(c) for c in n.named_children if c.type in ("abstract_modifier", "final_modifier")]
        constantes, propriedades, metodos = {}, {}, {}
        corpo = n.child_by_field_name("body") or next((c for c in n.named_children if c.type == "declaration_list"), None)
        for m in (corpo.named_children if corpo else []):
            if m.type == "const_declaration":
                for el in m.named_children:
                    if el.type == "const_element":
                        partes = _filhos(el)
                        constantes[_txt(partes[0])] = self.expr(partes[-1])
            elif m.type == "property_declaration":
                estatico = any(c.type == "static_modifier" for c in m.named_children)
                for el in m.named_children:
                    if el.type == "property_element":
                        nome_p = _txt(el.child_by_field_name("name"))[1:]
                        padrao = el.child_by_field_name("default_value")
                        propriedades[nome_p] = {"static": estatico, "valor": self.expr(padrao) if padrao else None}
            elif m.type == "use_declaration":
                tracos += [self._classe(c) for c in m.named_children if c.type in ("name", "qualified_name")]
            elif m.type == "method_declaration":
                nome_m = _txt(m.child_by_field_name("name"))
                params = self.params(m.child_by_field_name("parameters"))
                # Propriedade promovida no construtor (PHP 8) é propriedade da classe.
                for p in params:
                    if p.get("promovida"):
                        propriedades[p["nome"]] = {"static": False, "valor": None}
                corpo_m = m.child_by_field_name("body")
                metodos[nome_m] = {
                    "params": params,
                    "static": any(c.type == "static_modifier" for c in m.named_children),
                    "visibilidade": next((_txt(c) for c in m.named_children if c.type == "visibility_modifier"), "public"),
                    "corpo": self.bloco(corpo_m) if corpo_m else None,
                    "linha": m.start_point[0] + 1,
                }
        return {
            "nome": fq, "tipo": n.type.split("_")[0], "pai": pai, "interfaces": interfaces, "tracos": tracos,
            "abstrata": "abstract" in modificadores, "arquivo": self.arquivo, "linha": n.start_point[0] + 1,
            "constantes": constantes, "propriedades": propriedades, "metodos": metodos,
        }

    def params(self, n) -> list:
        saida = []
        for p in (n.named_children if n else []):
            if p.type not in ("simple_parameter", "property_promotion_parameter", "variadic_parameter"):
                continue
            tipo = p.child_by_field_name("type")
            nome = p.child_by_field_name("name")
            padrao = p.child_by_field_name("default_value")
            tipo_txt = None
            nulavel = False
            if tipo is not None:
                if tipo.type == "optional_type":
                    nulavel = True
                    tipo = _filhos(tipo)[0]
                if tipo.type in ("named_type",):
                    tipo_txt = self._classe(_filhos(tipo)[0])
                elif tipo.type == "primitive_type":
                    tipo_txt = _txt(tipo).lower()
                else:
                    tipo_txt = _txt(tipo)
            item = {"nome": _txt(nome).lstrip("$&"), "tipo": tipo_txt}
            if nulavel:
                item["nulavel"] = True
            if padrao is not None:
                item["padrao"] = self.expr(padrao)
            if p.type == "property_promotion_parameter":
                item["promovida"] = True
            if p.type == "variadic_parameter":
                item["variadico"] = True
            saida.append(item)
        return saida

    # ---------------------------------------------------------------- comandos
    def bloco(self, n) -> list:
        if n is None:
            return []
        if n.type != "compound_statement":
            return [self.stmt(n)]
        return [s for s in (self.stmt(c) for c in _filhos(n)) if s is not None]

    def _desconhecido(self, n) -> list:
        self.problemas.append({"tipo": n.type, "linha": n.start_point[0] + 1, "texto": _txt(n)[:80]})
        return ["?", n.type, n.start_point[0] + 1]

    def stmt(self, n):
        t = n.type
        f = _filhos(n)
        if t == "expression_statement":
            return ["expr", self.expr(f[0])]
        if t == "return_statement":
            return ["return", self.expr(f[0]) if f else None]
        if t == "compound_statement":
            return ["bloco", self.bloco(n)]
        if t == "if_statement":
            ramos = [[self.expr(n.child_by_field_name("condition")), self.bloco(n.child_by_field_name("body"))]]
            senao = None
            for c in n.children_by_field_name("alternative"):
                if c.type == "else_if_clause":
                    ramos.append([self.expr(c.child_by_field_name("condition")), self.bloco(c.child_by_field_name("body"))])
                elif c.type == "else_clause":
                    senao = self.bloco(c.child_by_field_name("body"))
            return ["if", ramos, senao]
        if t == "foreach_statement":
            partes = [c for c in n.named_children if c.type != "comment"]
            corpo = n.child_by_field_name("body")
            sujeito = partes[0]
            alvo = partes[1]
            if alvo.type == "pair":
                k, v = _filhos(alvo)
                return ["foreach", self.expr(sujeito), self.expr(k), self.expr(v), self.bloco(corpo)]
            return ["foreach", self.expr(sujeito), None, self.expr(alvo), self.bloco(corpo)]
        if t == "throw_expression":
            return ["throw", self.expr(f[0])]
        if t == "try_statement":
            corpo = self.bloco(n.child_by_field_name("body"))
            capturas, final = [], None
            for c in n.named_children:
                if c.type == "catch_clause":
                    tipos = [self._classe(x) for x in c.child_by_field_name("type").named_children] if c.child_by_field_name("type") else []
                    var = c.child_by_field_name("name")
                    capturas.append([tipos, _txt(var).lstrip("$") if var else None, self.bloco(c.child_by_field_name("body"))])
                elif c.type == "finally_clause":
                    final = self.bloco(_filhos(c)[0])
            return ["try", corpo, capturas, final]
        if t == "while_statement":
            return ["while", self.expr(n.child_by_field_name("condition")), self.bloco(n.child_by_field_name("body"))]
        if t == "break_statement":
            return ["break"]
        if t == "continue_statement":
            return ["continue"]
        if t == "unset_statement":
            return ["unset", [self.expr(c) for c in f]]
        if t == "empty_statement":
            return None
        return self._desconhecido(n)

    # ---------------------------------------------------------------- expressões
    def args(self, n) -> list:
        saida = []
        for a in (n.named_children if n else []):
            if a.type != "argument":
                continue
            nome = a.child_by_field_name("name")
            filhos = [c for c in _filhos(a) if c != nome]
            valor = self.expr(filhos[-1]) if filhos else ["lit", None]
            if any(c.type == "variadic_unpacking" or _txt(c) == "..." for c in a.children):
                valor = ["spread", valor]
            if nome is not None:
                valor = ["named", _txt(nome), valor]
            saida.append(valor)
        return saida

    def _string(self, n):
        conteudo = "".join(_txt(c) for c in n.named_children if c.type in ("string_content", "string_value"))
        bruto = _txt(n)
        if bruto.startswith("'"):
            return ["lit", conteudo.replace("\\\\", "\\").replace("\\'", "'")]
        return ["lit", conteudo]

    def expr(self, n):  # noqa: C901 - um despacho por tipo de nó, de propósito
        t = n.type
        f = _filhos(n)
        if t == "parenthesized_expression":
            return self.expr(f[0])
        if t == "integer":
            return ["lit", int(_txt(n).replace("_", ""), 0) if not _txt(n).startswith("0") or _txt(n) == "0" or _txt(n)[1:2] in "xXbBoO" else int(_txt(n), 8)]
        if t == "float":
            return ["lit", float(_txt(n).replace("_", ""))]
        if t == "boolean":
            return ["lit", _txt(n).lower() == "true"]
        if t == "null":
            return ["lit", None]
        if t == "string":
            return self._string(n)
        if t == "encapsed_string":
            partes = []
            for c in n.named_children:
                if c.type in ("string_content", "string_value"):
                    partes.append(["lit", _txt(c).replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\$", "$").replace("\\\\", "\\")])
                elif c.type == "escape_sequence":
                    partes.append(["lit", {"\\n": "\n", "\\t": "\t", '\\"': '"', "\\\\": "\\", "\\$": "$"}.get(_txt(c), _txt(c))])
                else:
                    partes.append(self.expr(c))
            if all(p[0] == "lit" for p in partes):
                return ["lit", "".join(p[1] for p in partes)]
            return ["str", partes]
        if t == "variable_name":
            nome = _txt(n)[1:]
            return ["this"] if nome == "this" else ["var", nome]
        if t == "name":
            nome = _txt(n)
            if nome.lower() in ("true", "false"):
                return ["lit", nome.lower() == "true"]
            if nome.lower() == "null":
                return ["lit", None]
            return ["const", nome]
        if t == "array_creation_expression":
            itens = []
            for el in n.named_children:
                if el.type != "array_element_initializer":
                    continue
                partes = _filhos(el)
                if any(c.type == "variadic_unpacking" for c in el.children) or _txt(el).startswith("..."):
                    itens.append([None, self.expr(partes[-1]), True])
                elif len(partes) == 2 and any(_txt(c) == "=>" for c in el.children):
                    itens.append([self.expr(partes[0]), self.expr(partes[1])])
                else:
                    itens.append([None, self.expr(partes[0])])
            return ["arr", itens]
        if t == "function_call_expression":
            fn = n.child_by_field_name("function")
            args = self.args(n.child_by_field_name("arguments"))
            if fn.type in ("name", "qualified_name"):
                return ["call", _txt(fn).lstrip("\\"), args]
            return ["invoke", self.expr(fn), args]
        if t in ("member_call_expression", "nullsafe_member_call_expression"):
            nome = n.child_by_field_name("name")
            if nome.type != "name":
                return self._desconhecido(n)
            return ["mcall", self.expr(n.child_by_field_name("object")), _txt(nome),
                    self.args(n.child_by_field_name("arguments")), t.startswith("nullsafe")]
        if t in ("member_access_expression", "nullsafe_member_access_expression"):
            nome = n.child_by_field_name("name")
            if nome.type != "name":
                return self._desconhecido(n)
            return ["prop", self.expr(n.child_by_field_name("object")), _txt(nome), t.startswith("nullsafe")]
        if t == "scoped_call_expression":
            escopo = n.child_by_field_name("scope")
            nome_m = n.child_by_field_name("name")
            if nome_m.type != "name":
                return self._desconhecido(n)
            if escopo.type not in ("name", "qualified_name", "relative_scope"):
                # $classe::metodo(): a classe só se sabe rodando.
                return ["scallx", self.expr(escopo), _txt(nome_m), self.args(n.child_by_field_name("arguments"))]
            return ["scall", self._classe(escopo), _txt(nome_m), self.args(n.child_by_field_name("arguments"))]
        if t == "class_constant_access_expression":
            escopo, nome = f[0], f[1]
            if escopo.type not in ("name", "qualified_name", "relative_scope"):
                if _txt(nome) == "class":
                    return ["call", "get_class", [self.expr(escopo)]]
                return ["cconstx", self.expr(escopo), _txt(nome)]
            if _txt(nome) == "class":
                return ["classref", self._classe(escopo)]
            return ["cconst", self._classe(escopo), _txt(nome)]
        if t == "scoped_property_access_expression":
            escopo = n.child_by_field_name("scope")
            if escopo.type not in ("name", "qualified_name", "relative_scope"):
                return ["spropx", self.expr(escopo), _txt(n.child_by_field_name("name")).lstrip("$")]
            return ["sprop", self._classe(escopo), _txt(n.child_by_field_name("name")).lstrip("$")]
        if t == "object_creation_expression":
            alvo = [c for c in f if c.type != "arguments"][0]
            args_n = next((c for c in f if c.type == "arguments"), None)
            if alvo.type in ("name", "qualified_name"):
                return ["new", self._classe(alvo), self.args(args_n)]
            if alvo.type == "relative_scope" or _txt(alvo) in ("self", "static"):
                return ["new", _txt(alvo).lower(), self.args(args_n)]
            return ["newx", self.expr(alvo), self.args(args_n)]
        if t == "subscript_expression":
            obj = self.expr(f[0])
            return ["idx", obj, self.expr(f[1]) if len(f) > 1 else None]
        if t == "binary_expression":
            op = _txt(n.child_by_field_name("operator"))
            direita = n.child_by_field_name("right")
            if op.lower() == "instanceof" and direita.type in ("name", "qualified_name"):
                return ["instanceof", self.expr(n.child_by_field_name("left")), self._classe(direita)]
            return ["bin", op.lower(), self.expr(n.child_by_field_name("left")), self.expr(n.child_by_field_name("right"))]
        if t == "unary_op_expression":
            op = next(_txt(c) for c in n.children if not c.is_named)
            return ["un", op, self.expr(f[0])]
        if t == "assignment_expression":
            esq, dir_ = n.child_by_field_name("left"), n.child_by_field_name("right")
            if esq.type == "list_literal" or esq.type == "array_creation_expression":
                alvos = []
                for el in esq.named_children:
                    if el.type == "comment":
                        continue
                    alvo_n = el if el.type != "array_element_initializer" else (_filhos(el) or [None])[0]
                    if alvo_n is not None:
                        alvos.append(self.expr(alvo_n))
                return ["destruct", alvos, self.expr(dir_)]
            return ["assign", self.expr(esq), self.expr(dir_)]
        if t == "augmented_assignment_expression":
            op = _txt(n.child_by_field_name("operator"))
            return ["assignop", op[:-1], self.expr(n.child_by_field_name("left")), self.expr(n.child_by_field_name("right"))]
        if t == "update_expression":
            op = "+" if "++" in _txt(n) else "-"
            return ["assignop", op, self.expr(f[0]), ["lit", 1]]
        if t == "cast_expression":
            return ["cast", _txt(n.child_by_field_name("type")).lower(), self.expr(n.child_by_field_name("value"))]
        if t == "conditional_expression":
            cond = self.expr(n.child_by_field_name("condition"))
            body = n.child_by_field_name("body")
            alt = self.expr(n.child_by_field_name("alternative"))
            return ["tern", cond, self.expr(body) if body else None, alt]
        if t == "arrow_function":
            return ["fn", self.params(n.child_by_field_name("parameters")), self.expr(n.child_by_field_name("body"))]
        if t == "anonymous_function":
            usos = []
            for c in n.named_children:
                if c.type == "anonymous_function_use_clause":
                    usos = [_txt(v).lstrip("&$") for v in c.named_children]
            return ["closure", self.params(n.child_by_field_name("parameters")), usos, self.bloco(n.child_by_field_name("body"))]
        if t == "throw_expression":
            return ["throwx", self.expr(f[0])]
        if t == "qualified_name":
            return ["const", _txt(n).lstrip("\\")]
        if t == "clone_expression":
            return ["clone", self.expr(f[0])]
        if t == "instanceof_expression" or (t == "binary_expression" and False):
            return ["instanceof", self.expr(f[0]), self._classe(f[1])]
        if t == "require_expression" or t == "include_expression" or t == "require_once_expression":
            return ["require", self.expr(f[0])]
        if t == "anonymous_class":
            return ["anonclass", self.classe(n)]
        if t == "error_suppression_expression":
            return self.expr(f[0])
        if t == "reference_modifier":
            return self._desconhecido(n)
        if t in ("print_intrinsic",):
            return self._desconhecido(n)
        if t == "sequence_expression":
            return self._desconhecido(n)
        if t == "match_expression":
            cond = self.expr(n.child_by_field_name("condition"))
            bracos = []
            for b in n.child_by_field_name("body").named_children:
                if b.type == "match_conditional_expression":
                    conds = [self.expr(x) for x in b.child_by_field_name("conditional_expressions").named_children]
                    bracos.append([conds, self.expr(b.child_by_field_name("return_expression"))])
                elif b.type == "match_default_expression":
                    bracos.append([None, self.expr(b.child_by_field_name("return_expression"))])
            return ["match", cond, bracos]
        return self._desconhecido(n)


def ler_arquivo(fonte: bytes, arquivo: str) -> tuple[dict, list]:
    leitor = Leitor(fonte, arquivo)
    resultado = leitor.ler()
    for p in leitor.problemas:
        p["arquivo"] = arquivo
    return resultado, leitor.problemas


def avaliar_literal(ir, consts: dict | None = None):
    """Valor de um IR que só tem literais e arrays (config, lang, $fillable).

    Devolve (ok, valor). Array PHP vira lista quando não tem chave, dict quando tem.
    """
    if ir is None:
        return True, None
    k = ir[0]
    if k == "lit":
        return True, ir[1]
    if k == "arr":
        tem_chave = any(it[0] is not None for it in ir[1])
        if tem_chave:
            saida = {}
            proximo = 0
            for it in ir[1]:
                if len(it) > 2:
                    return False, None
                if it[0] is None:
                    chave = proximo
                else:
                    ok, chave = avaliar_literal(it[0], consts)
                    if not ok:
                        return False, None
                ok, v = avaliar_literal(it[1], consts)
                if not ok:
                    return False, None
                saida[chave] = v
                if isinstance(chave, int):
                    proximo = chave + 1
            return True, saida
        valores = []
        for it in ir[1]:
            ok, v = avaliar_literal(it[1], consts)
            if not ok or len(it) > 2:
                return False, None
            valores.append(v)
        return True, valores
    if k == "bin" and ir[1] == ".":
        ok1, a = avaliar_literal(ir[2], consts)
        ok2, b = avaliar_literal(ir[3], consts)
        if ok1 and ok2 and isinstance(a, str) and isinstance(b, str):
            return True, a + b
    if k == "classref":
        return True, ir[1]
    if k == "cconst" and consts is not None and (ir[1], ir[2]) in consts:
        return True, consts[(ir[1], ir[2])]
    return False, None
