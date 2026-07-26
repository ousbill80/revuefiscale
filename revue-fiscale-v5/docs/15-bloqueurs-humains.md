# Bloqueurs humains — checklist 2AàZ

Ce que le code **ne peut pas** inventer. Tant que ces livrables manquent,
les marqueurs `a_confirmer` / « À CONFIRMER » restent affichés.

Voir aussi : `docs/15-session-fiscaliste-7-seuils.md`, `corpus_sources/ATTENTE-CGI-CI-2026.md`,
audit doctrine/portail `docs/24-audit-profondeur-saas.md`.

---

## 1. PDF CGI CI 2026 (intégral)

| | |
|---|---|
| **Statut** | PDF absent — **scrape cgici.com ingéré en brouillon** (`make ingerer-cgici`, voir `docs/17-ingestion-cgici.md`) |
| **Attente PDF** | Déposer `corpus_sources/CGI-CI-2026.pdf` (archive / double source) |
| **Corpus HTML** | ~1495 articles · ~3437 fragments — **≠ visa fiscaliste** |
| **Ensuite PDF** | `make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026` |
| **Débloque** | Porte agent / croisement sourcé ; purge `a_confirmer` reste **humaine** |

L’annexe fiscale 2026 est déjà liée et ingérée (`TYPE=annexe`) : utile pour la veille des
amendements, **insuffisante** seule pour purger les `a_confirmer` de seuils / articles CGI.
**Annexe ≠ CGI intégral.** Croisement : `docs/16-annexe-2026-vs-a-confirmer.md`
(~8 pistes claires sur 121 ; 0 purge auto).

---

## 2. Visa fiscaliste (file `a_confirmer`)

| | |
|---|---|
| **Statut** | 57 fiches / ~121 mentions encore marquées |
| **Outil** | Console `/console` → **À confirmer** |
| **Lot Annexe (~8)** | Filtre Vue → **Pistes Annexe** · checklist `docs/18-lot-fiscaliste-annexe-8.md` · seed `make seed-pistes-annexe` |
| **Lot CGI (~8)** | Filtre Vue → **Pistes CGI** · rapports `docs/19` + `docs/21-cgi-vs-a-confirmer-v2.md` · `make croiser-cgi` puis `make seed-pistes-cgi` (prérequis : `make ingerer-cgici DEPUIS_CACHE=1`) |
| **Faibles (~43)** | Filtre Vue → **Faibles (43)** · catalogue `referentiel/croisement_cgi_2026.json` — **pas** promus en claire |
| **Séance** | Playbook `docs/22-seance-fiscaliste.md` · bandeau **Ordre de séance** dans `/console` → À confirmer (Annexe → CGI → Faibles → Bloqués) + panneau **Contexte CGI** |
| **Vue unifiée** | Filtre Vue → **Pistes sourcées (Annexe+CGI)** (~16) |
| **Workflow OK** | Filtres + détail champ + « Marquer en revue » (note éditeur) |
| **Acceptation** | Console **Propositions** : **Accepter (statut)** · **Préparer patch** (téléchargement, YAML intact) · **Appliquer au YAML** (1 champ / 1 mention + backup + journal). Retrait `a_confirmer` seulement si `retirer_a_confirmer_autorise` **et** case cochée + double confirmation humaine |
| **Interdit** | Purger un `a_confirmer` sans source CGI certaine + action humaine explicite |

Seeds idempotents (file propositions `ouverte` / `a_valider_humain`) — **n'acceptent / ne purgent aucun YAML** par défaut :

```bash
make croiser-cgi            # régénère docs/21 + catalogue (nouvelles pistes)
make seed-editorial-pistes  # Annexe + CGI (alias des deux seeds)
make seed-pistes-annexe     # source annexe_2026_croisement
make seed-pistes-cgi        # source cgi_2026_croisement (idempotent)
```

Export checklist : console **À confirmer** → **Exporter CSV** (`GET /api/v1/editorial/a-confirmer/export.csv`).

« En revue » ≠ validé fiscalement. La purge YAML reste un acte humain sourcé.

---

## 3. Mentions légales facture

| Variable env | Défaut | À fournir |
|---|---|---|
| `FACTURE_RAISON_SOCIALE` | `2AàZ SAS — À CONFIRMER` | Forme / capital exacts |
| `FACTURE_SIEGE` (alias `FACTURE_SIEDGE`) | `À CONFIRMER` | Siège social |
| `FACTURE_RCCM` | `À CONFIRMER` | RCCM réel |
| `FACTURE_IDU` | `À CONFIRMER` | IDU réel |
| `FACTURE_COMPTE_BANCAIRE` | `À CONFIRMER` | IBAN / compte |
| `FACTURE_REGIME_TVA` | `A_CONFIRMER` | Assujetti / exonéré / hors champ |
| `FACTURE_TAUX_TVA` | `À CONFIRMER` | Taux applicable (jamais inventé) |

Renseigner via **Billing → Paramètres** (table `config_editeur`) et/ou `.env`
(modèle : `.env.example`). Le PDF facture lit la fusion saisie → env → À CONFIRMER.

**UI lecture seule** : `/billing` → **Tarifs & mentions** (`GET /api/v1/billing/tarifs-a-confirmer`)
affiche l’inventaire sans édition. Statut : **partiellement adressé** (visibilité staff) —
les vraies valeurs restent un livrable humain 2AàZ.

---

## 4. Grille tarifaire (paliers)

| | |
|---|---|
| **Statut** | Bornes **techniques provisoires** dans `backend/plateforme/paliers.py` — **partiellement adressé** (panneau lecture seule + badge) |
| **Saisie éditeur** | `/billing` → **Paramètres** (écrase le provisoire ; label responsabilité 2AàZ) |
| **Lecture seule** | `/billing` → **Tarifs & mentions** · `GET /api/v1/billing/tarifs-a-confirmer` |
| **Abonné** | `/app` → **Compte** : paliers en lecture seule + badge `tarifs_a_confirmer` ; demande de palier → file staff |
| **API** | `GET/PUT /api/v1/billing/parametres/*` · `GET /api/v1/billing/paliers` · `GET …/tarifs-a-confirmer` · `POST /api/v1/abonnement/demande-palier` |
| **Attente** | Grille commerciale officielle 2AàZ (montants + quotas) |

Ne pas présenter les montants provisoires comme une offre commerciale certifiée.
Vides / incomplets = `tarifs_a_confirmer: true`.

**Self-service vs staff** : l'abonné consulte factures, peut payer via **Paystack**
(carte / Mobile Money) ou signaler un virement (`demande_paiement`), et peut
demander un autre palier (`demande_palier`). `marquer_payee` : staff billing **ou**
webhook Paystack vérifié — jamais un appel JWT abonné direct. Acquisition =
assistée (billing) ; `ALLOW_PUBLIC_PROVISIONING` inchangé.

---

## 4bis. Paystack (`PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY`)

| | |
|---|---|
| **Sans clé** | `POST …/payer-paystack` → **503** ; UI Facturation désactivée + message ; virement OK |
| **Avec clés** | Checkout Visa + Mobile Money CI (Orange, MTN, Wave via Paystack) |
| **Webhook** | Dashboard Paystack → `POST {APP_PUBLIC_URL}/api/v1/webhooks/paystack` (`charge.success`) |
| **Attente** | Clés live/test + URL webhook publiques — **ops 2AàZ** |
| **Montants** | Toujours `facture.montant` stocké (XOF zero-decimal) — jamais inventés |

Voir `.env.example` et `backend/abonne/paystack.py`.

---

## 5. Resend (`RESEND_API_KEY`)

| | |
|---|---|
| **Sans clé (dev)** | Statut `simule_dev` + jeton UI + outbox |
| **Sans clé (prod)** | Statut `echec` explicite — pas de faux envoi |
| **UI** | `/app` Équipe → Outbox ; `/billing` → Emails / Outbox |
| **Attente** | Clé API Resend + domaine vérifié (`RESEND_FROM`) |

---

## 6. Clés LLM multi-fournisseurs (extraction identité)

Pas un bloqueur fiscal : l’IA **propose** un brouillon, l’humain valide.
Sans aucune clé → statut `indisponible` (pas d’invention de champs).

| Variable | Rôle |
|---|---|
| `MOONSHOT_API_KEY` | Priorité **vision / OCR** (DFE scanné, images, PDF image). Format **`sk-…`**. |
| `MOONSHOT_BASE_URL` | Défaut `https://api.moonshot.ai/v1` (Chine : `api.moonshot.cn`) |
| `MOONSHOT_MODEL` / `MOONSHOT_MODEL_VISION` | Défaut **`kimi-k3`** (flagship vision native internationale). CN : `moonshot-v1-*-vision-preview` possibles. |
| `MOONSHOT_REASONING_EFFORT` | `low` \| `high` \| `max` (K3 thinking ; défaut ops identité = `low`) |
| `LLM_VISION_TIMEOUT_SECONDS` | Timeout vision (défaut **180**) |
| `LLM_VISION_PDF_MAX_PAGES` / `DPI` / `JPEG_QUALITY` | Rasterisation scan (défaut **3** pages / **140** dpi / JPEG **82**) |
| `DEEPSEEK_API_KEY` | Texte / extraction structurée (failover) — **pas** pour remplacer la vision sur scans |
| `DEEPSEEK_MODEL` | Ex. `deepseek-chat` ou `deepseek-v4-flash` |
| `LLM_PROVIDER_ORDER` | Ordre maître (défaut `moonshot,deepseek`) |
| `LLM_VISION_ORDER` / `LLM_TEXT_ORDER` | Affinages vision vs texte |
| `MODELE_*` | Fallback legacy OpenAI-compatible |
| `PIECES_SESSION_TTL_HOURS` | Purge uploads sans fiche (défaut **72**) |

Implémentation : `backend/socle/llm_providers.py` · branchement
`proposer-identite` / `verifier-conformite`. Modèle d'env : `.env.example`
(**sans secrets**). Failover sur timeout / 429 / 5xx / auth.
Messages UX métier : français neutre (**sans** nom de fournisseur ni variable d'env) ;
détails techniques uniquement dans les logs serveur.

**Ops** : coller `MOONSHOT_API_KEY=sk-…` dans `revue-fiscale-v5/.env` (pas ailleurs),
puis `make check-llm` (masque les secrets). Vision = **`kimi-k3`** sur
`api.moonshot.ai`. DeepSeek seul suffit pour PDF texte ; les scans exigent la
vision. `uvicorn --reload` ne recharge pas le `.env` seul — le runtime recharge
au besoin, sinon relancer `make dev`.

**Flux pièces (abonné, RLS)**

1. Joindre (session UUID ou `contribuable_id`) → Extraire → Revue → Appliquer → Enregistrer.
2. L'IA n'écrit jamais dans `contribuable` ; `proposition_identite` = brouillon.
3. PDF scan : nécessite **poppler** (`pdftotext` + `pdftoppm`). Sinon message explicite
   dans la réponse + `GET /sante` → `poppler`. Fallback : joindre `.txt` / image.
4. Sessions orphelines : `POST …/abandonner-session` (UI) ou
   `make purge-sessions-upload` / `python -m backend.scripts.purge_sessions_upload`
   (ops, TTL, `SET LOCAL` par tenant). Dry-run : `make purge-sessions-upload DRY=1`.
5. Mission depuis fiche : wizard Sources affiche le dossier identité (NCC, centre, pièces)
   en **informatif** — hors source comptable / moteur.

**Ops** : si une clé a circulé hors `.env` (chat, ticket…), **rotation**
recommandée chez le fournisseur.

---

## Récapitulatif

| Bloqueur | Qui fournit | Bloque quoi |
|---|---|---|
| CGI PDF | 2AàZ / juridique | Purges sourcées art. / seuils |
| Visa fiscaliste | Fiscaliste 2AàZ | Certification référentiel |
| Mentions facture | Admin / juridique 2AàZ | PDF commercial « propre » — **visibilité** OK via `/billing` Tarifs & mentions |
| Tarifs | Commercial 2AàZ | Communication pricing — **visibilité** provisoire OK ; grille officielle absente |
| Paystack | Ops 2AàZ | Paiement carte / MoMo abonnement (sinon virement secours) |
| Resend | Ops 2AàZ | Emails réels (OTP, invitations) |
| Clés LLM | Ops 2AàZ | Extraction / conformité pièces (brouillon) — optionnel |

Aucun article, taux, seuil CGI ni RCCM inventé dans ce document.

**Identité contribuable (libellés UI)** — intitulés IME / TEE / RME / TCE / RNI / RSI
confirmés côté DGI (éd. système fiscal + Impôts et taxes 2025 ; Annexe 2026 pour les
dénominations « impôt des microentreprises » / « taxe d’Etat de l’entreprenant »).
Voir `frontend/mission/src/legalite.ts`. Ce n’est **pas** une validation de seuils de CA
ni de règles de calcul (référentiel / millésime).

---

## Hors checklist — démo commercial `/app`

Parcours seed documenté (pas un bloqueur humain) : `make seed && make demolot`.
Voir `docs/11-saas-surfaces.md` § Démo commercial. Credentials `CABINET_DEMO_*` (`.env.example`),
UI chips localhost + `ENV=dev` uniquement.

## Hors checklist — modèle d’engagement cabinet

Conception produit (périmètre partiel, statuts conclusion, seuil, suivi, prescription) :
`docs/23-engagement-cabinet.md`. Lot 1 prioritaire = cadrage + `perimetre_impots`.

**Lot 5 — prescription CGI CI** : checklist bloquante **À confirmer** (base légale CGI/LPF,
point de départ, suspensions, exceptions reports déficitaires / crédits TVA) dans
`docs/23-engagement-cabinet.md` § Lot 5.

**Ce que le code a le droit de faire aujourd’hui (R5 socle)** :

- PATCH manuel `risque.statut = prescrit` (jugement cabinet) — **autorisé**.
- `evaluer_prescription` / `python -m backend.scripts.evaluer_prescription` —
  **présent, non armé** : no-op + motif `attente_visa_lot5` tant qu’il n’existe pas
  de paramètres millésimés sourcés en référentiel (contrat table éditoriale
  `parametre_prescription` : `impot`, `millesime`, `delai_annees`, `point_depart`,
  `reference_legale` — **aucune de ces valeurs n’est inventée ni lue depuis
  l’Annexe PDF**).

**Ce qui reste interdit sans visa fiscaliste** :

- Délai / article / point de départ en dur dans le code applicatif.
- Armer le calcul de dates ou le filtre UX « exercice encore repris ».
- Remplir `parametre_prescription` (ou équivalent pivot) sans citations CGI/LPF
  visées case par case (checklist § Lot 5).

**Visa humain — texte à cocher avant armement R5** :

> Je confirme, pour chaque couple (impôt, millésime) publié dans
> `parametre_prescription` : (1) article(s) CGI CI / LPF exacts, (2) durée du
> délai, (3) point de départ du délai, (4) suspensions (ou « néant confirmé »),
> (5) exceptions reports déficitaires / crédits TVA — sources citées, sans
> analogie française. Sans cette confirmation, l’auto-`prescrit` reste désarmé.

**Registre post-mission** (risque au contribuable + actions) :
`docs/25-registre-risques-actions.md` — R1–R4 livrés ; R5 = socle non armé ci-dessus.

