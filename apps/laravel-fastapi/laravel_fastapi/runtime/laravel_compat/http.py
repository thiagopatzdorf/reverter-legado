"""Request, FormRequest, JsonResource e respostas do Laravel 9, e o renderizador de exceções.

O caminho de uma requisição repete o do Laravel: middleware global (TrimStrings,
ConvertEmptyStringsToNull) mexe na entrada antes de tudo; o middleware da rota
roda antes do controller; o FormRequest valida ao ser injetado; o retorno do
controller passa pelo `Router::toResponse`; e qualquer exceção passa pelo
`Handler::render`, inclusive pelos `renderable` que o app registrou.
"""
from __future__ import annotations

import json as _json
from urllib.parse import parse_qsl

from . import contexto, php
from .suporte import Arr, Base, Collection, data_get

# --------------------------------------------------------------------------- exceções HTTP
class HttpException(php.RuntimeException):
    _fqcn = "Symfony\\Component\\HttpKernel\\Exception\\HttpException"

    def __init__(self, status=500, message="", previous=None, headers=None, code=0):
        super().__init__(message, code, previous)
        self.status = status
        self.headers = headers or {}

    def _construct(self, status=500, message="", previous=None, headers=None, code=0):
        HttpException.__init__(self, status, message, previous, headers, code)

    def getStatusCode(self):
        return self.status

    def getHeaders(self):
        return self.headers


class NotFoundHttpException(HttpException):
    _fqcn = "Symfony\\Component\\HttpKernel\\Exception\\NotFoundHttpException"

    def __init__(self, message="", previous=None, code=0, headers=None):
        super().__init__(404, message, previous, headers, code)

    _construct = __init__


class AccessDeniedHttpException(HttpException):
    _fqcn = "Symfony\\Component\\HttpKernel\\Exception\\AccessDeniedHttpException"

    def __init__(self, message="", previous=None, code=0, headers=None):
        super().__init__(403, message, previous, headers, code)

    _construct = __init__


class MethodNotAllowedHttpException(HttpException):
    _fqcn = "Symfony\\Component\\HttpKernel\\Exception\\MethodNotAllowedHttpException"

    def __init__(self, permitidos=(), message="", previous=None, code=0, headers=None):
        super().__init__(405, message, previous, {"Allow": ", ".join(permitidos), **(headers or {})}, code)


class TooManyRequestsHttpException(HttpException):
    _fqcn = "Symfony\\Component\\HttpKernel\\Exception\\TooManyRequestsHttpException"

    def __init__(self, retry=None, message="", previous=None, code=0, headers=None):
        super().__init__(429, message, previous, headers, code)


class ThrottleRequestsException(TooManyRequestsHttpException):
    _fqcn = "Illuminate\\Http\\Exceptions\\ThrottleRequestsException"


class HttpResponseException(php.RuntimeException):
    _fqcn = "Illuminate\\Http\\Exceptions\\HttpResponseException"

    def __init__(self, resposta=None):
        super().__init__("")
        self.resposta = resposta

    def getResponse(self):
        return self.resposta


def abort(codigo, mensagem="", headers=None):
    if isinstance(codigo, Response):
        raise HttpResponseException(codigo)
    if codigo == 404:
        raise NotFoundHttpException(mensagem, None, 0, headers)
    raise HttpException(codigo, mensagem, None, headers)


def abort_if(cond, codigo, mensagem="", headers=None):
    if php.truthy(cond):
        abort(codigo, mensagem, headers)


def abort_unless(cond, codigo, mensagem="", headers=None):
    if not php.truthy(cond):
        abort(codigo, mensagem, headers)


# --------------------------------------------------------------------------- respostas
class Response(Base):
    _fqcn = "Illuminate\\Http\\Response"

    def _construct(self, conteudo="", status=200, headers=None):
        self.conteudo = conteudo
        self.status = php.to_int(status)
        self.headers = dict(headers or {})
        self.original = conteudo

    def setStatusCode(self, codigo, texto=None):
        self.status = php.to_int(codigo)
        return self

    def status_(self):
        return self.status

    def getStatusCode(self):
        return self.status

    def header(self, nome, valor, trocar=True):
        self.headers[nome] = valor
        return self

    def withHeaders(self, headers):
        self.headers.update(headers)
        return self

    def getContent(self):
        return php.to_str(self.conteudo)

    def corpo(self) -> tuple[bytes, str]:
        tipo = self.headers.get("Content-Type", "text/html; charset=UTF-8")
        return php.to_str(self.conteudo).encode("utf-8"), tipo


class JsonResponse(Response):
    _fqcn = "Illuminate\\Http\\JsonResponse"

    def _construct(self, dados=None, status=200, headers=None, opcoes=0, json=False):
        Response._construct(self, None, status, headers)
        self.opcoes = opcoes
        self.dados = php.para_json(dados if dados is not None else {})
        self.original = dados

    def getData(self, assoc=False):
        return self.dados

    def setData(self, dados):
        self.dados = php.para_json(dados)
        return self

    def corpo(self) -> tuple[bytes, str]:
        return php._json_texto(self.dados, self.opcoes).encode("utf-8"), "application/json"


class ResponseFactory(Base):
    _fqcn = "Illuminate\\Contracts\\Routing\\ResponseFactory"

    def json(self, dados=None, status=200, headers=None, opcoes=0):
        return JsonResponse(dados if dados is not None else [], status, headers, opcoes)

    def make(self, conteudo="", status=200, headers=None):
        return Response(conteudo, status, headers)

    def noContent(self, status=204, headers=None):
        return Response("", status, headers)


def response(conteudo=php.PADRAO, status=200, headers=None):
    if conteudo is php.PADRAO:
        return ResponseFactory()
    return Response(conteudo, status, headers)


# --------------------------------------------------------------------------- Request
def _limpar(bolsa, excecoes, prefixo=""):
    """TrimStrings + ConvertEmptyStringsToNull, chave completa com ponto (como o Laravel)."""
    if not isinstance(bolsa, dict):
        return bolsa
    saida = {}
    for k, v in bolsa.items():
        chave = f"{prefixo}{k}"
        if isinstance(v, dict):
            saida[k] = _limpar(v, excecoes, chave + ".")
        elif isinstance(v, list):
            saida[k] = [_limpar_valor(x, excecoes, f"{chave}.{i}") if not isinstance(x, dict) else _limpar(x, excecoes, f"{chave}.{i}.")
                        for i, x in enumerate(v)]
        else:
            saida[k] = _limpar_valor(v, excecoes, chave)
    return saida


def _limpar_valor(v, excecoes, chave):
    if isinstance(v, str):
        if "trim" in excecoes and chave not in excecoes["trim"]:
            v = v.strip(" \t\n\r\x00\x0b")
        if "vazio" in excecoes and v == "":
            v = None
    return v


class Request(Base):
    _fqcn = "Illuminate\\Http\\Request"
    # Bits do Symfony\\Request (o TrustProxies do app soma estes).
    k_HEADER_FORWARDED = 0b000001
    k_HEADER_X_FORWARDED_FOR = 0b000010
    k_HEADER_X_FORWARDED_HOST = 0b000100
    k_HEADER_X_FORWARDED_PROTO = 0b001000
    k_HEADER_X_FORWARDED_PORT = 0b010000
    k_HEADER_X_FORWARDED_PREFIX = 0b100000
    k_HEADER_X_FORWARDED_AWS_ELB = 0b0011010
    k_HEADER_X_FORWARDED_TRAEFIK = 0b0111110

    def _construct(self, metodo="GET", caminho="/", query=None, headers=None, corpo=b"", ip="127.0.0.1"):
        self.metodo = metodo.upper()
        self.caminho = caminho
        self.headers_ = {k.lower(): v for k, v in (headers or {}).items()}
        self.consulta = dict(query or {})
        self.corpo = corpo
        self.ip_ = ip
        self.json_ = {}
        self.formulario = {}
        self.rota_params: dict = {}
        self.rota_meta: dict = {}
        self.auth = None
        tipo = self.headers_.get("content-type", "")
        if self.isJson():
            try:
                v = _json.loads(corpo.decode("utf-8")) if corpo else {}
                self.json_ = v if isinstance(v, dict) else {}
            except (ValueError, UnicodeDecodeError):
                self.json_ = {}
        elif "application/x-www-form-urlencoded" in tipo:
            self.formulario = dict(parse_qsl(corpo.decode("utf-8", "replace"), keep_blank_values=True))

    @classmethod
    def copiar(cls, outro: Request):
        novo = cls.__new__(cls)
        novo.__dict__.update(outro.__dict__)
        novo.json_ = dict(outro.json_)
        novo.consulta = dict(outro.consulta)
        novo.formulario = dict(outro.formulario)
        novo.original = outro
        return novo

    def limpar_entrada(self, excecoes):
        self.consulta = _limpar(self.consulta, excecoes)
        if self.isJson():
            self.json_ = _limpar(self.json_, excecoes)
        else:
            self.formulario = _limpar(self.formulario, excecoes)

    # -------- leitura
    def isJson(self):
        tipo = self.headers_.get("content-type", "")
        return "/json" in tipo or "+json" in tipo

    def _fonte(self):
        if self.isJson():
            return self.json_
        return self.consulta if self.metodo in ("GET", "HEAD") else self.formulario

    def all(self, chaves=None):
        # input() = fonte + query (o `+` do PHP: a chave da fonte vence e vem antes).
        dados = dict(self._fonte())
        for k, v in self.consulta.items():
            dados.setdefault(k, v)
        if chaves is None:
            return dados
        return {k: data_get(dados, k) for k in php.valores(chaves if isinstance(chaves, (list, dict)) else [chaves])}

    def input(self, chave=None, padrao=None):
        dados = self.all()
        if chave is None:
            return dados
        v = data_get(dados, chave, php.PADRAO)
        if v is php.PADRAO:
            return padrao() if callable(padrao) else padrao
        return v

    def get(self, chave, padrao=None):
        return self.input(chave, padrao)

    def query(self, chave=None, padrao=None):
        if chave is None:
            return self.consulta
        v = data_get(self.consulta, chave, php.PADRAO)
        return padrao if v is php.PADRAO else v

    def json(self, chave=None, padrao=None):
        if chave is None:
            return Collection(self.json_)
        v = data_get(self.json_, chave, php.PADRAO)
        return padrao if v is php.PADRAO else v

    def only(self, *chaves):
        if len(chaves) == 1 and isinstance(chaves[0], (list, dict)):
            chaves = php.valores(chaves[0])
        dados = self.all()
        saida = {}
        for k in chaves:
            v = data_get(dados, k, php.PADRAO)
            if v is not php.PADRAO:
                Arr.set(saida, k, v)
        return saida

    def except_(self, *chaves):
        if len(chaves) == 1 and isinstance(chaves[0], (list, dict)):
            chaves = php.valores(chaves[0])
        dados = dict(self.all())
        Arr.forget(dados, list(chaves))
        return dados

    def has(self, chaves):
        chaves = chaves if isinstance(chaves, (list, dict)) else [chaves]
        return all(Arr.has(self.all(), k) for k in php.valores(chaves))

    def filled(self, chave):
        v = self.input(chave)
        return not (v is None or (isinstance(v, str) and v.strip() == "") or (isinstance(v, (list, dict)) and not v))

    def boolean(self, chave, padrao=False):
        return php.filter_var(self.input(chave, padrao), php.FILTER_VALIDATE_BOOLEAN)

    def integer(self, chave, padrao=0):
        return php.to_int(self.input(chave, padrao))

    def merge(self, entrada):
        alvo = self._fonte()
        for k, v in php.itens(entrada):
            alvo[k] = v
        return self

    def replace(self, entrada):
        alvo = self._fonte()
        alvo.clear()
        alvo.update(entrada)
        return self

    def offsetGet(self, chave):
        return self.input(chave)

    def offsetExists(self, chave):
        return Arr.has(self.all(), chave)

    def _p(self, nome):
        if hasattr(type(self), "p_" + nome) or ("p_" + nome) in self.__dict__:
            return getattr(self, "p_" + nome)
        return self.input(nome)

    # -------- metadados
    def header(self, chave=None, padrao=None):
        if chave is None:
            return dict(self.headers_)
        return self.headers_.get(php.to_str(chave).lower(), padrao)

    def hasHeader(self, chave):
        return php.to_str(chave).lower() in self.headers_

    def bearerToken(self):
        h = self.header("Authorization", "")
        pos = h.lower().find("bearer ")
        if pos >= 0:
            t = h[pos + 7:]
            return t.split(",")[0] if "," in t else t
        return None

    def method(self):
        return self.metodo

    def isMethod(self, m):
        return self.metodo == php.to_str(m).upper()

    def path(self):
        p = self.caminho.strip("/")
        return p if p else "/"

    def url(self):
        return "http://localhost/" + self.path().lstrip("/")

    def fullUrl(self):
        return self.url()

    def ip(self):
        return self.ip_

    def is_(self, *padroes):
        from .suporte import Str

        return any(Str.is_(p, self.path()) for p in padroes)

    def ajax(self):
        return self.headers_.get("x-requested-with") == "XMLHttpRequest"

    def pjax(self):
        return self.headers_.get("x-pjax") == "true"

    def wantsJson(self):
        aceita = self.headers_.get("accept", "")
        primeiro = aceita.split(",")[0].strip() if aceita else ""
        return "/json" in primeiro or "+json" in primeiro

    def acceptsAnyContentType(self):
        aceita = self.headers_.get("accept", "")
        return not aceita or aceita.split(",")[0].strip() in ("*/*", "*")

    def expectsJson(self):
        return (self.ajax() and not self.pjax() and self.acceptsAnyContentType()) or self.wantsJson()

    def route(self, param=None, padrao=None):
        if param is None:
            return self.rota_meta
        return self.rota_params.get(param, padrao)

    def user(self, guarda=None):
        from . import auth

        return auth.gerente(self).guard(guarda).user()

    def setUserResolver(self, fn):
        return self

    def validate(self, regras, mensagens=None, atributos=None):
        from .validacao import Validator

        return Validator(self.all(), regras, mensagens, atributos).validate()


# --------------------------------------------------------------------------- FormRequest
class FormRequest(Request):
    _fqcn = "Illuminate\\Foundation\\Http\\FormRequest"
    p_stopOnFirstFailure = False

    def _construct(self, *args, **kwargs):
        Request._construct(self, *args, **kwargs)

    def validationData(self):
        return self.all()

    def rules(self):
        return {}

    def messages(self):
        return {}

    def attributes(self):
        return {}

    def prepareForValidation(self):
        return None

    def passedValidation(self):
        return None

    def validar(self):
        """ValidatesWhenResolvedTrait::validateResolved."""
        from .auth import AuthorizationException
        from .validacao import ValidationException, Validator

        self.prepareForValidation()
        autoriza = getattr(type(self), "authorize", None)
        if autoriza is not None and not php.truthy(self.authorize()):
            raise AuthorizationException("This action is unauthorized.")
        self.validador = Validator(self.validationData(), self.rules(), self.messages(), self.attributes())
        if not self.validador.passes():
            raise ValidationException(self.validador)
        self.passedValidation()

    def validated(self, chave=None, padrao=None):
        dados = self.validador.validated()
        return dados if chave is None else data_get(dados, chave, padrao)

    def safe(self):
        return Collection(self.validated())

    def validator(self):
        return self.validador


# --------------------------------------------------------------------------- recursos JSON
class MissingValue(Base):
    _fqcn = "Illuminate\\Http\\Resources\\MissingValue"

    def isMissing(self):
        return True


class MergeValue(Base):
    _fqcn = "Illuminate\\Http\\Resources\\MergeValue"

    def _construct(self, dados):
        self.dados = dados.all() if isinstance(dados, Collection) else dados


class JsonResource(Base):
    _fqcn = "Illuminate\\Http\\Resources\\Json\\JsonResource"
    p_wrap = "data"

    def _construct(self, recurso=None):
        self.p_resource = recurso
        self.p_with = []
        self.p_additional = {}

    @classmethod
    def make(cls, *args):
        return cls(*args)

    @classmethod
    def collection(cls, recurso):
        return AnonymousResourceCollection(recurso, cls)

    @classmethod
    def withoutWrapping(cls):
        JsonResource.p_wrap = None

    @classmethod
    def wrap(cls, valor):
        cls.p_wrap = valor

    # DelegatesToResource: $this->campo lê do model embrulhado.
    def _p(self, nome):
        if hasattr(type(self), "p_" + nome) or ("p_" + nome) in self.__dict__:
            return getattr(self, "p_" + nome)
        r = self.__dict__.get("p_resource")
        return r._p(nome) if hasattr(r, "_p") else data_get(r, nome)

    def __getattr__(self, nome):
        if nome.startswith(("_", "p_", "k_")):
            raise AttributeError(nome)
        return getattr(self.__dict__["p_resource"], nome)

    def offsetGet(self, chave):
        r = self.p_resource
        return r.offsetGet(chave) if hasattr(r, "offsetGet") else php.idx(r, chave)

    def offsetExists(self, chave):
        r = self.p_resource
        return r.offsetExists(chave) if hasattr(r, "offsetExists") else php.isset(lambda: php.idx(r, chave))

    def toArray(self, requisicao=None):
        r = self.p_resource
        if r is None:
            return []
        if isinstance(r, (list, dict)):
            return r
        return r.toArray()

    def resolve(self, requisicao=None):
        dados = self.toArray(requisicao if requisicao is not None else contexto.requisicao())
        if isinstance(dados, Collection):
            dados = dados.toArray()
        elif hasattr(dados, "toArray") and not isinstance(dados, (list, dict)):
            dados = dados.toArray()
        elif hasattr(dados, "jsonSerialize"):
            dados = dados.jsonSerialize()
        return self.filter(php.to_array(dados))

    def filter(self, dados):
        if isinstance(dados, list):
            dados = dict(enumerate(dados))
        dados = dict(dados)
        for i, (k, v) in enumerate(list(dados.items())):
            if isinstance(v, (list, dict)):
                dados[k] = self.filter(v)
                continue
            if isinstance(k, int) and isinstance(v, MergeValue):
                return self._mesclar(dados, i, self.filter(v.dados))
            if isinstance(v, JsonResource) and v.__dict__.get("p_resource") is None:
                dados[k] = None
        return self._tirar_ausentes(dados)

    def _mesclar(self, dados, indice, mescla):
        itens = list(dados.items())
        antes, depois = dict(itens[:indice]), dict(itens[indice + 1:])
        return self.filter({**antes, **(mescla if isinstance(mescla, dict) else dict(enumerate(mescla))), **depois})

    def _tirar_ausentes(self, dados):
        saida = {}
        numericas = True
        for k, v in dados.items():
            if isinstance(v, MissingValue) or (isinstance(v, JsonResource) and isinstance(v.__dict__.get("p_resource"), MissingValue)):
                continue
            numericas = numericas and php.is_numeric(k)
            saida[k] = v
        return list(saida.values()) if numericas else saida

    def with_(self, requisicao=None):
        return self.p_with

    def additional(self, dados):
        self.p_additional = dados
        return self

    def when(self, condicao, valor, padrao=php.PADRAO):
        if php.truthy(condicao):
            return valor() if callable(valor) else valor
        if padrao is php.PADRAO:
            return MissingValue()
        return padrao() if callable(padrao) else padrao

    def unless(self, condicao, valor, padrao=php.PADRAO):
        return self.when(not php.truthy(condicao), valor, padrao)

    def whenNotNull(self, valor, padrao=php.PADRAO):
        return self.when(valor is not None, valor, padrao)

    def whenLoaded(self, relacao, valor=php.PADRAO, padrao=php.PADRAO):
        r = self.p_resource
        if not (hasattr(r, "relationLoaded") and r.relationLoaded(relacao)):
            return MissingValue() if padrao is php.PADRAO else (padrao() if callable(padrao) else padrao)
        carregado = r.getRelation(relacao)
        if valor is php.PADRAO:
            return carregado
        if carregado is None:
            return None
        return valor() if callable(valor) else valor

    def mergeWhen(self, condicao, valor, padrao=php.PADRAO):
        if php.truthy(condicao):
            return MergeValue(valor() if callable(valor) else valor)
        return MissingValue() if padrao is php.PADRAO else MergeValue(padrao() if callable(padrao) else padrao)

    def merge(self, valor):
        return self.mergeWhen(True, valor)

    def response(self, requisicao=None):
        return self.toResponse(requisicao if requisicao is not None else contexto.requisicao())

    def toResponse(self, requisicao=None):
        return ResourceResponse(self).toResponse(requisicao)

    def jsonSerialize(self):
        return self.resolve(contexto.requisicao())

    def withResponse(self, requisicao, resposta):
        return None


class ResourceCollection(JsonResource):
    _fqcn = "Illuminate\\Http\\Resources\\Json\\ResourceCollection"
    p_collects = None

    def _construct(self, recurso=None):
        JsonResource._construct(self, recurso)
        self.p_resource = self._coletar(recurso)

    def _coletar(self, recurso):
        if isinstance(recurso, MissingValue):
            return recurso
        if isinstance(recurso, (list, dict)):
            recurso = Collection(recurso)
        if recurso is None:
            recurso = Collection([])
        coleta = self._classe_coletada()
        if coleta is not None and not (recurso.first() is not None and php.instanceof(recurso.first(), coleta._fqcn)):
            self.p_collection = Collection([coleta(x) for x in recurso]) if isinstance(recurso.all(), list) \
                else Collection({k: coleta(x) for k, x in recurso.all().items()})
        else:
            self.p_collection = Collection(recurso.all() if isinstance(recurso, Collection) else recurso)
        return self.p_collection

    def _classe_coletada(self):
        if self.p_collects:
            return php.classe(self.p_collects)
        nome = php.fqcn(self)
        if nome.endswith("Collection"):
            for alvo in (nome[: -len("Collection")], nome[: -len("Collection")] + "Resource"):
                if php.existe_classe(alvo):
                    return php.classe(alvo)
        return None

    def toArray(self, requisicao=None):
        return [x.toArray(requisicao) if hasattr(x, "toArray") else x for x in self.p_collection]

    def count(self):
        return self.p_collection.count()

    def __iter__(self):
        return iter(self.p_collection)


class AnonymousResourceCollection(ResourceCollection):
    _fqcn = "Illuminate\\Http\\Resources\\Json\\AnonymousResourceCollection"

    def _construct(self, recurso=None, coleta=None):
        self.p_collects = coleta
        ResourceCollection._construct(self, recurso)


class ResourceResponse(Base):
    _fqcn = "Illuminate\\Http\\Resources\\Json\\ResourceResponse"

    def _construct(self, recurso):
        self.recurso = recurso

    def _embrulho(self):
        return type(self.recurso).p_wrap

    def toResponse(self, requisicao=None):
        from .eloquent import Model

        r = self.recurso
        dados = r.resolve(requisicao)
        com = r.with_(requisicao)
        extra = r.p_additional
        corpo = self.embrulhar(dados, com, extra)
        base = r.__dict__.get("p_resource")
        status = 201 if isinstance(base, Model) and base.p_wasRecentlyCreated else 200
        resposta = JsonResponse(corpo, status)
        resposta.original = base
        r.withResponse(requisicao, resposta)
        return resposta

    def embrulhar(self, dados, com, extra):
        if isinstance(dados, Collection):
            dados = dados.all()
        embrulho = self._embrulho()
        tem_chave = isinstance(dados, dict) and embrulho in dados
        if embrulho and not tem_chave:
            dados = {embrulho: dados}
        elif (com or extra) and (not embrulho or not tem_chave):
            dados = {(embrulho or "data"): dados}
        return php.array_merge_recursive(dados if isinstance(dados, dict) else dict(enumerate(dados)),
                                         php.to_array(com) or {}, php.to_array(extra) or {})


# --------------------------------------------------------------------------- conversão do retorno
def para_resposta(valor) -> Response:
    """Router::toResponse do Laravel 9."""
    from .eloquent import Model

    req = contexto.requisicao()
    if isinstance(valor, Response):
        return valor
    if hasattr(valor, "toResponse"):
        return para_resposta(valor.toResponse(req))
    if isinstance(valor, Model) and valor.p_wasRecentlyCreated:
        return JsonResponse(valor, 201)
    if isinstance(valor, (list, dict)) or hasattr(valor, "toArray") or hasattr(valor, "jsonSerialize"):
        return JsonResponse(valor)
    return Response("" if valor is None else php.to_str(valor), 200, {"Content-Type": "text/html; charset=UTF-8"})


class Controller(Base):
    """Illuminate\\Routing\\Controller + AuthorizesRequests + ValidatesRequests."""

    _fqcn = "Illuminate\\Routing\\Controller"

    def authorize(self, habilidade, argumentos=None):
        from .auth import Gate

        return Gate.authorize(habilidade, argumentos if argumentos is not None else [])

    def validate(self, requisicao, regras, mensagens=None, atributos=None):
        from .validacao import Validator

        return Validator(requisicao.all(), regras, mensagens or {}, atributos or {}).validate()

    def middleware(self, *args):
        return self

    def callAction(self, metodo, parametros):
        return getattr(self, metodo)(*php.valores(parametros))


# --------------------------------------------------------------------------- rotas nomeadas e redirecionamento
class RouteNotFoundException(php.PHPException):
    _fqcn = "Symfony\\Component\\Routing\\Exception\\RouteNotFoundException"


def route(nome, parametros=None, absoluto=True):
    """URL de rota nomeada, lida do contrato; rota que não existe falha como no Laravel."""
    rotas = contexto.aplicacao().dados.get("rotas", [])
    alvo = next((r for r in rotas if r.get("nome") == nome), None)
    if alvo is None:
        raise RouteNotFoundException(f"Route [{nome}] not defined.")
    caminho = alvo["caminho"]
    valores = php.valores(parametros) if isinstance(parametros, list) else []
    for p in alvo.get("parametros", []):
        v = parametros.get(p["nome"]) if isinstance(parametros, dict) else (valores.pop(0) if valores else None)
        caminho = caminho.replace("{" + p["nome"] + ("?" if p.get("opcional") else "") + "}", php.to_str(v))
    return ("http://localhost" if absoluto else "") + caminho


class RedirectResponse(Response):
    _fqcn = "Illuminate\\Http\\RedirectResponse"

    def _construct(self, destino="", status=302, headers=None):
        Response._construct(self, "", status, {**(headers or {}), "Location": destino})


class Redirector(Base):
    _fqcn = "Illuminate\\Routing\\Redirector"

    def to(self, destino, status=302, headers=None, seguro=None):
        return RedirectResponse(destino, status, headers)

    def route(self, nome, parametros=None, status=302, headers=None):
        return RedirectResponse(route(nome, parametros), status, headers)

    def intended(self, padrao="/", status=302, headers=None, seguro=None):
        return RedirectResponse(padrao, status, headers)

    def back(self, status=302, headers=None, fallback=False):
        return RedirectResponse("/", status, headers)


def redirect(destino=None, status=302, headers=None, seguro=None):
    if destino is None:
        return Redirector()
    return RedirectResponse(destino, status, headers)


class _Encadeavel(Base):
    def _construct(self, *a, **k):
        pass

    def _seguir(self, *a, **k):
        return self

    middleware = prefix = name = as_ = group = namespace = domain = controller = where = _seguir
    get = post = put = patch = delete = options = any = match = resource = apiResource = _seguir
    withoutMiddleware = only = except_ = _seguir


class RouteFacade(_Encadeavel):
    """Fachada Route: as rotas já vêm do contrato; registrar de novo não faz nada."""

    _fqcn = "Illuminate\\Support\\Facades\\Route"

    @classmethod
    def _seguir(cls, *a, **k):
        return _Encadeavel()

    middleware = prefix = name = as_ = group = namespace = domain = controller = where = _seguir
    get = post = put = patch = delete = options = any = match = resource = apiResource = _seguir
