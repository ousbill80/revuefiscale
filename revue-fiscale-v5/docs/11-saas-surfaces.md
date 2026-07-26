# Surfaces SaaS — Landing, Console, Billing, App, Client

Cinq surfaces distinctes. Quatre applicatives (auth séparées) + une vitrine marketing publique.

| Surface | URL | Public | Auth | Rôle |
|---|---|---|---|---|
| **Landing** | `/` | Public (marketing) | Aucune | Vitrine produit, CTA démo / connexion |
| **Console** | `/console` | Staff éditorial 2AàZ | JWT `typ=staff` (`editorial` \| `ops`) | Référentiel, propositions, contestations |
| **Admin billing** | `/billing` | Staff propriétaire plateforme | JWT `typ=staff` (`billing` \| `ops`) | Abonnés, paliers, quotas, factures |
| **Espace abonné** | `/app` | Cabinet / entreprise | JWT tenant | Missions, clients, équipe |
| **Portail client** | `/client` | Contact contribuable | Token magique `lien_acces_mission` | Restitution **lecture seule** |

Redirection : `/admin` → `/console` (308).

## Landing marketing (`/`)

- Front statique : `frontend/landing/` (HTML + CSS + JS léger), servi par `StaticFiles(html=True)` monté **en dernier** dans `backend/main.py` pour ne pas masquer `/app`, `/api`, `/console`, `/billing`, `/client`, `/sante`, `/shared`.
- CTA principal : **Accéder à l’espace** → `/app/`. Secondaire : demande de démo (ancre `#contact` / `mailto:contact@2aaz.ci`).
- Signup public fermé hors `ENV=dev` / `ALLOW_PUBLIC_PROVISIONING` — la landing ne propose pas d’inscription libre en production.
- Pas de grille tarifaire chiffrée : renvoi « sur devis » / contact éditeur (voir `docs/15-bloqueurs-humains.md` § tarifs).

## Layout full-page (S2–S6)

Chrome SaaS finance-comptable sur les quatre surfaces applicatives (`/console`, `/billing`, `/app`, `/client`) — pas la landing `/` :

- **Full-bleed** (`width: 100%`) — plus de shell centré ~960 px
- **Topbar sticky** pleine largeur
- **Sidebar** gauche (desktop) / drawer (mobile, touch 48 px, safe-area)
- **Contenu** fluide, tableaux data-dense pleine largeur

Accents : Billing teal · Console bleu · App teal cabinet · Client cyan lecture seule.

## Alignement UX console (polish `/console`)

La console reste en HTML/JS (`frontend/admin/`) — pas de migration React. Patterns portés depuis
`/app` via le DS partagé (`frontend/shared/saas-ds.css` + `infotip.js`) :

- Métriques cliquables (Versions), empty states, filtres chips (Propositions / À confirmer)
- InfoTip process (pastille ⓘ) — pas de pédagogie fiscale inventée dans l’UI
- Nav groupée Référentiel / Files, badges compteurs, confirmation avant publication
- Contestations : lecture seule explicite (API write non branchée)

## Séparation stricte

- **Console ≠ Billing.** L'éditorial ne gère pas les abonnements ; le billing ne publie pas le
  référentiel. Rôle `billing` seul → **403** sur `/api/v1/editorial/*`. **À CONFIRMER** : `ops` peut
  les deux.
- **Staff 2AàZ ≠ utilisateur abonné.** Un jeton staff est refusé sur les routes abonné. Un jeton
  tenant est refusé sur `/api/v1/billing/*`.
- **Billing ne lit jamais** `solde_compte`, `conclusion`, ni grand livre.

## Quotas (S2)

- Création mission (`POST /api/v1/missions`) : incrémente `quota.missions_utilisees` ; si épuisé → **403**.
- `GET /api/v1/quota` (abonné) et `GET /api/v1/billing/usage` : résumé `inclus / utilisés / ratio / alerte_80`.

## Espace abonné (S3)

- `GET /contribuables`, `PATCH`, `GET /missions` (filtres), invitations, utilisateurs (admin).
- RBAC : `lecteur` ne crée pas de mission ; `admin` gère les invitations.
- Frontend `/app` : dashboard + nav Clients | Missions | Nouvelle | Équipe.

## Facturation (S5)

- Table `facture` — montants **commerciaux** (abonnement), **pas** fiscaux.
- API staff : brouillon / émettre / payer / annuler / export CSV / **PDF** (`GET …/billing/factures/{id}/pdf`).
- API abonné (JWT tenant) : `GET /api/v1/factures`, détail, PDF, `POST …/signaler-paiement`
  → table `demande_paiement` (rapprochement). **L'abonné n'appelle jamais `marquer_payee`.**
- **Paystack** (Visa + Mobile Money CI : Orange / MTN / Wave via checkout) :
  - `GET /api/v1/factures/paystack-config` → `{disponible, public_key}` (pas de secret)
  - `POST /api/v1/factures/{id}/payer-paystack` (`gerer_abonnement`) → `authorization_url`
  - Webhook `POST /api/v1/webhooks/paystack` (`charge.success`, HMAC SHA512) → verify +
    `marquer_payee` sous `contexte_tenant` (`SET LOCAL`)
  - Table `paiement_paystack` (`023`, FORCE RLS). XOF zero-decimal : `amount = int(facture.montant)`.
  - Sans `PAYSTACK_SECRET_KEY` : API **503**, UI désactivée ; **virement** reste le secours.
- Demande de palier : `POST /api/v1/abonnement/demande-palier` → file staff
  (`GET/POST /api/v1/billing/demandes-palier/…`) ; acceptation via `patcher_tenant`.
- Prix mensuels provisoires dans `backend/plateforme/paliers.py` — **À CONFIRMER**
  (`tarifs_a_confirmer` exposé lecture seule côté `/app` Compte et `/billing`).

## Self-service vs staff (portail commercial)

| Action | Qui | Mécanisme |
|---|---|---|
| Créer un abonné | Staff billing | `POST /api/v1/billing/tenants` (acquisition assistée) |
| Signup public | Fermé hors `ENV=dev` / `ALLOW_PUBLIC_PROVISIONING` | Inchangé — pas d'ouverture PSP |
| Lister / PDF factures | Abonné (son tenant) | `GET /api/v1/factures[/{id}/pdf]` |
| Payer (carte / MoMo) | Admin cabinet → Paystack | Init checkout ; webhook marque payée |
| Signaler un virement | Admin cabinet | `demande_paiement` — statut facture inchangé (secours) |
| Marquer facture payée | Staff **ou** webhook Paystack | `POST …/billing/factures/{id}/payer` / webhook ; jamais JWT abonné direct |
| Changer de palier | Demande abonné → staff | `demande_palier` puis `patcher_tenant` |
| Muter quota / palier depuis `/compte` | Interdit | Profil = dénomination + identité légale (NCC, RCCM…) + téléphone contact |

UI `/app` : sections **Facturation & paiement** et **Compte**. UI `/billing` : file **Demandes**.
PSP : Paystack uniquement (clés ops 2AàZ) — pas de Stripe inventé.
## Portail client (S6 — Option A)

- `POST /api/v1/liens-acces` (cabinet) → token une fois.
- `GET /api/v1/client/{token}/restitution` via `client_lookup_lien` (SECURITY DEFINER) + RLS tenant.
- Sans exécution : **200** + `sans_restitution` (empty state UI), pas 404.
- UI `/client/?token=…`.

## Provisionnement

`POST /api/v1/provisionnement` fermé hors `ENV=dev` / `ALLOW_PUBLIC_PROVISIONING`.
Production : Admin billing (`POST /api/v1/billing/tenants`).

Self-service `/app` : `POST /api/v1/inscription/demarrer` → `verifier-otp` → `finaliser`
(OTP email via **Resend** : `RESEND_API_KEY` + `RESEND_FROM` dans `.env`).
En `ENV=dev`, la réponse peut inclure `otp_debug` pour QA.

## Comptes démo (local)

| Surface | Identifiant | Mot de passe |
|---|---|---|
| Billing | `billing@2aaz.ci` | `BillingDemo2026!` |
| Console | `editorial@2aaz.ci` | `EditorialDemo2026!` |
| Ops | `ops@2aaz.ci` | `OpsDemo2026!` |
| App cabinet | `admin@demo.local` | `demo-demo1` |

### Démo commercial `/app` (chemin unique)

```bash
make seed && make demolot    # cabinet isolé + client + mission FICTIF exécutée
make frontend && make dev    # → http://localhost:8000/app/
# Connexion : chip « Remplir Cabinet » / « Connexion démo » (localhost + ENV=dev)
# Rejouer : make demolot
```

- Credentials : `CABINET_DEMO_EMAIL` / `CABINET_DEMO_PASSWORD` (`.env.example`).
- Script : `backend/scripts/demo_commercial.py` — refuse hors `ENV=dev` (sauf `--force`).
- Alias : `make demo-mission` ≡ `make demolot`.
- Parcours techniques moteur : `make demolot1` / `make demolot234` (pas le pitch commercial).
- UI : indices démo via `GET /sante` uniquement si `ENV=dev` + gate localhost.

Ne pas réutiliser en production.

## S7 — Durcissement

Voir `docs/13-s7-durcissement.md` (auth agent/usages, empty state client, PDF facture, jeton invitation copiable).
