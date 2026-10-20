"""laravel_compat: o pedaço do Laravel 9 que o código traduzido usa, em Python.

O gerador copia este pacote para dentro do app FastAPI gerado, então o app não
depende deste repositório para rodar. `CLASSES` e `FUNCOES` são o catálogo: o
gerador consulta os dois para saber o que tem tradução (e marca pendência no
que não tem), e o código traduzido chama `classe(...)`/`funcao(...)` por nome.
"""
from __future__ import annotations

from . import auth, contexto, eloquent, http, php, suporte, validacao
from .aplicacao import Aplicacao, ExceptionHandler, nome_python
from .suporte import Base

CLASSES = {
    "stdClass": Base,
    "Throwable": php.Throwable, "Exception": php.PHPException, "Error": php.Error,
    "InvalidArgumentException": php.InvalidArgumentException, "RuntimeException": php.RuntimeException,
    "LogicException": php.LogicException, "JsonException": php.JsonException, "TypeError": php.TypeError_,
    # Support
    "Illuminate\\Support\\Collection": suporte.Collection, "Illuminate\\Support\\Arr": suporte.Arr,
    "Illuminate\\Support\\Str": suporte.Str, "Illuminate\\Support\\Carbon": suporte.Carbon,
    "Carbon\\Carbon": suporte.Carbon, "Illuminate\\Support\\Facades\\Hash": suporte.Hash,
    "Illuminate\\Support\\Facades\\DB": eloquent.DB,
    # Eloquent
    "Illuminate\\Database\\Eloquent\\Model": eloquent.Model, "Illuminate\\Database\\Eloquent\\Builder": eloquent.Builder,
    "Illuminate\\Database\\Eloquent\\Collection": eloquent.EloquentCollection,
    "Illuminate\\Database\\Eloquent\\ModelNotFoundException": eloquent.ModelNotFoundException,
    "Illuminate\\Database\\Eloquent\\Relations\\Relation": eloquent.Relation,
    "Illuminate\\Database\\Eloquent\\Relations\\BelongsTo": eloquent.BelongsTo,
    "Illuminate\\Database\\Eloquent\\Relations\\HasMany": eloquent.HasMany,
    "Illuminate\\Database\\Eloquent\\Relations\\HasOne": eloquent.HasOne,
    "Illuminate\\Database\\Eloquent\\Relations\\BelongsToMany": eloquent.BelongsToMany,
    "Illuminate\\Database\\Eloquent\\MassAssignmentException": eloquent.MassAssignmentException,
    "Illuminate\\Database\\QueryException": eloquent.QueryException,
    "Illuminate\\Foundation\\Auth\\User": auth.Authenticatable,
    # HTTP
    "Illuminate\\Http\\Request": http.Request, "Illuminate\\Foundation\\Http\\FormRequest": http.FormRequest,
    "Illuminate\\Http\\Response": http.Response, "Illuminate\\Http\\JsonResponse": http.JsonResponse,
    "Illuminate\\Http\\Resources\\Json\\JsonResource": http.JsonResource,
    "Illuminate\\Http\\Resources\\Json\\ResourceCollection": http.ResourceCollection,
    "Illuminate\\Http\\Resources\\Json\\AnonymousResourceCollection": http.AnonymousResourceCollection,
    "Illuminate\\Http\\Resources\\MissingValue": http.MissingValue,
    "Illuminate\\Routing\\Controller": http.Controller,
    "Symfony\\Component\\HttpKernel\\Exception\\HttpException": http.HttpException,
    "Symfony\\Component\\HttpKernel\\Exception\\NotFoundHttpException": http.NotFoundHttpException,
    "Symfony\\Component\\HttpKernel\\Exception\\AccessDeniedHttpException": http.AccessDeniedHttpException,
    "Illuminate\\Http\\Exceptions\\HttpResponseException": http.HttpResponseException,
    "Illuminate\\Http\\Exceptions\\ThrottleRequestsException": http.ThrottleRequestsException,
    "Illuminate\\Foundation\\Exceptions\\Handler": ExceptionHandler,
    "Illuminate\\Support\\Facades\\Route": http.RouteFacade,
    "Illuminate\\Http\\RedirectResponse": http.RedirectResponse,
    "Symfony\\Component\\Routing\\Exception\\RouteNotFoundException": http.RouteNotFoundException,
    # Validação
    "Illuminate\\Validation\\Rule": validacao.Rule, "Illuminate\\Validation\\Rules\\Password": validacao.Password,
    "Illuminate\\Validation\\Rules\\Unique": validacao.Unique, "Illuminate\\Validation\\ValidationException": validacao.ValidationException,
    "Illuminate\\Support\\Facades\\Validator": validacao.ValidatorFacade,
    # Auth
    "Illuminate\\Support\\Facades\\Auth": auth.Auth, "Illuminate\\Support\\Facades\\Gate": auth.Gate,
    "Illuminate\\Auth\\GuardHelpers": auth.GuardHelpers, "Illuminate\\Auth\\AuthenticationException": auth.AuthenticationException,
    "Illuminate\\Auth\\Access\\AuthorizationException": auth.AuthorizationException,
    "Illuminate\\Auth\\Access\\HandlesAuthorization": auth.HandlesAuthorization,
    "Illuminate\\Auth\\Middleware\\Authenticate": auth.Authenticate,
    "Illuminate\\Routing\\Middleware\\ThrottleRequests": auth.ThrottleRequests,
    "Illuminate\\Support\\ServiceProvider": auth.ServiceProvider,
    "Illuminate\\Foundation\\Support\\Providers\\AuthServiceProvider": auth.AuthServiceProvider,
    "Illuminate\\Foundation\\Support\\Providers\\RouteServiceProvider": auth.RouteServiceProvider,
    "Illuminate\\Foundation\\Support\\Providers\\EventServiceProvider": auth.EventServiceProvider,
    "Illuminate\\Support\\Facades\\RateLimiter": auth.RateLimiter,
    "Illuminate\\Cache\\RateLimiting\\Limit": auth.Limit,
    "Illuminate\\Foundation\\Application": auth.Container,
}

# Traits e interfaces do framework que não mudam comportamento visível da API.
TRACOS_SEM_EFEITO = {
    "Illuminate\\Database\\Eloquent\\Factories\\HasFactory", "Illuminate\\Notifications\\Notifiable",
    "Illuminate\\Foundation\\Bus\\DispatchesJobs", "Illuminate\\Foundation\\Validation\\ValidatesRequests",
    "Illuminate\\Foundation\\Auth\\Access\\AuthorizesRequests", "Illuminate\\Bus\\Queueable",
    "Illuminate\\Queue\\SerializesModels", "Illuminate\\Foundation\\Events\\Dispatchable",
}
TRACOS = {"Illuminate\\Auth\\GuardHelpers": auth.GuardHelpers,
          "Illuminate\\Auth\\Access\\HandlesAuthorization": auth.HandlesAuthorization}

# Middleware de framework sem efeito na resposta da API (o runtime cobre ou não se aplica).
CLASSES["Illuminate\\Foundation\\Http\\Middleware\\TrimStrings"] = auth.TrimStrings
CLASSES["Illuminate\\Foundation\\Http\\Middleware\\ConvertEmptyStringsToNull"] = auth.ConvertEmptyStringsToNull
for _m in ("Illuminate\\Routing\\Middleware\\SubstituteBindings", "Illuminate\\Http\\Middleware\\HandleCors",
           "Illuminate\\Http\\Middleware\\TrustProxies", "Illuminate\\Foundation\\Http\\Middleware\\ValidatePostSize",
           "Illuminate\\Foundation\\Http\\Middleware\\PreventRequestsDuringMaintenance",
           "Illuminate\\Foundation\\Http\\Middleware\\TrimStrings",
           "Illuminate\\Foundation\\Http\\Middleware\\ConvertEmptyStringsToNull",
           "Illuminate\\Http\\Middleware\\TrustHosts", "Illuminate\\Cookie\\Middleware\\EncryptCookies",
           "Illuminate\\Foundation\\Http\\Middleware\\VerifyCsrfToken"):
    CLASSES.setdefault(_m, auth.sem_efeito(_m))
CLASSES["Illuminate\\Support\\Facades\\Facade"] = suporte.Facade

FUNCOES = {
    "collect": suporte.collect, "config": suporte.config, "env": suporte.env, "trans": suporte.trans,
    "__": suporte.__, "trans_choice": suporte.trans_choice, "now": suporte.now, "base_path": suporte.base_path,
    "value": suporte.value, "tap": suporte.tap, "blank": suporte.blank, "filled": suporte.filled,
    "data_get": suporte.data_get, "data_set": suporte.data_set, "optional": suporte.optional,
    "bcrypt": suporte.bcrypt_, "response": http.response, "abort": http.abort, "abort_if": http.abort_if,
    "abort_unless": http.abort_unless, "auth": auth.auth, "route": http.route, "redirect": http.redirect,
    "request": lambda chave=None, padrao=None: contexto.requisicao() if chave is None else contexto.requisicao().input(chave, padrao),
    "app": lambda nome=None: contexto.aplicacao().container if nome is None else contexto.aplicacao().resolver(nome),
    "class_basename": lambda c: php.fqcn(c).rsplit("\\", 1)[-1] if not isinstance(c, str) else c.rsplit("\\", 1)[-1],
    "logger": lambda *a, **k: None, "info": lambda *a, **k: None, "report": lambda *a, **k: None,
}


def classe(nome: str):
    """Classe por FQCN: do app (registrada) ou do framework (catálogo)."""
    chave = nome.lstrip("\\")
    if php.existe_classe(chave):
        return php.classe(chave)
    if chave in CLASSES:
        return CLASSES[chave]
    raise php.Pendencia(f"classe {chave}")


def funcao(nome: str):
    if nome in FUNCOES:
        return FUNCOES[nome]
    f = php.funcao(nome)
    if f is None:
        raise php.Pendencia(f"função {nome}()")
    return f


def tem_classe(nome: str) -> bool:
    return nome.lstrip("\\") in CLASSES


def tem_funcao(nome: str) -> bool:
    return nome in FUNCOES or php.funcao(nome) is not None


php.registrar(CLASSES)

__all__ = ["Aplicacao", "CLASSES", "FUNCOES", "TRACOS", "TRACOS_SEM_EFEITO", "classe", "funcao", "nome_python",
           "tem_classe", "tem_funcao", "php", "suporte", "eloquent", "http", "auth", "validacao", "contexto"]
