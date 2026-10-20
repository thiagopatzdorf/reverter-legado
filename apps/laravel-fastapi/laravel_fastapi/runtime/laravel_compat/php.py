"""Semântica do PHP que o código traduzido precisa e o Python não dá igual.

O tradutor nunca usa `and`/`or`/`==` do Python direto em valor vindo do PHP:
"0" é falso no PHP e verdadeiro no Python, `==` do PHP compara "1" com 1, e
`.` converte null em "". Cada diferença dessas vira uma função aqui, com o nome
da regra do PHP que ela reproduz.
"""
from __future__ import annotations

import base64 as _b64
import copy as _copy
import hashlib
import hmac
import json as _json
import math
import re

# --------------------------------------------------------------------------- classes
_CLASSES: dict[str, type] = {}


def registrar(mapa: dict) -> None:
    """FQCN -> classe Python. O PHP passa classe como string (`User::class`)."""
    for nome, cls in mapa.items():
        _CLASSES[nome.lstrip("\\").lower()] = cls
        # Apelido (mesma classe com dois nomes) não troca o nome canônico.
        if "_fqcn" not in cls.__dict__:
            cls._fqcn = nome.lstrip("\\")


def classe(nome):
    if isinstance(nome, type):
        return nome
    cls = _CLASSES.get(str(nome).lstrip("\\").lower())
    if cls is None:
        raise Error(f'Class "{nome}" not found')
    return cls


def existe_classe(nome) -> bool:
    return str(nome).lstrip("\\").lower() in _CLASSES


def fqcn(obj) -> str:
    cls = obj if isinstance(obj, type) else type(obj)
    return getattr(cls, "_fqcn", cls.__name__)


def instanceof(obj, nome) -> bool:
    if obj is None or isinstance(obj, (str, int, float, bool, list, dict)):
        return False
    alvo = str(nome).lstrip("\\").lower()
    for cls in type(obj).__mro__:
        if getattr(cls, "_fqcn", "").lower() == alvo and "_fqcn" in cls.__dict__:
            return True
        for i in cls.__dict__.get("_interfaces", ()):
            if i.lower() == alvo or _interface_herda(i, alvo):
                return True
    return False


def _interface_herda(i: str, alvo: str) -> bool:
    cls = _CLASSES.get(i.lower())
    if cls is None:
        return False
    return any(x.lower() == alvo or _interface_herda(x, alvo) for x in cls.__dict__.get("_interfaces", ()))


def classe_de(alvo):
    """`$x::metodo()`: $x pode ser o nome da classe ou um objeto dela."""
    return classe(alvo) if isinstance(alvo, str) else type(alvo)


def novo(nome, *args):
    return classe(nome)(*args)


def clone(obj):
    if hasattr(obj, "__clone__"):
        return obj.__clone__()
    return _copy.copy(obj)


# --------------------------------------------------------------------------- exceções
class Throwable(Exception):
    _fqcn = "Throwable"

    def __init__(self, message="", code=0, previous=None, *args):
        super().__init__(message)
        self.message = message
        self.code = code
        self.previous = previous

    def getMessage(self):
        return self.message

    def getCode(self):
        return self.code

    def getPrevious(self):
        return self.previous

    # Classe PHP que estende Exception chega aqui pelo construtor transpilado.
    def _construct(self, message="", code=0, previous=None, *args):
        Throwable.__init__(self, message, code, previous)


class Error(Throwable):
    _fqcn = "Error"


class PHPException(Throwable):
    _fqcn = "Exception"


class InvalidArgumentException(PHPException):
    _fqcn = "InvalidArgumentException"


class RuntimeException(PHPException):
    _fqcn = "RuntimeException"


class LogicException(PHPException):
    _fqcn = "LogicException"


class JsonException(PHPException):
    _fqcn = "JsonException"


class TypeError_(Error):
    _fqcn = "TypeError"


class UnhandledMatchError(Error):
    _fqcn = "UnhandledMatchError"


class Pendencia(Error):
    """Trecho que o tradutor não fechou: a rota que passa por aqui responde 501."""

    def __init__(self, oque):
        super().__init__(f"pendência do contrato: {oque}")
        self.oque = oque


def pendencia(oque, *args, **kwargs):
    raise Pendencia(oque)


def lancar(e):
    if isinstance(e, BaseException):
        raise e
    raise Error(f"Can only throw objects, {type(e).__name__} given")


def capturaveis(*nomes) -> tuple:
    saida = []
    for n in nomes:
        n = n.lstrip("\\")
        if n in ("Throwable", "Exception"):
            saida.append(Throwable if n == "Throwable" else PHPException)
            if n == "Throwable":
                saida.append(Exception)
        elif existe_classe(n):
            saida.append(classe(n))
    return tuple(saida) or (Throwable,)


# --------------------------------------------------------------------------- valores
class _Padrao:
    def __repr__(self):
        return "PADRAO"


PADRAO = _Padrao()


def truthy(v) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, str):
        return v not in ("", "0")
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, (list, dict, tuple)):
        return len(v) > 0
    return True


def to_str(v) -> str:
    if v is None or v is False:
        return ""
    if v is True:
        return "1"
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    if isinstance(v, (list, dict)):
        return "Array"
    if hasattr(v, "_php_toString"):
        return v._php_toString()
    return str(v)


def to_int(v) -> int:
    if v is None or v is False:
        return 0
    if v is True:
        return 1
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if math.isfinite(v) else 0
    if isinstance(v, str):
        m = re.match(r"\s*([+-]?\d+(\.\d+)?([eE][+-]?\d+)?)", v)
        if not m:
            return 0
        return int(float(m.group(1))) if (m.group(2) or m.group(3)) else int(m.group(1))
    if isinstance(v, (list, dict)):
        return 1 if v else 0
    return 1


def to_float(v) -> float:
    if isinstance(v, str):
        m = re.match(r"\s*([+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?)", v)
        return float(m.group(1)) if m else 0.0
    return float(to_int(v)) if not isinstance(v, float) else v


def to_array(v):
    if v is None:
        return []
    if isinstance(v, (list, dict)):
        return v
    if hasattr(v, "toArray"):
        return v.toArray()
    return [v]


def is_numeric(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    return isinstance(v, str) and re.fullmatch(r"\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*", v) is not None


def concat(*partes) -> str:
    return "".join(to_str(p) for p in partes)


def eq(a, b) -> bool:
    """`==` do PHP 8: número com string numérica compara como número."""
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return truthy(a) == truthy(b)
    if a is None or b is None:
        outro = b if a is None else a
        return not truthy(outro) if not isinstance(outro, str) else outro == ""
    if isinstance(a, (int, float)) and isinstance(b, str):
        return is_numeric(b) and a == to_float(b)
    if isinstance(b, (int, float)) and isinstance(a, str):
        return is_numeric(a) and b == to_float(a)
    if isinstance(a, str) and isinstance(b, str) and is_numeric(a) and is_numeric(b):
        return to_float(a) == to_float(b)
    return a == b


def ident(a, b) -> bool:
    """`===`: mesmo tipo e mesmo valor; objeto, a mesma instância."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float, str, type(None))) or isinstance(b, (int, float, str, type(None))):
        return type(a) is type(b) and a == b
    if isinstance(a, (list, dict)):
        return type(a) is type(b) and a == b
    return a is b


def spaceship(a, b) -> int:
    return (a > b) - (a < b)


def add(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        r = dict(a)
        for k, v in b.items():
            r.setdefault(k, v)
        return r
    if isinstance(a, list) and isinstance(b, list):
        return a + b[len(a):]
    return _num(a) + _num(b)


def _num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and is_numeric(v):
        f = to_float(v)
        return int(f) if f.is_integer() and "." not in v and "e" not in v.lower() else f
    return to_int(v)


def sub(a, b):
    return _num(a) - _num(b)


def mul(a, b):
    return _num(a) * _num(b)


def div(a, b):
    a, b = _num(a), _num(b)
    if b == 0:
        raise Error("Division by zero")
    r = a / b
    return int(r) if isinstance(a, int) and isinstance(b, int) and a % b == 0 else r


def mod(a, b):
    a, b = to_int(a), to_int(b)
    if b == 0:
        raise Error("Modulo by zero")
    return int(math.fmod(a, b))


def lt(a, b):
    return _cmp(a, b) < 0


def gt(a, b):
    return _cmp(a, b) > 0


def le(a, b):
    return _cmp(a, b) <= 0


def ge(a, b):
    return _cmp(a, b) >= 0


def _cmp(a, b) -> int:
    if a is None:
        a = "" if isinstance(b, str) else 0
    if b is None:
        b = "" if isinstance(a, str) else 0
    if isinstance(a, str) and isinstance(b, str) and not (is_numeric(a) and is_numeric(b)):
        return spaceship(a, b)
    if isinstance(a, (int, float, str, bool)) and isinstance(b, (int, float, str, bool)):
        return spaceship(_num(a) if not isinstance(a, bool) else int(a), _num(b) if not isinstance(b, bool) else int(b))
    return spaceship(a, b)


def coalesce(esquerda, direita):
    """`a ?? b`: lado esquerdo indefinido ou null cai para o direito."""
    try:
        v = esquerda() if callable(esquerda) and getattr(esquerda, "__name__", "") == "<lambda>" else esquerda
    except (KeyError, IndexError, AttributeError, NameError, UnboundLocalError, TypeError):
        v = None
    if v is None:
        return direita() if callable(direita) and getattr(direita, "__name__", "") == "<lambda>" else direita
    return v


def elvis(a, b):
    return a if truthy(a) else (b() if callable(b) and getattr(b, "__name__", "") == "<lambda>" else b)


def isset(*getters) -> bool:
    for g in getters:
        try:
            v = g() if callable(g) and getattr(g, "__name__", "") == "<lambda>" else g
        except (KeyError, IndexError, AttributeError, NameError, UnboundLocalError, TypeError):
            return False
        if v is None:
            return False
    return True


def empty(g) -> bool:
    try:
        v = g() if callable(g) and getattr(g, "__name__", "") == "<lambda>" else g
    except (KeyError, IndexError, AttributeError, NameError, UnboundLocalError, TypeError):
        return True
    return not truthy(v)


def tentar(fn, rotulo=""):
    """Valor de constante/propriedade de classe que depende de algo sem tradução: vira null."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        import sys

        print(f"[laravel_compat] aviso: {rotulo}: {e}", file=sys.stderr)
        return None


def tipos(fn, lista):
    """Guarda o tipo dos parâmetros de uma closure (o Laravel lê por reflexão)."""
    fn.__tipos__ = lista
    return fn


def nullsafe(obj, fn):
    return None if obj is None else fn(obj)


# --------------------------------------------------------------------------- objetos
def prop(o, nome):
    """`$o->nome` com receptor qualquer: null dá null, array (stdClass) dá a chave."""
    if o is None:
        return None
    if hasattr(o, "_p"):
        return o._p(nome)
    if isinstance(o, dict):
        return o.get(nome)
    return getattr(o, "p_" + nome, None)


def prop_set(o, nome, valor):
    if hasattr(o, "_ps"):
        return o._ps(nome, valor)
    if isinstance(o, dict):
        o[nome] = valor
        return valor
    setattr(o, "p_" + nome, valor)
    return valor


def sprop_set(cls, nome, valor):
    setattr(cls, "p_" + nome, valor)
    return valor


def to_object(v):
    return v


def arr(pares):
    """Array PHP com chave e sem chave misturadas, ou com `...$spread`."""
    saida, proximo = {}, 0
    for item in pares:
        if item[0] == "...":
            for k, v in itens(item[1]):
                if isinstance(k, int):
                    saida[proximo] = v
                    proximo += 1
                else:
                    saida[k] = v
            continue
        k, v = item
        if k is PADRAO:
            k = proximo
        k = _chave(k)
        saida[k] = v
        if isinstance(k, int) and k >= proximo:
            proximo = k + 1
    if list(saida.keys()) == list(range(len(saida))):
        return list(saida.values())
    return saida


def match_(valor, bracos):
    for conds, resultado in bracos:
        if conds is None or any(ident(valor, c) for c in conds):
            return resultado()
    raise UnhandledMatchError(f"Unhandled match case {to_str(valor)!r}")


# --------------------------------------------------------------------------- arrays
def idx_ref(a, k):
    """`$a[k]` em posição de escrita: cria o array que falta, como o PHP."""
    v = idx(a, k)
    if v is None:
        v = {}
        idx_set(a, k, v)
    return v


def idx(a, k):
    """Leitura `$a[k]`: chave ausente é null (o PHP só avisa)."""
    if a is None:
        return None
    if isinstance(a, dict):
        k = _chave(k)
        if k in a:
            return a[k]
        # Array que passou por JSON (contrato, banco) tem chave inteira como texto.
        return a.get(str(k)) if isinstance(k, int) else None
    if isinstance(a, list):
        k = _chave(k)
        return a[k] if isinstance(k, int) and 0 <= k < len(a) else None
    if isinstance(a, str):
        k = to_int(k)
        return a[k] if -len(a) <= k < len(a) else ""
    if hasattr(a, "offsetGet"):
        return a.offsetGet(k)
    return None


def _chave(k):
    if isinstance(k, bool):
        return int(k)
    if isinstance(k, float):
        return int(k)
    if isinstance(k, str) and re.fullmatch(r"-?[1-9]\d*|0", k):
        return int(k)
    if k is None:
        return ""
    return k


def idx_set(a, k, v):
    if isinstance(a, dict):
        a[_chave(k)] = v
    elif isinstance(a, list):
        k = _chave(k)
        if isinstance(k, int) and k == len(a):
            a.append(v)
        elif isinstance(k, int) and 0 <= k < len(a):
            a[k] = v
        else:
            raise Error("lista PHP virou array com chave: traduza com dict")
    elif hasattr(a, "offsetSet"):
        a.offsetSet(k, v)
    else:
        raise Error("Cannot use a scalar value as an array")
    return v


def push(a, v):
    if isinstance(a, list):
        a.append(v)
    elif isinstance(a, dict):
        prox = max([k for k in a if isinstance(k, int)], default=-1) + 1
        a[prox] = v
    elif hasattr(a, "offsetSet"):
        a.offsetSet(None, v)
    return v


def unset(a, k) -> None:
    if isinstance(a, dict):
        a.pop(_chave(k), None)
    elif isinstance(a, list):
        k = _chave(k)
        if isinstance(k, int) and 0 <= k < len(a):
            # Lista PHP com buraco vira array com chave: a ordem das chaves fica.
            del a[k]
    elif hasattr(a, "offsetUnset"):
        a.offsetUnset(k)


def itens(a):
    """`foreach ($a as $k => $v)`."""
    if a is None:
        return []
    if isinstance(a, dict):
        return list(a.items())
    if isinstance(a, list):
        return list(enumerate(a))
    if hasattr(a, "all"):
        return itens(a.all())
    if hasattr(a, "__iter__"):
        return list(enumerate(a))
    return list(vars(a).items())


def valores(a):
    return [v for _, v in itens(a)]


def destruct(v, n):
    vals = valores(v) if not isinstance(v, dict) else [v.get(i) for i in range(n)]
    return (list(vals) + [None] * n)[:n]


def eh_lista(a) -> bool:
    return isinstance(a, list) or (isinstance(a, dict) and list(a.keys()) == list(range(len(a))))


def array_merge(*arrs):
    if all(isinstance(a, list) for a in arrs):
        return [x for a in arrs for x in a]
    saida = {}
    i = 0
    for a in arrs:
        for k, v in itens(a):
            if isinstance(k, int):
                saida[i] = v
                i += 1
            else:
                saida[k] = v
    return saida


def array_merge_recursive(*arrs):
    if all(isinstance(a, list) for a in arrs):
        return [x for a in arrs for x in a]
    saida = {}
    i = 0
    for a in arrs:
        for k, v in itens(a):
            if isinstance(k, int):
                saida[i] = v
                i += 1
            elif k in saida:
                velho = saida[k]
                if isinstance(velho, (list, dict)) and isinstance(v, (list, dict)):
                    saida[k] = array_merge_recursive(velho, v)
                else:
                    # Valor escalar repetido vira lista com os dois, como o PHP faz.
                    a1 = velho if isinstance(velho, (list, dict)) else [velho]
                    a2 = v if isinstance(v, (list, dict)) else [v]
                    saida[k] = array_merge_recursive(a1, a2)
            else:
                saida[k] = v
    return saida


def chamavel(f):
    """Callable do PHP: closure, 'nome_de_funcao', 'Classe::metodo' ou [objeto, 'metodo']."""
    if callable(f) and not isinstance(f, (str, list)):
        return f
    if isinstance(f, str):
        if "::" in f:
            cls, m = f.split("::", 1)
            return getattr(classe(cls), m)
        g = funcao(f)
        if g is None:
            raise Pendencia(f"callable '{f}'")
        return g
    if isinstance(f, (list, tuple)) and len(f) == 2:
        alvo = classe(f[0]) if isinstance(f[0], str) else f[0]
        return getattr(alvo, f[1])
    raise Error("Argument must be a valid callback")


def array_map(fn, *arrs):
    fn = chamavel(fn) if fn is not None else (lambda *x: list(x) if len(x) > 1 else x[0])
    if len(arrs) == 1:
        a = arrs[0]
        if isinstance(a, dict):
            return {k: fn(v) for k, v in a.items()}
        return [fn(v) for v in valores(a)]
    return [fn(*vs) for vs in zip(*[valores(a) for a in arrs])]


def array_filter(a, fn=None, modo=0):
    fn = chamavel(fn) if fn is not None else None
    pares = itens(a)
    if fn is None:
        manter = [(k, v) for k, v in pares if truthy(v)]
    else:
        manter = [(k, v) for k, v in pares if truthy(fn(v) if modo == 0 else fn(k) if modo == 2 else fn(v, k))]
    return dict(manter)


def array_keys(a):
    return [k for k, _ in itens(a)]


def array_values(a):
    return valores(a)


def array_key_exists(k, a):
    if isinstance(a, dict):
        k = _chave(k)
        return k in a or (isinstance(k, int) and str(k) in a)
    if isinstance(a, list):
        k = _chave(k)
        return isinstance(k, int) and 0 <= k < len(a)
    return False


def in_array(v, a, estrito=False):
    return any((ident(v, x) if estrito else eq(v, x)) for x in valores(a))


def array_unique(a):
    vistos, saida = [], {}
    for k, v in itens(a):
        if not any(eq(v, x) for x in vistos):
            vistos.append(v)
            saida[k] = v
    return saida


def array_flip(a):
    return {v: k for k, v in itens(a)}


def array_slice(a, ini, tam=None):
    vals = valores(a)
    return vals[ini: None if tam is None else ini + tam]


def array_combine(ks, vs):
    return dict(zip(valores(ks), valores(vs)))


def array_search(v, a, estrito=False):
    for k, x in itens(a):
        if ident(v, x) if estrito else eq(v, x):
            return k
    return False


def array_shift(a):
    if isinstance(a, list) and a:
        return a.pop(0)
    if isinstance(a, dict) and a:
        k = next(iter(a))
        return a.pop(k)
    return None


def array_pop(a):
    if isinstance(a, list) and a:
        return a.pop()
    if isinstance(a, dict) and a:
        return a.pop(list(a)[-1])
    return None


def array_fill_keys(ks, v):
    return {k: v for k in valores(ks)}


def array_diff(a, *outros):
    tirar = {to_str(x) for o in outros for x in valores(o)}
    return {k: v for k, v in itens(a) if to_str(v) not in tirar}


def array_intersect(a, *outros):
    manter = [set(to_str(x) for x in valores(o)) for o in outros]
    return {k: v for k, v in itens(a) if all(to_str(v) in m for m in manter)}


def array_key_first(a):
    ks = array_keys(a)
    return ks[0] if ks else None


def array_key_last(a):
    ks = array_keys(a)
    return ks[-1] if ks else None


def count(a, modo=0):
    if a is None:
        raise TypeError_("count(): Argument #1 ($value) must be of type Countable|array, null given")
    if isinstance(a, (list, dict)):
        return len(a)
    if hasattr(a, "count"):
        return a.count()
    raise TypeError_("count(): Argument #1 ($value) must be of type Countable|array")


sizeof = count


def is_array(v):
    return isinstance(v, (list, dict))


def is_string(v):
    return isinstance(v, str)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


is_integer = is_int


def is_bool(v):
    return isinstance(v, bool)


def is_float(v):
    return isinstance(v, float)


def is_null(v):
    return v is None


def is_object(v):
    return v is not None and not isinstance(v, (str, int, float, bool, list, dict))


def is_callable(v):
    return callable(v)


def intval(v, base=10):
    if isinstance(v, str) and base != 10:
        try:
            return int(v.strip(), base)
        except ValueError:
            return 0
    return to_int(v)


def floatval(v):
    return to_float(v)


def strval(v):
    return to_str(v)


def boolval(v):
    return truthy(v)


def gettype(v):
    return {bool: "boolean", int: "integer", float: "double", str: "string", list: "array", dict: "array",
            type(None): "NULL"}.get(type(v), "object")


def get_class(o):
    return fqcn(o)


def method_exists(o, m):
    return hasattr(o if not isinstance(o, str) else classe(o), m)


def property_exists(o, p):
    return hasattr(o if not isinstance(o, str) else classe(o), p)


def class_exists(n, autoload=True):
    return existe_classe(n)


def func_get_args():
    raise Pendencia("func_get_args")


# --------------------------------------------------------------------------- strings
def strlen(s):
    return len(to_str(s).encode("utf-8"))


def mb_strlen(s, enc=None):
    return len(to_str(s))


def strtolower(s):
    return to_str(s).lower()


def strtoupper(s):
    return to_str(s).upper()


mb_strtolower = strtolower
mb_strtoupper = strtoupper


def ucfirst(s):
    s = to_str(s)
    return s[:1].upper() + s[1:]


def lcfirst(s):
    s = to_str(s)
    return s[:1].lower() + s[1:]


def ucwords(s, sep=" \t\r\n\f\v"):
    s = to_str(s)
    return "".join(c.upper() if i == 0 or s[i - 1] in sep else c for i, c in enumerate(s))


def trim(s, chars=" \n\r\t\v\x00"):
    return to_str(s).strip(chars)


def ltrim(s, chars=" \n\r\t\v\x00"):
    return to_str(s).lstrip(chars)


def rtrim(s, chars=" \n\r\t\v\x00"):
    return to_str(s).rstrip(chars)


def explode(sep, s, limite=None):
    if sep == "":
        raise Error("explode(): Argument #1 ($separator) cannot be empty")
    partes = to_str(s).split(sep)
    if limite is not None and limite > 0 and len(partes) > limite:
        partes = partes[: limite - 1] + [sep.join(partes[limite - 1:])]
    elif limite is not None and limite < 0:
        partes = partes[:limite]
    return partes


def implode(sep, a=None):
    if a is None:
        sep, a = "", sep
    if isinstance(sep, (list, dict)):
        sep, a = a, sep
    return to_str(sep).join(to_str(v) for v in valores(a))


join = implode


def str_replace(busca, troca, s, *_):
    s = to_str(s)
    buscas = valores(busca) if isinstance(busca, (list, dict)) else [busca]
    trocas = valores(troca) if isinstance(troca, (list, dict)) else None
    for i, b in enumerate(buscas):
        t = (trocas[i] if i < len(trocas) else "") if trocas is not None else troca
        s = s.replace(to_str(b), to_str(t))
    return s


def str_contains(s, agulha):
    return to_str(agulha) in to_str(s)


def str_starts_with(s, agulha):
    return to_str(s).startswith(to_str(agulha))


def str_ends_with(s, agulha):
    return to_str(s).endswith(to_str(agulha))


def strpos(s, agulha, ini=0):
    i = to_str(s).find(to_str(agulha), ini)
    return False if i < 0 else i


def substr(s, ini, tam=None):
    s = to_str(s)
    if tam is None:
        return s[ini:]
    if tam < 0:
        return s[ini:tam]
    return s[ini: (ini + tam) if ini >= 0 else (len(s) + ini + tam)]


mb_substr = substr


def str_repeat(s, n):
    return to_str(s) * n


def sprintf(fmt, *args):
    fmt = to_str(fmt)
    it = iter(args)

    def troca(m):
        if m.group(0) == "%%":
            return "%"
        spec = m.group(0)
        v = next(it)
        conv = spec[-1]
        py = spec.replace("'", "")
        if conv in "di":
            return (py[:-1] + "d") % to_int(v)
        if conv in "fF":
            return (py[:-1] + "f") % to_float(v)
        if conv == "s":
            return py % to_str(v)
        return py % v

    return re.sub(r"%%|%[-+ 0'#]*\d*(\.\d+)?[bcdeEfFgGosuxX]", troca, fmt)


def str_pad(s, n, pad=" ", tipo=1):
    s = to_str(s)
    falta = n - len(s)
    if falta <= 0:
        return s
    if tipo == 0:
        return (pad * n)[:falta] + s
    if tipo == 2:
        esq = falta // 2
        return (pad * n)[:esq] + s + (pad * n)[: falta - esq]
    return s + (pad * n)[:falta]


def nl2br(s):
    return to_str(s).replace("\n", "<br />\n")


def htmlspecialchars(s, *_):
    return to_str(s).replace("&", "&amp;").replace('"', "&quot;").replace("'", "&#039;").replace("<", "&lt;").replace(">", "&gt;")


e = htmlspecialchars


def number_format(n, dec=0, ponto=".", milhar=","):
    t = f"{to_float(n):,.{dec}f}"
    return t.replace(",", "\0").replace(".", ponto).replace("\0", milhar)


def preg_match(padrao, s, saida=None, *_):
    rx, flags = _regex(padrao)
    import regex as _re2

    return 1 if _re2.search(rx, to_str(s), flags) else 0


def preg_replace(padrao, troca, s, *_):
    import regex as _re2

    rx, flags = _regex(padrao)
    troca_py = re.sub(r"\$(\d+)|\\(\d+)", lambda m: "\\g<" + (m.group(1) or m.group(2)) + ">", to_str(troca))
    return _re2.sub(rx, troca_py, to_str(s), flags=flags)


def preg_quote(s, delim=None):
    especiais = set(".\\+*?[^]$(){}=!<>|:-#/" + (delim or ""))
    return "".join("\\" + c if c in especiais else c for c in to_str(s))


def preg_split(padrao, s, limite=-1, flags=0):
    import regex as _re2

    rx, f = _regex(padrao)
    partes = _re2.split(rx, to_str(s), flags=f)
    if flags & 1:
        partes = [p for p in partes if p != ""]
    return partes


def _regex(padrao: str):
    """'/x/iu' do PCRE -> (padrão, flags) do módulo `regex` (que entende \\pL)."""
    import regex as _re2

    padrao = to_str(padrao)
    delim = padrao[0]
    fecha = {"(": ")", "{": "}", "[": "]", "<": ">"}.get(delim, delim)
    fim = padrao.rfind(fecha)
    corpo, mods = padrao[1:fim], padrao[fim + 1:]
    flags = _re2.V0
    for m in mods:
        flags |= {"i": _re2.I, "m": _re2.M, "s": _re2.S, "x": _re2.X, "u": _re2.U}.get(m, 0)
    # `$` do PCRE casa antes de \n final, como no Python; `\z` vira `\Z`.
    corpo = corpo.replace("\\z", "\\Z")
    return corpo, flags


def md5(s):
    return hashlib.md5(to_str(s).encode()).hexdigest()


def sha1(s):
    return hashlib.sha1(to_str(s).encode()).hexdigest()


def hash(algo, dados, binario=False):  # noqa: A001 - nome da função do PHP
    h = hashlib.new(algo, _bytes(dados))
    return h.digest().decode("latin-1") if binario else h.hexdigest()


def hash_hmac(algo, dados, chave, binario=False):
    h = hmac.new(_bytes(chave), _bytes(dados), algo)
    return h.digest().decode("latin-1") if binario else h.hexdigest()


def hash_equals(a, b):
    return hmac.compare_digest(_bytes(a), _bytes(b))


def _bytes(s) -> bytes:
    # Strings PHP são bytes; aqui, texto vira UTF-8 e binário guardado em latin-1 volta igual.
    s = to_str(s)
    try:
        return s.encode("latin-1")
    except UnicodeEncodeError:
        return s.encode("utf-8")


def base64_encode(s):
    return _b64.b64encode(_bytes(s)).decode("ascii")


def base64_decode(s, estrito=False):
    s = to_str(s)
    if estrito and re.search(r"[^A-Za-z0-9+/=\s]", s):
        return False
    limpo = re.sub(r"[^A-Za-z0-9+/]", "", s)
    limpo += "=" * (-len(limpo) % 4)
    try:
        bruto = _b64.b64decode(limpo)
    except ValueError:
        return False
    try:
        return bruto.decode("utf-8")
    except UnicodeDecodeError:
        return bruto.decode("latin-1")


def random_bytes(n):
    import os

    return os.urandom(n).decode("latin-1")


def bin2hex(s):
    return _bytes(s).hex()


# --------------------------------------------------------------------------- json
JSON_THROW_ON_ERROR = 4194304
JSON_UNESCAPED_SLASHES = 64
JSON_UNESCAPED_UNICODE = 256
JSON_PRETTY_PRINT = 128
JSON_PRESERVE_ZERO_FRACTION = 1024


def json_encode(v, flags=0, profundidade=512):
    return _json_texto(para_json(v), flags)


def _json_texto(v, flags=0) -> str:
    """Bytes iguais aos do json_encode do PHP: barra escapada e unicode em \\uXXXX."""
    texto = _json.dumps(v, ensure_ascii=not (flags & JSON_UNESCAPED_UNICODE), separators=(",", ":"),
                        indent=4 if flags & JSON_PRETTY_PRINT else None)
    if not flags & JSON_UNESCAPED_SLASHES:
        texto = texto.replace("/", "\\/")
    return texto


def para_json(v):
    """Valor PHP -> estrutura JSON (JsonSerializable, Arrayable, Carbon, lista/objeto)."""
    if hasattr(v, "jsonSerialize"):
        return para_json(v.jsonSerialize())
    if hasattr(v, "toArray") and not isinstance(v, (list, dict)):
        return para_json(v.toArray())
    if isinstance(v, dict):
        if eh_lista(v):
            return [para_json(x) for x in v.values()]
        return {to_str(k): para_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [para_json(x) for x in v]
    if isinstance(v, float) and v.is_integer():
        return v
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return {k: para_json(x) for k, x in vars(v).items() if not k.startswith("_")}


def json_decode(texto, assoc=False, prof=512, flags=0):
    try:
        v = _json.loads(to_str(texto))
    except ValueError:
        if flags & JSON_THROW_ON_ERROR:
            raise JsonException("Syntax error", 4)
        return None
    return v


def json_last_error():
    return 0


PHP_EOL = "\n"
PHP_INT_MAX = 2**63 - 1
SORT_REGULAR = 0
ARRAY_FILTER_USE_KEY = 2
ARRAY_FILTER_USE_BOTH = 1
ENT_QUOTES = 3
FILTER_VALIDATE_INT = 257
FILTER_VALIDATE_EMAIL = 274
FILTER_VALIDATE_BOOLEAN = 258
FILTER_VALIDATE_URL = 273


def constante(nome):
    v = globals().get(nome)
    if v is None:
        raise Pendencia(f"constante {nome}")
    return v


def filter_var(v, filtro=516, opcoes=None):
    if filtro == FILTER_VALIDATE_INT:
        if isinstance(v, bool):
            return 1 if v else False
        if isinstance(v, int):
            return v
        s = to_str(v).strip()
        return int(s) if re.fullmatch(r"[+-]?(0|[1-9]\d*)", s) else False
    if filtro == FILTER_VALIDATE_BOOLEAN:
        s = to_str(v).strip().lower()
        return True if s in ("1", "true", "on", "yes") else False
    if filtro == FILTER_VALIDATE_EMAIL:
        s = to_str(v)
        return s if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s) else False
    if filtro == FILTER_VALIDATE_URL:
        s = to_str(v)
        return s if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/?#]+[^\s]*", s) else False
    return v


def min_(*a):
    vals = valores(a[0]) if len(a) == 1 else list(a)
    return min(vals, key=lambda x: _num(x) if not isinstance(x, str) or is_numeric(x) else 0)


def max_(*a):
    vals = valores(a[0]) if len(a) == 1 else list(a)
    return max(vals, key=lambda x: _num(x) if not isinstance(x, str) or is_numeric(x) else 0)


def abs_(v):
    return abs(_num(v))


def round_(v, p=0):
    # PHP arredonda metade para longe do zero; o Python, para o par.
    q = 10 ** p
    x = _num(v) * q
    r = math.floor(abs(x) + 0.5) * (1 if x >= 0 else -1)
    return float(r / q)


def floor_(v):
    return float(math.floor(_num(v)))


def ceil_(v):
    return float(math.ceil(_num(v)))


def array_sum(a):
    return sum(_num(v) for v in valores(a))


def range_(a, b, passo=1):
    if a <= b:
        return list(range(a, b + 1, passo))
    return list(range(a, b - 1, -passo))


def compact(*_):
    raise Pendencia("compact()")


def call_user_func(f, *args):
    return chamavel(f)(*args)


def call_user_func_array(f, args):
    return chamavel(f)(*valores(args))


def usort(a, fn):
    import functools

    a.sort(key=functools.cmp_to_key(chamavel(fn)))
    return True


def iterator_to_array(it, chaves=True):
    return list(it)


def uniqid(prefixo=""):
    import time

    t = time.time()
    return f"{prefixo}{int(t):8x}{int((t % 1) * 1e6):05x}"


def time_():
    import time

    return int(time.time())


# Nomes que colidem com builtins do Python ficam com `_` e entram no catálogo pelo nome PHP.
APELIDOS = {"min": min_, "max": max_, "abs": abs_, "round": round_, "floor": floor_, "ceil": ceil_,
            "range": range_, "time": time_}


def funcao(nome):
    """Função global do PHP pelo nome; None se o runtime não tem."""
    if nome in APELIDOS:
        return APELIDOS[nome]
    f = globals().get(nome)
    if callable(f) and not isinstance(f, type) and not nome.startswith("_"):
        return f
    return None
