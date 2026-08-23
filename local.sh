#!/usr/bin/env bash
# Levanta Stockero en local: DB Postgres (Docker) + servidor Django.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Falta .env (copiá .env.example y completá SECRET_KEY, DATABASE_URL, etc.)"
  exit 1
fi

if [ ! -d venv ]; then
  python3 -m venv venv
fi
venv/bin/pip install -q -r requirements.txt

docker compose up -d db
echo "Esperando a que Postgres esté listo..."
until docker compose exec -T db pg_isready -U optica -d stockero >/dev/null 2>&1; do sleep 1; done

venv/bin/python manage.py migrate

if [ "${1:-}" = "test" ]; then
  venv/bin/python manage.py test
  exit 0
fi

PORT="${PORT:-8034}"
echo "Levantando servidor en http://localhost:${PORT}/"
venv/bin/python manage.py runserver "${PORT}"
