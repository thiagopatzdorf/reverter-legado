#!/bin/bash
# Uma rodada do diferencial do caso RealWorld, em containers descartáveis `lf-*`.
#
#   LF_TRABALHO=<pasta de trabalho> bash apps/laravel-fastapi/casos/realworld/rodada.sh
#   NEGATIVO=1 ...   # controle negativo: muda um artigo só no banco do FastAPI
#
# A pasta de trabalho precisa de: app_key (APP_KEY de teste, base64:...), rw/ (checkout do
# laravel-realworld-example-app no commit fixado), repo/ (este repositório), dados/base/banco.sqlite
# (migrado pelo próprio Laravel: MIGRAR=1 em entrar.sh) e as imagens lf-laravel-rw:c14fb83 e
# lf-fastapi:1 (receitas no README do app). Portas só em 127.0.0.1; inversa: docker rm -f lf-laravel lf-fastapi.
set -euo pipefail
B=${LF_TRABALHO:?defina LF_TRABALHO}
cd "$B"
export LF_APP_KEY=$(cat app_key)
LIM="--cpus 1.5 --memory 4g"
APP=$B/repo/apps/laravel-fastapi
docker rm -f lf-laravel lf-fastapi >/dev/null 2>&1 || true

echo "== 1. contrato e gerador"
rm -rf saida && mkdir -p saida && chmod 777 saida
docker run --rm --name lf-gerar $LIM -v "$APP":/app:ro -v "$B/rw":/rw:ro -v "$B/saida":/saida \
  -w /app lf-fastapi:1 python casos/realworld.py contrato --fonte /rw --saida /saida

echo "== 2. bancos: migrado pelo Laravel + semente, duas cópias idênticas"
rm -rf dados/laravel dados/fastapi dados/esquema && mkdir -p dados/laravel dados/fastapi dados/esquema
cp dados/base/banco.sqlite dados/laravel/banco.sqlite
python3 -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.executescript(open(sys.argv[2]).read());c.commit()" \
  dados/laravel/banco.sqlite "$APP/casos/realworld/semente.sql"
cp dados/laravel/banco.sqlite dados/fastapi/banco.sqlite
if [ "${NEGATIVO:-0}" = "1" ]; then
  python3 -c "import sqlite3;c=sqlite3.connect('dados/fastapi/banco.sqlite');c.execute(\"update articles set body='alterado' where id=4\");c.commit()"
fi
chmod -R a+rwX dados/laravel dados/fastapi dados/esquema
sha256sum dados/laravel/banco.sqlite dados/fastapi/banco.sqlite

echo "== 3. esquema que o SQLAlchemy gerado cria"
docker run --rm --name lf-esquema $LIM -v "$B/saida/fastapi":/app:ro -v "$B/dados/esquema":/dados -w /app lf-fastapi:1 \
  python -c "import sqlalchemy as sa, modelos; modelos.metadata.create_all(sa.create_engine('sqlite:////dados/banco.sqlite'))"

echo "== 4. servidores"
docker run -d --name lf-laravel $LIM -e LF_APP_KEY -p 127.0.0.1:18101:8000 \
  -v "$APP/casos/realworld/entrar.sh":/entrar.sh:ro -v "$B/dados/laravel":/dados lf-laravel-rw:c14fb83 sh /entrar.sh >/dev/null
docker run -d --name lf-fastapi $LIM -e APP_KEY="$LF_APP_KEY" -e DATABASE_URL=sqlite:////dados/banco.sqlite \
  -e PYTHONDONTWRITEBYTECODE=1 -p 127.0.0.1:18102:8000 -v "$B/saida/fastapi":/app:ro -v "$B/dados/fastapi":/dados \
  -w /app lf-fastapi:1 uvicorn main:app --host 0.0.0.0 --port 8000 --log-level warning >/dev/null
for _ in $(seq 1 30); do
  a=$(curl -s -o /dev/null -w '%{http_code}' -H 'Accept: application/json' http://127.0.0.1:18101/api/tags || true)
  f=$(curl -s -o /dev/null -w '%{http_code}' -H 'Accept: application/json' http://127.0.0.1:18102/api/tags || true)
  [ "$a" = 200 ] && [ "$f" = 200 ] && break
  sleep 1
done
echo "laravel=$a fastapi=$f"

echo "== 5. diferencial"
python3 -c "import json,sys; json.dump(json.load(open(sys.argv[1]))['volateis'], open(sys.argv[2],'w'))" \
  saida/contrato.json saida/volateis.json
SUF=${NEGATIVO:+-negativo}
(cd "$APP" && python3 casos/realworld.py diferencial --laravel "http://127.0.0.1:18101,$B/dados/laravel/banco.sqlite" \
  --fastapi "http://127.0.0.1:18102,$B/dados/fastapi/banco.sqlite" --volateis "$B/saida/volateis.json" \
  --saida "$B/saida/resultado$SUF.json")
(cd "$APP" && python3 -c "import json,sys; sys.path.insert(0,'.'); from laravel_fastapi import diferencial as d; print(json.dumps(d.comparar_esquema(sys.argv[1], sys.argv[2])))" \
  "$B/dados/base/banco.sqlite" "$B/dados/esquema/banco.sqlite") > saida/esquema.json
cat saida/esquema.json
docker logs lf-fastapi > saida/fastapi.log 2>&1 || true
docker rm -f lf-laravel lf-fastapi >/dev/null
echo "== fim"
