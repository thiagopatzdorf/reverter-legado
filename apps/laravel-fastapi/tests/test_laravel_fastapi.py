"""Testes do conversor Laravel -> FastAPI, com o app `fixtures/mini` (escrito para isto).

Cada nome diz a falha que o teste pega.
"""
from __future__ import annotations

import importlib
import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from laravel_fastapi import contrato, diferencial, gerar  # noqa: E402

MINI = Path(__file__).resolve().parent / "fixtures" / "mini"


@pytest.fixture(scope="module")
def contrato_mini():
    return json.loads(contrato.serializar(contrato.extrair(MINI)))


# --------------------------------------------------------------------------- contrato
def test_contrato_muda_de_bytes_entre_duas_extracoes_iguais():
    a = contrato.serializar(contrato.extrair(MINI))
    b = contrato.serializar(contrato.extrair(MINI))
    assert a == b
    assert str(MINI) not in a, "caminho absoluto vazou para o contrato"


def test_rota_perde_prefixo_ou_middleware_do_route_service_provider(contrato_mini):
    rotas = {(r["metodos"][0], r["caminho"]): r for r in contrato_mini["rotas"]}
    assert ("GET", "/api/posts/{id}") in rotas
    r = rotas[("GET", "/api/posts/{id}")]
    assert r["middleware"] == ["api"]
    assert r["parametros"] == [{"nome": "id", "opcional": False}]
    assert r["acao"] == {"tipo": "controller", "classe": "App\\Http\\Controllers\\PostController", "metodo": "show"}


def test_rota_de_closure_some_do_contrato_em_vez_de_virar_pendencia(contrato_mini):
    assert any(p["tipo"] == "rota_closure" and "/api/ping" in p["onde"] for p in contrato_mini["pendencias"])


def test_sql_cru_evento_e_job_passam_sem_pendencia(contrato_mini):
    tipos = {p["tipo"] for p in contrato_mini["pendencias"] if "PostController::relatorio" in p["onde"]}
    assert {"sql_cru", "evento", "job"} <= tipos


def test_migration_perde_tipo_nulo_unico_ou_chave_estrangeira(contrato_mini):
    posts = {c["nome"]: c for c in contrato_mini["tabelas"]["posts"]["colunas"]}
    assert posts["author_id"]["ref"] == {"tabela": "authors", "coluna": "id", "ao_apagar": "cascade"}
    assert posts["body"]["nulo"] is True and posts["title"]["nulo"] is False
    autores = contrato_mini["tabelas"]["authors"]
    assert {c["nome"]: c for c in autores["colunas"]}["name"]["tamanho"] == 80
    assert ["name"] in autores["unicos"]


def test_model_perde_tabela_fillable_hidden_ou_relacao(contrato_mini):
    autor = contrato_mini["models"]["App\\Models\\Author"]
    assert autor["tabela"] == "authors" and autor["hidden"] == ["password"]
    assert {(r["nome"], r["tipo"]) for r in autor["relacoes"]} == {("posts", "hasMany")}


def test_regra_literal_de_formrequest_fica_fora_do_contrato(contrato_mini):
    regras = contrato_mini["validacoes"]["App\\Http\\Requests\\StorePostRequest"]["regras"]
    assert regras["title"] == ["required", "string", "max:20"]


def test_data_do_eloquent_e_senha_com_hash_nao_sao_marcadas_volateis(contrato_mini):
    assert {"created_at", "updated_at", "password"} <= set(contrato_mini["volateis"]["colunas"])
    assert "createdAt" in contrato_mini["volateis"]["resposta"]


def test_verificar_aceita_contrato_editado_a_mao(contrato_mini):
    editado = json.loads(json.dumps(contrato_mini))
    editado["rotas"][0]["caminho"] = "/api/outra"
    erros = contrato.verificar(editado, MINI)
    assert any("rotas" in e for e in erros)
    assert contrato.verificar(contrato_mini, MINI) == []


# --------------------------------------------------------------------------- gerador + app gerado
@pytest.fixture(scope="module")
def app_gerado(contrato_mini, tmp_path_factory):
    pasta = tmp_path_factory.mktemp("gerado")
    cob = gerar.gerar(contrato_mini, pasta)
    banco = pasta / "banco.sqlite"
    import sqlalchemy as sa

    sys.path.insert(0, str(pasta))
    try:
        modelos = importlib.import_module("modelos")
        modelos.metadata.create_all(sa.create_engine(f"sqlite:///{banco}"))
        con = sqlite3.connect(banco)
        con.execute("insert into authors (id, name, password, created_at, updated_at) values "
                    "(1, 'Ana', 'x', '2026-01-01 00:00:00', '2026-01-01 00:00:00')")
        con.execute("insert into posts (id, author_id, title, body, created_at, updated_at) values "
                    "(1, 1, 'Primeiro', 'b', '2026-01-02 00:00:00', '2026-01-02 00:00:00')")
        con.commit()
        con.close()
        import os

        os.environ["DATABASE_URL"] = f"sqlite:///{banco}"
        from laravel_compat import eloquent

        eloquent._motor = None
        main = importlib.import_module("main")
        from fastapi.testclient import TestClient

        yield cob, TestClient(main.app, raise_server_exceptions=False), banco
    finally:
        sys.path.remove(str(pasta))
        for m in ("main", "modelos", "rotas", "dados", "config_app", "app_traduzido", "validacoes"):
            sys.modules.pop(m, None)


H = {"Accept": "application/json"}


def test_gerador_marca_coberta_rota_com_funcao_sem_traducao(app_gerado):
    cob, _, _ = app_gerado
    por_rota = {r["rota"]: r for r in cob["por_rota"]}
    assert por_rota["GET /api/posts"]["coberta"] is True
    assert por_rota["GET /api/relatorio"]["coberta"] is False
    assert any(m.get("detalhe") == "algo_desconhecido" for m in por_rota["GET /api/relatorio"]["motivos"])
    assert por_rota["GET /api/ping"]["coberta"] is False


def test_app_gerado_nao_embrulha_recurso_com_o_wrap_do_laravel(app_gerado):
    _, cliente, _ = app_gerado
    r = cliente.get("/api/posts/1", headers=H)
    assert r.status_code == 200
    assert r.json() == {"post": {"id": 1, "title": "Primeiro", "author": "Ana", "createdAt": "2026-01-02T00:00:00.000000Z"}}


def test_422_sai_em_formato_diferente_do_laravel(app_gerado):
    _, cliente, _ = app_gerado
    r = cliente.post("/api/posts", json={"title": "  ", "author_id": "x"}, headers=H)
    assert r.status_code == 422
    assert r.json() == {
        "message": "The title field is required. (and 2 more errors)",
        "errors": {"title": ["The title field is required."], "body": ["The body field is required."],
                   "author_id": ["The author id must be an integer."]},
    }


def test_criacao_nao_responde_201_nem_grava_no_banco(app_gerado):
    _, cliente, banco = app_gerado
    r = cliente.post("/api/posts", json={"title": "Novo", "body": "texto", "author_id": 1}, headers=H)
    assert r.status_code == 201, r.text
    assert r.json()["post"]["title"] == "Novo"
    linhas = sqlite3.connect(banco).execute("select title, author_id from posts order by id").fetchall()
    assert linhas[-1] == ("Novo", 1)


def test_model_ausente_nao_vira_404_com_a_mensagem_do_laravel(app_gerado):
    _, cliente, _ = app_gerado
    r = cliente.get("/api/posts/99", headers=H)
    assert r.status_code == 404
    assert r.json() == {"message": "No query results for model [App\\Models\\Post] 99"}


def test_rota_nao_traduzida_responde_como_se_funcionasse(app_gerado):
    _, cliente, _ = app_gerado
    r = cliente.get("/api/relatorio", headers=H)
    assert r.status_code == 501
    assert "pendência" in r.json()["message"]


# --------------------------------------------------------------------------- runtime
def test_runtime_trata_string_numerica_e_zero_como_o_python():
    from laravel_compat import php

    assert php.eq("1", 1) and not php.ident("1", 1)
    assert not php.truthy("0") and php.truthy("0.0")
    assert php.concat("a", None, True, 2) == "a12"


def test_carbon_addseconds_nao_muta_o_objeto_como_no_php():
    from laravel_compat.suporte import Carbon

    agora = Carbon.now()
    antes = agora.getTimestamp()
    agora.addSeconds(60)
    assert agora.getTimestamp() == antes + 60


def test_str_slug_nao_tira_acento_como_o_laravel():
    from laravel_compat.suporte import Str

    assert Str.slug("Ação rápida em São Paulo") == "acao-rapida-em-sao-paulo"
    assert Str.slug("a_b @ c") == "a-b-at-c"


def test_json_encode_nao_escapa_barra_como_o_php():
    from laravel_compat import php

    assert php.json_encode({"u": "a/b", "s": "é"}) == '{"u":"a\\/b","s":"\\u00e9"}'


# --------------------------------------------------------------------------- diferencial
class _Servidor(BaseHTTPRequestHandler):
    respostas: dict = {}

    def _responder(self):
        status, corpo = self.respostas.get((self.command, self.path), (404, {"message": ""}))
        bruto = json.dumps(corpo).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    do_GET = do_POST = _responder

    def log_message(self, *a):
        pass


def _subir(respostas):
    cls = type("S", (_Servidor,), {"respostas": respostas})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _banco(caminho, nome):
    con = sqlite3.connect(caminho)
    con.execute("create table t (id integer primary key, nome text, created_at text)")
    con.execute("insert into t values (1, ?, ?)", (nome, "2026-01-01 00:00:00"))
    con.commit()
    con.close()


def test_diferencial_nao_acusa_status_corpo_e_banco_diferentes(tmp_path):
    a = _subir({("GET", "/x"): (200, {"v": 1, "createdAt": "2026-01-01T00:00:00.000000Z"}), ("POST", "/y"): (201, {})})
    b = _subir({("GET", "/x"): (200, {"v": 2, "createdAt": "2030-05-05T10:00:00.000000Z"}), ("POST", "/y"): (200, {})})
    _banco(tmp_path / "a.sqlite", "igual")
    _banco(tmp_path / "b.sqlite", "outro")
    cen = {"rotas": ["GET /x", "POST /y"], "passos": [
        {"id": 1, "rota": "GET /x", "metodo": "GET", "caminho": "/x"},
        {"id": 2, "rota": "POST /y", "metodo": "POST", "caminho": "/y", "corpo": {}},
    ]}
    try:
        res = diferencial.rodar(cen, {"resposta": ["createdAt"], "colunas": ["created_at"]},
                                {"base": f"http://127.0.0.1:{a.server_port}", "banco": str(tmp_path / "a.sqlite")},
                                {"base": f"http://127.0.0.1:{b.server_port}", "banco": str(tmp_path / "b.sqlite")}, pausa=0)
    finally:
        a.shutdown()
        b.shutdown()
    p1, p2 = res["por_passo"]
    assert any("$.v" in m for m in p1["motivos"])
    assert not any("createdAt" in m for m in p1["motivos"]), "campo volátil com formato de data não pode acusar"
    assert any(m.startswith("status 201 != 200") for m in p2["motivos"])
    assert any(m.startswith("banco t:") for m in p1["motivos"])
    assert res["endpoints_iguais"] == 0 and res["endpoints"] == 2


def test_diferencial_acusa_diferenca_quando_os_dois_lados_respondem_igual(tmp_path):
    resp = {("GET", "/x"): (200, {"v": 1})}
    a, b = _subir(resp), _subir(resp)
    _banco(tmp_path / "a.sqlite", "igual")
    _banco(tmp_path / "b.sqlite", "igual")
    cen = {"rotas": ["GET /x"], "passos": [{"id": 1, "rota": "GET /x", "metodo": "GET", "caminho": "/x"}]}
    try:
        res = diferencial.rodar(cen, {}, {"base": f"http://127.0.0.1:{a.server_port}", "banco": str(tmp_path / "a.sqlite")},
                                {"base": f"http://127.0.0.1:{b.server_port}", "banco": str(tmp_path / "b.sqlite")}, pausa=0)
    finally:
        a.shutdown()
        b.shutdown()
    assert res["endpoints_iguais"] == 1 and res["por_passo"][0]["motivos"] == []


def test_volatil_com_formato_diferente_passa_despercebido():
    assert diferencial.normalizar({"createdAt": "2026-01-01T00:00:00.000000Z"}, {"createdAt"}) == {"createdAt": "<data>"}
    assert diferencial.normalizar({"createdAt": "2026-01-01 00:00:00"}, {"createdAt"}) == {"createdAt": "<texto>"}


def test_cli_verificar_nao_sai_com_erro_quando_o_fonte_muda(tmp_path, contrato_mini):
    from laravel_fastapi.__main__ import main

    arquivo = tmp_path / "contrato.json"
    arquivo.write_text(contrato.serializar(contrato_mini), encoding="utf-8")
    assert main(["verificar", str(arquivo), str(MINI)]) == 0
    editado = json.loads(json.dumps(contrato_mini))
    editado["models"]["App\\Models\\Post"]["fillable"] = []
    arquivo.write_text(contrato.serializar(editado), encoding="utf-8")
    assert main(["verificar", str(arquivo), str(MINI)]) == 1
