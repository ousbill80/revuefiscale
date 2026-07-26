# Audit profondeur SaaS — doctrine & portail commercial

**Périmètre** : `revue-fiscale-v5` (lecture seule code + migrations + docs),
avec focus Phase A portail abonné commercial (`020`, routes abonné/billing,
tests `tests/abonne/test_portail_commercial.py`).

**Date** : 2026-07-26 · **Éditeur** : 2AàZ SAS · **Doctrine** : `AGENTS.md`

**Méthode** : confronter le code aux sept règles + interdits AGENTS ; ne pas
inventer d’article CGI ni de PSP. Les montants commerciaux provisoires ne sont
**pas** des seuils fiscaux.

Voir aussi : `docs/15-bloqueurs-humains.md`, `docs/11-saas-surfaces.md`,
`docs/23-engagement-cabinet.md`, `docs/09-multitenant.md`.

---

## Synthèse

| Sévérité | Nb | Verdict court |
|---|---|---|
| **Bloquant** | 0 code · 5 humains ouverts | Aucune violation doctrine runtime détectée sur le portail ; go-live commercial / certification référentiel bloqués par livrables humains |
| **Majeur** | 2 | Dette Phase A restante : pas d’email sur demandes ; tarifs À CONFIRMER. **`facture` RLS : corrigé (`022`)** |
| **Mineur** | 3 | Mentions facture placeholders ; Resend optionnel ; UX résiliation absente côté abonné (voulu) |
| **Info** | 5 | Conformités SET LOCAL, domaines, `marquer_payee` staff-only, lots engagement 1–4 shippés / lot 5 doc-only |

---

## Matrice parcours abonné (portail commercial)

| Parcours | Qui | État code | Note doctrine |
|---|---|---|---|
| **Inscription** | Public / OTP | `POST /api/v1/inscription/{demarrer,verifier-otp,finaliser}` | Fermé hors `ENV=dev` / `ALLOW_PUBLIC_PROVISIONING` pour provisionnement libre ; acquisition prod = staff billing |
| **Factures lecture** | JWT tenant | `GET /api/v1/factures`, détail, PDF | FORCE RLS `facture` (`022`) + filtre app + `session_abonne` |
| **Demande palier** | Admin cabinet | `POST /api/v1/abonnement/demande-palier` | Insert `demande_palier` ; **ne mute pas** le palier |
| **Paiement Paystack** | Admin cabinet → PSP | `POST …/payer-paystack` ; webhook `charge.success` | Init seule ; `marquer_payee` via webhook + verify (`023`) |
| **Paiement (signal)** | Admin cabinet | `POST …/factures/{id}/signaler-paiement` | `demande_paiement` seulement ; statut facture inchangé (secours) |
| **Marquer payée** | Staff billing **ou** webhook Paystack | `POST …/billing/factures/{id}/payer` / webhook | JWT abonné → jamais `marquer_payee` direct |
| **Résiliation** | Staff only | `patcher_tenant` statut `resilie` via `/api/v1/billing/tenants/…` | **Pas** d’endpoint abonné — voulu |

Paystack (Visa + MoMo CI) branché ; virement = secours. Clés = bloqueur ops (`docs/15` §4bis).

---

## Findings

### Bloquant

#### B1 — PDF CGI CI 2026 intégral absent
| | |
|---|---|
| **Sévérité** | Bloquant (humain) |
| **Constat** | Pas de `corpus_sources/CGI-CI-2026.pdf` ; scrape cgici ingéré en brouillon ≠ visa. Annexe 2026 ≠ CGI intégral. |
| **Impact** | Purges sourcées d’articles / seuils ; porte agent croisement |
| **Action** | Déposer le PDF → `make ingerer-corpus … TYPE=cgi` ; croiser puis visa humain (`docs/15` §1, `docs/17`) |

#### B2 — Visa fiscaliste file `a_confirmer`
| | |
|---|---|
| **Sévérité** | Bloquant (humain) |
| **Constat** | ~57 fiches / ~121 mentions encore marquées ; outils console + lots Annexe/CGI en place ; purge YAML = acte humain sourcé |
| **Impact** | Certification référentiel pour abonnés |
| **Action** | Séance `docs/22` ; lot Annexe `docs/18` ; lot CGI `docs/19`/`21` ; pas de purge auto |

#### B3 — Grille tarifaire officielle absente
| | |
|---|---|
| **Sévérité** | Bloquant (commercial / go-live pricing) |
| **Constat** | Bornes techniques dans `backend/plateforme/paliers.py` + badge `tarifs_a_confirmer` ; saisie éditeur possible via `/billing` Paramètres |
| **Impact** | Communication pricing non certifiée ; factures avec montants provisoires |
| **Action** | Grille 2AàZ (montants + quotas) → `PUT /billing/parametres/paliers` ; retirer présentation provisoire |

#### B4 — Mentions légales facture incomplètes
| | |
|---|---|
| **Sévérité** | Bloquant (PDF commercial « propre ») |
| **Constat** | Défauts `À CONFIRMER` (raison sociale, siège, RCCM, IDU, compte, régime/taux TVA) — aucun taux inventé |
| **Impact** | PDF facture non opposable / non présentable client final |
| **Action** | Billing → Paramètres / env (`docs/15` §3) |

#### B5 — Prescription Lot 5 (engagement) non visée
| | |
|---|---|
| **Sévérité** | Bloquant (produit fiscal futur) |
| **Constat** | Checklist À confirmer dans `docs/23` § Lot 5 ; **aucun** filtre runtime « exercice encore repris » — correct doctrine |
| **Impact** | Ouverture au contrôle non automatisable tant que non sourcé |
| **Action** | Visa fiscaliste CGI CI / LPF (base, point de départ, suspensions, exceptions) **avant** tout code |

---

### Majeur

#### M1 — Table `facture` — RLS FORCE (corrigé `022`)
| | |
|---|---|
| **Sévérité** | ~~Majeur~~ → **Info (OK)** depuis migration `022_facture_rls.sql` |
| **Constat (historique)** | Migration `006` : domaine plateforme, `tenant_id NOT NULL`, **pas** de FORCE RLS. Isolation lecture/écriture uniquement applicative. |
| **Correctif** | `ENABLE` + `FORCE ROW LEVEL SECURITY` + policy `tenant_id = SET LOCAL`. Staff : `billing_lire_facture` / `billing_lister_factures` DEFINER. Mutations Python sous `contexte_tenant`. Trigger `demande_paiement.tenant_id = facture.tenant_id`. `REVOKE UPDATE, DELETE` sur `demande_*` ; clôture via `billing_clore_demande_*`. |
| **Tests** | `test_isolation_factures_et_demandes_paiement` (0 ligne sans SET LOCAL) ; `test_rls_facture_forcee_et_grants_demande`. |

#### M2 — Aucun email sur `demande_paiement` / `demande_palier`
| | |
|---|---|
| **Sévérité** | Majeur (ops commercial) |
| **Constat** | Insert demande → file UI `/billing` Demandes uniquement. Pas d’entrée outbox / Resend à la création. |
| **Impact** | Staff peut manquer un signalement hors session billing |
| **Action** | Après Resend branché : notifier staff (template outbox) à l’ouverture + éventuellement abonné à l’acceptation/refus. Ne pas coupler à `marquer_payee`. |

#### M3 — Tarifs commerciaux encore « À CONFIRMER » en code
| | |
|---|---|
| **Sévérité** | Majeur (produit) |
| **Constat** | `PRIX_MENSUEL_XOF` / `MISSIONS_PAR_PALIER` provisoires ; `TARIFS_A_CONFIRMER = True` tant que grille éditeur incomplète. **Pas** des taux CGI. |
| **Impact** | Risque de présentation commerciale erronée si badge ignoré |
| **Action** | Même que B3 ; UI abonné/staff doit garder le badge jusqu’à saisie complète |

---

### Mineur

#### m1 — Mentions facture visibles mais placeholders
| | |
|---|---|
| **Sévérité** | Mineur (visibilité OK, valeurs non) |
| **Constat** | `/billing` Tarifs & mentions + `/app` instructions virement exposent l’inventaire |
| **Action** | Remplir (B4) ; pas de travail code bloquant |

#### m2 — Resend non branché en prod typique
| | |
|---|---|
| **Sévérité** | Mineur → majeur si prod sans clé |
| **Constat** | Sans clé : `simule_dev` (dev) / `echec` (prod) — pas de faux envoi. OTP / invitations impactés. |
| **Action** | `RESEND_API_KEY` + `RESEND_FROM` domaine vérifié (`docs/15` §5) |

#### m3 — Résiliation self-service absente
| | |
|---|---|
| **Sévérité** | Mineur / info produit |
| **Constat** | Volontaire : seul staff mute `statut=resilie`. Abonné lit statut via Compte / Abonnement. |
| **Action** | Documenter dans parcours commercial ; éventuel « demander résiliation » (signal) plus tard — **sans** mute direct |

---

### Info (conformités)

#### I1 — `SET LOCAL` / `set_config(..., true)` respecté
Point unique : `backend/plateforme/contexte.py`. Aucun `SET app.tenant_id` nu ni `set_config(..., false)` dans le backend applicatif. Scripts purge : SET LOCAL par tenant. **OK doctrine.**

#### I2 — Pas de taux / seuil fiscal CGI en dur dans le portail
Montants `paliers.py` = commerciaux abonnement. Moteur / référentiel séparés. Mentions TVA facture = placeholders À CONFIRMER, jamais inventés. **OK interdits AGENTS** (sous réserve B2/B3/B5).

#### I3 — Domaines éditorial vs abonné respectés sur nouvelles tables
| Table | Domaine | `tenant_id` | RLS |
|---|---|---|---|
| `demande_paiement` | Abonné | `NOT NULL` | ENABLE + FORCE + policy ; trigger tenant=facture ; INSERT/SELECT only |
| `demande_palier` | Abonné | `NOT NULL` | ENABLE + FORCE + policy ; INSERT/SELECT only |
| `paiement_paystack` | Abonné | `NOT NULL` | ENABLE + FORCE + policy (`023`) ; SELECT/INSERT/UPDATE |
| `facture` | Cloisonné (ex-plateforme billing) | `NOT NULL` | ENABLE + FORCE + policy (`022`) |
| Référentiel / corpus | Éditorial | Non | N/A |

Staff lit factures/demandes via fonctions SECURITY DEFINER. **OK** isolation base.

#### I4 — JWT abonné n’appelle jamais `marquer_payee`
- Route payer staff : `StaffBillingDep` uniquement.
- `signaler_paiement` / `payer-paystack` (init) n’appellent pas `marquer_payee`.
- Webhook Paystack (HMAC + verify) peut appeler `marquer_payee` sous `contexte_tenant`.
- Test `test_abonne_ne_peut_pas_marquer_payee` : POST billing/payer → 401/403 ; après signal statut reste `emise`.
- Acceptation staff peut appeler `marquer_payee` explicitement. **OK.**

#### I5 — Engagement lots 1–4 shippés ; lot 5 doc-only
| Lot | Statut |
|---|---|
| 1 Cadrage / périmètre | **Fait** (`015`, `018`, UI, tests) |
| 2 Statuts conclusion + pièce | **Fait** (`016`) |
| 3 Seuil signification | **Livré** (colonne + brouillon `sous_seuil`) |
| 4 Points ouverts | **Livré** (`017`, `019` tâches) |
| 5 Prescription | **Doc only** — checklist À confirmer ; pas de runtime (B5) |

---

## Dette Phase A (rappel explicite)

1. ~~**`facture` sans RLS**~~ — **corrigé** `migrations/022_facture_rls.sql` (M1).
2. **Pas d’email** à la création des demandes paiement/palier (M2).
3. **Tarifs À CONFIRMER** — provisoire technique + badge (M3 / B3).

---

## Actions prioritaires (ordre suggéré)

| Prio | Action | Owner | Finding |
|---|---|---|---|
| 1 | Visa fiscaliste pistes Annexe/CGI + ne pas purger sans source | Fiscaliste 2AàZ | B2 |
| 2 | Déposer / ingérer PDF CGI CI 2026 | Juridique / ops | B1 |
| 3 | Grille tarifaire + mentions facture officielles | Commercial / admin | B3, B4, M3 |
| 4 | Brancher Resend prod | Ops | m2 → M2 |
| 5 | Notifier staff sur nouvelles demandes | ZenAPI | M2 |
| 6 | ~~Trancher RLS `facture`~~ — **fait** (`022`) | Architecture | M1 |
| 7 | Checklist prescription Lot 5 avant tout code | Fiscaliste | B5 |
| — | Ne pas ouvrir PSP sans décision 2AàZ | Produit | — |

---

## Références code (ancres)

| Sujet | Emplacement |
|---|---|
| SET LOCAL | `backend/plateforme/contexte.py` |
| Demandes + RLS | `migrations/020_portail_abonne_commercial.sql` |
| Facture FORCE RLS | `migrations/022_facture_rls.sql` (historique `006`) |
| Signal ≠ payer | `backend/abonne/facturation.py`, `backend/abonne/routes.py` |
| Staff payer | `backend/billing/routes.py` → `marquer_payee` |
| Traitement demandes | `backend/billing/demandes.py` (`billing_clore_demande_*`) |
| Unicité ouvert | `migrations/021_demandes_unicite_ouvert.sql` |
| Tests Phase A | `tests/abonne/test_portail_commercial.py` |
| Surfaces | `docs/11-saas-surfaces.md` |
| Bloqueurs humains | `docs/15-bloqueurs-humains.md` |

---

## Correctifs Bugbot (courses concurrentes) — 2026-07-26

Source : revue Bugbot NL sur le portail commercial.

| Sévérité | Finding | Correctif |
|---|---|---|
| **Majeur** | `accepter_demande_paiement` / `_palier` mutaient facture/palier **avant** le verrou `UPDATE … statut='ouvert'` | Ordre inversé : `UPDATE … RETURNING` d’abord ; si 0 ligne → erreur concurrence ; puis `marquer_payee` / `patcher_tenant` |
| **Majeur** | Doublons demandes « ouvert » possibles (SELECT puis INSERT) | Index uniques partiels `021` + catch `IntegrityError` côté abonné |

---

Aucun article CGI, taux fiscal ou prestataire de paiement inventé dans cet audit.
**À confirmer** : délais de prescription (Lot 5) ; grille commerciale officielle ; valeurs RCCM/IDU/TVA facture.

---

## Audit sécurité — portail abonné commercial (lecture seule)

**Périmètre** : `migrations/020_portail_abonne_commercial.sql`,
`backend/abonne/{facturation,abonnement,routes}.py`,
`backend/billing/{demandes,routes,factures,auth,dependances}.py`,
`backend/plateforme/{contexte,dependances,rbac,auth}.py`, `migrations/006`
(facture), tests `tests/abonne/test_portail_commercial.py`.

**Méthode** : revue de code + schéma ; pas d’exploitation active ; pas d’invention
de faille HTTP non démontrée. Les findings DB « si SQL arbitraire » sont de la
défense en profondeur (rôle unique `app_revue`).

### Tableau des findings

| Sévérité | Emplacement | Finding |
|---|---|---|
| ~~**High**~~ → **Corrigé** | `migrations/022_facture_rls.sql` | Table `facture` : FORCE RLS + policy ; `billing_lire_facture` DEFINER ; mutations sous `contexte_tenant`. |
| **Medium** | `migrations/020_portail_abonne_commercial.sql:73-160` | `billing_lister_demandes_paiement/palier` en `SECURITY DEFINER` + `GRANT EXECUTE … TO app_revue`. Contournement RLS possible pour **énumérer toutes les demandes cross-tenant** si exécution SQL hors routes staff (pas d’endpoint abonné qui les appelle aujourd’hui). |
| ~~**Medium**~~ → **Corrigé** | `migrations/022` · trigger | `demande_paiement.tenant_id` doit égaler `facture.tenant_id` (trigger SECURITY DEFINER). |
| ~~**Medium**~~ → **Corrigé** | `migrations/022` | `REVOKE UPDATE, DELETE` sur `demande_*` ; clôture staff via `billing_clore_demande_*` SECURITY DEFINER. |
| **Medium** | `backend/plateforme/dependances.py:30-42` · `auth.py` | JWT abonné : `role` / `actif` **non rechargés** depuis `utilisateur` à chaque requête. Après rétrogradation admin→lecteur ou `actif=false`, le jeton conserve `gerer_abonnement` jusqu’à `exp` (TTL 24h). Escalade / révocation retardée (périmètre cabinet, pas cross-tenant). |
| **Low** | `backend/abonne/routes.py:506-524` | `POST …/signaler-paiement` mappe toute `ErreurAbonne` en **400** (y compris facture hors tenant / introuvable), alors que GET détail/PDF renvoient **404**. Pas de fuite différentielle de statut ; incohérence cosmétique. |
| **Info (OK)** | `backend/plateforme/contexte.py` | `set_config('app.tenant_id', …, true)` ≡ **SET LOCAL** partout sur le chemin portail ; aucun `SET` nu / `is_local=false` détecté. |
| **Info (OK)** | `abonne/facturation.py` · `abonne/routes.py` · `billing/routes.py` · test | JWT abonné **n’appelle jamais** `marquer_payee`. Payer = `StaffBillingDep` uniquement. Signalement + garde-fou statut facture inchangé. Testé. |
| **Info (OK)** | `billing/auth.py` · `plateforme/auth.py` | Chaînes JWT distinctes (`typ` + clé HMAC dérivée `:staff`). Jeton tenant refusé sur billing ; jeton staff refusé sur routes abonné. Rôles billing = `billing`\|`ops` seulement. |
| **Info (OK)** | `abonne/facturation.py` · test isolation | IDOR HTTP + RLS facture (0 ligne sans SET LOCAL). Test `test_isolation_factures_et_demandes_paiement`. |
| **Info (OK)** | `plateforme/rbac.py` · routes abonné | `gerer_abonnement` = admin cabinet seul (signalement, patch compte, demande palier). Lecteur/réviseur : lecture factures/abonnement uniquement. Pas d’escalade staff via JWT tenant. |
| **Info (dette)** | `migrations/002` · `abonnement.py:77-79` | Table `tenant` aussi **sans RLS** + `GRANT UPDATE` : mute `palier`/`statut` possible au SQL malgré garde app (`patcher_compte` ne touche que `denomination`). |

### Dette explicite — `facture` RLS

**Fermée** (`022`) :

- FORCE RLS + policy `facture_tenant`.
- `billing_lire_facture` / clôture `demande_*` en SECURITY DEFINER.
- Mutations facture sous `SET LOCAL` ; grants `demande_*` : SELECT + INSERT seulement.

### Non-findings (contrôles demandés — OK)

| Contrôle | Résultat |
|---|---|
| SET LOCAL vs SET | OK |
| RLS `demande_*` + `tenant_id NOT NULL` | OK (FORCE) |
| RLS `facture` FORCE | OK (`022`) |
| Abonné ne marque pas payée | OK (HTTP + code + test) |
| IDOR `facture_id` / demandes (HTTP) | OK (app + RLS) |
| Escalade staff ↔ abonné (JWT) | OK (clés/`typ` séparés) |

**À confirmer** : éventuelle revalidation DB du JWT abonné ; RLS table `tenant` (dette restante).
