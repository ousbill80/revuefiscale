# Mission guidée (Vite + React + TypeScript)

Parcours cabinet : connexion → contribuable → mission → balance → restitution.

## Développement

```bash
# Terminal 1 — API
make dev

# Terminal 2 — UI hot-reload (proxy /api → :8000)
cd frontend/mission && npm install && npm run dev
# → http://localhost:5173/app/
```

## Production (servie par FastAPI)

```bash
make frontend          # npm install + build → frontend/mission/dist
make dev               # ouvre http://localhost:8000/app/
```

Si `frontend/mission/dist` est absent, FastAPI retombe sur `frontend/app/index.html` (HTML statique).
