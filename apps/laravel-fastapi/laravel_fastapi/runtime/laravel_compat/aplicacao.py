"""A aplicação: liga o código traduzido, os dados do contrato e o FastAPI.

Faz o papel do kernel HTTP do Laravel: monta a requisição (com o middleware
global), roda o middleware da rota como `Depends`, resolve o controller e seus
parâmetros (FormRequest, model por binding implícito, valores da rota), converte
o retorno e entrega toda exceção ao Handler do app.
"""
from __future__ import annotations

import sys
import traceback

from . import auth as _auth
from . import contexto, http, php
from .eloquent import Model, ModelNotFoundException
from .suporte import Arr, Base
from .validacao import ValidationException

SENTINELA = object()

# Middleware de framework que o runtime cobre (efeito igual ou já feito em outro lugar).
MIDDLEWARE_FRAMEWORK = {
    "Illuminate\\Auth\\Middleware\\Authenticate": _auth.Authenticate,
    "Illuminate\\Routing\\Middleware\\ThrottleRequests": _auth.ThrottleRequests,
    "Illuminate\\Routing\\Middleware\\SubstituteBindings": _auth.SemEfeito,
}
GLOBAIS_SEM_EFEITO = {
    "Illuminate\\Http\\Middleware\\HandleCors", "Illuminate\\Http\\Middleware\\TrustProxies",
    "Illuminate\\Foundation\\Http\\Middleware\\ValidatePostSize",
    "Illuminate\\Foundation\\Http\\Middleware\\PreventRequestsDuringMaintenance",
    "Illuminate\\Http\\Middleware\\TrustHosts", "Fruitcake\\Cors\\HandleCors",
}
TRIM = "Illuminate\\Foundation\\Http\\Middleware\\TrimStrings"
VAZIO = "Illuminate\\Foundation\\Http\\Middleware\\ConvertEmptyStringsToNull"


class ExceptionHandler(Base):
    """Illuminate\\Foundation\\Exceptions\\Handler: guarda os `renderable` do app."""

    _fqcn = "Illuminate\\Foundation\\Exceptions\\Handler"
    p_dontReport: list = []
    p_dontFlash: list = []
    p_levels: dict = {}

    def _construct(self, container=None):
        self.callbacks = []

    def register(self):
        return None

    def renderable(self, fn):
        self.callbacks.append(fn)
        return self

    def reportable(self, fn):
        return _Reportavel()

    def report(self, e):
        return None


class _Reportavel(Base):
    def stop(self):
        return self


class Aplicacao:
    def __init__(self, dados: dict, config: dict):
        self.dados = dados
        self.config_fontes = config
        self.config: dict = {}
        self.config_lida: set = set()
        self.traducoes = dados.get("traducoes", {})
        self.politicas = dict(dados.get("politicas", {}))
        self.criadores_guarda: dict = {}
        self.habilidades: dict = {}
        self.limitadores: dict = {}
        self.container = _auth.Container()
        self.handler = None
        self.avisos: list[str] = []
        mw = dados.get("middleware", {})
        self.grupos = mw.get("grupos") or {}
        self.apelidos = mw.get("apelidos") or {}
        self.globais = mw.get("global") or []
        self.excecoes = {}
        contexto.definir_aplicacao(self)

    # -------- config
    def _carregar(self, arquivo):
        if arquivo in self.config_lida:
            return
        self.config_lida.add(arquivo)
        fonte = self.config_fontes.get(arquivo)
        if fonte is None:
            return
        try:
            self.config[arquivo] = fonte()
        except Exception as e:  # noqa: BLE001 - config com trecho não traduzido não derruba o resto
            self.avisos.append(f"config/{arquivo}.php: {e}")
            self.config[arquivo] = {}

    def config_ler(self, chave, padrao=None):
        arquivo = php.to_str(chave).split(".")[0]
        self._carregar(arquivo)
        v = Arr.get(self.config, chave, php.PADRAO)
        if v is php.PADRAO:
            return padrao() if callable(padrao) else padrao
        return v

    def config_definir(self, chave, valor):
        self._carregar(php.to_str(chave).split(".")[0])
        Arr.set(self.config, chave, valor)

    # -------- partida
    def iniciar(self):
        if php.existe_classe("App\\Exceptions\\Handler"):
            self.handler = php.classe("App\\Exceptions\\Handler")(self.container)
        else:
            self.handler = ExceptionHandler(self.container)
        try:
            self.handler.register()
        except Exception as e:  # noqa: BLE001
            self.avisos.append(f"Handler::register: {e}")
        provedores = []
        for nome in php.valores(self.config_ler("app.providers", [])):
            if isinstance(nome, str) and php.existe_classe(nome) and not nome.startswith("Illuminate\\"):
                try:
                    p = php.classe(nome)(self.container)
                    p.register()
                    provedores.append(p)
                except Exception as e:  # noqa: BLE001
                    self.avisos.append(f"{nome}::register: {e}")
        for p in provedores:
            try:
                p.boot()
            except Exception as e:  # noqa: BLE001
                self.avisos.append(f"{php.fqcn(p)}::boot: {e}")
        for nome in self.globais:
            if nome in GLOBAIS_SEM_EFEITO:
                continue
            cls = php.classe(nome) if php.existe_classe(nome) else None
            bases = [getattr(c, "_fqcn", "") for c in cls.__mro__] if cls else [nome]
            if TRIM in bases or nome == TRIM:
                self.excecoes["trim"] = set(php.valores(getattr(cls, "p_except", []) or [])) if cls else set()
            elif VAZIO in bases or nome == VAZIO:
                self.excecoes["vazio"] = True
            elif cls is not None and issubclass(cls, _auth.SemEfeito):
                continue
            else:
                self.avisos.append(f"middleware global sem tradução: {nome}")
        for a in self.avisos:
            print(f"[laravel_compat] aviso: {a}", file=sys.stderr)

    # -------- container
    def resolver(self, nome):
        if nome in ("Illuminate\\Http\\Request", "Request"):
            return contexto.requisicao()
        if nome in ("Illuminate\\Contracts\\Foundation\\Application", "Illuminate\\Foundation\\Application"):
            return self.container
        if not php.existe_classe(nome):
            raise php.Pendencia(f"injeção de {nome}")
        cls = php.classe(nome)
        if issubclass(cls, http.FormRequest):
            fr = cls.copiar(contexto.requisicao())
            fr.validar()
            return fr
        params = getattr(cls, "__params__", {}).get("_construct", [])
        args = []
        for p in params:
            if p.get("tipo") and p["tipo"] not in php_escalares:
                args.append(self.resolver(p["tipo"]))
            elif "padrao" in p:
                break
            else:
                raise php.Pendencia(f"construtor de {nome} pede {p['nome']}")
        return cls(*args)

    # -------- rota
    def executar(self, rota: dict, req: http.Request, valores: dict):
        req.rota_params = dict(valores)
        req.rota_meta = rota
        acao = rota["acao"]
        if acao.get("tipo") != "controller":
            raise php.Pendencia(f"rota com ação {acao.get('tipo')}")
        ctrl = self.resolver(acao["classe"])
        nome_m = acao["metodo"]
        metodo = getattr(ctrl, nome_python(nome_m), None)
        if metodo is None:
            raise php.Pendencia(f"método {acao['classe']}::{nome_m}")
        params = metadados_params(type(ctrl), nome_m)
        args = self._argumentos(params, rota, valores)
        return http.para_resposta(metodo(*args))

    def _argumentos(self, params, rota, valores):
        fila = []
        for p in rota.get("parametros", []):
            if p["nome"] in valores:
                fila.append((p["nome"], valores[p["nome"]]))
        args = []
        for p in params:
            tipo = p.get("tipo")
            if tipo and tipo not in php_escalares:
                cls = php.classe(tipo) if php.existe_classe(tipo) else None
                if cls is not None and issubclass(cls, Model):
                    nome_rota = p["nome"]
                    par = next((x for x in fila if x[0] == nome_rota), None)
                    if par is not None:
                        fila.remove(par)
                        modelo = cls()
                        achado = cls.query().where(modelo.getRouteKeyName(), par[1]).first()
                        if achado is None:
                            raise ModelNotFoundException().setModel(cls._fqcn, [par[1]])
                        args.append(achado)
                        continue
                args.append(self.resolver(tipo))
            elif fila:
                v = fila.pop(0)[1]
                if tipo in ("int", "integer"):
                    if not php.is_numeric(v):
                        raise php.TypeError_("Argument must be of type int, string given")
                    v = php.to_int(v)
                args.append(v)
            elif "padrao" in p:
                break
        return args

    # -------- middleware de rota
    def expandir(self, nomes):
        for n in nomes:
            if n in self.grupos:
                yield from self.expandir(self.grupos[n])
            else:
                yield n

    def rodar_middleware(self, rota, req):
        for item in self.expandir(rota.get("middleware", [])):
            nome, _, params = item.partition(":")
            alvo = self.apelidos.get(nome, nome)
            params = params.split(",") if params else []
            if php.existe_classe(alvo):
                inst = php.classe(alvo)()
            elif alvo in MIDDLEWARE_FRAMEWORK:
                inst = MIDDLEWARE_FRAMEWORK[alvo]()
            else:
                raise php.Pendencia(f"middleware {item}")
            r = inst.handle(req, lambda _r: SENTINELA, *params)
            if r is not SENTINELA:
                raise http.HttpResponseException(r)

    # -------- exceções
    def renderizar(self, req, e) -> http.Response:
        if isinstance(e, php.Pendencia):
            return http.JsonResponse({"message": str(e)}, 501)
        try:
            return self._renderizar(req, e)
        except Exception as erro:  # noqa: BLE001 - o próprio Handler falhou: 500, como o PHP
            traceback.print_exception(erro, file=sys.stderr)
            return http.JsonResponse({"message": "Server Error"}, 500)

    def _renderizar(self, req, e):
        if hasattr(e, "render") and callable(e.render):
            r = e.render(req)
            if r is not None and r is not False:
                return http.para_resposta(r)
        if isinstance(e, ModelNotFoundException):
            e = http.NotFoundHttpException(e.getMessage(), e)
        elif isinstance(e, _auth.AuthorizationException):
            e = http.AccessDeniedHttpException(e.getMessage(), e)
        for fn in getattr(self.handler, "callbacks", []):
            tipos = getattr(fn, "__tipos__", None) or []
            if not tipos or any(php.instanceof(e, t) for t in tipos):
                r = fn(e, req)
                if r is not None:
                    return http.para_resposta(r)
        quer_json = req is None or req.expectsJson()
        if isinstance(e, http.HttpResponseException):
            return http.para_resposta(e.getResponse())
        if isinstance(e, _auth.AuthenticationException):
            if quer_json:
                return http.JsonResponse({"message": e.getMessage()}, 401)
            return http.Response("", 302, {"Location": php.to_str(e.redirect)})
        if isinstance(e, ValidationException):
            return http.JsonResponse({"message": e.getMessage(), "errors": e.errors()}, e.status)
        if isinstance(e, http.HttpException):
            if quer_json:
                return http.JsonResponse({"message": e.getMessage()}, e.getStatusCode(), e.getHeaders())
            return http.Response(e.getMessage(), e.getStatusCode(), e.getHeaders())
        traceback.print_exception(e, file=sys.stderr)
        if quer_json:
            return http.JsonResponse({"message": "Server Error"}, 500)
        return http.Response("Server Error", 500)


php_escalares = {"string", "int", "integer", "float", "bool", "boolean", "array", "mixed", "callable", "iterable",
                 "object", "null", "false", "true", None}

PALAVRAS = {"False", "None", "True", "and", "as", "assert", "async", "await", "break", "class", "continue", "def",
            "del", "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in", "is",
            "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
            "match", "case", "type", "print"}


def nome_python(nome: str) -> str:
    """Método PHP com nome de palavra reservada do Python ganha `_` no fim."""
    if nome == "__construct":
        return "_construct"
    return nome + "_" if nome in PALAVRAS else nome


def metadados_params(cls, metodo):
    for c in cls.__mro__:
        p = c.__dict__.get("__params__", {})
        if metodo in p:
            return p[metodo]
    return []
