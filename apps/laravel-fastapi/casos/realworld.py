"""Caso real: a API RealWorld ("Conduit") em Laravel 9, de ponta a ponta.

App: https://github.com/f1amy/laravel-realworld-example-app (MIT), commit fixado
abaixo. É a implementação Laravel listada no codebase.show do projeto RealWorld:
19 rotas REST com auth por JWT caseiro, FormRequest, JsonResource, políticas e
relações muitos-para-muitos. A especificação da API é pública, o que deixa o
cenário do diferencial conferível por qualquer um.

    python3 apps/laravel-fastapi/casos/realworld.py semente   # escreve semente.sql
    python3 apps/laravel-fastapi/casos/realworld.py contrato --fonte <checkout> --saida <dir>
    python3 apps/laravel-fastapi/casos/realworld.py diferencial --laravel URL:banco --fastapi URL:banco \\
        --contrato contrato.json --saida resultado.json

O app Laravel e o FastAPI gerado rodam em containers descartáveis (receita em
casos/realworld/README.md); este script só fala HTTP e lê os dois SQLite.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

PRODUTO = {
    "nome": "laravel-realworld-example-app",
    "repo": "https://github.com/f1amy/laravel-realworld-example-app",
    "commit": "c14fb8370b71a42a3a74b8ea936a1f96b2af9d69",
    "licenca": "MIT",
    "laravel": "v9.17.0",
    "php": "8.1 (imagem php:8.1-cli)",
}

USUARIOS = [
    # id, usuário, e-mail, senha (dado de teste), bio, imagem, criado, sal fixo do bcrypt
    (1, "alice", "alice@exemplo.io", "senha-alice-1", "Escreve sobre PHP.", None, "2026-10-01 10:00:00", "abcdefghijklmnopqrstuu"),
    (2, "bruno", "bruno@exemplo.io", "senha-bruno-2", None, "https://exemplo.io/bruno.png", "2026-10-01 10:01:00", "bcdefghijklmnopqrstuvu"),
    (3, "carla", "carla@exemplo.io", "senha-carla-3", "Python e dados.", None, "2026-10-01 10:02:00", "cdefghijklmnopqrstuvwu"),
]
ARTIGOS = [
    (1, 1, "como-migrar-php", "Como migrar PHP", "Um roteiro curto", "Corpo do artigo um.", "2026-10-02 09:00:00"),
    (2, 2, "laravel-na-pratica", "Laravel na prática", "Exemplos reais", "Corpo do artigo dois.", "2026-10-03 09:00:00"),
    (3, 1, "contratos-de-api", "Contratos de API", "O que o legado promete", "Corpo do artigo três.", "2026-10-04 09:00:00"),
    (4, 3, "fastapi-do-zero", "FastAPI do zero", "Pydantic e rotas", "Corpo do artigo quatro.", "2026-10-05 09:00:00"),
]
TAGS = [(1, "php", "2026-10-02 09:00:00"), (2, "laravel", "2026-10-03 09:00:00"), (3, "python", "2026-10-05 09:00:00")]
ARTIGO_TAG = [(1, 1), (2, 1), (2, 2), (3, 1), (4, 3)]
COMENTARIOS = [(1, 1, 2, "Muito bom.", "2026-10-06 08:00:00"), (2, 1, 3, "Ajudou aqui.", "2026-10-06 08:05:00"),
               (3, 2, 1, "Faltou testes.", "2026-10-06 08:10:00")]
FAVORITOS = [(1, 2), (2, 1), (4, 1)]
SEGUINDO = [(1, 2), (3, 1)]  # author_follower (author_id, follower_id)


def _q(v):
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def semente() -> str:
    import bcrypt

    linhas = ["-- Semente do caso RealWorld (gerada por casos/realworld.py semente; não edite à mão).",
              "-- Senhas com sal fixo: a semente sai igual a cada geração."]
    for i, u, e, pw, bio, img, ts, sal in USUARIOS:
        h = bcrypt.hashpw(pw.encode(), b"$2b$10$" + sal.encode()).decode()
        h = "$2y$" + h[4:]
        linhas.append(f"INSERT INTO users (id, username, email, password, bio, image, created_at, updated_at) "
                      f"VALUES ({i}, {_q(u)}, {_q(e)}, {_q(h)}, {_q(bio)}, {_q(img)}, {_q(ts)}, {_q(ts)});")
    for i, a, s, t, d, b, ts in ARTIGOS:
        linhas.append(f"INSERT INTO articles (id, author_id, slug, title, description, body, created_at, updated_at) "
                      f"VALUES ({i}, {a}, {_q(s)}, {_q(t)}, {_q(d)}, {_q(b)}, {_q(ts)}, {_q(ts)});")
    for i, n, ts in TAGS:
        linhas.append(f"INSERT INTO tags (id, name, created_at, updated_at) VALUES ({i}, {_q(n)}, {_q(ts)}, {_q(ts)});")
    for a, t in ARTIGO_TAG:
        linhas.append(f"INSERT INTO article_tag (article_id, tag_id) VALUES ({a}, {t});")
    for i, a, u, b, ts in COMENTARIOS:
        linhas.append(f"INSERT INTO comments (id, article_id, author_id, body, created_at, updated_at) "
                      f"VALUES ({i}, {a}, {u}, {_q(b)}, {_q(ts)}, {_q(ts)});")
    for a, u in FAVORITOS:
        linhas.append(f"INSERT INTO article_favorite (article_id, user_id) VALUES ({a}, {u});")
    for a, f in SEGUINDO:
        linhas.append(f"INSERT INTO author_follower (author_id, follower_id) VALUES ({a}, {f});")
    return "\n".join(linhas) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("semente")
    c = sub.add_parser("contrato")
    c.add_argument("--fonte", type=Path, required=True)
    c.add_argument("--saida", type=Path, required=True)
    d = sub.add_parser("diferencial")
    d.add_argument("--laravel", required=True, help="URL,caminho-do-sqlite")
    d.add_argument("--fastapi", required=True, help="URL,caminho-do-sqlite")
    d.add_argument("--volateis", type=Path, required=True, help="JSON com a seção volateis do contrato")
    d.add_argument("--saida", type=Path, required=True)
    d.add_argument("--pausa", type=float, default=1.1)
    a = p.parse_args(argv)
    if a.cmd == "semente":
        (AQUI / "realworld" / "semente.sql").write_text(semente(), encoding="utf-8")
        return 0
    if a.cmd == "contrato":
        from laravel_fastapi import contrato, gerar

        k = contrato.extrair(a.fonte)
        a.saida.mkdir(parents=True, exist_ok=True)
        (a.saida / "contrato.json").write_text(contrato.serializar(k), encoding="utf-8")
        cob = gerar.gerar(json.loads(contrato.serializar(k)), a.saida / "fastapi")
        print(json.dumps({"contrato": k["cobertura"], "gerador": {"rotas": cob["rotas"], "cobertas": cob["cobertas"]}}))
        return 0
    from laravel_fastapi import diferencial

    cen = json.loads((AQUI / "realworld" / "cenario.json").read_text(encoding="utf-8"))
    vol = json.loads(a.volateis.read_text(encoding="utf-8"))
    lb, lc = a.laravel.split(",", 1)
    fb, fc = a.fastapi.split(",", 1)

    def registro(item):
        marca = "igual" if item["igual"] else "DIFERE"
        print(f"{item['id']:>3} {marca:6} {item['pedido']} {item['status']} {'; '.join(item['motivos'])[:300]}", flush=True)

    res = diferencial.rodar(cen, vol, {"base": lb, "banco": lc}, {"base": fb, "banco": fc}, a.pausa, registro)
    res["produto"] = PRODUTO
    a.saida.write_text(json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"placar: {res['endpoints_iguais']} de {res['endpoints']} endpoints respondem igual; "
          f"{res['passos_iguais']} de {res['passos']} passos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
