"""IR do contrato -> Python que roda sobre o laravel_compat.

Regras da tradução (cada uma impede um defeito medido ou previsível):

- propriedade PHP vira `p_<nome>` e constante vira `k_<nome>`: no PHP método,
  propriedade e constante podem ter o mesmo nome (`$rules` e `rules()`); no
  Python, não;
- `$obj->x` vira `php.prop(obj, "x")` (ou `self.p_x` quando a classe declara `x`):
  no Eloquent `$model->tags` é a relação carregada, não o método `tags()`;
- todo valor que entra em `if`, `&&`, `.`, `==` passa por `php.truthy`,
  `php.concat`, `php.eq`: "0" é falso no PHP, null vira "" na concatenação;
- o que não tem tradução vira `php.pendencia(...)` e uma entrada em
  `problemas`, nunca um palpite: a rota que passa por ali responde 501 e o
  diferencial mostra.
"""
from __future__ import annotations

import keyword
import re

import laravel_compat as lv

from . import php as _php

ESCALARES = _php.ESCALARES | {"int", "integer"}
OPS_ARIT = {"+": "php.add", "-": "php.sub", "*": "php.mul", "/": "php.div", "%": "php.mod", ".": "php.concat"}
OPS_CMP = {"==": "php.eq", "===": "php.ident", "<": "php.lt", ">": "php.gt", "<=": "php.le", ">=": "php.ge",
           "<=>": "php.spaceship"}
BOOLEANOS = ("php.eq(", "php.ident(", "php.lt(", "php.gt(", "php.le(", "php.ge(", "(not ", "php.isset(",
             "php.empty(", "php.instanceof(", "php.truthy(", "(php.truthy(", "php.is_", "php.in_array(")
# Métodos que o framework chama nos objetos do app: entram na cobertura quando a classe é usada.
ENTRADAS_FRAMEWORK = {"__construct", "toArray", "with", "rules", "authorize", "messages", "attributes",
                      "prepareForValidation", "validationData", "passedValidation", "handle", "register", "boot",
                      "render", "report", "user", "check", "validate", "toResponse", "passes", "message",
                      "__invoke", "getRouteKeyName", "before", "redirectTo", "getJwtIdentifier"}


def py_var(nome: str) -> str:
    if keyword.iskeyword(nome) or nome in ("self", "cls", "php", "lv", "Base", "super", "lambda", "print", "type"):
        return nome + "_"
    return nome


def py_metodo(nome: str) -> str:
    if nome.startswith("__") and nome != "__construct":
        return "_php_" + nome[2:]
    return lv.nome_python(nome)


class Contexto:
    def __init__(self, classe=None, estatico=False):
        self.classe = classe  # FQCN
        self.estatico = estatico
        self.em_lambda = 0
        self.corpo_classe = False


class Transpilador:
    def __init__(self, contrato: dict):
        self.c = contrato
        self.classes = contrato["classes"]
        self.nomes = self._nomes()
        self.framework: dict[str, str] = {}
        self.funcoes: dict[str, str] = {}
        self.problemas: list[dict] = []
        self.contador = 0
        self.pre: list[str] = []
        self.onde = ""
        self.refs: dict[str, set] = {}
        self.ref_atual: set | None = None

    # ------------------------------------------------------------------ nomes
    def _nomes(self) -> dict:
        curtos: dict[str, list] = {}
        for fq in self.classes:
            curtos.setdefault(fq.rsplit("\\", 1)[-1], []).append(fq)
        nomes = {}
        for curto, fqs in curtos.items():
            for fq in fqs:
                base = curto if len(fqs) == 1 else re.sub(r"\W", "_", fq.replace("\\", "_"))
                if base in ("php", "lv", "Base") or base.startswith(("F_", "f_")) or keyword.iskeyword(base):
                    base = "C_" + base
                nomes[fq] = base
        return nomes

    def eh_app(self, fq) -> bool:
        return fq in self.classes

    def ref_framework(self, fq: str) -> str:
        if fq not in self.framework:
            self.framework[fq] = f"F_{len(self.framework) + 1}_{fq.rsplit(chr(92), 1)[-1]}"
        return self.framework[fq]

    def ref_classe(self, fq: str, ctx: Contexto) -> str:
        if self.ref_atual is not None and self.eh_app(fq):
            self.ref_atual.add((fq, "*"))
        if self.eh_app(fq):
            return self.nomes[fq]
        if lv.tem_classe(fq):
            return self.ref_framework(fq)
        self.problema("classe_sem_traducao", fq)
        return f'php.pendencia({fq!r})'

    def ref_funcao(self, nome: str) -> str | None:
        if not lv.tem_funcao(nome):
            return None
        if nome not in self.funcoes:
            self.funcoes[nome] = "f_" + re.sub(r"\W", "_", nome)
        return self.funcoes[nome]

    def problema(self, tipo, detalhe):
        self.problemas.append({"tipo": tipo, "onde": self.onde, "detalhe": str(detalhe)[:160]})

    # ------------------------------------------------------------------ hierarquia
    def ancestrais(self, fq):
        saida = []
        atual = self.classes.get(fq)
        while atual and atual.get("pai"):
            saida.append(atual["pai"])
            atual = self.classes.get(atual["pai"])
        return saida

    def metodo_app(self, fq, nome):
        atual = fq
        while atual in self.classes:
            m = self.classes[atual]["metodos"].get(nome)
            if m is not None:
                return atual, m
            for t in self.classes[atual].get("tracos", []):
                if t in self.classes and nome in self.classes[t]["metodos"]:
                    return t, self.classes[t]["metodos"][nome]
            atual = self.classes[atual].get("pai")
        return None, None

    def raiz_framework(self, fq):
        """Primeira classe do framework na cadeia de herança (ou None)."""
        atual = fq
        while atual in self.classes:
            atual = self.classes[atual].get("pai")
        return atual

    def prop_declarada(self, fq, nome) -> bool:
        atual = fq
        while atual in self.classes:
            c = self.classes[atual]
            if nome in c["propriedades"]:
                return True
            for t in c.get("tracos", []):
                if t in self.classes and nome in self.classes[t]["propriedades"]:
                    return True
                if lv.tem_classe(t) and hasattr(lv.classe(t), "p_" + nome):
                    return True
            atual = c.get("pai")
        if atual and lv.tem_classe(atual):
            cls = lv.classe(atual)
            if getattr(cls, "_fqcn", "").startswith("Illuminate\\Database\\Eloquent\\Model") or issubclass(cls, lv.eloquent.Model):
                return nome in ("exists", "wasRecentlyCreated", "table", "primaryKey", "fillable", "hidden",
                                "casts", "guarded", "timestamps", "incrementing", "keyType", "with", "appends")
            return hasattr(cls, "p_" + nome)
        return False

    # ------------------------------------------------------------------ expressões
    def ex(self, ir, ctx: Contexto) -> str:  # noqa: C901 - um ramo por nó do IR
        if ir is None:
            return "None"
        k = ir[0]
        if k == "lit":
            return repr(ir[1])
        if k == "var":
            if ir[1] in ("GLOBALS", "_SERVER", "_GET", "_POST", "_COOKIE", "_FILES", "_ENV", "_REQUEST", "_SESSION"):
                self.problema("superglobal", ir[1])
                return f"php.pendencia('${ir[1]}')"
            return py_var(ir[1])
        if k == "this":
            if ctx.estatico:
                self.problema("this_em_estatico", "")
                return "php.pendencia('$this')"
            return "self"
        if k == "arr":
            return self.ex_arr(ir[1], ctx)
        if k == "call":
            return self.ex_call(ir, ctx)
        if k == "invoke":
            return f"({self.ex(ir[1], ctx)})({self.args(ir[2], ctx)})"
        if k == "mcall":
            return self.ex_mcall(ir, ctx)
        if k == "prop":
            return self.ex_prop(ir, ctx)
        if k == "scall":
            return self.ex_scall(ir, ctx)
        if k == "cconst":
            return self.ex_cconst(ir, ctx)
        if k == "scallx":
            if self.ref_atual is not None:
                self.ref_atual.add(("?", ir[2]))
            return f"php.classe_de({self.ex(ir[1], ctx)}).{py_metodo(ir[2])}({self.args(ir[3], ctx)})"
        if k == "spropx":
            return f"php.classe_de({self.ex(ir[1], ctx)}).p_{ir[2]}"
        if k == "cconstx":
            return f"php.classe_de({self.ex(ir[1], ctx)}).k_{ir[2]}"
        if k == "sprop":
            return f"{self.alvo_estatico(ir[1], ctx)}.p_{ir[2]}"
        if k == "classref":
            if ir[1] == "static":
                return "php.fqcn(self)" if not ctx.estatico else "cls._fqcn"
            if ir[1] in ("self",):
                return repr(ctx.classe)
            if ir[1] == "parent":
                return repr(self.classes.get(ctx.classe, {}).get("pai"))
            if self.ref_atual is not None and self.eh_app(ir[1]):
                self.ref_atual.add((ir[1], "*"))
            return repr(ir[1])
        if k == "new":
            return self.ex_new(ir, ctx)
        if k == "newx":
            return f"php.novo({self.ex(ir[1], ctx)}{', ' + self.args(ir[2], ctx) if ir[2] else ''})"
        if k == "idx":
            if ir[2] is None:
                self.problema("leitura_de_[]", "")
                return "php.pendencia('$a[] em leitura')"
            return f"php.idx({self.ex(ir[1], ctx)}, {self.ex(ir[2], ctx)})"
        if k == "bin":
            return self.ex_bin(ir, ctx)
        if k == "un":
            a = self.ex(ir[2], ctx)
            if ir[1] == "!":
                return f"(not {self.verdade(a)})"
            if ir[1] == "-":
                return f"(-php._num({a}))"
            if ir[1] == "+":
                return f"php._num({a})"
            if ir[1] == "~":
                return f"(~php.to_int({a}))"
            self.problema("operador", ir[1])
            return f"php.pendencia('operador {ir[1]}')"
        if k == "assign":
            return self.ex_assign(ir[1], self.ex(ir[2], ctx), ctx)
        if k == "assignop":
            return self.ex_assign(ir[2], self.op_composto(ir[1], ir[2], ir[3], ctx), ctx)
        if k == "cast":
            f = {"int": "php.to_int", "integer": "php.to_int", "string": "php.to_str", "bool": "php.truthy",
                 "boolean": "php.truthy", "float": "php.to_float", "double": "php.to_float", "real": "php.to_float",
                 "array": "php.to_array", "object": "php.to_object"}.get(ir[1])
            if f is None:
                self.problema("cast", ir[1])
                return f"php.pendencia('cast {ir[1]}')"
            return f"{f}({self.ex(ir[2], ctx)})"
        if k == "tern":
            if ir[2] is None:
                return f"php.elvis({self.ex(ir[1], ctx)}, lambda: {self.ex(ir[3], ctx)})"
            return f"({self.ex(ir[2], ctx)} if {self.verdade(self.ex(ir[1], ctx))} else {self.ex(ir[3], ctx)})"
        if k == "fn":
            return self.ex_fn(ir, ctx)
        if k == "closure":
            return self.ex_closure(ir, ctx)
        if k == "str":
            return "php.concat(" + ", ".join(self.ex(p, ctx) for p in ir[1]) + ")"
        if k == "const":
            nome = ir[1]
            if nome.upper() in ("PHP_EOL", "PHP_INT_MAX") or hasattr(lv.php, nome):
                if hasattr(lv.php, nome) and not callable(getattr(lv.php, nome)):
                    return f"php.{nome}"
            self.problema("constante", nome)
            return f"php.pendencia('constante {nome}')"
        if k == "clone":
            return f"php.clone({self.ex(ir[1], ctx)})"
        if k == "instanceof":
            if self.ref_atual is not None and self.eh_app(ir[2]):
                self.ref_atual.add((ir[2], "*"))
            return f"php.instanceof({self.ex(ir[1], ctx)}, {ir[2]!r})"
        if k == "throwx":
            return f"php.lancar({self.ex(ir[1], ctx)})"
        if k == "match":
            bracos = []
            for conds, res in ir[2]:
                c = "None" if conds is None else "[" + ", ".join(self.ex(x, ctx) for x in conds) + "]"
                bracos.append(f"({c}, lambda: {self.ex(res, ctx)})")
            return f"php.match_({self.ex(ir[1], ctx)}, [{', '.join(bracos)}])"
        if k == "named":
            return f"{py_var(ir[1])}={self.ex(ir[2], ctx)}"
        if k == "spread":
            return f"*php.valores({self.ex(ir[1], ctx)})"
        if k == "destruct":
            self.problema("desestruturacao_em_expressao", "")
            return "php.pendencia('desestruturação em expressão')"
        if k == "?":
            self.problema("php_nao_lido", f"{ir[1]} linha {ir[2]}")
            return f"php.pendencia({('nó ' + ir[1])!r})"
        self.problema("ir_sem_traducao", k)
        return f"php.pendencia({('IR ' + k)!r})"

    def verdade(self, s: str) -> str:
        return s if s.startswith(BOOLEANOS) or s in ("True", "False") else f"php.truthy({s})"

    def args(self, args, ctx) -> str:
        return ", ".join(self.ex(a, ctx) for a in args)

    def ex_arr(self, itens, ctx) -> str:
        tem_chave = any(it[0] is not None for it in itens)
        tem_spread = any(len(it) > 2 for it in itens)
        sem_chave = any(it[0] is None for it in itens)
        if not tem_chave and not tem_spread:
            return "[" + ", ".join(self.ex(it[1], ctx) for it in itens) + "]"
        if tem_chave and not sem_chave and not tem_spread:
            partes = []
            for it in itens:
                chave = it[0]
                if chave[0] == "lit":
                    chave_py = repr(lv.php._chave(chave[1]))
                else:
                    chave_py = f"php._chave({self.ex(chave, ctx)})"
                partes.append(f"{chave_py}: {self.ex(it[1], ctx)}")
            return "{" + ", ".join(partes) + "}"
        pares = []
        for it in itens:
            if len(it) > 2:
                pares.append(f"('...', {self.ex(it[1], ctx)})")
            elif it[0] is None:
                pares.append(f"(php.PADRAO, {self.ex(it[1], ctx)})")
            else:
                pares.append(f"({self.ex(it[0], ctx)}, {self.ex(it[1], ctx)})")
        return "php.arr([" + ", ".join(pares) + "])"

    def preguica(self, ir, ctx) -> str:
        """Argumento de isset/empty/??: com atribuição dentro, avalia já (walrus não sai de lambda)."""
        s = self.ex(ir, ctx)
        if ":=" in s:
            return s
        return f"lambda: {s}"

    def ex_call(self, ir, ctx) -> str:
        nome, args = ir[1], ir[2]
        baixo = nome.lower()
        if baixo == "isset":
            return "php.isset(" + ", ".join(self.preguica(a, ctx) for a in args) + ")"
        if baixo == "empty":
            return f"php.empty({self.preguica(args[0], ctx)})"
        if baixo in ("compact", "extract", "func_get_args", "get_defined_vars", "eval"):
            self.problema("funcao_dinamica", nome)
            return f"php.pendencia('{nome}()')"
        if nome in self.c.get("funcoes", {}):
            if self.ref_atual is not None:
                self.ref_atual.add(("fn", nome))
            return f"fn_{nome}({self.args(args, ctx)})"
        ref = self.ref_funcao(nome) or self.ref_funcao(baixo)
        if ref is None:
            self.problema("funcao_sem_traducao", nome)
            return f"php.pendencia('função {nome}()')"
        return f"{ref}({self.args(args, ctx)})"

    def ex_mcall(self, ir, ctx) -> str:
        _, obj, nome, args, nulo = ir
        if self.ref_atual is not None:
            self.ref_atual.add(("?", nome))
        alvo = self.ex(obj, ctx)
        chamada = f"{py_metodo(nome)}({self.args(args, ctx)})"
        if nulo:
            return f"php.nullsafe({alvo}, lambda _o: _o.{chamada})"
        return f"{alvo}.{chamada}"

    def ex_prop(self, ir, ctx) -> str:
        _, obj, nome, _nulo = ir
        if self.ref_atual is not None:
            self.ref_atual.add(("?", nome))
            self.ref_atual.add(("?", "get" + nome[:1].upper() + nome[1:] + "Attribute"))
        if obj == ["this"] and not ctx.estatico and self.prop_declarada(ctx.classe, nome):
            return f"self.p_{nome}"
        if obj == ["this"] and not ctx.estatico:
            return f"self._p({nome!r})"
        return f"php.prop({self.ex(obj, ctx)}, {nome!r})"

    def alvo_estatico(self, cls, ctx) -> str:
        if cls in ("static",):
            return "cls" if ctx.estatico else "type(self)"
        if cls == "self":
            return self.nomes[ctx.classe] if not ctx.corpo_classe else "__classe__"
        if cls == "parent":
            pai = self.classes.get(ctx.classe, {}).get("pai")
            return self.ref_classe(pai, ctx) if pai else "php.pendencia('parent')"
        return self.ref_classe(cls, ctx)

    def ex_scall(self, ir, ctx) -> str:
        _, cls, nome, args = ir
        m = py_metodo(nome)
        a = self.args(args, ctx)
        if cls == "parent":
            pai = self.classes.get(ctx.classe, {}).get("pai")
            if self.ref_atual is not None and pai in self.classes:
                self.ref_atual.add((pai, nome))
            eu = self.nomes[ctx.classe]
            alvo = f"super({eu}, cls)" if ctx.estatico else f"super({eu}, self)"
            return f"{alvo}.{m}({a})"
        alvo_fq = ctx.classe if cls in ("self", "static") else cls
        if self.ref_atual is not None and self.eh_app(alvo_fq):
            self.ref_atual.add((alvo_fq, nome))
        dono, metodo = self.metodo_app(alvo_fq, nome) if self.eh_app(alvo_fq) else (None, None)
        if cls in ("self", "static"):
            if metodo is not None and not metodo["static"] and not ctx.estatico:
                return f"self.{m}({a})"
            return f"{self.alvo_estatico(cls, ctx)}.{m}({a})"
        alvo = self.ref_classe(cls, ctx)
        if metodo is not None and not metodo["static"] and not ctx.estatico and ctx.classe and \
                (cls == ctx.classe or cls in self.ancestrais(ctx.classe)):
            # Classe::metodo() de dentro da subclasse é chamada na mesma instância.
            return f"{alvo}.{m}(self{', ' + a if a else ''})"
        if not self.eh_app(cls) and lv.tem_classe(cls) and not self.conferir_estatico(cls, nome):
            # Sem tradução: a rota responde 501 (pendência) em vez de 500 por AttributeError.
            return f"php.pendencia({(cls + '::' + nome + '()')!r})"
        return f"{alvo}.{m}({a})"

    def conferir_estatico(self, cls, nome):
        import inspect

        alvo = lv.classe(cls)
        m = py_metodo(nome)
        # getattr_static: fachada e Model resolvem nome por __getattr__ do metaclass,
        # que precisaria da aplicação montada.
        if inspect.getattr_static(alvo, m, None) is not None:
            return True
        if isinstance(alvo, lv.eloquent._MetaModel) or (isinstance(alvo, type) and issubclass(alvo, lv.eloquent.Model)):
            if hasattr(lv.eloquent.Builder, m) or nome.startswith("where"):
                return True
        fachadas = {lv.auth.Auth: (lv.auth.AuthManager, lv.auth.SessionGuard, lv.auth.GuardHelpers),
                    lv.auth.Gate: (lv.auth.GateImpl,), lv.auth.RateLimiter: (lv.auth.RateLimiterImpl,)}
        if alvo in fachadas and any(inspect.getattr_static(x, m, None) is not None for x in fachadas[alvo]):
            return True
        self.problema("metodo_sem_traducao", f"{cls}::{nome}")
        return False

    def ex_cconst(self, ir, ctx) -> str:
        _, cls, nome = ir
        if ctx.corpo_classe and cls in ("self", "static"):
            return f"k_{nome}"
        if cls not in ("self", "static", "parent") and not self.eh_app(cls) and lv.tem_classe(cls):
            import inspect

            if inspect.getattr_static(lv.classe(cls), "k_" + nome, None) is None:
                self.problema("constante_sem_traducao", f"{cls}::{nome}")
        return f"{self.alvo_estatico(cls, ctx)}.k_{nome}"

    def ex_new(self, ir, ctx) -> str:
        _, cls, args = ir
        a = self.args(args, ctx)
        if cls == "static":
            return f"{'cls' if ctx.estatico else 'type(self)'}({a})"
        if cls == "self":
            return f"{self.nomes[ctx.classe]}({a})"
        if self.ref_atual is not None and self.eh_app(cls):
            self.ref_atual.add((cls, "*"))
        return f"{self.ref_classe(cls, ctx)}({a})"

    def ex_bin(self, ir, ctx) -> str:
        _, op, a_ir, b_ir = ir
        if op == ".":
            partes = []

            def juntar(n):
                if n[0] == "bin" and n[1] == ".":
                    juntar(n[2])
                    juntar(n[3])
                else:
                    partes.append(self.ex(n, ctx))
            juntar(ir)
            return "php.concat(" + ", ".join(partes) + ")"
        if op == "??":
            return f"php.coalesce({self.preguica(a_ir, ctx)}, lambda: {self.ex(b_ir, ctx)})"
        a, b = self.ex(a_ir, ctx), self.ex(b_ir, ctx)
        if op in OPS_ARIT:
            return f"{OPS_ARIT[op]}({a}, {b})"
        if op in OPS_CMP:
            return f"{OPS_CMP[op]}({a}, {b})"
        if op in ("!=", "<>"):
            return f"(not php.eq({a}, {b}))"
        if op == "!==":
            return f"(not php.ident({a}, {b}))"
        if op in ("&&", "and"):
            return f"({self.verdade(a)} and {self.verdade(b)})"
        if op in ("||", "or"):
            return f"({self.verdade(a)} or {self.verdade(b)})"
        if op == "xor":
            return f"({self.verdade(a)} != {self.verdade(b)})"
        if op == "**":
            return f"(php._num({a}) ** php._num({b}))"
        if op in ("|", "&", "^", "<<", ">>"):
            return f"(php.to_int({a}) {op} php.to_int({b}))"
        if op == "instanceof":
            return f"php.instanceof({a}, {b})"
        self.problema("operador", op)
        return f"php.pendencia('operador {op}')"

    def op_composto(self, op, alvo_ir, valor_ir, ctx) -> str:
        atual = self.ex(alvo_ir, ctx)
        v = self.ex(valor_ir, ctx)
        if op == "??":
            return f"php.coalesce(lambda: {atual}, lambda: {v})"
        if op in OPS_ARIT:
            return f"{OPS_ARIT[op]}({atual}, {v})"
        if op in ("|", "&", "^", "<<", ">>"):
            return f"(php.to_int({atual}) {op} php.to_int({v}))"
        if op == "**":
            return f"(php._num({atual}) ** php._num({v}))"
        self.problema("operador", op + "=")
        return f"php.pendencia('operador {op}=')"

    def alvo_escrita(self, ir, ctx) -> str:
        """`$a['x']` aninhado em escrita cria o array do meio (idx_ref)."""
        if ir[0] == "idx" and ir[2] is not None:
            return f"php.idx_ref({self.alvo_escrita(ir[1], ctx)}, {self.ex(ir[2], ctx)})"
        return self.ex(ir, ctx)

    def ex_assign(self, alvo, valor: str, ctx) -> str:
        """Atribuição como expressão (valor de retorno é o valor atribuído)."""
        k = alvo[0]
        if k == "var":
            return f"({py_var(alvo[1])} := {valor})"
        if k == "idx":
            base = self.alvo_escrita(alvo[1], ctx)
            if alvo[2] is None:
                return f"php.push({base}, {valor})"
            return f"php.idx_set({base}, {self.ex(alvo[2], ctx)}, {valor})"
        if k == "prop":
            return f"php.prop_set({self.ex(alvo[1], ctx)}, {alvo[2]!r}, {valor})"
        if k == "sprop":
            return f"php.sprop_set({self.alvo_estatico(alvo[1], ctx)}, {alvo[2]!r}, {valor})"
        self.problema("atribuicao", k)
        return "php.pendencia('atribuição')"

    def parametros(self, params, ctx) -> tuple[str, list]:
        """(assinatura, prólogo): padrão mutável vira PADRAO e é montado na entrada."""
        partes, prologo = [], []
        for p in params:
            nome = py_var(p["nome"])
            if p.get("variadico"):
                partes.append("*" + nome)
                continue
            if "padrao" in p:
                ok, v = _php.avaliar_literal(p["padrao"])
                if ok and not isinstance(v, (list, dict)):
                    partes.append(f"{nome}={v!r}")
                else:
                    partes.append(f"{nome}=php.PADRAO")
                    prologo.append(f"if {nome} is php.PADRAO:")
                    prologo.append(f"    {nome} = {self.ex(p['padrao'], ctx)}")
            else:
                partes.append(nome)
        # O PHP ignora argumento a mais (o Handler passa $e e $request a uma closure
        # que só declara $e); sem isso, a chamada quebraria no Python.
        if not any(p.get("variadico") for p in params):
            partes.append("*_extras")
        return ", ".join(partes), prologo

    def tipos_classe(self, params) -> list:
        return [p["tipo"] for p in params if p.get("tipo") and p["tipo"] not in ESCALARES][:1]

    def ex_fn(self, ir, ctx) -> str:
        assinatura, prologo = self.parametros(ir[1], ctx)
        if prologo:
            return self.ex_closure(["closure", ir[1], [], [["return", ir[2]]]], ctx)
        ctx.em_lambda += 1
        corpo = self.ex(ir[2], ctx)
        ctx.em_lambda -= 1
        s = f"(lambda {assinatura}: {corpo})" if assinatura else f"(lambda: {corpo})"
        tipos = self.tipos_classe(ir[1])
        return f"php.tipos({s}, {tipos!r})" if tipos else s

    def ex_closure(self, ir, ctx) -> str:
        if ctx.em_lambda:
            self.problema("closure_dentro_de_fn", "")
            return "php.pendencia('closure dentro de fn')"
        self.contador += 1
        nome = f"_fn_{self.contador}"
        assinatura, prologo = self.parametros(ir[1], ctx)
        guardado = self.pre
        self.pre = []
        corpo = prologo + self.bloco(ir[3], ctx)
        antes = self.pre
        self.pre = guardado
        linhas = [f"def {nome}({assinatura}):"] + ["    " + x for x in (antes + corpo or ["pass"])]
        self.pre.extend(linhas)
        tipos = self.tipos_classe(ir[1])
        return f"php.tipos({nome}, {tipos!r})" if tipos else nome

    # ------------------------------------------------------------------ comandos
    def bloco(self, stmts, ctx) -> list[str]:
        linhas = []
        for s in stmts or []:
            linhas += self.stmt(s, ctx)
        return linhas

    def _com_pre(self, linhas) -> list[str]:
        pre, self.pre = self.pre, []
        return pre + linhas

    def stmt(self, s, ctx) -> list[str]:  # noqa: C901
        k = s[0]
        if k == "expr":
            e = s[1]
            if e[0] == "assign":
                return self._com_pre(self.atribuir(e[1], self.ex(e[2], ctx), ctx))
            if e[0] == "assignop":
                return self._com_pre(self.atribuir(e[2], self.op_composto(e[1], e[2], e[3], ctx), ctx))
            if e[0] == "destruct":
                alvos = [py_var(a[1]) if a[0] == "var" else None for a in e[1]]
                if None in alvos:
                    self.problema("desestruturacao", "")
                    return ["php.pendencia('desestruturação')"]
                return self._com_pre([f"{', '.join(alvos)}{',' if len(alvos) == 1 else ''} = php.destruct({self.ex(e[2], ctx)}, {len(alvos)})"])
            if e[0] == "throwx":
                return self._com_pre([f"php.lancar({self.ex(e[1], ctx)})"])
            return self._com_pre([self.ex(e, ctx)])
        if k == "return":
            return self._com_pre([f"return {self.ex(s[1], ctx)}" if s[1] is not None else "return None"])
        if k == "bloco":
            return self.bloco(s[1], ctx)
        if k == "if":
            # As condições são traduzidas antes: um def de closure numa condição de
            # elif sobe para antes do if inteiro (definir cedo não executa nada).
            conds = [self.verdade(self.ex(cond, ctx)) for cond, _ in s[1]]
            linhas, self.pre = self.pre, []
            for i, ((_, corpo), c) in enumerate(zip(s[1], conds)):
                linhas.append(("if " if i == 0 else "elif ") + c + ":")
                linhas += ["    " + x for x in (self.bloco(corpo, ctx) or ["pass"])]
            if s[2] is not None:
                linhas.append("else:")
                linhas += ["    " + x for x in (self.bloco(s[2], ctx) or ["pass"])]
            return linhas
        if k == "foreach":
            sujeito = self.ex(s[1], ctx)
            pre, self.pre = self.pre, []
            if s[3][0] != "var" or (s[2] is not None and s[2][0] != "var"):
                self.problema("foreach_alvo", s[3][0])
                return pre + ["php.pendencia('foreach com alvo complexo')"]
            v = py_var(s[3][1])
            if s[2] is not None:
                cabeca = f"for {py_var(s[2][1])}, {v} in php.itens({sujeito}):"
            else:
                cabeca = f"for {v} in php.valores({sujeito}):"
            return pre + [cabeca] + ["    " + x for x in (self.bloco(s[4], ctx) or ["pass"])]
        if k == "while":
            c = self.verdade(self.ex(s[1], ctx))
            pre, self.pre = self.pre, []
            return pre + [f"while {c}:"] + ["    " + x for x in (self.bloco(s[2], ctx) or ["pass"])]
        if k == "throw":
            return self._com_pre([f"php.lancar({self.ex(s[1], ctx)})"])
        if k == "try":
            linhas = ["try:"] + ["    " + x for x in (self.bloco(s[1], ctx) or ["pass"])]
            for tipos, var, corpo in s[2]:
                for t in tipos:
                    if self.eh_app(t) and self.ref_atual is not None:
                        self.ref_atual.add((t, "*"))
                nomes = ", ".join(repr(t) for t in tipos)
                linhas.append(f"except php.capturaveis({nomes})" + (f" as {py_var(var)}:" if var else ":"))
                linhas += ["    " + x for x in (self.bloco(corpo, ctx) or ["pass"])]
            if s[3] is not None:
                linhas.append("finally:")
                linhas += ["    " + x for x in (self.bloco(s[3], ctx) or ["pass"])]
            if not s[2] and s[3] is None:
                linhas.append("finally:")
                linhas.append("    pass")
            return linhas
        if k == "break":
            return ["break"]
        if k == "continue":
            return ["continue"]
        if k == "unset":
            linhas = []
            for alvo in s[1]:
                if alvo[0] == "idx" and alvo[2] is not None:
                    linhas.append(f"php.unset({self.alvo_escrita(alvo[1], ctx)}, {self.ex(alvo[2], ctx)})")
                elif alvo[0] == "var":
                    linhas.append(f"{py_var(alvo[1])} = None")
                elif alvo[0] == "prop":
                    linhas.append(f"php.prop_set({self.ex(alvo[1], ctx)}, {alvo[2]!r}, None)")
                else:
                    self.problema("unset", alvo[0])
            return self._com_pre(linhas)
        if k == "?":
            self.problema("php_nao_lido", f"{s[1]} linha {s[2]}")
            return [f"php.pendencia({('nó ' + s[1])!r})"]
        self.problema("comando_sem_traducao", k)
        return [f"php.pendencia({('comando ' + k)!r})"]

    def atribuir(self, alvo, valor: str, ctx) -> list[str]:
        k = alvo[0]
        if k == "var":
            return [f"{py_var(alvo[1])} = {valor}"]
        if k == "prop" and alvo[1] == ["this"] and not ctx.estatico and self.prop_declarada(ctx.classe, alvo[2]):
            return [f"self.p_{alvo[2]} = {valor}"]
        return [self.ex_assign(alvo, valor, ctx)]

    # ------------------------------------------------------------------ classes
    def ordem(self) -> list[str]:
        feitas, saida = set(), []

        def visitar(fq, pilha=()):
            if fq in feitas or fq not in self.classes or fq in pilha:
                return
            c = self.classes[fq]
            for dep in [c.get("pai"), *c.get("tracos", [])]:
                if dep in self.classes:
                    visitar(dep, pilha + (fq,))
            feitas.add(fq)
            saida.append(fq)

        for fq in sorted(self.classes):
            visitar(fq)
        return saida

    def classe(self, fq) -> list[str]:
        c = self.classes[fq]
        nome = self.nomes[fq]
        ctx = Contexto(fq)
        self.onde = f"{c['arquivo']}:{c['linha']} {nome}"
        bases = []
        for t in c.get("tracos", []):
            if t in self.classes:
                bases.append(self.nomes[t])
            elif t in lv.TRACOS:
                bases.append(self.ref_framework(t))
            elif t not in lv.TRACOS_SEM_EFEITO:
                self.problema("traco_sem_traducao", t)
        pai = c.get("pai")
        if pai:
            if pai in self.classes:
                bases.append(self.nomes[pai])
            elif lv.tem_classe(pai):
                bases.append(self.ref_framework(pai))
            else:
                self.problema("classe_base_sem_traducao", pai)
        if not bases:
            bases.append("Base")
        linhas = [f"class {nome}({', '.join(bases)}):", f"    _fqcn = {fq!r}"]
        if c.get("interfaces"):
            linhas.append(f"    _interfaces = {tuple(c['interfaces'])!r}")
        ctx.corpo_classe = True
        for k_nome, valor in c["constantes"].items():
            self.ref_atual = self.refs.setdefault(f"{fq}::*", set())
            linhas += ["    " + x for x in self._com_pre([f"k_{k_nome} = {self.valor_de_classe(valor, ctx, nome + '::' + k_nome)}"])]
        for p_nome, p in c["propriedades"].items():
            self.ref_atual = self.refs.setdefault(f"{fq}::*", set())
            v = self.valor_de_classe(p["valor"], ctx, nome + "::$" + p_nome) if p["valor"] is not None else "None"
            linhas += ["    " + x for x in self._com_pre([f"p_{p_nome} = {v}"])]
        ctx.corpo_classe = False
        # Tipos dos parâmetros por nome PHP: o runtime injeta FormRequest, model e
        # dependências do construtor lendo daqui (o Laravel lê por reflexão).
        meta = {}
        for m_nome, m in c["metodos"].items():
            chave = "_construct" if m_nome == "__construct" else m_nome
            meta[chave] = [{k: v for k, v in p.items() if k in ("nome", "tipo")} | ({"padrao": True} if "padrao" in p else {})
                           for p in m["params"]]
            linhas += ["    " + x for x in self.metodo(fq, m_nome, m)]
        linhas.append(f"    __params__ = {meta!r}")
        self.ref_atual = None
        return linhas

    def valor_de_classe(self, ir, ctx, rotulo) -> str:
        """Constante e propriedade com expressão (não literal) não derrubam o import do módulo."""
        ok, _ = _php.avaliar_literal(ir)
        s = self.ex(ir, ctx)
        if ok or ir[0] in ("classref", "lit"):
            return s
        return f"php.tentar(lambda: {s}, {rotulo!r})"

    def metodo(self, fq, nome, m) -> list[str]:
        ctx = Contexto(fq, m["static"])
        self.onde = f"{self.classes[fq]['arquivo']}:{m['linha']} {self.nomes[fq]}::{nome}"
        self.ref_atual = self.refs.setdefault(f"{fq}::{nome}", set())
        self.pre = []
        params, prologo = self.parametros(m["params"], ctx)
        assinatura = ", ".join(x for x in ("cls" if m["static"] else "self", params) if x)
        for p in m["params"]:
            if p.get("promovida"):
                prologo.append(f"self.p_{p['nome']} = {py_var(p['nome'])}")
        if m["corpo"] is None:
            corpo = ["raise NotImplementedError"]
        else:
            corpo = prologo + self.bloco(m["corpo"], ctx)
        linhas = (["@classmethod"] if m["static"] else []) + [f"def {py_metodo(nome)}({assinatura}):"]
        linhas += ["    " + x for x in (corpo or ["pass"])]
        return linhas

    def funcao_global(self, nome, f) -> list[str]:
        """Função de helpers.php do app: vira função do módulo, com o nome prefixado."""
        ctx = Contexto(None, True)
        self.onde = f"{f['arquivo']}:{f['linha']} fn {nome}"
        self.ref_atual = self.refs.setdefault(f"fn::{nome}", set())
        self.pre = []
        params, prologo = self.parametros(f["params"], ctx)
        corpo = prologo + self.bloco(f["corpo"], ctx)
        self.ref_atual = None
        return [f"def fn_{nome}({params}):"] + ["    " + x for x in (corpo or ["pass"])]

    def modulo(self) -> str:
        corpos = []
        for fq in self.ordem():
            corpos.append("\n".join(self.classe(fq)))
        for nome, f in sorted(self.c.get("funcoes", {}).items()):
            corpos.append("\n".join(self.funcao_global(nome, f)))
        cabeca = [
            '"""Código do app Laravel traduzido do contrato (gerado; não edite à mão)."""',
            "# ruff: noqa",
            "import laravel_compat as lv",
            "from laravel_compat import php",
            "from laravel_compat.suporte import Base",
            "",
        ]
        for fq, apelido in sorted(self.framework.items(), key=lambda x: x[1]):
            cabeca.append(f"{apelido} = lv.classe({fq!r})")
        for nome, apelido in sorted(self.funcoes.items()):
            cabeca.append(f"{apelido} = lv.funcao({nome!r})")
        registro = "php.registrar({\n" + "".join(f"    {fq!r}: {self.nomes[fq]},\n" for fq in self.ordem()) + "})"
        return "\n".join(cabeca) + "\n\n\n" + "\n\n\n".join(corpos) + "\n\n\n" + registro + "\n"

    # ------------------------------------------------------------------ config
    def config(self, nome, ir) -> tuple[str, list]:
        antes = len(self.problemas)
        self.onde = f"config/{nome}.php"
        ctx = Contexto(None, True)
        self.pre = []
        corpo = self.ex(ir, ctx) if ir is not None else "{}"
        pre, self.pre = self.pre, []
        linhas = [f"def config_{re.sub(chr(92) + 'W', '_', nome)}():"] + ["    " + x for x in pre] + [f"    return {corpo}"]
        return "\n".join(linhas), self.problemas[antes:]
