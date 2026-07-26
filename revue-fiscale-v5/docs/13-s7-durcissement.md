# S7 — Durcissement & dettes actionnables

Complète S0–S6 + UI. Voir aussi `docs/11-saas-surfaces.md`.

## Fait

| Point | Détail |
|---|---|
| **Auth agent / usages** | `POST /api/v1/agent/*`, `POST /api/v1/editorial/propositions`, `POST /api/v1/editorial/usages/*` exigent staff `editorial` \| `ops` (401 sans jeton, 403 si billing seul). Corpus déjà protégé. |
| **Compte cabinet démo** | Documenté dans `.env.example` : `CABINET_DEMO_*`. Reproductible : `make seed && make demolot`. UI : chip démo + hint « Rejouer : make demolot » (localhost + ENV=dev). |
| **Portail client empty state** | Mission sans exécution → **200** + `sans_restitution: true` + message clair (plus de 404 brut). UI `/client` affiche un panneau dédié. |
| **Facture PDF** | `GET /api/v1/billing/factures/{id}/pdf` (reportlab, montant commercial). Bouton PDF dans `/billing`. CSV conservé. |
| **Invitations** | Après création, jeton affiché dans une boîte sélectionnable + bouton « Copier le jeton » (une fois). |
| **Tests** | `tests/isolation/test_s7_durcissement.py` (+ mise à jour portail client). |

## Reporté / dettes restantes

| Dette | Statut |
|---|---|
| Email réel (invitations) | **Partiel** — table `email_outbox` + template ; Resend si `RESEND_API_KEY` ; en prod sans clé → `echec` explicite (pas de faux envoi). Jeton toujours renvoyé à l'UI. |
| Liens client par email | Reporté — URL à transmettre manuellement |
| PDF facture « production » | Placeholders **À CONFIRMER** (mentions légales, TVA) — aucun taux inventé |
| Lint global strict | `make ci` = ruff backend/tests + isolation + règles + smoke |
| Seed SQL fixe d'un tenant cabinet | Non — volontairement via provisionnement démo |
| Tarifs paliers | Toujours **À CONFIRMER** (`backend/plateforme/paliers.py`) |

### Brancher Resend (invitations)

```bash
# .env
RESEND_API_KEY=re_…
RESEND_FROM="Revue Fiscale <noreply@votre-domaine.ci>"
```

Sans clé : `ENV=dev` → outbox `simule_dev` ; hors dev → outbox `echec` + message « brancher clé API ».

## Comptes démo (local)

| Surface | URL | Identifiant | Mot de passe |
|---|---|---|---|
| Billing | `/billing` | `billing@2aaz.ci` | `BillingDemo2026!` |
| Console | `/console` | `editorial@2aaz.ci` | `EditorialDemo2026!` |
| Ops | `/billing` + `/console` | `ops@2aaz.ci` | `OpsDemo2026!` |
| App cabinet | `/app` | `admin@demo.local` | `demo-demo1` |
| Portail client | `/client/?token=…` | token magique | — |

Ne pas réutiliser en production.
