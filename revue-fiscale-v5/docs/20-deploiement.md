# Déploiement ZenAPI — local prod-like et go-live

Éditeur : **2AàZ SAS** · Développement / hébergement ops : **ZenAPI SAS**.
Ce document ne fixe aucun tarif ni article CGI. Les bloqueurs humains restent
dans `docs/15-bloqueurs-humains.md`.

---

## Deux modes

| Mode | Commande | Usage |
|---|---|---|
| **Dev quotidien** | `make db-up` + `make frontend` + `make dev` | Hot-reload API ; DB seule en Docker (port hôte **5433**) |
| **Prod-like local** | `docker compose up -d --build` | API + DB dans Compose ; UI mission buildée dans l’image |

---

## Prérequis

- Docker Engine + Compose v2
- Fichier `.env` (jamais committer) : `cp .env.example .env`
- Python 3.12+ uniquement pour le mode dev / `make ci`

Variables critiques :

| Variable | Prod-like | Notes |
|---|---|---|
| `SECRET_KEY` | **Obligatoire** (non vide) | Refus au démarrage si `ENV≠dev` et clé vide |
| `ENV` | `prod` (défaut compose) | Ferme le provisionnement public sauf flag |
| `DATABASE_URL` | écrasée vers `db:5432` dans Compose | Sur l’hôte en dev : `localhost:5433` |
| `ALLOW_PUBLIC_PROVISIONING` | `false` | Ne pas ouvrir en prod réelle |
| `RESEND_API_KEY` | optionnel | Sans clé en prod : envois en `echec` explicite |
| `FACTURE_*` / paliers | À CONFIRMER | Ne pas inventer RCCM, IDU, taux TVA, grilles |

Mots de passe démo (`billing@2aaz.ci`, `editorial@…`, `admin@demo.local`) :
**local uniquement** — à invalider / ne pas réutiliser en production réelle.

---

## Déployer en local « prod-like »

```bash
cd revue-fiscale-v5
cp .env.example .env
# Éditer SECRET_KEY (valeur longue aléatoire). Garder ENV=prod pour le mode compose,
# ou laisser Compose forcer ENV=prod via docker-compose.yml.

docker compose up -d --build
# Attendre healthy : docker compose ps
curl -fsS http://localhost:8000/sante
# → {"statut":"ok","env":"prod"}

# Référentiel YAML → DB (profil optionnel)
docker compose --profile seed run --rm seed
```

Surfaces une fois l’API healthy :

| URL | Rôle |
|---|---|
| http://localhost:8000/sante | Healthcheck |
| http://localhost:8000/app/ | Espace abonné (React buildée) |
| http://localhost:8000/console/ | Console éditoriale |
| http://localhost:8000/billing/ | Admin billing |
| http://localhost:8000/docs | OpenAPI FastAPI |

Arrêt / reset données DB :

```bash
docker compose down          # conserve volumes pgdata + pieces_data
docker compose down -v       # EFFACE la base et les pièces — irréversible
```

### Ce que fait le démarrage API

1. Attente `pg_isready` sur le service `db`
2. Si `MIGRATE_ON_START=1` (défaut) : application séquentielle de `migrations/*.sql`
   (rôle `app_revue`, RLS, tables plateforme / missions / billing / …)
3. `uvicorn backend.main:app --host 0.0.0.0 --port 8000`
4. Healthcheck HTTP `GET /sante`

Volume nommé `pieces_data` → `/app/var/pieces` (pièces jointes mission, domaine abonné).

---

## Architecture Compose

```
┌─────────────┐     réseau compose      ┌──────────────────┐
│  navigateur │ ──:8000───────────────► │ api (Dockerfile) │
└─────────────┘                         │  + migrations    │
                                        │  + UI /app       │
                                        └────────┬─────────┘
                                                 │ :5432
                                        ┌────────▼─────────┐
                                        │ db postgres:16   │
                                        │ volume pgdata    │
                                        └──────────────────┘
```

Services :

| Service | Image | Obligatoire | Rôle |
|---|---|---|---|
| `db` | `postgres:16-alpine` | oui | PostgreSQL + volume `pgdata` |
| `api` | build local | oui | FastAPI + static + migrate on start |
| `seed` | même image | non (`--profile seed`) | `python -m backend.scripts.seed_referentiel` |

Ports hôte configurables : `API_HOST_PORT` (défaut 8000), `POSTGRES_HOST_PORT` (défaut 5433).

---

## CI (locale et GitHub Actions)

```bash
make install   # une fois
make db-up     # Postgres + migrations (dev)
make ci        # lint NEW_CODE + isolation + règles + smoke
```

GitHub Actions (`.github/workflows/ci.yml`) :

- Service Postgres 16 (port 5433) + healthcheck
- Cache pip (`actions/setup-python` cache)
- Même cible que local : **`make ci`** (évite la dérive lint CI ↔ Makefile)
- Seed référentiel avant les tests qui en dépendent

Dette connue (documentée, non bloquante pour `make ci`) :

- Lint **global** `ruff` / `mypy` sur tout le dépôt : dette E501 / I001 hors `NEW_CODE`
- `make lint` strict ≠ `make ci` (ci = sous-ensemble NEW_CODE + tests isolation/règles/smoke)
- Compte démo / mots de passe seed : hors prod

---

## Checklist go-live (courte)

Ops ZenAPI / 2AàZ — cocher avant exposition publique.

### Technique

- [ ] `.env` prod : `SECRET_KEY` fort, `ENV=prod`, mots de passe DB ≠ défauts `changeme` / `postgres`
- [ ] `ALLOW_PUBLIC_PROVISIONING=false`
- [ ] TLS terminé (reverse proxy) devant `:8000` — pas d’HTTP nu en public
- [ ] Sauvegardes volume `pgdata` + test de restauration
- [ ] `GET /sante` vert ; `make ci` vert sur le commit déployé
- [ ] Comptes seed démo désactivés / mots de passe changés
- [ ] `RESEND_API_KEY` + domaine `RESEND_FROM` vérifiés **ou** acceptation explicite des emails en `echec`

### Produit / éditorial (pas inventés ici)

- [ ] Mentions facture (`FACTURE_*` / `config_editeur`) fournies par 2AàZ — sinon restent **À CONFIRMER**
- [ ] Grille tarifaire officielle saisie — sinon badge `tarifs_a_confirmer`
- [ ] Visa fiscaliste / CGI : voir `docs/15-bloqueurs-humains.md` (ne bloque pas le runtime SaaS, bloque la certification référentiel)

### Isolation (non négociable)

- [ ] App tourne sous rôle `app_revue` (pas superuser)
- [ ] Tests `tests/isolation` verts en CI
- [ ] Aucun `SET app.tenant_id` sans `LOCAL` / `set_config(..., true)`

---

## Fichiers concernés

| Fichier | Rôle |
|---|---|
| `Dockerfile` | Image API multi-stage (Node build UI + Python) |
| `docker-compose.yml` | `db` + `api` + profil `seed` |
| `scripts/docker-entrypoint.sh` | Wait DB + migrations + uvicorn |
| `.dockerignore` | Contexte de build léger |
| `.env.example` | Modèle variables (hôte + notes Compose) |
| `.github/workflows/ci.yml` | CI GitHub = `make ci` + cache + Postgres |
| `Makefile` (`ci`, `prod-up`, …) | Cibles ops locales |

---

## Seeds éditoriaux (hors Compose)

Après `make seed` (YAML → DB) et éventuellement corpus CGI :

| Cible | Effet | Doc |
|---|---|---|
| `make seed-pistes-annexe` | 8 propositions Annexe (`annexe_2026_croisement`) | `docs/18-lot-fiscaliste-annexe-8.md` |
| `make seed-pistes-cgi` | 7 propositions CGI (`cgi_2026_croisement`) | `docs/19-cgi-vs-a-confirmer.md` |

Idempotents ; **aucune purge** `a_confirmer`. Console : `/console` → À confirmer → Vue **Pistes sourcées** / Annexe / CGI.

---

## Dette / limites assumées

1. **Migrations non versionnées en table** — chaque démarrage ré-applique `migrations/*.sql` (scripts majoritairement idempotents `IF NOT EXISTS`). Une vraie table `schema_migrations` reste à faire.
2. **Pas de reverse proxy / TLS dans Compose** — à ajouter côté infra ZenAPI (Caddy, Traefik, nginx).
3. **Pas de réplicas / HA** — un seul Postgres, un seul worker uvicorn (suffisant prod-like local ; scale = chantier séparé).
4. **Scrape / corpus CGI** — hors périmètre de ce doc ; ne pas mélanger avec le déploiement runtime.
5. **Lint global** — `make lint` (ruff + mypy strict sur tout le dépôt) ≠ `make ci` (sous-ensemble `NEW_CODE`). Dette E501/I001 hors périmètre ci.
6. **Build Docker** — si `docker-credential-desktop` manque dans le PATH du shell, utiliser un `DOCKER_CONFIG` temporaire sans `credsStore`, ou lancer depuis Docker Desktop.
