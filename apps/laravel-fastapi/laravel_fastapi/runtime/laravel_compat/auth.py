"""Auth, Gate, providers e os middlewares de rota (auth, throttle) do Laravel 9.

Guarda customizada (`Auth::extend('jwt', ...)` num ServiceProvider do app) roda
traduzida: o runtime só faz o papel do container, como o Laravel faz. Por isso o
JWT caseiro de um app vira código Python sem ninguém reescrevê-lo à mão.
"""
from __future__ import annotations

import time

from . import contexto, php
from .eloquent import Model
from .suporte import Base, Hash, config


class AuthenticationException(php.PHPException):
    _fqcn = "Illuminate\\Auth\\AuthenticationException"

    def __init__(self, message="Unauthenticated.", guards=None, redirectTo=None):
        super().__init__(message)
        self.guards = guards or []
        self.redirect = redirectTo

    def guards_(self):
        return self.guards


class AuthorizationException(php.PHPException):
    _fqcn = "Illuminate\\Auth\\Access\\AuthorizationException"

    def __init__(self, message=None, code=0, previous=None):
        super().__init__(message or "This action is unauthorized.", code, previous)


# --------------------------------------------------------------------------- usuários
class Authenticatable(Model):
    _fqcn = "Illuminate\\Foundation\\Auth\\User"
    p_rememberTokenName = "remember_token"

    def getAuthIdentifierName(self):
        return self.getKeyName()

    def getAuthIdentifier(self):
        return self.getKey()

    def getAuthPassword(self):
        return self.getAttribute("password")

    def can(self, habilidade, argumentos=None):
        return Gate.forUser(self).allows(habilidade, argumentos or [])

    def cannot(self, habilidade, argumentos=None):
        return not self.can(habilidade, argumentos)


class EloquentUserProvider(Base):
    _fqcn = "Illuminate\\Auth\\EloquentUserProvider"

    def _construct(self, hasher=None, modelo=None):
        self.modelo = php.classe(modelo)

    def retrieveById(self, id_):
        return self.modelo.query().whereKey(id_).first()

    def retrieveByCredentials(self, credenciais):
        filtradas = {k: v for k, v in php.itens(credenciais) if "password" not in str(k)}
        if not filtradas:
            return None
        consulta = self.modelo.query()
        for k, v in filtradas.items():
            if isinstance(v, (list, dict)):
                consulta.whereIn(k, v)
            else:
                consulta.where(k, v)
        return consulta.first()

    def validateCredentials(self, usuario, credenciais):
        return Hash.check(php.idx(credenciais, "password"), usuario.getAuthPassword())

    def getModel(self):
        return self.modelo._fqcn


class GuardHelpers(Base):
    """Trait Illuminate\\Auth\\GuardHelpers: guarda o usuário em `$this->user`."""

    _fqcn = "Illuminate\\Auth\\GuardHelpers"
    p_user = None
    p_provider = None

    def authenticate(self):
        u = self.user()
        if u is None:
            raise AuthenticationException()
        return u

    def hasUser(self):
        return self.p_user is not None

    def check(self):
        return self.user() is not None

    def guest(self):
        return not self.check()

    def id(self):
        u = self.user()
        return u.getAuthIdentifier() if u is not None else None

    def setUser(self, usuario):
        self.p_user = usuario
        return self

    def forgetUser(self):
        self.p_user = None
        return self

    def getProvider(self):
        return self.p_provider

    def setProvider(self, p):
        self.p_provider = p


class SessionGuard(GuardHelpers):
    _fqcn = "Illuminate\\Auth\\SessionGuard"

    def _construct(self, nome, provedor, sessao=None, requisicao=None):
        self.nome = nome
        self.p_provider = provedor
        self.p_user = None

    def user(self):
        return self.p_user

    def validate(self, credenciais=None):
        u = self.p_provider.retrieveByCredentials(credenciais or {})
        return u is not None and self.p_provider.validateCredentials(u, credenciais)

    def attempt(self, credenciais=None, lembrar=False):
        credenciais = credenciais or {}
        u = self.p_provider.retrieveByCredentials(credenciais)
        if u is not None and self.p_provider.validateCredentials(u, credenciais):
            self.login(u, lembrar)
            return True
        return False

    def login(self, usuario, lembrar=False):
        self.setUser(usuario)

    def loginUsingId(self, id_, lembrar=False):
        u = self.p_provider.retrieveById(id_)
        if u is not None:
            self.login(u)
        return u or False

    def logout(self):
        self.p_user = None


class TokenGuard(GuardHelpers):
    _fqcn = "Illuminate\\Auth\\TokenGuard"

    def _construct(self, provedor, requisicao, chave_entrada="api_token", chave_banco="api_token", hash_=False):
        self.p_provider, self.req, self.entrada, self.banco = provedor, requisicao, chave_entrada, chave_banco

    def user(self):
        if self.p_user is not None:
            return self.p_user
        t = self.req.query(self.entrada) or self.req.input(self.entrada) or self.req.bearerToken()
        if t:
            self.p_user = self.p_provider.retrieveByCredentials({self.banco: t})
        return self.p_user


# --------------------------------------------------------------------------- AuthManager
class AuthManager(Base):
    _fqcn = "Illuminate\\Auth\\AuthManager"

    def _construct(self, requisicao):
        self.req = requisicao
        self.guardas = {}
        self.padrao = None

    def nome_padrao(self):
        return self.padrao or config("auth.defaults.guard")

    def guard(self, nome=None):
        nome = nome or self.nome_padrao()
        if nome not in self.guardas:
            self.guardas[nome] = self.criar(nome)
        return self.guardas[nome]

    def criar(self, nome):
        cfg = config(f"auth.guards.{nome}")
        if not isinstance(cfg, dict):
            raise php.InvalidArgumentException(f"Auth guard [{nome}] is not defined.")
        driver = cfg.get("driver")
        app = contexto.aplicacao()
        if driver in app.criadores_guarda:
            return app.criadores_guarda[driver](app.container, nome, cfg)
        if driver == "session":
            return SessionGuard(nome, self.createUserProvider(cfg.get("provider")))
        if driver == "token":
            return TokenGuard(self.createUserProvider(cfg.get("provider")), self.req, cfg.get("input_key", "api_token"),
                              cfg.get("storage_key", "api_token"))
        raise php.Pendencia(f"guarda de auth com driver {driver}")

    def createUserProvider(self, nome=None):
        nome = nome or config("auth.defaults.provider")
        cfg = config(f"auth.providers.{nome}")
        if not isinstance(cfg, dict):
            return None
        if cfg.get("driver") == "eloquent":
            return EloquentUserProvider(None, cfg.get("model"))
        raise php.Pendencia(f"provider de auth {cfg.get('driver')}")

    def shouldUse(self, nome):
        self.padrao = nome or self.nome_padrao()

    def extend(self, driver, criador):
        contexto.aplicacao().criadores_guarda[driver] = criador
        return self

    def __getattr__(self, nome):
        if nome.startswith("_"):
            raise AttributeError(nome)
        return getattr(self.guard(), nome)


def gerente(requisicao=None) -> AuthManager:
    req = requisicao or contexto.requisicao()
    if req is None:
        return AuthManager(None)
    if getattr(req, "auth", None) is None:
        alvo = getattr(req, "original", None) or req
        if getattr(alvo, "auth", None) is None:
            alvo.auth = AuthManager(alvo)
        req.auth = alvo.auth
    return req.auth


class _MetaFachada(type):
    def __getattr__(cls, nome):
        if nome.startswith("_"):
            raise AttributeError(nome)
        return getattr(cls.alvo(), nome)


class Auth(Base, metaclass=_MetaFachada):
    """Fachada Auth: estática no PHP, aqui encaminha para o AuthManager da requisição."""

    _fqcn = "Illuminate\\Support\\Facades\\Auth"

    @staticmethod
    def alvo():
        return gerente()

    @staticmethod
    def extend(driver, criador):
        contexto.aplicacao().criadores_guarda[driver] = criador

    @staticmethod
    def createUserProvider(nome=None):
        return AuthManager(None).createUserProvider(nome)


def auth(guarda=None):
    g = gerente()
    return g if guarda is None else g.guard(guarda)


# --------------------------------------------------------------------------- Gate
class Response_(Base):
    _fqcn = "Illuminate\\Auth\\Access\\Response"


class GateImpl(Base):
    def _construct(self, usuario_fn=None):
        self.usuario_fn = usuario_fn

    def _usuario(self):
        return self.usuario_fn() if self.usuario_fn else gerente().guard().user()

    def _politica(self, alvo):
        app = contexto.aplicacao()
        nome = alvo if isinstance(alvo, str) else php.fqcn(alvo)
        pol = app.politicas.get(nome)
        if pol is None and "\\Models\\" in nome:
            candidato = nome.replace("\\Models\\", "\\Policies\\") + "Policy"
            pol = candidato if php.existe_classe(candidato) else None
        return php.classe(pol)() if pol else None

    def inspect(self, habilidade, argumentos=None):
        args = argumentos if isinstance(argumentos, list) else ([argumentos] if argumentos is not None else [])
        usuario = self._usuario()
        app = contexto.aplicacao()
        if habilidade in app.habilidades:
            if usuario is None:
                return False
            return php.truthy(app.habilidades[habilidade](usuario, *args))
        pol = self._politica(args[0]) if args else None
        if pol is None:
            return False
        if hasattr(pol, "before"):
            r = pol.before(usuario, habilidade)
            if r is not None:
                return php.truthy(r)
        metodo = getattr(pol, habilidade, None)
        if metodo is None or usuario is None:
            return False
        alvo = args[0] if not isinstance(args[0], str) else None
        resto = args[1:]
        return php.truthy(metodo(usuario, alvo, *resto) if alvo is not None else metodo(usuario, *resto))

    def allows(self, habilidade, argumentos=None):
        return self.inspect(habilidade, argumentos)

    def denies(self, habilidade, argumentos=None):
        return not self.inspect(habilidade, argumentos)

    def check(self, habilidade, argumentos=None):
        return self.inspect(habilidade, argumentos)

    def authorize(self, habilidade, argumentos=None):
        if not self.inspect(habilidade, argumentos):
            raise AuthorizationException()
        return True

    def forUser(self, usuario):
        return GateImpl(lambda: usuario)

    def define(self, habilidade, fn):
        contexto.aplicacao().habilidades[habilidade] = fn
        return self

    def policy(self, modelo, politica):
        contexto.aplicacao().politicas[modelo] = politica
        return self


class Gate(Base, metaclass=_MetaFachada):
    _fqcn = "Illuminate\\Support\\Facades\\Gate"

    @staticmethod
    def alvo():
        return GateImpl()


class HandlesAuthorization(Base):
    _fqcn = "Illuminate\\Auth\\Access\\HandlesAuthorization"

    def allow(self, mensagem=None):
        return True

    def deny(self, mensagem=None):
        raise AuthorizationException(mensagem)


# --------------------------------------------------------------------------- providers e container
class Container(Base):
    _fqcn = "Illuminate\\Foundation\\Application"

    def offsetGet(self, chave):
        if chave == "request":
            return contexto.requisicao()
        if chave == "config":
            return contexto.aplicacao().config
        if chave == "auth":
            return gerente()
        return self.make(chave)

    def make(self, nome, parametros=None):
        return contexto.aplicacao().resolver(nome)

    def environment(self, *nomes):
        env = config("app.env")
        return env in nomes if nomes else env

    def runningInConsole(self):
        return False


class ServiceProvider(Base):
    _fqcn = "Illuminate\\Support\\ServiceProvider"

    def _construct(self, app=None):
        self.p_app = app

    def register(self):
        return None

    def boot(self):
        return None


class AuthServiceProvider(ServiceProvider):
    _fqcn = "Illuminate\\Foundation\\Support\\Providers\\AuthServiceProvider"
    p_policies: dict = {}

    def registerPolicies(self):
        for modelo, politica in php.itens(self.p_policies):
            contexto.aplicacao().politicas[modelo] = politica


class RouteServiceProvider(ServiceProvider):
    _fqcn = "Illuminate\\Foundation\\Support\\Providers\\RouteServiceProvider"

    def routes(self, fn):
        # As rotas já foram geradas a partir do contrato; aqui não se registra nada.
        return self


class EventServiceProvider(ServiceProvider):
    _fqcn = "Illuminate\\Foundation\\Support\\Providers\\EventServiceProvider"


# --------------------------------------------------------------------------- limites (throttle)
class Limit(Base):
    _fqcn = "Illuminate\\Cache\\RateLimiting\\Limit"

    def _construct(self, chave="", maximo=60, decaimento=1):
        self.chave, self.maximo, self.decaimento = chave, maximo, decaimento

    @classmethod
    def perMinute(cls, n):
        return cls("", n, 1)

    @classmethod
    def perMinutes(cls, decaimento, n):
        return cls("", n, decaimento)

    @classmethod
    def perHour(cls, n, decaimento=1):
        return cls("", n, 60 * decaimento)

    @classmethod
    def perDay(cls, n, decaimento=1):
        return cls("", n, 1440 * decaimento)

    @classmethod
    def none(cls):
        return cls("", None, 1)

    def by(self, chave):
        self.chave = chave
        return self

    def response(self, fn):
        return self


class RateLimiterImpl(Base):
    def for_(self, nome, fn):
        contexto.aplicacao().limitadores[nome] = fn
        return self

    def limiter(self, nome):
        return contexto.aplicacao().limitadores.get(nome)


class RateLimiter(Base, metaclass=_MetaFachada):
    _fqcn = "Illuminate\\Support\\Facades\\RateLimiter"

    @staticmethod
    def alvo():
        return RateLimiterImpl()


_batidas: dict = {}


def _bater(chave, maximo, decaimento_min) -> bool:
    agora = time.time()
    ini, n = _batidas.get(chave, (agora, 0))
    if agora - ini >= decaimento_min * 60:
        ini, n = agora, 0
    n += 1
    _batidas[chave] = (ini, n)
    return n <= maximo


class Middleware(Base):
    def handle(self, requisicao, proximo, *params):
        return proximo(requisicao)


class Authenticate(Middleware):
    _fqcn = "Illuminate\\Auth\\Middleware\\Authenticate"

    def handle(self, requisicao, proximo, *guardas):
        self.authenticate(requisicao, list(guardas))
        return proximo(requisicao)

    def authenticate(self, requisicao, guardas):
        g = gerente(requisicao)
        for nome in guardas or [None]:
            if g.guard(nome).check():
                g.shouldUse(nome)
                return None
        self.unauthenticated(requisicao, guardas)

    def unauthenticated(self, requisicao, guardas):
        destino = None if requisicao.expectsJson() else self.redirectTo(requisicao)
        raise AuthenticationException("Unauthenticated.", guardas, destino)

    def redirectTo(self, requisicao):
        return None


class ThrottleRequests(Middleware):
    _fqcn = "Illuminate\\Routing\\Middleware\\ThrottleRequests"

    def handle(self, requisicao, proximo, maximo=60, decaimento=1, prefixo=""):
        app = contexto.aplicacao()
        fn = app.limitadores.get(maximo) if isinstance(maximo, str) and not maximo.isdigit() else None
        if fn is not None:
            limites = fn(requisicao)
            limites = limites if isinstance(limites, list) else [limites]
            for lim in limites:
                if not isinstance(lim, Limit) or lim.maximo is None:
                    continue
                if not _bater(php.md5(php.to_str(maximo) + php.to_str(lim.chave)), lim.maximo, lim.decaimento):
                    from .http import ThrottleRequestsException

                    raise ThrottleRequestsException(None, "Too Many Attempts.")
        else:
            chave = php.sha1(requisicao.ip())
            if not _bater(prefixo + chave, php.to_int(maximo), php.to_int(decaimento)):
                from .http import ThrottleRequestsException

                raise ThrottleRequestsException(None, "Too Many Attempts.")
        return proximo(requisicao)


class SemEfeito(Middleware):
    """Middleware cujo efeito o runtime já faz ou que não muda a resposta da API."""


class TrimStrings(SemEfeito):
    """O efeito (aparar texto da entrada) é aplicado quando a requisição é montada."""

    _fqcn = "Illuminate\\Foundation\\Http\\Middleware\\TrimStrings"
    p_except: list = []


class ConvertEmptyStringsToNull(SemEfeito):
    _fqcn = "Illuminate\\Foundation\\Http\\Middleware\\ConvertEmptyStringsToNull"


def sem_efeito(fq: str):
    """Uma classe por middleware de framework sem efeito: herdar dela mantém o nome certo."""
    return type(fq.rsplit("\\", 1)[-1], (SemEfeito,), {"_fqcn": fq, "p_except": [], "p_headers": None, "p_proxies": None})
