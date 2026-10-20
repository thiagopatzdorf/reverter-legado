"""Estado por requisição (o que no Laravel mora no container durante um request)."""
from __future__ import annotations

import contextvars

_app = None
_req: contextvars.ContextVar = contextvars.ContextVar("lf_requisicao", default=None)


def definir_aplicacao(app) -> None:
    global _app
    _app = app


def aplicacao():
    if _app is None:
        raise RuntimeError("aplicação não montada")
    return _app


def requisicao():
    return _req.get()


def definir_requisicao(r):
    return _req.set(r)


def restaurar(token) -> None:
    _req.reset(token)
