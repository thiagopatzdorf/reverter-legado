#!/bin/sh
# Roda DENTRO do container lf-laravel: configura o app para SQLite e sobe o servidor.
# O banco vem pronto de fora (/dados/banco.sqlite); com MIGRAR=1 só migra e sai.
# APP_DEBUG=false: o diferencial compara as respostas de produção, não a página de debug.
set -e
cd /app
cp .env.example .env
sed -i -e 's/^APP_ENV=.*/APP_ENV=production/' -e 's/^APP_DEBUG=.*/APP_DEBUG=false/' \
  -e 's/^DB_CONNECTION=.*/DB_CONNECTION=sqlite/' -e 's#^DB_DATABASE=.*#DB_DATABASE=/dados/banco.sqlite#' \
  -e '/^DB_HOST=/d' -e '/^DB_PORT=/d' -e '/^DB_USERNAME=/d' -e '/^DB_PASSWORD=/d' \
  -e 's/^LOG_CHANNEL=.*/LOG_CHANNEL=stderr/' -e "s#^APP_KEY=.*#APP_KEY=${LF_APP_KEY}#" .env
php artisan config:clear >/dev/null
if [ "${MIGRAR:-0}" = "1" ]; then
  php artisan migrate --force
  exit 0
fi
exec php artisan serve --host 0.0.0.0 --port 8000
