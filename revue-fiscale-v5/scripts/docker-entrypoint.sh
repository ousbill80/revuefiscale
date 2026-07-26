#!/bin/sh
# Entrypoint prod-like : attend PostgreSQL, applique les migrations SQL, lance l'API.
set -eu

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-revue_fiscale}"
MIGRATE_ON_START="${MIGRATE_ON_START:-1}"

echo "Attente PostgreSQL (${DB_HOST}:${DB_PORT})..."
i=0
until PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "PostgreSQL indisponible après 60 s." >&2
    exit 1
  fi
  sleep 1
done
echo "PostgreSQL prêt."

if [ "$MIGRATE_ON_START" = "1" ] || [ "$MIGRATE_ON_START" = "true" ]; then
  echo "Application des migrations..."
  for f in /app/migrations/*.sql; do
    echo "→ $f"
    PGPASSWORD="${POSTGRES_PASSWORD:-postgres}" psql \
      -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
      -v ON_ERROR_STOP=1 -f "$f"
  done
  echo "Migrations appliquées."
fi

exec "$@"
