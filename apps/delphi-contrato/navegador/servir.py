"""Serve a pasta montada com os mesmos cabeçalhos do site (CSP do manifesto, tipos certos).

    python3 apps/delphi-contrato/navegador/servir.py <pasta montada> [--porta 8765]

Para conferir localmente e para o teste no Chromium. Só GET/HEAD: um POST recebe 405,
então até um defeito na página que tentasse enviar o arquivo daria erro visível.
"""
from __future__ import annotations

import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TIPOS = {".mjs": "text/javascript", ".js": "text/javascript", ".wasm": "application/wasm",
         ".json": "application/json", ".zip": "application/zip", ".exe": "application/octet-stream",
         ".css": "text/css", ".html": "text/html; charset=utf-8", ".py": "text/plain; charset=utf-8"}


class Pagina(SimpleHTTPRequestHandler):
    csp = ""
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, **TIPOS}

    def end_headers(self):
        self.send_header("Content-Security-Policy", self.csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        self.send_error(405)

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, *_):
        pass


def servidor(pasta: Path, porta: int = 0) -> ThreadingHTTPServer:
    manifesto = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    tratador = type("PaginaMontada", (Pagina,), {"csp": manifesto["csp"]})
    s = ThreadingHTTPServer(("127.0.0.1", porta), functools.partial(tratador, directory=str(pasta)))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("pasta", type=Path)
    a.add_argument("--porta", type=int, default=8765)
    x = a.parse_args()
    s = servidor(x.pasta, x.porta)
    print(f"http://127.0.0.1:{s.server_address[1]}/  (Ctrl+C para parar)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        s.shutdown()
