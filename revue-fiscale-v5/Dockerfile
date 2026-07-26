# Image API ZenAPI — FastAPI + UI mission buildée + consoles statiques.
# Ne contient aucun taux / seuil fiscal en dur : le référentiel vient des YAML + DB.

# --- Build UI mission (Vite) -------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /ui
COPY frontend/mission/package.json frontend/mission/package-lock.json ./
RUN npm ci
COPY frontend/mission/ ./
RUN npm run build

# --- Runtime Python ----------------------------------------------------------
FROM python:3.12-slim AS api
WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl postgresql-client \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY migrations ./migrations
COPY referentiel ./referentiel
COPY fixtures ./fixtures
COPY frontend/app ./frontend/app
COPY frontend/admin ./frontend/admin
COPY frontend/billing ./frontend/billing
COPY frontend/client ./frontend/client
COPY frontend/shared ./frontend/shared
COPY --from=frontend /ui/dist ./frontend/mission/dist
COPY scripts/docker-entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir . \
  && chmod +x /entrypoint.sh

ENV ENV=prod \
    PYTHONUNBUFFERED=1 \
    MIGRATE_ON_START=1 \
    DB_HOST=db \
    DB_PORT=5432

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/sante || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
