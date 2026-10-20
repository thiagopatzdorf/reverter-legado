"""Cola com o FastAPI: dependências (requisição, middleware de rota) e handlers de exceção."""
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi import Request as RequisicaoStarlette
from fastapi.responses import Response as RespostaStarlette
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import contexto, http, php


def _app():
    return contexto.aplicacao()


async def requisicao(request: RequisicaoStarlette) -> http.Request:
    """Monta o Illuminate\\Request uma vez por requisição, com o middleware global aplicado."""
    atual = getattr(request.state, "lv", None)
    if atual is not None:
        return atual
    corpo = await request.body()
    cliente = request.client.host if request.client else "127.0.0.1"
    req = http.Request(request.method, request.url.path, dict(request.query_params), dict(request.headers), corpo, cliente)
    req.limpar_entrada(_app().excecoes)
    request.state.lv = req
    contexto.definir_requisicao(req)
    return req


def middleware(rota: dict):
    """O middleware da rota (auth:api, throttle...) como dependência do FastAPI."""

    def dependencia(req: http.Request = Depends(requisicao)):
        contexto.definir_requisicao(req)
        _app().rodar_middleware(rota, req)
        return None

    dependencia.__name__ = "middleware_" + "_".join(m.replace(":", "_") for m in rota.get("middleware", [])) or "nenhum"
    return dependencia


def executar(rota: dict, req: http.Request, valores: dict) -> RespostaStarlette:
    contexto.definir_requisicao(req)
    resposta = _app().executar(rota, req, valores)
    return converter(resposta)


def converter(resposta: http.Response) -> RespostaStarlette:
    corpo, tipo = resposta.corpo()
    headers = {k: php.to_str(v) for k, v in resposta.headers.items() if k.lower() != "content-type"}
    return RespostaStarlette(content=corpo, status_code=resposta.status, headers=headers, media_type=tipo)


def _metodos_do_caminho(caminho: str) -> list:
    import re

    saida = []
    for r in _app().dados.get("rotas", []):
        padrao = "^" + re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(r["caminho"])) + "$"
        if re.match(padrao, caminho):
            saida += [m for m in r["metodos"] if m not in saida]
    return saida


def montar(app: FastAPI) -> None:
    async def tratar(request: RequisicaoStarlette, exc: Exception):
        req = getattr(request.state, "lv", None)
        return converter(_app().renderizar(req, exc))

    async def tratar_http(request: RequisicaoStarlette, exc: StarletteHTTPException):
        req = getattr(request.state, "lv", None)
        if req is None:
            req = http.Request(request.method, request.url.path, dict(request.query_params), dict(request.headers), b"")
        if exc.status_code == 405:
            # O Laravel lista os métodos na ordem em que a rota os declara (GET, HEAD), não na do Starlette.
            permitidos = _metodos_do_caminho(request.url.path)
            erro = http.MethodNotAllowedHttpException(
                permitidos, f"The {request.method} method is not supported for this route. Supported methods: {', '.join(permitidos)}.")
        elif exc.status_code == 404:
            # Laravel 9.17 (medido no caso RealWorld): rota inexistente responde {"message": ""}.
            erro = http.NotFoundHttpException("")
        else:
            erro = http.HttpException(exc.status_code, php.to_str(exc.detail))
        return converter(_app().renderizar(req, erro))

    app.add_exception_handler(php.Throwable, tratar)
    # Erro de Python (bug do runtime ou do código traduzido) também vira o 500 do Laravel.
    app.add_exception_handler(Exception, tratar)
    app.add_exception_handler(StarletteHTTPException, tratar_http)
