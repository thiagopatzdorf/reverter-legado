"""Eloquent sobre SQLAlchemy Core: Model, Builder, relações e coleção de models.

A regra que guia este arquivo é **o mesmo SQL no mesmo formato**. Sem ORDER BY, o
SQLite devolve as linhas na ordem do plano de execução; se o Laravel junta
`tags` com `article_tag` e aqui a junção fosse ao contrário, a lista de tags
sairia em outra ordem e o diferencial acusaria. Por isso as consultas repetem a
forma das do Laravel 9 (`select tabela.* ... inner join pivô ... where pivô.fk = ?`,
`exists (select * ...)`, `"tabela"."fk" is not null` no hasMany).

Os valores são lidos crus (sem conversão de tipo do SQLAlchemy) e convertidos
como o Eloquent converte: datas viram Carbon, `$casts` vale, o resto fica.
"""
from __future__ import annotations

import inspect
import os
import threading

import sqlalchemy as sa

from . import php
from .suporte import FORMATO_BANCO, Base, Carbon, Collection, Str, data_get, str_snake

# --------------------------------------------------------------------------- conexão
_motor = None
_trava = threading.Lock()
TABELAS: dict[str, list[str]] = {}


def registrar_tabelas(metadata: sa.MetaData) -> None:
    for t in metadata.tables.values():
        TABELAS[t.name] = [c.name for c in t.columns]


def motor():
    global _motor
    with _trava:
        if _motor is None:
            url = os.environ.get("DATABASE_URL", "sqlite:///banco.sqlite")
            _motor = sa.create_engine(url, isolation_level="AUTOCOMMIT")
            if url.startswith("sqlite"):
                @sa.event.listens_for(_motor, "connect")
                def _fk(conn, _):
                    # O Laravel liga foreign_keys no SQLite (DB_FOREIGN_KEYS=true): cascade depende disso.
                    conn.execute("PRAGMA foreign_keys = ON")
        return _motor


def executar(stmt):
    with motor().connect() as conn:
        res = conn.execute(stmt)
        if res.returns_rows:
            return [dict(r._mapping) for r in res]
        return res


def _tem(cls, nome) -> bool:
    """hasattr sem passar pelo __getattr__ do metaclass (que encaminharia ao Builder)."""
    return any(nome in c.__dict__ for c in cls.__mro__)


def q(nome: str):
    """Identificador citado como no Laravel: "tabela"."coluna"."""
    if nome == "*":
        return sa.literal_column("*")
    partes = nome.split(".")
    return sa.literal_column(".".join('"' + p + '"' if p != "*" else "*" for p in partes))


def _tabela(nome, colunas=()):
    return sa.table(nome, *[sa.column(c) for c in colunas])


def _inserir(nome, linhas):
    """INSERT com as colunas na ordem do dicionário (a mesma ordem em que o Eloquent monta)."""
    colunas = list(dict.fromkeys(k for linha in linhas for k in linha))
    t = _tabela(nome, colunas)
    return t.insert().values([{t.c[k]: v for k, v in linha.items()} for linha in linhas] if len(linhas) > 1
                             else {t.c[k]: v for k, v in linhas[0].items()})


def _atualizar(nome, valores, cond):
    t = _tabela(nome, list(valores))
    stmt = t.update()
    if cond is not None:
        stmt = stmt.where(cond)
    return stmt.values({t.c[k]: v for k, v in valores.items()})


# --------------------------------------------------------------------------- exceções
class ModelNotFoundException(php.RuntimeException):
    _fqcn = "Illuminate\\Database\\Eloquent\\ModelNotFoundException"

    def setModel(self, modelo, ids=None):
        self.model = modelo
        self.ids = php.valores(php.to_array(ids)) if ids is not None else []
        self.message = f"No query results for model [{modelo}]"
        self.message += (" " + ", ".join(php.to_str(i) for i in self.ids)) if self.ids else "."
        Exception.__init__(self, self.message)
        return self

    def getModel(self):
        return self.model

    def getIds(self):
        return self.ids


class MassAssignmentException(php.RuntimeException):
    _fqcn = "Illuminate\\Database\\Eloquent\\MassAssignmentException"


class QueryException(php.PHPException):
    _fqcn = "Illuminate\\Database\\QueryException"


# --------------------------------------------------------------------------- Builder
OPERADORES = {"=", "<", ">", "<=", ">=", "<>", "!=", "like", "not like", "ilike"}


class Builder(Base):
    _fqcn = "Illuminate\\Database\\Eloquent\\Builder"

    def _construct(self, modelo=None):
        self.modelo = modelo  # classe
        self.tabela = modelo.tabela_de() if modelo else None
        self.colunas: list = []
        self.joins: list = []
        self.wheres: list = []
        self.ordens: list = []
        self.lim = None
        self.desloc = None
        self.carregar: list = []

    def __clone__(self):
        b = type(self)(self.modelo)
        b.colunas, b.joins, b.wheres = list(self.colunas), list(self.joins), list(self.wheres)
        b.ordens, b.lim, b.desloc, b.carregar = list(self.ordens), self.lim, self.desloc, list(self.carregar)
        return b

    def clone(self):
        return self.__clone__()

    def getModel(self):
        return self.modelo()

    # -------- where
    def where(self, coluna, op=None, valor=php.PADRAO, booleano="and"):
        if callable(coluna) and not isinstance(coluna, str):
            sub = Builder(self.modelo)
            coluna(sub)
            if sub.wheres:
                self.wheres.append((booleano, ("aninhado", sub.wheres)))
            return self
        if isinstance(coluna, dict):
            for k, v in coluna.items():
                self.where(k, "=", v, booleano)
            return self
        if valor is php.PADRAO:
            op, valor = "=", op
        if op not in OPERADORES:
            op, valor = "=", op
        if valor is None:
            return self.whereNull(coluna, booleano, op in ("!=", "<>"))
        self.wheres.append((booleano, ("basico", coluna, op, valor)))
        return self

    def orWhere(self, coluna, op=None, valor=php.PADRAO):
        return self.where(coluna, op, valor, "or")

    def whereNull(self, coluna, booleano="and", nao=False):
        self.wheres.append((booleano, ("nulo", coluna, nao)))
        return self

    def whereNotNull(self, coluna, booleano="and"):
        return self.whereNull(coluna, booleano, True)

    def whereIn(self, coluna, valores, booleano="and", nao=False):
        if isinstance(valores, Builder):
            raise php.Pendencia("whereIn com subconsulta")
        if hasattr(valores, "all"):
            valores = valores.all()
        self.wheres.append((booleano, ("em", coluna, php.valores(valores), nao)))
        return self

    def whereNotIn(self, coluna, valores, booleano="and"):
        return self.whereIn(coluna, valores, booleano, True)

    def whereColumn(self, a, op=None, b=None, booleano="and"):
        if b is None:
            op, b = "=", op
        self.wheres.append((booleano, ("coluna", a, op, b)))
        return self

    def whereKey(self, id_):
        if isinstance(id_, Model):
            id_ = id_.getKey()
        if isinstance(id_, (list, dict, Collection)):
            return self.whereIn(self.modelo().getQualifiedKeyName(), id_)
        return self.where(self.modelo().getQualifiedKeyName(), "=", id_)

    def whereKeyNot(self, id_):
        if isinstance(id_, Model):
            id_ = id_.getKey()
        return self.where(self.modelo().getQualifiedKeyName(), "!=", id_)

    def whereHas(self, relacao, callback=None, op=">=", n=1, booleano="and", nao=False):
        rel = getattr(self.modelo.sem_restricoes(), relacao)()
        sub = rel.consulta_de_existencia(self)
        if callback is not None:
            callback(sub)
        self.wheres.append((booleano, ("existe", sub, nao)))
        return self

    def has(self, relacao, op=">=", n=1, booleano="and", callback=None):
        return self.whereHas(relacao, callback, op, n, booleano)

    def doesntHave(self, relacao, booleano="and", callback=None):
        return self.whereHas(relacao, callback, nao=True, booleano=booleano)

    def whereDoesntHave(self, relacao, callback=None):
        return self.whereHas(relacao, callback, nao=True)

    def orWhereHas(self, relacao, callback=None):
        return self.whereHas(relacao, callback, booleano="or")

    # -------- ordem, limite, colunas
    def orderBy(self, coluna, direcao="asc"):
        self.ordens.append((coluna, php.to_str(direcao).lower()))
        return self

    def orderByDesc(self, coluna):
        return self.orderBy(coluna, "desc")

    def latest(self, coluna=None):
        return self.orderBy(coluna or self.modelo.k_CREATED_AT, "desc")

    def oldest(self, coluna=None):
        return self.orderBy(coluna or self.modelo.k_CREATED_AT, "asc")

    def limit(self, n):
        if php.to_int(n) >= 0:
            self.lim = php.to_int(n)
        return self

    take = limit

    def offset(self, n):
        self.desloc = max(0, php.to_int(n))
        return self

    skip = offset

    def select(self, *colunas):
        if len(colunas) == 1 and isinstance(colunas[0], (list, dict)):
            colunas = tuple(php.valores(colunas[0]))
        self.colunas = list(colunas)
        return self

    def addSelect(self, colunas):
        self.colunas += php.valores(colunas) if isinstance(colunas, (list, dict)) else [colunas]
        return self

    def with_(self, *relacoes):
        if len(relacoes) == 1 and isinstance(relacoes[0], (list, dict)):
            relacoes = php.valores(relacoes[0])
        self.carregar += list(relacoes)
        return self

    def when(self, valor, fn, senao=None):
        if php.truthy(valor):
            return fn(self, valor) or self
        if senao is not None:
            return senao(self, valor) or self
        return self

    def scopes(self, nomes):
        for n in php.valores(nomes) if isinstance(nomes, (list, dict)) else [nomes]:
            getattr(self, n)()
        return self

    # -------- compilação
    def _cond(self, w):
        tipo = w[0]
        if tipo == "basico":
            _, col, op, v = w
            c = q(col)
            if op in ("=",):
                return c == sa.bindparam(None, v)
            if op in ("!=", "<>"):
                return c != sa.bindparam(None, v)
            if op in ("like", "not like", "ilike"):
                cond = c.like(sa.bindparam(None, v))
                return sa.not_(cond) if op == "not like" else cond
            return c.op(op)(sa.bindparam(None, v))
        if tipo == "nulo":
            return q(w[1]).isnot(None) if w[2] else q(w[1]).is_(None)
        if tipo == "em":
            if not w[2]:
                return sa.text("0 = 1") if not w[3] else sa.text("1 = 1")
            cond = q(w[1]).in_([sa.bindparam(None, v) for v in w[2]])
            return sa.not_(cond) if w[3] else cond
        if tipo == "coluna":
            return q(w[1]).op(w[2])(q(w[3]))
        if tipo == "aninhado":
            return self._juntar(w[1])
        if tipo == "existe":
            cond = sa.exists(w[1].compilar(asterisco=True))
            return sa.not_(cond) if w[2] else cond
        raise php.Pendencia(f"where {tipo}")

    def _juntar(self, wheres):
        cond = None
        for booleano, w in wheres:
            c = self._cond(w)
            cond = c if cond is None else (sa.and_(cond, c) if booleano == "and" else sa.or_(cond, c))
        return cond

    def compilar(self, asterisco=False, contar=False):
        if contar:
            cols = [sa.func.count().label("aggregate")]
        elif self.colunas:
            cols = [q(c) if isinstance(c, str) else c for c in self.colunas]
        else:
            cols = [q("*") if asterisco and not self.joins else q(f"{self.tabela}.*") if self.joins else q("*")]
        stmt = sa.select(*cols).select_from(self._origem())
        cond = self._juntar(self.wheres)
        if cond is not None:
            stmt = stmt.where(cond)
        if not contar:
            for col, direcao in self.ordens:
                stmt = stmt.order_by(q(col).desc() if direcao == "desc" else q(col).asc())
            if self.lim is not None:
                stmt = stmt.limit(self.lim)
            if self.desloc is not None:
                stmt = stmt.offset(self.desloc)
        return stmt

    def _origem(self):
        origem = _tabela(self.tabela)
        for tabela, a, b in self.joins:
            origem = origem.join(_tabela(tabela), q(a) == q(b))
        return origem

    # -------- execução
    def _linhas(self):
        return executar(self.compilar())

    def get(self, colunas=None):
        if colunas and colunas != ["*"]:
            self.select(colunas)
        models = [self.modelo.do_banco(r) for r in self._linhas()]
        for m in models:
            for rel in self.carregar:
                m.load(rel)
        return EloquentCollection(models)

    def all(self):
        return self.get()

    def first(self, colunas=None):
        b = self.clone().limit(1)
        return b.get(colunas).first()

    def firstOrFail(self, colunas=None):
        m = self.first(colunas)
        if m is None:
            raise ModelNotFoundException().setModel(self.modelo._fqcn)
        return m

    def find(self, id_, colunas=None):
        if isinstance(id_, (list, dict, Collection)):
            return self.clone().whereKey(id_).get(colunas)
        return self.clone().whereKey(id_).first(colunas)

    def findOrFail(self, id_, colunas=None):
        r = self.find(id_, colunas)
        if r is None or (isinstance(r, Collection) and r.count() != len(php.valores(php.to_array(id_)))):
            raise ModelNotFoundException().setModel(self.modelo._fqcn, id_)
        return r

    def exists(self):
        stmt = sa.select(sa.exists(self.compilar(asterisco=True)).label("exists"))
        return bool(executar(stmt)[0]["exists"])

    def doesntExist(self):
        return not self.exists()

    def count(self, coluna="*"):
        return int(executar(self.compilar(contar=True))[0]["aggregate"])

    def pluck(self, coluna, chave=None):
        b = self.clone()
        b.colunas = [coluna] if chave is None else [coluna, chave]
        linhas = b._linhas()
        nome = coluna.split(".")[-1]
        if chave is None:
            return Collection([self.modelo.do_banco(r)._p(nome) for r in linhas])
        return Collection({r[chave.split(".")[-1]]: self.modelo.do_banco(r)._p(nome) for r in linhas})

    def value(self, coluna):
        m = self.first([coluna])
        return m._p(coluna.split(".")[-1]) if m else None

    def update(self, valores):
        valores = dict(valores)
        if self.modelo.p_timestamps and self.modelo.k_UPDATED_AT and self.modelo.k_UPDATED_AT not in valores:
            valores[self.modelo.k_UPDATED_AT] = Carbon.now().toDateTimeString()
        res = executar(_atualizar(self.tabela, valores, self._juntar(self.wheres)))
        return res.rowcount

    def delete(self):
        stmt = sa.delete(_tabela(self.tabela))
        cond = self._juntar(self.wheres)
        if cond is not None:
            stmt = stmt.where(cond)
        return executar(stmt).rowcount

    def create(self, atributos=None):
        return self.modelo.create(atributos or {})

    def firstOrCreate(self, atributos=None, valores=None):
        atributos = atributos or {}
        m = self.clone().where(atributos).first()
        if m is not None:
            return m
        return self.modelo.create(php.array_merge(atributos, valores or {}))

    def firstOrNew(self, atributos=None, valores=None):
        m = self.clone().where(atributos or {}).first()
        return m if m is not None else self.modelo(php.array_merge(atributos or {}, valores or {}))

    def updateOrCreate(self, atributos, valores=None):
        m = self.firstOrNew(atributos)
        m.fill(valores or {}).save()
        return m

    def paginate(self, *_):
        raise php.Pendencia("paginate()")

    # -------- escopos e where dinâmico
    def __getattr__(self, nome):
        if nome.startswith(("_", "p_", "k_")) or self.modelo is None:
            raise AttributeError(nome)
        escopo = "scope" + nome[:1].upper() + nome[1:]
        if _tem(self.modelo, escopo):
            def chamar(*args):
                r = getattr(self.modelo.sem_restricoes(), escopo)(self, *args)
                return self if r is None else r
            return chamar
        if nome.startswith("where") and len(nome) > 5 and nome[5].isupper():
            coluna = str_snake(nome[5:])
            return lambda valor: self.where(coluna, "=", valor)
        raise php.Error(f"Call to undefined method {self._fqcn}::{nome}()")


# --------------------------------------------------------------------------- Model
class _MetaModel(type):
    def __getattr__(cls, nome):
        # Model::metodo() que não é estático vai para o Builder, como o __callStatic do Laravel.
        if nome.startswith(("_", "p_", "k_", "scope")):
            raise AttributeError(nome)
        return getattr(cls.query(), nome)


class Model(Base, metaclass=_MetaModel):
    _fqcn = "Illuminate\\Database\\Eloquent\\Model"
    p_table = None
    p_primaryKey = "id"
    p_keyType = "int"
    p_incrementing = True
    p_timestamps = True
    p_fillable: list = []
    p_guarded = ["*"]
    p_hidden: list = []
    p_visible: list = []
    p_casts: dict = {}
    p_dates: list = []
    p_appends: list = []
    k_CREATED_AT = "created_at"
    k_UPDATED_AT = "updated_at"

    def _construct(self, atributos=None):
        d = self.__dict__
        d["_attrs"] = {}
        d["_original"] = {}
        d["_relations"] = {}
        d["p_exists"] = False
        d["p_wasRecentlyCreated"] = False
        d["_visivel_extra"] = []
        d["_oculto_extra"] = []
        if atributos:
            self.fill(atributos)

    @classmethod
    def sem_restricoes(cls):
        return cls()

    @classmethod
    def tabela_de(cls):
        if cls.p_table:
            return cls.p_table
        return Str.plural(str_snake(cls._fqcn.rsplit("\\", 1)[-1]))

    @classmethod
    def do_banco(cls, linha: dict):
        m = cls()
        attrs = {k: v for k, v in linha.items() if not k.startswith("pivot_")}
        m.__dict__["_attrs"] = attrs
        m.__dict__["_original"] = dict(attrs)
        m.__dict__["p_exists"] = True
        pivo = {k[6:]: v for k, v in linha.items() if k.startswith("pivot_")}
        if pivo:
            m.__dict__["_pivo"] = pivo
        return m

    @classmethod
    def query(cls):
        return Builder(cls)

    @classmethod
    def all(cls, colunas=None):
        return cls.query().get(colunas)

    @classmethod
    def create(cls, atributos=None):
        m = cls()
        m.fill(atributos or {})
        m.save()
        return m

    @classmethod
    def destroy(cls, ids):
        n = 0
        for m in cls.query().whereKey(ids).get():
            m.delete()
            n += 1
        return n

    # -------- chaves e nomes
    def getKeyName(self):
        return self.p_primaryKey

    def getKey(self):
        return self.getAttribute(self.p_primaryKey)

    def getTable(self):
        return type(self).tabela_de()

    def getQualifiedKeyName(self):
        return f"{self.getTable()}.{self.p_primaryKey}"

    def qualifyColumn(self, coluna):
        return coluna if "." in coluna else f"{self.getTable()}.{coluna}"

    def getForeignKey(self):
        return str_snake(self._fqcn.rsplit("\\", 1)[-1]) + "_" + self.p_primaryKey

    def getCreatedAtColumn(self):
        return self.k_CREATED_AT

    def getUpdatedAtColumn(self):
        return self.k_UPDATED_AT

    def getRouteKeyName(self):
        return self.getKeyName()

    def newQuery(self):
        return type(self).query()

    # -------- atributos
    def _datas(self):
        datas = list(self.p_dates)
        if self.p_timestamps:
            datas += [self.k_CREATED_AT, self.k_UPDATED_AT]
        for k, v in self.p_casts.items():
            if php.to_str(v).split(":")[0] in ("date", "datetime", "immutable_date", "immutable_datetime", "timestamp", "custom_datetime"):
                datas.append(k)
        return datas

    def getAttribute(self, chave):
        if not chave:
            return None
        acessor = "get" + Str.studly(chave) + "Attribute"
        attrs = self.__dict__.get("_attrs", {})
        if chave in attrs or _tem(type(self), acessor):
            valor = attrs.get(chave)
            if _tem(type(self), acessor):
                return getattr(self, acessor)(valor)
            return self._converter(chave, valor)
        rels = self.__dict__.get("_relations", {})
        if chave in rels:
            return rels[chave]
        metodo = next((c.__dict__[chave] for c in type(self).__mro__ if chave in c.__dict__), None)
        if callable(metodo) and chave not in Model.__dict__ and not chave.startswith("_"):
            rel = getattr(self, chave)()
            if isinstance(rel, Relation):
                rels[chave] = rel.getResults()
                return rels[chave]
        return None

    def _converter(self, chave, valor):
        if valor is None:
            return None
        tipo = php.to_str(self.p_casts.get(chave, "")).split(":")[0].lower()
        if chave in self._datas():
            if isinstance(valor, Carbon):
                return valor
            if isinstance(valor, (int, float)):
                return Carbon.createFromTimestamp(valor)
            return Carbon(php.to_str(valor))
        if tipo in ("int", "integer"):
            return php.to_int(valor)
        if tipo in ("bool", "boolean"):
            return php.truthy(valor)
        if tipo in ("float", "double", "real"):
            return php.to_float(valor)
        if tipo == "string":
            return php.to_str(valor)
        if tipo in ("array", "json"):
            return php.json_decode(valor, True) if isinstance(valor, str) else valor
        if tipo == "collection":
            return Collection(php.json_decode(valor, True) if isinstance(valor, str) else valor)
        return valor

    def setAttribute(self, chave, valor):
        mutador = "set" + Str.studly(chave) + "Attribute"
        if _tem(type(self), mutador):
            getattr(self, mutador)(valor)
            return self
        if valor is not None and chave in self._datas():
            valor = self.fromDateTime(valor)
        tipo = php.to_str(self.p_casts.get(chave, "")).split(":")[0].lower()
        if valor is not None and tipo in ("array", "json", "collection", "object"):
            valor = php.json_encode(valor)
        self.__dict__["_attrs"][chave] = valor
        return self

    def fromDateTime(self, v):
        if isinstance(v, Carbon):
            return v.dt.strftime(FORMATO_BANCO)
        if isinstance(v, str):
            return Carbon(v).dt.strftime(FORMATO_BANCO)
        return v

    def freshTimestamp(self):
        return Carbon.now()

    def _p(self, nome):
        if nome in ("exists", "wasRecentlyCreated", "incrementing", "timestamps", "table", "primaryKey") or nome.startswith("_"):
            return getattr(self, "p_" + nome, None)
        return self.getAttribute(nome)

    def _ps(self, nome, valor):
        if _tem(type(self), "p_" + nome) or ("p_" + nome) in self.__dict__:
            self.__dict__["p_" + nome] = valor
        else:
            self.setAttribute(nome, valor)
        return valor

    def offsetGet(self, chave):
        return self.getAttribute(chave)

    def offsetExists(self, chave):
        return self.getAttribute(chave) is not None

    def offsetSet(self, chave, valor):
        self.setAttribute(chave, valor)

    def offsetUnset(self, chave):
        self.__dict__["_attrs"].pop(chave, None)
        self.__dict__["_relations"].pop(chave, None)

    def __getattr__(self, nome):
        # $model->metodoDoBuilder() vira consulta, como o __call do Laravel.
        if nome.startswith(("_", "p_", "k_")):
            raise AttributeError(nome)
        return getattr(self.newQuery(), nome)

    def isFillable(self, chave):
        if chave in self.p_fillable:
            return True
        if self.p_guarded == ["*"] or "*" in self.p_guarded:
            return False
        return not self.p_fillable and chave not in self.p_guarded

    def totallyGuarded(self):
        return not self.p_fillable and self.p_guarded == ["*"]

    def fill(self, atributos):
        for k, v in php.itens(atributos):
            if self.isFillable(k):
                self.setAttribute(k, v)
            elif self.totallyGuarded():
                raise MassAssignmentException(
                    f"Add [{k}] to fillable property to allow mass assignment on [{self._fqcn}].")
        return self

    def forceFill(self, atributos):
        for k, v in php.itens(atributos):
            self.setAttribute(k, v)
        return self

    def getDirty(self):
        sujos = {}
        orig = self.__dict__["_original"]
        for k, v in self.__dict__["_attrs"].items():
            if k not in orig:
                sujos[k] = v
            elif not self._equivalente(k, v, orig[k]):
                sujos[k] = v
        return sujos

    def _equivalente(self, chave, atual, original):
        if php.ident(atual, original):
            return True
        if atual is None or original is None:
            return False
        if chave in self._datas():
            return self.fromDateTime(atual) == self.fromDateTime(original)
        if php.is_numeric(atual) and php.is_numeric(original):
            return php.to_float(atual) == php.to_float(original)
        return False

    def isDirty(self, chaves=None):
        sujos = self.getDirty()
        if chaves is None:
            return bool(sujos)
        chaves = chaves if isinstance(chaves, (list, dict)) else [chaves]
        return any(k in sujos for k in php.valores(chaves))

    def getAttributes(self):
        return dict(self.__dict__["_attrs"])

    def getOriginal(self, chave=None):
        return self.__dict__["_original"].get(chave) if chave else dict(self.__dict__["_original"])

    def syncOriginal(self):
        self.__dict__["_original"] = dict(self.__dict__["_attrs"])
        return self

    # -------- persistência
    def _tocar_datas(self):
        agora = self.freshTimestamp()
        if self.k_UPDATED_AT and not self.isDirty(self.k_UPDATED_AT):
            self.setAttribute(self.k_UPDATED_AT, agora)
        if not self.p_exists and self.k_CREATED_AT and not self.isDirty(self.k_CREATED_AT):
            self.setAttribute(self.k_CREATED_AT, agora)

    def save(self, opcoes=None):
        tabela = self.getTable()
        if self.p_exists:
            sujos = self.getDirty()
            if sujos:
                if self.p_timestamps:
                    self._tocar_datas()
                    sujos = self.getDirty()
                executar(_atualizar(tabela, sujos, q(self.p_primaryKey) == sa.bindparam(None, self.getKey())))
        else:
            if self.p_timestamps:
                self._tocar_datas()
            attrs = self.__dict__["_attrs"]
            res = executar(_inserir(tabela, [attrs]))
            if self.p_incrementing and res.lastrowid is not None and self.p_primaryKey not in attrs:
                attrs[self.p_primaryKey] = res.lastrowid
            self.__dict__["p_exists"] = True
            self.__dict__["p_wasRecentlyCreated"] = True
        self.syncOriginal()
        return True

    def update(self, atributos=None, opcoes=None):
        if not self.p_exists:
            return False
        return self.fill(atributos or {}).save()

    def delete(self):
        if not self.p_exists:
            return None
        executar(sa.delete(_tabela(self.getTable())).where(q(self.p_primaryKey) == sa.bindparam(None, self.getKey())))
        self.__dict__["p_exists"] = False
        return True

    def refresh(self):
        if not self.p_exists:
            return self
        novo = type(self).query().whereKey(self.getKey()).firstOrFail()
        self.__dict__["_attrs"] = dict(novo.__dict__["_attrs"])
        self.syncOriginal()
        self.__dict__["_relations"] = {}
        return self

    def fresh(self, com=None):
        if not self.p_exists:
            return None
        return type(self).query().whereKey(self.getKey()).first()

    def load(self, *relacoes):
        if len(relacoes) == 1 and isinstance(relacoes[0], (list, dict)):
            relacoes = php.valores(relacoes[0]) if isinstance(relacoes[0], list) else list(relacoes[0].keys())
        for r in relacoes:
            if isinstance(r, str):
                nome = r.split(":")[0].split(".")[0]
                self.__dict__["_relations"][nome] = getattr(self, nome)().getResults()
        return self

    def loadMissing(self, *relacoes):
        return self.load(*[r for r in relacoes if r not in self.__dict__["_relations"]])

    def relationLoaded(self, nome):
        return nome in self.__dict__["_relations"]

    def setRelation(self, nome, valor):
        self.__dict__["_relations"][nome] = valor
        return self

    def getRelation(self, nome):
        return self.__dict__["_relations"].get(nome)

    def unsetRelations(self):
        self.__dict__["_relations"] = {}
        return self

    def is_(self, outro):
        return outro is not None and isinstance(outro, Model) and self.getKey() == outro.getKey() \
            and self.getTable() == outro.getTable()

    def __clone__(self):
        m = type(self)()
        for k in ("_attrs", "_original", "_relations"):
            m.__dict__[k] = dict(self.__dict__[k])
        m.__dict__["p_exists"] = self.__dict__["p_exists"]
        return m

    def replicate(self):
        m = self.__clone__()
        m.__dict__["_attrs"].pop(self.p_primaryKey, None)
        m.__dict__["p_exists"] = False
        return m

    # -------- serialização
    def makeVisible(self, chaves):
        self.__dict__["_visivel_extra"] += php.valores(chaves) if isinstance(chaves, (list, dict)) else [chaves]
        return self

    def makeHidden(self, chaves):
        self.__dict__["_oculto_extra"] += php.valores(chaves) if isinstance(chaves, (list, dict)) else [chaves]
        return self

    def _visivel(self, chave):
        if chave in self.__dict__["_visivel_extra"]:
            return True
        if chave in self.p_hidden or chave in self.__dict__["_oculto_extra"]:
            return False
        return not self.p_visible or chave in self.p_visible

    def attributesToArray(self):
        saida = {}
        for k in self.__dict__["_attrs"]:
            if not self._visivel(k):
                continue
            v = self.getAttribute(k)
            saida[k] = v.toJSON() if isinstance(v, Carbon) else v
        for k in self.p_appends:
            saida[k] = self.getAttribute(k)
        return saida

    def toArray(self):
        saida = self.attributesToArray()
        for nome, v in self.__dict__["_relations"].items():
            if not self._visivel(nome):
                continue
            saida[str_snake(nome)] = v.toArray() if hasattr(v, "toArray") else v
        return saida

    def jsonSerialize(self):
        return self.toArray()

    def toJson(self, flags=0):
        return php.json_encode(self.toArray(), flags)

    # -------- relações
    def _nome_relacao(self):
        return inspect.stack()[2].function

    def belongsTo(self, relacionado, chave_estrangeira=None, chave_dono=None, relacao=None):
        cls = php.classe(relacionado)
        relacao = relacao or self._nome_relacao()
        dono = chave_dono or cls().getKeyName()
        fk = chave_estrangeira or (str_snake(relacao) + "_" + dono)
        return BelongsTo(self, cls, fk, dono, relacao)

    def hasMany(self, relacionado, chave_estrangeira=None, chave_local=None):
        cls = php.classe(relacionado)
        return HasMany(self, cls, chave_estrangeira or self.getForeignKey(), chave_local or self.getKeyName())

    def hasOne(self, relacionado, chave_estrangeira=None, chave_local=None):
        cls = php.classe(relacionado)
        return HasOne(self, cls, chave_estrangeira or self.getForeignKey(), chave_local or self.getKeyName())

    def belongsToMany(self, relacionado, tabela=None, fk_pivo=None, rk_pivo=None, chave_pai=None,
                      chave_relacionada=None, relacao=None):
        cls = php.classe(relacionado)
        outro = cls()
        if tabela is None:
            segmentos = sorted([str_snake(cls._fqcn.rsplit("\\", 1)[-1]), str_snake(self._fqcn.rsplit("\\", 1)[-1])])
            tabela = "_".join(segmentos).lower()
        return BelongsToMany(self, cls, tabela, fk_pivo or self.getForeignKey(), rk_pivo or outro.getForeignKey(),
                             chave_pai or self.getKeyName(), chave_relacionada or outro.getKeyName(),
                             relacao or self._nome_relacao())


# --------------------------------------------------------------------------- relações
class Relation(Base):
    _fqcn = "Illuminate\\Database\\Eloquent\\Relations\\Relation"

    def _construct(self, pai, relacionado):
        self.pai = pai
        self.relacionado = relacionado
        self.consulta = Builder(relacionado)
        if pai.p_exists:
            self.restringir()

    def restringir(self):
        pass

    def getQuery(self):
        return self.consulta

    def __getattr__(self, nome):
        if nome.startswith(("_", "p_", "k_")):
            raise AttributeError(nome)
        alvo = getattr(self.consulta, nome)
        if not callable(alvo):
            return alvo

        def chamar(*args, **kwargs):
            r = alvo(*args, **kwargs)
            return self if r is self.consulta else r
        return chamar

    def get(self, colunas=None):
        return self.consulta.get(colunas)

    def first(self, colunas=None):
        return self.consulta.first(colunas)

    def exists(self):
        return self.consulta.exists()

    def count(self):
        return self.consulta.count()


class BelongsTo(Relation):
    _fqcn = "Illuminate\\Database\\Eloquent\\Relations\\BelongsTo"

    def _construct(self, pai, relacionado, fk, dono, relacao):
        self.fk, self.dono, self.relacao = fk, dono, relacao
        Relation._construct(self, pai, relacionado)

    def restringir(self):
        self.consulta.where(f"{self.consulta.tabela}.{self.dono}", "=", self.pai.getAttribute(self.fk))

    def getResults(self):
        if self.pai.getAttribute(self.fk) is None:
            return None
        return self.consulta.first()

    def consulta_de_existencia(self, pai_builder):
        sub = Builder(self.relacionado)
        sub.whereColumn(f"{pai_builder.tabela}.{self.fk}", "=", f"{sub.tabela}.{self.dono}")
        return sub

    def associate(self, modelo):
        self.pai.setAttribute(self.fk, modelo.getAttribute(self.dono) if isinstance(modelo, Model) else modelo)
        if isinstance(modelo, Model):
            self.pai.setRelation(self.relacao, modelo)
        return self.pai


class HasMany(Relation):
    _fqcn = "Illuminate\\Database\\Eloquent\\Relations\\HasMany"
    um = False

    def _construct(self, pai, relacionado, fk, local):
        self.fk, self.local = fk, local
        Relation._construct(self, pai, relacionado)

    def restringir(self):
        col = f"{self.consulta.tabela}.{self.fk}"
        self.consulta.where(col, "=", self.pai.getAttribute(self.local))
        self.consulta.whereNotNull(col)

    def getResults(self):
        if self.pai.getAttribute(self.local) is None:
            return None if self.um else EloquentCollection([])
        return self.consulta.first() if self.um else self.consulta.get()

    def consulta_de_existencia(self, pai_builder):
        sub = Builder(self.relacionado)
        sub.whereColumn(f"{pai_builder.tabela}.{self.local}", "=", f"{sub.tabela}.{self.fk}")
        return sub

    def create(self, atributos=None):
        m = self.relacionado()
        m.fill(atributos or {})
        m.setAttribute(self.fk, self.pai.getAttribute(self.local))
        m.save()
        return m

    def save(self, modelo):
        modelo.setAttribute(self.fk, self.pai.getAttribute(self.local))
        modelo.save()
        return modelo


class HasOne(HasMany):
    _fqcn = "Illuminate\\Database\\Eloquent\\Relations\\HasOne"
    um = True


class BelongsToMany(Relation):
    _fqcn = "Illuminate\\Database\\Eloquent\\Relations\\BelongsToMany"

    def _construct(self, pai, relacionado, tabela, fk_pivo, rk_pivo, chave_pai, chave_rel, relacao):
        self.tabela, self.fk_pivo, self.rk_pivo = tabela, fk_pivo, rk_pivo
        self.chave_pai, self.chave_rel, self.relacao = chave_pai, chave_rel, relacao
        Relation._construct(self, pai, relacionado)
        tab = self.consulta.tabela
        self.consulta.joins.append((tabela, f"{tab}.{chave_rel}", f"{tabela}.{rk_pivo}"))

    def restringir(self):
        self.consulta.where(f"{self.tabela}.{self.fk_pivo}", "=", self.pai.getAttribute(self.chave_pai))

    def _colunas(self):
        tab = self.consulta.tabela
        return [q(f"{tab}.*"), q(f"{self.tabela}.{self.fk_pivo}").label(f"pivot_{self.fk_pivo}"),
                q(f"{self.tabela}.{self.rk_pivo}").label(f"pivot_{self.rk_pivo}")]

    def get(self, colunas=None):
        if not self.consulta.colunas:
            self.consulta.colunas = self._colunas()
        return self.consulta.get()

    def getResults(self):
        if self.pai.getAttribute(self.chave_pai) is None:
            return EloquentCollection([])
        return self.get()

    def first(self, colunas=None):
        b = self.consulta.clone().limit(1)
        if not b.colunas:
            b.colunas = self._colunas()
        return b.get().first()

    def consulta_de_existencia(self, pai_builder):
        sub = Builder(self.relacionado)
        sub.joins.append((self.tabela, f"{sub.tabela}.{self.chave_rel}", f"{self.tabela}.{self.rk_pivo}"))
        sub.whereColumn(f"{pai_builder.tabela}.{self.chave_pai}", "=", f"{self.tabela}.{self.fk_pivo}")
        return sub

    def _ids(self, valor):
        if valor is None:
            return None
        if isinstance(valor, Model):
            return [valor.getAttribute(self.chave_rel)]
        if isinstance(valor, Collection):
            return [x.getAttribute(self.chave_rel) if isinstance(x, Model) else x for x in valor]
        if isinstance(valor, (list, dict)):
            if isinstance(valor, dict) and not php.eh_lista(valor):
                return list(valor.keys())
            return [x.getAttribute(self.chave_rel) if isinstance(x, Model) else x for x in php.valores(valor)]
        return [valor]

    def _atuais(self):
        stmt = sa.select(q(f"{self.tabela}.{self.rk_pivo}")).select_from(_tabela(self.tabela)).where(
            q(f"{self.tabela}.{self.fk_pivo}") == sa.bindparam(None, self.pai.getAttribute(self.chave_pai)))
        return [list(r.values())[0] for r in executar(stmt)]

    def attach(self, ids, atributos=None):
        linhas = [{self.fk_pivo: self.pai.getAttribute(self.chave_pai), self.rk_pivo: i, **(atributos or {})}
                  for i in self._ids(ids)]
        if linhas:
            executar(_inserir(self.tabela, linhas))

    def detach(self, ids=None, tocar=True):
        stmt = sa.delete(_tabela(self.tabela)).where(
            q(f"{self.tabela}.{self.fk_pivo}") == sa.bindparam(None, self.pai.getAttribute(self.chave_pai)))
        lista = self._ids(ids)
        if lista is not None:
            if not lista:
                return 0
            stmt = stmt.where(q(f"{self.tabela}.{self.rk_pivo}").in_([sa.bindparam(None, i) for i in lista]))
        return executar(stmt).rowcount

    def sync(self, ids, desanexar=True):
        atuais = self._atuais()
        novos = self._ids(ids) or []
        saida = {"attached": [], "detached": [], "updated": []}
        if desanexar:
            tirar = [i for i in atuais if not any(php.eq(i, n) for n in novos)]
            if tirar:
                self.detach(tirar)
            saida["detached"] = tirar
        anexar = [n for n in novos if not any(php.eq(n, i) for i in atuais)]
        if anexar:
            self.attach(anexar)
        saida["attached"] = anexar
        return saida

    def syncWithoutDetaching(self, ids):
        return self.sync(ids, False)

    def toggle(self, ids):
        atuais = self._atuais()
        lista = self._ids(ids) or []
        tirar = [i for i in lista if any(php.eq(i, a) for a in atuais)]
        por = [i for i in lista if i not in tirar]
        if tirar:
            self.detach(tirar)
        if por:
            self.attach(por)
        return {"attached": por, "detached": tirar}


# --------------------------------------------------------------------------- coleção
class EloquentCollection(Collection):
    _fqcn = "Illuminate\\Database\\Eloquent\\Collection"

    def modelKeys(self):
        return [m.getKey() for m in self]

    def find(self, chave, padrao=None):
        if isinstance(chave, Model):
            chave = chave.getKey()
        for m in self:
            if php.eq(m.getKey(), chave):
                return m
        return padrao

    def contains(self, chave, *args):
        if isinstance(chave, Model):
            return any(m.is_(chave) for m in self)
        return Collection.contains(self, chave, *args)

    def load(self, *relacoes):
        for m in self:
            m.load(*relacoes)
        return self

    def toArray(self):
        return [m.toArray() if hasattr(m, "toArray") else m for m in self]


def _dg(alvo, chave, padrao=None):
    return data_get(alvo, chave, padrao)


class DB(Base):
    _fqcn = "Illuminate\\Support\\Facades\\DB"

    @staticmethod
    def transaction(fn, tentativas=1):
        return fn()

    @staticmethod
    def beginTransaction():
        return None

    @staticmethod
    def commit():
        return None

    @staticmethod
    def rollBack():
        return None
