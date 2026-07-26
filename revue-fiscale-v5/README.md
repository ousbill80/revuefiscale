# Plateforme SaaS de revue fiscale — Côte d'Ivoire

Multi-cabinets. Moteur de règles déterministe, référentiel central maintenu par l'éditeur,
couche d'intelligence encadrée. CGI 2026 · SYSCOHADA · 14 domaines fiscaux · 57 règles.

---

## Démarrage

```bash
cp .env.example .env          # DATABASE_URL (port hôte 5433), SECRET_KEY, RESEND_API_KEY
make install                  # environnement Python + dépendances
make db-up                    # base + migrations + rôle applicatif + politiques RLS
make test-isolation           # 6 tests d'étanchéité — bloquant
make test                     # 35 tests (expressions + isolation)
make dev                      # API sur :8000
```

## Commandes

| Commande | Effet |
|---|---|
| `make test` | Tests unitaires et d'intégration |
| `make test-regles` | Harnais de règles — chaque règle contre son cas attendu |
| `make test-isolation` | **Tente une lecture inter-cabinets et vérifie qu'elle échoue** |
| `make lint` | ruff, mypy --strict |
| `make migrate` | Applique les migrations |
| `make seed` | Valide et charge `referentiel/*.yaml` |
| `make etat-referentiel` | Scan YAML → `docs/14-etat-referentiel.md` |
| `make inventaire-a-confirmer` | File `a_confirmer` MD + JSON |
| `make ingerer-corpus FICHIER=… TYPE=cgi` | Ingère PDF/MD dans le corpus (voir `corpus_sources/`) |
| `make demolot` | **Démo commercial `/app`** — cabinet isolé + mission FICTIF (`CABINET_DEMO_*`) |
| `make demo-mission` | Alias de `make demolot` |
| `make frontend` | Build React mission → `frontend/mission/dist` (servi sur `/app`) |
| `make frontend-dev` | Vite hot-reload (proxy API) — en parallèle de `make dev` |
| `make prod-up` | Stack Docker prod-like (api + db) — `docs/20-deploiement.md` |
| `make ci` | Lint NEW_CODE + isolation + règles + smoke (même cible que GitHub Actions) |

## Arborescence

```
.cursor/rules/          Règles Cursor (.mdc)
docs/                   Conception
backend/
  plateforme/           Tenants, abonnements, utilisateurs, quotas, métrage
  editorial/            Référentiel central, versions, publication, contestations
  socle/                Couche 1 — import, fiabilisation, contrôles
  referentiel/          Couche 2 — lecture des règles, millésimes, expressions
  profil/               Couche 3 — questionnaire, filtre amont
  moteur/               Couche 4 — DÉTERMINISTE. Aucun LLM ici.
  restitution/          Couche 5 — passage fiscal, risques, rapport
  corpus/               Couche 6 — ingestion, index, recherche
  agent/                Couche 6 — outils, boucle, garde-fous
frontend/
  landing/              Landing marketing publique (HTML/CSS/JS) → /
  mission/              App React mission guidée (Vite) → dist servi sur /app
  app/                  Fallback HTML statique si dist absent
  admin/                Console éditoriale 2AàZ (servie sur /console)
  billing/              Admin billing plateforme (servie sur /billing)
tests/
  regles/               Un cas par règle
  isolation/            Tests d'étanchéité inter-cabinets
  eval/                 Jeu de référence du copilote
migrations/
```

## État d'avancement

| Étape | État |
|---|---|
| 0 — Fondations métier | **PV provisoire** — `docs/00-fondations-pv.md` (À CONFIRMER) |
| 1 — Socle multi-cabinets, RLS, provisionnement | **fait** — migrations 001–005, isolation verte |
| 2 — Socle de données (balance, EF, GL, FEC) | **fait** — soldes dérivés vers `solde_compte` |
| 3 — Référentiel + console admin | **fait** (console `/console` ; billing `/billing`) |
| 4 — Moteur déterministe + épinglage | **fait** |
| 5 — Harnais 57 règles | **fait** (57 fiches métier ; **0** EMPLACEMENT ; toutes `a_confirmer` — voir `docs/14-etat-referentiel.md`) |
| 6 — Restitution + frontend | **fait** (markdown ; Word/PDF à étendre) |
| 7–10 — Corpus / eval / agent / usages | **fait** (démo FICTIF ; CGI réel à ingérer) |

```bash
make install && make db-up
make seed && make etat-referentiel
make test              # 204+ tests
make test-isolation    # étanchéité cabinets
make test-regles       # 57 YAML
make demolot           # admin@demo.local + mission FICTIF (rejeu : même commande)
make frontend          # build React → frontend/mission/dist
make dev               # API :8000 — / · /app · /console · /billing (/admin → /console)
```

Landing marketing : `http://localhost:8000/` (`frontend/landing/`). Surfaces : `docs/11-saas-surfaces.md`.
Démo commercial : § Démo `/app`. Compte billing : `billing@2aaz.ci` (mdp dans `.env.example`).


## Les trois règles à ne jamais oublier

1. `backend/moteur/` ne contient **aucun appel LLM** et **aucun taux en dur**.
2. Une table du domaine abonné porte `tenant_id NOT NULL` et une politique RLS **forcée**.
3. Le contexte de tenant se pose avec **`set_config(..., true)`** (≡ `SET LOCAL`), jamais `SET`.
   Avec un pool de connexions, un `SET` survit à la transaction et sert le tenant suivant.
