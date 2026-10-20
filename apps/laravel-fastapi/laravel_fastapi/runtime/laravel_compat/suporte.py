"""Illuminate\\Support que o código traduzido usa: Collection, Arr, Str, Carbon, Hash,
config(), trans(), env().

Cada classe reproduz o comportamento do Laravel 9 que dá para ver de fora (o que
volta, o que muta), não a implementação. Onde o Laravel muta (Carbon::addSeconds,
Arr::pull), aqui também muta: o diferencial pega quem não mutar.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import unicodedata

from . import contexto, php


class Base:
    """Raiz de toda classe traduzida: o construtor do PHP é `_construct`."""

    _fqcn = "stdClass"

    def __init__(self, *args, **kwargs):
        self._construct(*args, **kwargs)

    def _construct(self, *args, **kwargs):
        pass

    # Propriedade PHP mora em `p_<nome>`: método e propriedade com o mesmo nome
    # (comum no PHP, ex.: $rules e rules()) não colidem no Python.
    def _p(self, nome):
        return getattr(self, "p_" + nome, None)

    def _ps(self, nome, valor):
        setattr(self, "p_" + nome, valor)
        return valor


# --------------------------------------------------------------------------- Collection
class Collection(Base):
    _fqcn = "Illuminate\\Support\\Collection"

    def _construct(self, items=None):
        if items is None:
            items = []
        elif isinstance(items, Collection):
            items = items.items_copia()
        elif hasattr(items, "toArray") and not isinstance(items, (list, dict)):
            items = items.toArray()
        elif not isinstance(items, (list, dict)):
            items = [items]
        self.items = items

    def items_copia(self):
        return dict(self.items) if isinstance(self.items, dict) else list(self.items)

    def __clone__(self):
        return type(self)(self.items_copia())

    @classmethod
    def make(cls, items=None):
        return cls(items)

    # -------- acesso
    def all(self):
        return self.items

    def toArray(self):
        return [php.para_json(v) if hasattr(v, "toArray") else v for v in self.items] if isinstance(self.items, list) \
            else {k: (v.toArray() if hasattr(v, "toArray") and not isinstance(v, (list, dict)) else v) for k, v in self.items.items()}

    def jsonSerialize(self):
        return self.items

    def toJson(self, flags=0):
        return php.json_encode(self.items, flags)

    def __iter__(self):
        return iter(php.valores(self.items))

    def __len__(self):
        return len(self.items)

    def count(self):
        return len(self.items)

    def get(self, chave, padrao=None):
        if php.array_key_exists(chave, self.items):
            return php.idx(self.items, chave)
        return padrao() if callable(padrao) else padrao

    def has(self, chave):
        return php.array_key_exists(chave, self.items)

    def offsetGet(self, chave):
        return php.idx(self.items, chave)

    def offsetSet(self, chave, valor):
        if chave is None:
            php.push(self.items, valor)
        else:
            if isinstance(self.items, list) and not (isinstance(chave, int) and chave <= len(self.items)):
                self.items = dict(enumerate(self.items))
            php.idx_set(self.items, chave, valor)

    def offsetExists(self, chave):
        return php.array_key_exists(chave, self.items)

    def offsetUnset(self, chave):
        php.unset(self.items, chave)

    def __getitem__(self, chave):
        return self.offsetGet(chave)

    def put(self, chave, valor):
        self.offsetSet(chave, valor)
        return self

    def push(self, *valores):
        for v in valores:
            php.push(self.items, v)
        return self

    def first(self, fn=None, padrao=None):
        for k, v in php.itens(self.items):
            if fn is None or php.truthy(fn(v, k)):
                return v
        return padrao

    def last(self, fn=None, padrao=None):
        for k, v in reversed(php.itens(self.items)):
            if fn is None or php.truthy(fn(v, k)):
                return v
        return padrao

    def isEmpty(self):
        return len(self.items) == 0

    def isNotEmpty(self):
        return len(self.items) > 0

    def keys(self):
        return Collection(php.array_keys(self.items))

    def values(self):
        return Collection(php.valores(self.items))

    def contains(self, chave, *args):
        if callable(chave):
            return any(php.truthy(chave(v, k)) for k, v in php.itens(self.items))
        if args:
            return any(php.eq(data_get(v, chave), args[-1]) for v in self)
        return any(php.eq(v, chave) for v in self)

    # -------- transformação
    def map(self, fn):
        if isinstance(self.items, dict):
            return Collection({k: fn(v, k) for k, v in self.items.items()})
        return Collection([fn(v, k) for k, v in enumerate(self.items)])

    def each(self, fn):
        for k, v in php.itens(self.items):
            if fn(v, k) is False:
                break
        return self

    def filter(self, fn=None):
        if isinstance(self.items, list):
            return Collection(dict((k, v) for k, v in enumerate(self.items)
                                   if php.truthy(fn(v, k) if fn else v)))
        return Collection({k: v for k, v in self.items.items() if php.truthy(fn(v, k) if fn else v)})

    def reject(self, fn):
        return self.filter(lambda v, k: not php.truthy(fn(v, k)))

    def pluck(self, valor, chave=None):
        if chave is None:
            return Collection([data_get(v, valor) for v in self])
        return Collection({data_get(v, chave): data_get(v, valor) for v in self})

    def where(self, chave, op=None, valor=None):
        if valor is None and op is not None and op not in ("=", "==", "===", "!=", "<>", ">", "<", ">=", "<="):
            op, valor = "=", op
        return self.filter(lambda v, k: php.eq(data_get(v, chave), valor) if op in ("=", "==") else
                           php.ident(data_get(v, chave), valor) if op == "===" else not php.eq(data_get(v, chave), valor))

    def whereIn(self, chave, vals):
        vals = php.valores(php.to_array(vals))
        return self.filter(lambda v, k: any(php.eq(data_get(v, chave), x) for x in vals))

    def sortBy(self, chave, opcoes=0, desc=False):
        fn = chave if callable(chave) else (lambda v: data_get(v, chave))
        pares = sorted(php.itens(self.items), key=lambda kv: fn(kv[1]), reverse=desc)
        return Collection(dict(pares))

    def sortByDesc(self, chave, opcoes=0):
        return self.sortBy(chave, opcoes, True)

    def unique(self, chave=None):
        vistos, saida = [], {}
        for k, v in php.itens(self.items):
            x = data_get(v, chave) if chave else v
            if not any(php.eq(x, y) for y in vistos):
                vistos.append(x)
                saida[k] = v
        return Collection(saida)

    def merge(self, outros):
        return Collection(php.array_merge(self.items, php.to_array(outros.all() if isinstance(outros, Collection) else outros)))

    def flatten(self, prof=float("inf")):
        saida = []

        def ir(xs, p):
            for v in php.valores(xs):
                if isinstance(v, (list, dict, Collection)) and p > 0:
                    ir(v.all() if isinstance(v, Collection) else v, p - 1)
                else:
                    saida.append(v)

        ir(self.items, prof)
        return Collection(saida)

    def implode(self, valor, cola=None):
        if cola is None:
            return php.implode(valor, self.items)
        return php.implode(cola, [data_get(v, valor) for v in self])

    def sum(self, chave=None):
        return sum(php._num(data_get(v, chave) if chave else v) for v in self)

    def mapWithKeys(self, fn):
        saida = {}
        for k, v in php.itens(self.items):
            saida.update(fn(v, k))
        return Collection(saida)

    def keyBy(self, chave):
        return Collection({data_get(v, chave): v for v in self})

    def groupBy(self, chave):
        saida = {}
        for v in self:
            saida.setdefault(data_get(v, chave), []).append(v)
        return Collection({k: Collection(x) for k, x in saida.items()})

    def take(self, n):
        vals = php.itens(self.items)
        return Collection(dict(vals[:n] if n >= 0 else vals[n:]))

    def only(self, chaves):
        chaves = php.valores(chaves)
        return Collection({k: v for k, v in php.itens(self.items) if k in chaves})

    def except_(self, chaves):
        chaves = php.valores(chaves)
        return Collection({k: v for k, v in php.itens(self.items) if k not in chaves})

    def reverse(self):
        return Collection(dict(reversed(php.itens(self.items))))

    def __repr__(self):
        return f"Collection({self.items!r})"


def collect(items=None):
    return Collection(items)


def data_get(alvo, chave, padrao=None):
    if chave is None:
        return alvo
    for parte in str(chave).split("."):
        if alvo is None:
            return padrao
        if isinstance(alvo, (list, dict)):
            if not php.array_key_exists(parte, alvo):
                return padrao
            alvo = php.idx(alvo, parte)
        elif hasattr(alvo, "offsetExists") and alvo.offsetExists(parte):
            alvo = alvo.offsetGet(parte)
        elif hasattr(alvo, "_p"):
            alvo = alvo._p(parte)
        else:
            return padrao
    return alvo


# --------------------------------------------------------------------------- Arr
class Arr(Base):
    _fqcn = "Illuminate\\Support\\Arr"

    @staticmethod
    def get(a, chave, padrao=None):
        if chave is None:
            return a
        if isinstance(a, (list, dict)) and php.array_key_exists(chave, a):
            return php.idx(a, chave)
        atual = a
        for parte in str(chave).split("."):
            if isinstance(atual, (list, dict)) and php.array_key_exists(parte, atual):
                atual = php.idx(atual, parte)
            elif hasattr(atual, "offsetExists") and atual.offsetExists(parte):
                atual = atual.offsetGet(parte)
            else:
                return padrao() if callable(padrao) else padrao
        return atual

    @staticmethod
    def set(a, chave, valor):
        partes = str(chave).split(".")
        atual = a
        for parte in partes[:-1]:
            prox = php.idx(atual, parte)
            if not isinstance(prox, (list, dict)):
                prox = {}
                php.idx_set(atual, parte, prox)
            atual = prox
        php.idx_set(atual, partes[-1], valor)
        return a

    @staticmethod
    def has(a, chave):
        sentinela = object()
        return Arr.get(a, chave, sentinela) is not sentinela

    @staticmethod
    def forget(a, chaves):
        for chave in (chaves if isinstance(chaves, list) else [chaves]):
            if isinstance(a, (list, dict)) and php.array_key_exists(chave, a):
                php.unset(a, chave)
                continue
            partes = str(chave).split(".")
            atual = a
            for parte in partes[:-1]:
                atual = php.idx(atual, parte)
                if not isinstance(atual, (list, dict)):
                    atual = None
                    break
            if atual is not None:
                php.unset(atual, partes[-1])

    @staticmethod
    def pull(a, chave, padrao=None):
        valor = Arr.get(a, chave, padrao)
        Arr.forget(a, chave)
        return valor

    @staticmethod
    def wrap(v):
        if v is None:
            return []
        return v if isinstance(v, (list, dict)) else [v]

    @staticmethod
    def only(a, chaves):
        chaves = php.valores(chaves) if isinstance(chaves, (list, dict)) else [chaves]
        return {k: v for k, v in php.itens(a) if k in chaves}

    @staticmethod
    def except_(a, chaves):
        copia = dict(php.itens(a))
        Arr.forget(copia, php.valores(chaves) if isinstance(chaves, (list, dict)) else [chaves])
        return copia

    @staticmethod
    def first(a, fn=None, padrao=None):
        for k, v in php.itens(a):
            if fn is None or php.truthy(fn(v, k)):
                return v
        return padrao

    @staticmethod
    def pluck(a, valor, chave=None):
        return Collection(a).pluck(valor, chave).all()

    @staticmethod
    def isAssoc(a):
        return not php.eh_lista(a)

    @staticmethod
    def dot(a, prefixo=""):
        saida = {}
        for k, v in php.itens(a):
            if isinstance(v, (list, dict)) and v:
                saida.update(Arr.dot(v, f"{prefixo}{k}."))
            else:
                saida[f"{prefixo}{k}"] = v
        return saida


# --------------------------------------------------------------------------- Str
def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


class Str(Base):
    _fqcn = "Illuminate\\Support\\Str"

    @staticmethod
    def slug(titulo, separador="-", lingua="en", dicionario=None):
        """Str::slug do Laravel 9: ASCII, '@' vira 'at', o resto vira separador."""
        if dicionario is None:
            dicionario = {"@": "at"}
        titulo = _ascii(php.to_str(titulo)) if lingua else php.to_str(titulo)
        flip = "_" if separador == "-" else "-"
        titulo = re.sub("[" + re.escape(flip) + "]+", separador, titulo)
        for k, v in dicionario.items():
            titulo = titulo.replace(k, separador + v + separador)
        titulo = re.sub(r"[^" + re.escape(separador) + r"\w\s]+", "", titulo.lower(), flags=re.UNICODE)
        titulo = re.sub(r"[" + re.escape(separador) + r"\s]+", separador, titulo)
        return titulo.strip(separador)

    @staticmethod
    def snake(valor, d="_"):
        # Str::snake: ctype_lower (só letras minúsculas) volta igual; senão ucwords,
        # tira espaço e põe o separador antes de cada maiúscula.
        valor = php.to_str(valor)
        if re.fullmatch(r"[a-z]+", valor):
            return valor
        valor = re.sub(r"\s+", "", php.ucwords(valor))
        return re.sub(r"(.)(?=[A-Z])", r"\1" + d, valor).lower()

    @staticmethod
    def camel(valor):
        s = Str.studly(valor)
        return s[:1].lower() + s[1:]

    @staticmethod
    def studly(valor):
        partes = re.split(r"[-_\s]+", php.to_str(valor))
        return "".join(p[:1].upper() + p[1:] for p in partes)

    @staticmethod
    def lower(v):
        return php.to_str(v).lower()

    @staticmethod
    def upper(v):
        return php.to_str(v).upper()

    @staticmethod
    def title(v):
        return php.to_str(v).title()

    @staticmethod
    def startsWith(s, agulhas):
        agulhas = agulhas if isinstance(agulhas, (list, dict)) else [agulhas]
        return any(php.to_str(a) != "" and php.to_str(s).startswith(php.to_str(a)) for a in php.valores(agulhas))

    @staticmethod
    def endsWith(s, agulhas):
        agulhas = agulhas if isinstance(agulhas, (list, dict)) else [agulhas]
        return any(php.to_str(a) != "" and php.to_str(s).endswith(php.to_str(a)) for a in php.valores(agulhas))

    @staticmethod
    def contains(s, agulhas, ignorar=False):
        agulhas = agulhas if isinstance(agulhas, (list, dict)) else [agulhas]
        s = php.to_str(s)
        return any(php.to_str(a) != "" and (php.to_str(a).lower() in s.lower() if ignorar else php.to_str(a) in s)
                   for a in php.valores(agulhas))

    @staticmethod
    def substr(s, ini, tam=None, enc="UTF-8"):
        return php.substr(s, ini, tam)

    @staticmethod
    def length(s, enc=None):
        return len(php.to_str(s))

    @staticmethod
    def limit(s, limite=100, fim="..."):
        s = php.to_str(s)
        return s if len(s) <= limite else s[:limite].rstrip() + fim

    @staticmethod
    def random(n=16):
        import secrets
        import string

        return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))

    @staticmethod
    def plural(valor, n=2):
        if php.to_int(n) == 1:
            return valor
        if re.search(r"[^aeiou]y$", valor):
            return valor[:-1] + "ies"
        if re.search(r"(s|x|z|ch|sh)$", valor):
            return valor + "es"
        return valor + "s"

    @staticmethod
    def singular(valor):
        if valor.endswith("ies"):
            return valor[:-3] + "y"
        if re.search(r"(ses|xes|zes|ches|shes)$", valor):
            return valor[:-2]
        return valor[:-1] if valor.endswith("s") and not valor.endswith("ss") else valor

    @staticmethod
    def uuid():
        import uuid

        return str(uuid.uuid4())

    @staticmethod
    def is_(padrao, valor):
        rx = "^" + re.escape(php.to_str(padrao)).replace("\\*", ".*") + r"\Z"
        return re.match(rx, php.to_str(valor)) is not None


def str_snake(nome: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", nome).lower()


# --------------------------------------------------------------------------- Carbon
FORMATO_BANCO = "%Y-%m-%d %H:%M:%S"


class Carbon(Base):
    """Data mutável como a do Carbon 2 (Illuminate\\Support\\Carbon): addSeconds muda o objeto."""

    _fqcn = "Illuminate\\Support\\Carbon"
    _agora_fixo: _dt.datetime | None = None

    def _construct(self, quando=None, tz=None):
        if isinstance(quando, _dt.datetime):
            self.dt = quando
        elif quando is None or quando == "now":
            self.dt = Carbon._agora()
        else:
            self.dt = Carbon._ler(php.to_str(quando))

    @staticmethod
    def _agora() -> _dt.datetime:
        if Carbon._agora_fixo is not None:
            return Carbon._agora_fixo
        return _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _ler(texto: str) -> _dt.datetime:
        texto = texto.strip().replace("T", " ").rstrip("Z")
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return _dt.datetime.strptime(texto, fmt)
            except ValueError:
                continue
        raise php.InvalidArgumentException(f"Could not parse '{texto}'")

    @classmethod
    def now(cls, tz=None):
        return cls(Carbon._agora())

    @classmethod
    def parse(cls, texto, tz=None):
        return cls(texto)

    @classmethod
    def createFromTimestamp(cls, ts, tz=None):
        return cls(_dt.datetime.fromtimestamp(php.to_float(ts), _dt.timezone.utc).replace(tzinfo=None))

    @classmethod
    def instance(cls, d):
        return cls(d.dt if isinstance(d, Carbon) else d)

    def __clone__(self):
        return type(self)(self.dt)

    def copy(self):
        return self.__clone__()

    def getTimestamp(self):
        return int(self.dt.replace(tzinfo=_dt.timezone.utc).timestamp())

    @property
    def timestamp(self):
        return self.getTimestamp()

    def _somar(self, **delta):
        self.dt = self.dt + _dt.timedelta(**delta)
        return self

    def addSeconds(self, n=1):
        return self._somar(seconds=php.to_int(n))

    def addSecond(self):
        return self.addSeconds(1)

    def subSeconds(self, n=1):
        return self._somar(seconds=-php.to_int(n))

    def addMinutes(self, n=1):
        return self._somar(minutes=php.to_int(n))

    def subMinutes(self, n=1):
        return self._somar(minutes=-php.to_int(n))

    def addHours(self, n=1):
        return self._somar(hours=php.to_int(n))

    def addDays(self, n=1):
        return self._somar(days=php.to_int(n))

    def subDays(self, n=1):
        return self._somar(days=-php.to_int(n))

    def lessThan(self, outro):
        return self.dt < _dt_de(outro)

    def greaterThan(self, outro):
        return self.dt > _dt_de(outro)

    def isPast(self):
        return self.dt < Carbon._agora()

    def isFuture(self):
        return self.dt > Carbon._agora()

    lt = lessThan
    gt = greaterThan

    def format(self, fmt):
        mapa = {"Y": "%Y", "m": "%m", "d": "%d", "H": "%H", "i": "%M", "s": "%S", "u": "%f", "y": "%y", "D": "%a",
                "M": "%b", "j": "%-d", "n": "%-m", "G": "%-H"}
        saida = []
        for c in fmt:
            saida.append(self.dt.strftime(mapa[c]) if c in mapa else c)
        return "".join(saida)

    def toDateTimeString(self):
        return self.dt.strftime(FORMATO_BANCO)

    def toJSON(self):
        return self.dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.dt.microsecond:06d}Z"

    toISOString = toJSON

    def jsonSerialize(self):
        return self.toJSON()

    def __toString(self):
        return self.toDateTimeString()

    def __str__(self):
        return self.toDateTimeString()

    def __eq__(self, outro):
        return isinstance(outro, Carbon) and self.dt == outro.dt

    def __hash__(self):
        return hash(self.dt)


def _dt_de(v):
    return v.dt if isinstance(v, Carbon) else Carbon._ler(php.to_str(v)) if isinstance(v, str) else v


def now(tz=None):
    return Carbon.now()


# --------------------------------------------------------------------------- Hash
class Hash(Base):
    _fqcn = "Illuminate\\Support\\Facades\\Hash"
    RODADAS = 10

    @staticmethod
    def make(valor, opcoes=None):
        import bcrypt

        h = bcrypt.hashpw(php.to_str(valor).encode(), bcrypt.gensalt(Hash.RODADAS)).decode()
        # O PHP grava bcrypt como $2y$; o algoritmo é o mesmo do $2b$.
        return "$2y$" + h[4:]

    @staticmethod
    def check(valor, hash_, opcoes=None):
        import bcrypt

        if not hash_:
            return False
        h = php.to_str(hash_)
        if h.startswith("$2y$"):
            h = "$2b$" + h[4:]
        try:
            return bcrypt.checkpw(php.to_str(valor).encode(), h.encode())
        except ValueError:
            return False

    @staticmethod
    def needsRehash(h, opcoes=None):
        return False


def bcrypt_(valor, opcoes=None):
    return Hash.make(valor)


# --------------------------------------------------------------------------- config, env, trans
def env(nome, padrao=None):
    v = os.environ.get(nome)
    if v is None:
        return padrao() if callable(padrao) else padrao
    baixo = v.lower()
    if baixo in ("true", "(true)"):
        return True
    if baixo in ("false", "(false)"):
        return False
    if baixo in ("null", "(null)"):
        return None
    if baixo in ("empty", "(empty)"):
        return ""
    if len(v) > 1 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def config(chave=None, padrao=None):
    app = contexto.aplicacao()
    if chave is None:
        return app.config
    if isinstance(chave, dict):
        for k, v in chave.items():
            app.config_definir(k, v)
        return None
    return app.config_ler(chave, padrao)


def trans(chave=None, troca=None, lingua=None):
    if chave is None:
        return None
    app = contexto.aplicacao()
    arquivo, _, resto = php.to_str(chave).partition(".")
    texto = Arr.get(app.traducoes.get(arquivo, {}), resto) if resto else app.traducoes.get(arquivo)
    if texto is None:
        texto = chave
    if isinstance(texto, str) and troca:
        texto = substituir(texto, troca)
    return texto


def substituir(texto: str, troca: dict) -> str:
    """Troca :nome, :Nome e :NOME como o Translator do Laravel, chaves mais longas antes."""
    for k in sorted(troca, key=lambda x: -len(str(x))):
        v = php.to_str(troca[k])
        texto = texto.replace(":" + str(k), v).replace(":" + str(k)[:1].upper() + str(k)[1:], v[:1].upper() + v[1:]).replace(":" + str(k).upper(), v.upper())
    return texto


def __(chave=None, troca=None, lingua=None):
    return trans(chave, troca, lingua)


def trans_choice(chave, n, troca=None, lingua=None):
    texto = trans(chave)
    if isinstance(texto, str) and "|" in texto:
        partes = texto.split("|")
        texto = partes[0] if php.to_int(n) == 1 else partes[-1]
    return substituir(texto, {"count": n, **(troca or {})}) if isinstance(texto, str) else texto


def base_path(rel=""):
    return php.to_str(rel)


def value(v, *args):
    return v(*args) if callable(v) else v


def tap(v, fn=None):
    if fn is not None:
        fn(v)
    return v


def blank(v):
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict)):
        return len(v) == 0
    if isinstance(v, Collection):
        return v.isEmpty()
    return False


def filled(v):
    return not blank(v)


def data_set(alvo, chave, valor):
    return Arr.set(alvo, chave, valor)


def optional(v):
    return v


class Facade(Base):
    _fqcn = "Illuminate\\Support\\Facades\\Facade"

    @staticmethod
    def defaultAliases():
        # Apelidos de fachada só servem às views e ao tinker; a API não lê.
        return Collection({})
