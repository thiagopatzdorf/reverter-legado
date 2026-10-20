"""Validator do Laravel 9: as mesmas regras, a mesma ordem, as mesmas mensagens.

A resposta 422 é contrato visível do legado (o front lê `errors.campo[0]`), então
não basta "validar parecido": a ordem das regras, quando uma regra para as
outras (`required` que falha, `sometimes` sem o campo, `nullable` com null) e o
texto vindo de `lang/en/validation.php` do próprio app seguem o
`Illuminate\\Validation\\Validator`. O Pydantic gerado documenta o corpo no
OpenAPI; quem decide 422 é este arquivo.
"""
from __future__ import annotations

import re

from . import contexto, php
from .suporte import Arr, Base, Collection, Str, substituir

IMPLICITAS = {"Accepted", "AcceptedIf", "Declined", "DeclinedIf", "Filled", "Missing", "MissingIf",
              "MissingUnless", "MissingWith", "MissingWithAll", "Present", "Required", "RequiredIf",
              "RequiredIfAccepted", "RequiredUnless", "RequiredWith", "RequiredWithAll", "RequiredWithout",
              "RequiredWithoutAll"}
NUMERICAS = {"Numeric", "Integer", "Decimal"}
TAMANHO = {"Size", "Between", "Min", "Max", "Gt", "Lt", "Gte", "Lte"}
DEPENDENTES = {"RequiredWith", "RequiredWithAll", "RequiredWithout", "RequiredWithoutAll", "RequiredIf",
               "RequiredUnless", "Confirmed", "Same", "Different", "Unique", "Exists"}


class _Ausente:
    pass


AUSENTE = _Ausente()


class ValidationException(php.PHPException):
    _fqcn = "Illuminate\\Validation\\ValidationException"

    def __init__(self, validador=None, resposta=None, bag="default"):
        self.validator = validador
        self.status = 422
        mensagem = ValidationException.resumir(validador) if validador else "The given data was invalid."
        super().__init__(mensagem)

    @staticmethod
    def resumir(validador) -> str:
        """`ValidationException::summarize` do Laravel 9: 1ª mensagem + "(and N more errors)"."""
        msgs = [m for ms in validador.erros.values() for m in ms]
        if not msgs:
            return "The given data was invalid."
        primeira = msgs[0]
        resto = len(msgs) - 1
        if resto:
            plural = "error" if resto == 1 else "errors"
            primeira += " " + substituir(f"(and :count more {plural})", {"count": resto})
        return primeira

    def errors(self):
        return self.validator.erros

    @classmethod
    def withMessages(cls, mensagens):
        v = Validator({}, {})
        for k, ms in php.itens(mensagens):
            for m in (ms if isinstance(ms, (list, dict)) else [ms]):
                v._adicionar(k, m)
        return cls(v)


# --------------------------------------------------------------------------- objetos de regra
class Unique(Base):
    _fqcn = "Illuminate\\Validation\\Rules\\Unique"

    def _construct(self, tabela, coluna="NULL"):
        self.tabela, self.coluna = tabela, coluna
        self.ignorar, self.coluna_id = None, "id"
        self.extras = []

    def ignore(self, id_, coluna_id=None):
        if hasattr(id_, "getKey") and hasattr(id_, "getKeyName"):
            return self.ignoreModel(id_, coluna_id)
        self.ignorar, self.coluna_id = id_, coluna_id or "id"
        return self

    def ignoreModel(self, modelo, coluna_id=None):
        self.coluna_id = coluna_id or modelo.getKeyName()
        self.ignorar = modelo._p(self.coluna_id)
        return self

    def where(self, coluna, valor=None):
        self.extras.append((coluna, valor))
        return self


class Exists(Unique):
    _fqcn = "Illuminate\\Validation\\Rules\\Exists"


class In(Base):
    _fqcn = "Illuminate\\Validation\\Rules\\In"

    def _construct(self, valores):
        self.valores = php.valores(valores.all() if isinstance(valores, Collection) else valores)

    def regra(self):
        return ["in", [php.to_str(v) for v in self.valores]]


class NotIn(In):
    _fqcn = "Illuminate\\Validation\\Rules\\NotIn"

    def regra(self):
        return ["not_in", [php.to_str(v) for v in self.valores]]


class RequiredIf(Base):
    _fqcn = "Illuminate\\Validation\\Rules\\RequiredIf"

    def _construct(self, condicao):
        self.condicao = condicao

    def regra(self):
        c = self.condicao() if callable(self.condicao) else self.condicao
        return ["required", []] if php.truthy(c) else None


class Password(Base):
    _fqcn = "Illuminate\\Validation\\Rules\\Password"

    def _construct(self, minimo=8):
        self.minimo = max(8, php.to_int(minimo)) if False else php.to_int(minimo)
        self.letras = self.numeros = self.simbolos = self.misto = False
        self.mensagens = []

    @classmethod
    def min(cls, n):
        return cls(n)

    @classmethod
    def defaults(cls, fn=None):
        return cls(8)

    def letters(self):
        self.letras = True
        return self

    def numbers(self):
        self.numeros = True
        return self

    def symbols(self):
        self.simbolos = True
        return self

    def mixedCase(self):
        self.misto = True
        return self

    def uncompromised(self, *_):
        return self

    def passes(self, atributo, valor, validador):
        sub = Validator({atributo: valor}, {atributo: ["string", f"min:{self.minimo}"]})
        sub.passes()
        self.mensagens = list(sub.erros.get(atributo, []))
        if isinstance(valor, str):
            trad = contexto.aplicacao().traducoes.get("validation", {})
            if self.misto and not (re.search(r"\p{Lu}", valor) if False else (any(c.isupper() for c in valor) and any(c.islower() for c in valor))):
                self.mensagens.append(validador._texto_cru("The :attribute must contain at least one uppercase and one lowercase letter.", atributo, trad))
            if self.letras and not any(c.isalpha() for c in valor):
                self.mensagens.append(validador._texto_cru("The :attribute must contain at least one letter.", atributo, trad))
            if self.numeros and not any(c.isdigit() for c in valor):
                self.mensagens.append(validador._texto_cru("The :attribute must contain at least one number.", atributo, trad))
            if self.simbolos and not re.search(r"[^\w\s]", valor):
                self.mensagens.append(validador._texto_cru("The :attribute must contain at least one symbol.", atributo, trad))
        return not self.mensagens

    def message(self):
        return self.mensagens


class Rule(Base):
    _fqcn = "Illuminate\\Validation\\Rule"

    @staticmethod
    def unique(tabela, coluna="NULL"):
        return Unique(tabela, coluna)

    @staticmethod
    def exists(tabela, coluna="NULL"):
        return Exists(tabela, coluna)

    @staticmethod
    def in_(valores):
        return In(valores)

    @staticmethod
    def notIn(valores):
        return NotIn(valores)

    @staticmethod
    def requiredIf(condicao):
        return RequiredIf(condicao)


# --------------------------------------------------------------------------- Validator
def _studly(nome: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[_\-]", nome))


def _normalizar(regras) -> list:
    """Cada regra vira (Nome, parâmetros) ou objeto de regra."""
    if isinstance(regras, str):
        regras = regras.split("|")
    elif not isinstance(regras, (list, dict)):
        regras = [regras]
    saida = []
    for r in php.valores(regras):
        if isinstance(r, (In, RequiredIf)):
            conv = r.regra()
            if conv is None:
                continue
            saida.append((_studly(conv[0]), conv[1]))
        elif isinstance(r, Unique):
            saida.append(("Unique" if type(r) is Unique else "Exists", r))
        elif isinstance(r, str):
            if r == "":
                continue
            nome, _, param = r.partition(":")
            nome_l = nome.strip().lower()
            if nome_l in ("regex", "not_regex"):
                params = [param]
            else:
                params = [p for p in _csv(param)] if param else []
            saida.append((_studly(nome_l), params))
        else:
            saida.append(("objeto", r))
    return saida


def _csv(texto: str) -> list:
    import csv
    import io

    return next(csv.reader(io.StringIO(texto)))


class Validator(Base):
    _fqcn = "Illuminate\\Validation\\Validator"

    def _construct(self, dados, regras, mensagens=None, atributos=None):
        self.dados = dados if isinstance(dados, (dict, list)) else {}
        self.regras_originais = regras or {}
        self.mensagens = mensagens or {}
        self.atributos = atributos or {}
        self.erros: dict[str, list] = {}
        self.falhas: dict[str, dict] = {}
        self.implicitos: dict[str, str] = {}
        self.regras = self._explodir(regras or {})
        self.depois = []

    # Validator::make
    @classmethod
    def make(cls, dados, regras, mensagens=None, atributos=None):
        return cls(dados, regras, mensagens, atributos)

    def _explodir(self, regras) -> dict:
        saida = {}
        curingas = []
        for chave, r in php.itens(regras):
            chave = php.to_str(chave)
            if "*" in chave:
                curingas.append((chave, r))
            else:
                saida[chave] = saida.get(chave, []) + _normalizar(r)
        planos = Arr.dot(self.dados) if isinstance(self.dados, (dict, list)) else {}
        chaves_dados = self._todas_chaves(self.dados)
        for chave, r in curingas:
            padrao = "^" + re.escape(chave).replace(r"\*", "[^\\.]+") + r"\Z"
            for k in chaves_dados:
                if re.match(padrao, k):
                    self.implicitos[k] = chave
                    saida[k] = saida.get(k, []) + _normalizar(r)
        del planos
        return saida

    def _todas_chaves(self, dados, prefixo=""):
        chaves = []
        for k, v in php.itens(dados):
            nome = f"{prefixo}{k}"
            chaves.append(nome)
            if isinstance(v, (list, dict)):
                chaves += self._todas_chaves(v, nome + ".")
        return chaves

    def _valor(self, atributo):
        return Arr.get(self.dados, atributo)

    def _presente(self, atributo):
        return Arr.has(self.dados, atributo)

    def _tem(self, atributo, nomes) -> bool:
        return any(n in nomes for n, _ in self.regras.get(atributo, []) if isinstance(n, str))

    # -------- laço principal
    def passes(self):
        self.erros, self.falhas = {}, {}
        for atributo, regras in self.regras.items():
            for nome, params in regras:
                self._validar(atributo, nome, params)
                if self._parar(atributo):
                    break
        for fn in self.depois:
            fn(self)
        return not self.erros

    def fails(self):
        return not self.passes()

    def validate(self):
        if self.fails():
            raise ValidationException(self)
        return self.validated()

    def after(self, fn):
        self.depois.append(fn)
        return self

    def errors(self):
        return MessageBag(self.erros)

    def _parar(self, atributo) -> bool:
        if self._tem(atributo, {"Bail"}):
            return atributo in self.erros
        falhou = set(self.falhas.get(atributo, {}))
        return bool(falhou & IMPLICITAS)

    def _validavel(self, nome, atributo, valor) -> bool:
        implicita = nome in IMPLICITAS
        if isinstance(valor, str) and valor.strip() == "":
            presente = implicita
        else:
            presente = self._presente(atributo) or implicita
        if not presente:
            return False
        if self._tem(atributo, {"Sometimes"}) and not self._presente(atributo):
            return False
        if not implicita and self._tem(atributo, {"Nullable"}) and Arr.get(self.dados, atributo, 0) is None:
            return False
        if nome in ("Unique", "Exists") and atributo in self.erros:
            return False
        return True

    def _validar(self, atributo, nome, params):
        valor = self._valor(atributo)
        if nome == "objeto":
            if not self._validavel("objeto", atributo, valor):
                return
            regra = params
            if callable(regra) and not hasattr(regra, "passes"):
                mensagens = []
                regra(atributo, valor, lambda m: mensagens.append(m))
                for m in mensagens:
                    self._adicionar(atributo, self._substituir(m, atributo, "Closure", []))
                if mensagens:
                    self.falhas.setdefault(atributo, {})["Closure"] = []
                return
            if not php.truthy(regra.passes(atributo, valor) if regra.passes.__code__.co_argcount <= 3 else
                              regra.passes(atributo, valor, self)):
                self.falhas.setdefault(atributo, {})[php.fqcn(regra)] = []
                msgs = regra.message()
                msgs = msgs if isinstance(msgs, (list, dict)) else [msgs]
                for k, m in php.itens(msgs):
                    chave = k if isinstance(k, str) else atributo
                    self._adicionar(chave, self._substituir(php.to_str(m), chave, php.fqcn(regra), []))
            return
        if nome in ("Sometimes", "Nullable", "Bail", "Exclude"):
            return
        if not self._validavel(nome, atributo, valor):
            return
        metodo = getattr(self, "validate" + nome, None)
        if metodo is None:
            raise php.Pendencia(f"regra de validação {nome}")
        if not metodo(atributo, valor, params):
            self.falhas.setdefault(atributo, {})[nome] = params
            self._adicionar(atributo, self._mensagem(atributo, nome, params))

    def _adicionar(self, atributo, mensagem):
        lista = self.erros.setdefault(atributo, [])
        # MessageBag::add só guarda mensagem que ainda não está lá.
        if mensagem not in lista:
            lista.append(mensagem)

    # -------- mensagens
    def _trad(self):
        return contexto.aplicacao().traducoes.get("validation", {})

    def _mensagem(self, atributo, nome, params) -> str:
        trad = self._trad()
        snake = Str.snake(nome)
        personal = self.mensagens.get(f"{atributo}.{snake}") or self.mensagens.get(snake)
        if personal is None:
            custom = Arr.get(trad, f"custom.{atributo}.{snake}")
            personal = custom if isinstance(custom, str) else None
        if personal is None:
            linha = trad.get(snake)
            if nome in TAMANHO and isinstance(linha, dict):
                linha = linha.get(self._tipo(atributo))
            personal = linha if isinstance(linha, str) else f"validation.{snake}"
        return self._substituir(personal, atributo, nome, params)

    def _texto_cru(self, texto, atributo, trad=None):
        return self._substituir(texto, atributo, "", [])

    def _tipo(self, atributo):
        if self._tem(atributo, NUMERICAS):
            return "numeric"
        if self._tem(atributo, {"Array"}):
            return "array"
        return "string"

    def _nome_visivel(self, atributo) -> str:
        if atributo in self.atributos:
            return self.atributos[atributo]
        trad = self._trad().get("attributes", {})
        primario = self.implicitos.get(atributo, atributo)
        for a in (atributo, primario):
            if isinstance(trad, dict) and a in trad:
                return trad[a]
        return Str.snake(atributo).replace("_", " ")

    def _substituir(self, texto, atributo, nome, params) -> str:
        troca = {"attribute": self._nome_visivel(atributo)}
        if nome in ("Min",):
            troca["min"] = params[0]
        elif nome in ("Max",):
            troca["max"] = params[0]
        elif nome in ("Size",):
            troca["size"] = params[0]
        elif nome in ("Between", "DigitsBetween"):
            troca["min"], troca["max"] = params[0], params[1]
        elif nome in ("In", "NotIn"):
            troca["values"] = ", ".join(params)
        elif nome in ("RequiredWith", "RequiredWithAll", "RequiredWithout", "RequiredWithoutAll"):
            troca["values"] = " / ".join(self._nome_visivel(p) for p in params)
        elif nome in ("Same", "Different"):
            troca["other"] = self._nome_visivel(params[0])
        elif nome in ("RequiredIf", "RequiredUnless"):
            troca["other"] = self._nome_visivel(params[0])
            troca["value"] = params[1] if len(params) > 1 else ""
            troca["values"] = ", ".join(params[1:])
        elif nome == "Digits":
            troca["digits"] = params[0]
        elif nome in ("StartsWith", "EndsWith"):
            troca["values"] = ", ".join(params)
        valor = self._valor(atributo)
        if isinstance(valor, (str, int, float)):
            troca["input"] = php.to_str(valor)
        return substituir(texto, troca)

    # -------- validated
    def validated(self):
        if not self.erros and not getattr(self, "_rodou", False):
            self._rodou = True
            if not self.passes():
                raise ValidationException(self)
        if self.erros:
            raise ValidationException(self)
        resultado = {}
        chaves = list(self.regras.keys())
        for chave in chaves:
            nomes = [n for n, _ in self.regras[chave] if isinstance(n, str)]
            if "Array" in nomes and any(k.startswith(chave + ".") for k in chaves):
                continue
            sentinela = AUSENTE
            v = Arr.get(self.dados, chave, sentinela)
            if v is not sentinela:
                Arr.set(resultado, chave, v)
        return resultado

    def safe(self):
        return Collection(self.validated())

    # -------- regras
    def _tamanho(self, atributo, valor):
        if php.is_numeric(valor) and self._tem(atributo, NUMERICAS):
            return php._num(valor)
        if isinstance(valor, (list, dict)):
            return len(valor)
        return len(php.to_str(valor))

    def validateRequired(self, a, v, p):
        if v is None:
            return False
        if isinstance(v, str) and v.strip() == "":
            return False
        if isinstance(v, (list, dict)) and len(v) == 0:
            return False
        if isinstance(v, Collection) and v.count() == 0:
            return False
        return True

    def validateFilled(self, a, v, p):
        return self.validateRequired(a, v, p) if self._presente(a) else True

    def validatePresent(self, a, v, p):
        return self._presente(a)

    def validateString(self, a, v, p):
        return isinstance(v, str)

    def validateInteger(self, a, v, p):
        return php.filter_var(v, php.FILTER_VALIDATE_INT) is not False

    def validateNumeric(self, a, v, p):
        return php.is_numeric(v)

    def validateBoolean(self, a, v, p):
        return any(php.ident(v, x) for x in (True, False, 0, 1, "0", "1"))

    def validateArray(self, a, v, p):
        if not isinstance(v, (list, dict)):
            return False
        if not p:
            return True
        return all(php.to_str(k) in p for k in php.array_keys(v))

    def validateEmail(self, a, v, p):
        if not isinstance(v, str):
            return False
        return re.fullmatch(r"[^@\s\"(),:;<>\[\\\]]+@[^@\s\"(),:;<>\[\\\]]+", v) is not None and ".." not in v

    def validateUrl(self, a, v, p):
        if not isinstance(v, str):
            return False
        return re.fullmatch(r"(?i)(https?|ftp|ftps|file|mailto|ssh|git|svn|ws|wss)://([^\s/?#@]+@)?(\[[0-9a-f:.]+\]|[\w.-]+\.?)(:\d+)?([/?#][^\s]*)?", v) is not None \
            or re.fullmatch(r"(?i)https?://localhost(:\d+)?([/?#][^\s]*)?", v) is not None

    def validateMin(self, a, v, p):
        return self._tamanho(a, v) >= php._num(p[0])

    def validateMax(self, a, v, p):
        return self._tamanho(a, v) <= php._num(p[0])

    def validateSize(self, a, v, p):
        return self._tamanho(a, v) == php._num(p[0])

    def validateBetween(self, a, v, p):
        t = self._tamanho(a, v)
        return php._num(p[0]) <= t <= php._num(p[1])

    def validateIn(self, a, v, p):
        if isinstance(v, (list, dict)):
            return all(php.to_str(x) in p for x in php.valores(v))
        return not isinstance(v, (list, dict)) and php.to_str(v) in p

    def validateNotIn(self, a, v, p):
        return not self.validateIn(a, v, p)

    def validateRegex(self, a, v, p):
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            return False
        return php.preg_match(p[0], php.to_str(v)) > 0

    def validateNotRegex(self, a, v, p):
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            return False
        return php.preg_match(p[0], php.to_str(v)) < 1

    def validateAlpha(self, a, v, p):
        return isinstance(v, str) and re.fullmatch(r"[^\W\d_]+", v) is not None

    def validateAlphaNum(self, a, v, p):
        return isinstance(v, (str, int)) and re.fullmatch(r"[^\W_]+", php.to_str(v)) is not None

    def validateAlphaDash(self, a, v, p):
        return isinstance(v, (str, int)) and re.fullmatch(r"[\w-]+", php.to_str(v)) is not None

    def validateDigits(self, a, v, p):
        s = php.to_str(v)
        return s.isdigit() and len(s) == php.to_int(p[0])

    def validateDigitsBetween(self, a, v, p):
        s = php.to_str(v)
        return s.isdigit() and php.to_int(p[0]) <= len(s) <= php.to_int(p[1])

    def validateJson(self, a, v, p):
        if not isinstance(v, str):
            return False
        import json

        try:
            json.loads(v)
            return True
        except ValueError:
            return False

    def validateUuid(self, a, v, p):
        return isinstance(v, str) and re.fullmatch(r"(?i)[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}", v) is not None

    def validateAccepted(self, a, v, p):
        return self.validateRequired(a, v, p) and any(php.ident(v, x) for x in ("yes", "on", "1", 1, True, "true"))

    def validateDate(self, a, v, p):
        if not isinstance(v, str):
            return False
        try:
            from .suporte import Carbon

            Carbon(v)
            return True
        except php.Throwable:
            return False

    def validateStartsWith(self, a, v, p):
        return any(php.to_str(v).startswith(x) for x in p)

    def validateEndsWith(self, a, v, p):
        return any(php.to_str(v).endswith(x) for x in p)

    def validateConfirmed(self, a, v, p):
        return self.validateSame(a, v, [a + "_confirmation"])

    def validateSame(self, a, v, p):
        return php.ident(v, Arr.get(self.dados, p[0]))

    def validateDifferent(self, a, v, p):
        return all(not php.ident(v, Arr.get(self.dados, x)) for x in p)

    def _falha_algum(self, campos):
        return any(not self.validateRequired(c, self._valor(c), []) for c in campos)

    def _falham_todos(self, campos):
        return all(not self.validateRequired(c, self._valor(c), []) for c in campos)

    def validateRequiredWith(self, a, v, p):
        return self.validateRequired(a, v, p) if not self._falham_todos(p) else True

    def validateRequiredWithAll(self, a, v, p):
        return self.validateRequired(a, v, p) if not self._falha_algum(p) else True

    def validateRequiredWithout(self, a, v, p):
        return self.validateRequired(a, v, p) if self._falha_algum(p) else True

    def validateRequiredWithoutAll(self, a, v, p):
        return self.validateRequired(a, v, p) if self._falham_todos(p) else True

    def validateRequiredIf(self, a, v, p):
        outro = Arr.get(self.dados, p[0])
        if any(php.to_str(outro) == x for x in p[1:]):
            return self.validateRequired(a, v, p)
        return True

    def validateRequiredUnless(self, a, v, p):
        outro = Arr.get(self.dados, p[0])
        if not any(php.to_str(outro) == x for x in p[1:]):
            return self.validateRequired(a, v, p)
        return True

    def _contar(self, regra, a, v):
        from .eloquent import executar, q
        import sqlalchemy as sa

        if isinstance(regra, Unique):
            tabela, coluna, ignorar, coluna_id, extras = regra.tabela, regra.coluna, regra.ignorar, regra.coluna_id, regra.extras
        else:
            tabela = regra[0]
            coluna = regra[1] if len(regra) > 1 else "NULL"
            ignorar = regra[2] if len(regra) > 2 else None
            coluna_id = regra[3] if len(regra) > 3 and regra[3] != "NULL" else "id"
            extras = []
            if ignorar is not None:
                ignorar = ignorar.strip('"') if ignorar not in ("NULL", "") else None
        if php.existe_classe(tabela):
            tabela = php.classe(tabela)().getTable()
        if coluna == "NULL":
            coluna = a.split(".")[-1]
        stmt = sa.select(sa.func.count().label("n")).select_from(sa.table(tabela)).where(q(coluna) == sa.bindparam(None, v))
        if ignorar is not None and ignorar != "NULL":
            stmt = stmt.where(q(coluna_id or "id") != sa.bindparam(None, ignorar))
        for col, val in extras:
            stmt = stmt.where(q(col) == sa.bindparam(None, val))
        return executar(stmt)[0]["n"]

    def validateUnique(self, a, v, p):
        return self._contar(p, a, v) == 0

    def validateExists(self, a, v, p):
        if isinstance(v, (list, dict)):
            return all(self._contar(p, a, x) > 0 for x in php.valores(v))
        return self._contar(p, a, v) > 0


class MessageBag(Base):
    _fqcn = "Illuminate\\Support\\MessageBag"

    def _construct(self, msgs=None):
        self.msgs = msgs or {}

    def all(self):
        return [m for ms in self.msgs.values() for m in ms]

    def first(self, chave=None):
        if chave:
            return (self.msgs.get(chave) or [""])[0]
        todos = self.all()
        return todos[0] if todos else ""

    def has(self, chave):
        return bool(self.msgs.get(chave))

    def toArray(self):
        return self.msgs

    def messages(self):
        return self.msgs

    def isEmpty(self):
        return not self.msgs

    def isNotEmpty(self):
        return bool(self.msgs)


class ValidatorFacade(Base):
    _fqcn = "Illuminate\\Support\\Facades\\Validator"

    @staticmethod
    def make(dados, regras, mensagens=None, atributos=None):
        return Validator(dados, regras, mensagens, atributos)
