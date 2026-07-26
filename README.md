# Plateforme de revue fiscale — Côte d'Ivoire

Moteur de règles déterministe augmenté d'une couche d'intelligence encadrée.
CGI 2026 · SYSCOHADA · 14 domaines fiscaux · 57 règles à la mise en service.

---

## Démarrage

```bash
# Prérequis : Python 3.12, PostgreSQL 16, Node 20
cp .env.example .env          # renseigner DATABASE_URL et les clés
make install                  # dépendances backend et frontend
make db-up                    # base locale + migrations
make seed                     # charge le référentiel de règles
make dev                      # API sur :8000, front sur :5173
```

## Commandes

| Commande | Effet |
|---|---|
| `make test` | Tests unitaires et d'intégration |
| `make test-regles` | Harnais de règles — chaque règle contre son cas attendu |
| `make eval` | Jeu de référence du copilote — bloque si régression |
| `make lint` | Ruff, mypy, eslint |
| `make migrate` | Applique les migrations |
| `make corpus-ingest` | Ingère et indexe le corpus réglementaire |

## Arborescence

```
.cursor/rules/          Règles Cursor (.mdc) — voir AGENTS.md
docs/                   Documentation de conception
backend/
  socle/                Couche 1 — import, fiabilisation, contrôles
  referentiel/          Couche 2 — règles, millésimes, sanctions, effets croisés
  profil/               Couche 3 — questionnaire, filtre amont
  moteur/               Couche 4 — DÉTERMINISTE. Aucun appel LLM ici.
  restitution/          Couche 5 — passage fiscal, risques, rapport
  agent/                Couche 6 — orchestration, outils, garde-fous
  corpus/               Couche 6 — ingestion, découpage, index, recherche
frontend/               React + TypeScript
tests/
  regles/               Un cas par règle du référentiel
  eval/                 Jeu de référence du copilote
migrations/             Migrations SQL versionnées et réversibles
```

## La règle à ne jamais oublier

`backend/moteur/` ne contient **aucun appel à un modèle de langage**, et **aucun taux, seuil ou
condition fiscale en dur**. Si vous êtes tenté d'en écrire un, c'est que le référentiel manque
un champ — corrigez le référentiel, pas le moteur.
