# Registre des risques & suivi des actions

> **Conception unifiée** (trois documents en un) — à figer **avant** toute
> migration runtime / « Phase 0 » schéma.
>
> Chaînon manquant économique : le rapport n’est pas la fin du produit —
> c’est le début du suivi qui rend le renouvellement d’abonnement évident.
>
> Voir aussi : `docs/23-engagement-cabinet.md` (mission / tâches),
> `docs/03-schema-donnees.md`, `AGENTS.md`, `docs/15-bloqueurs-humains.md`.

---

## 0. Décision éditoriale : un seul livrable de conception

Les trois sujets ci-dessous **partagent le même schéma** et la même doctrine
d’appartenance. Les écrire séparément créerait trois vérités divergentes.

| Section | Contenu |
|---|---|
| **I** | Modèle de mission prolongé (enchaînement bout en bout) |
| **II** | Registre des risques (survit à la mission) |
| **III** | Suivi des actions (corrective / préventive) |

**Statut code** : lots **R1–R4 livrés** (migrations `020`/`021`/`024`, API, UI
registre / dashboard / N+1). `point_ouvert` (`017`) = **legacy lecture seule**
(GET) ; POST/PATCH et `…/point-ouvert` → **410 Gone** (utiliser `/risques`).
**R5** : socle `evaluer_prescription` **livré mais non armé** (aucun délai CGI
dans le référentiel / pivot) — auto = no-op ; PATCH manuel `prescrit` OK.

---

## I — Modèle de mission prolongé

### I.1 Enchaînement unique

```text
mission
  └── objectif fiscal (impôt + exercices)
        └── tache          ← plan dérivé déterministe (019)
              └── conclusion
                    └── [si anomalie validée] → risque (contribuable)
                          └── action[] (corrective | preventive)
```

| Étape | Qui décide | Nature |
|---|---|---|
| Liste des tâches | Référentiel + profil + périmètre + version épinglée | **Dérivé**, déterministe |
| Montants / sens | Moteur | Déterministe |
| Statut conclusion | Humain (brouillon moteur) | Validation |
| Naissance d’un risque | Humain (ou règle produit explicite à la clôture) | **Pas** un LLM |
| Plan d’actions | Humain / copilote **propose** seulement | Copilote ≠ conclusion |

### I.2 Ce que la mission produit encore

Inchangé par rapport à `docs/23` + `019` :

- cadrage, objectifs fiscaux, tâches, conclusions, rapport « non examiné » ;
- à la clôture : **R4** — création d’un `risque` depuis tâches `anomalie`
  (`creer_risques_depuis_anomalies`) ; **plus** de création `point_ouvert`.

### I.3 Ce que la mission ne porte plus

Le **risque ouvert** et ses **actions** ne meurent pas avec
`mission.statut = cloturee`. Ils vivent sur le **contribuable**.

---

## II — Registre des risques

### II.1 Appartenance (non négociable)

**Le risque appartient au contribuable, pas à la mission.**

- `contribuable_id NOT NULL` + `tenant_id NOT NULL` + RLS ;
- `origine_conclusion_id` (et mission source) = **provenance**, pas parent
  de cycle de vie ;
- si on rattache le risque à la mission seule, il disparaît à la clôture et
  on perd le levier d’abonnement.

### II.2 Pourquoi ça change l’économie SaaS

| Sans registre | Avec registre |
|---|---|
| Rapport = livrable unique | Rapport = ouverture du suivi |
| Résiliation = perte faible | Résiliation = perte du registre d’engagements |
| Outil ouvert en période de mission | Outil ouvert un mardi de mai (retards) |

### II.3 Schéma cible (domaine abonné)

```sql
CREATE TABLE risque (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id        BIGINT NOT NULL REFERENCES contribuable(id),
    origine_conclusion_id  BIGINT REFERENCES conclusion(id) ON DELETE SET NULL,
    origine_mission_id     BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    origine_tache_id       BIGINT REFERENCES tache(id) ON DELETE SET NULL,
    impot                  TEXT NOT NULL,           -- code pivot
    reference_legale       TEXT,                    -- article / source, pas inventé
    libelle                TEXT NOT NULL,
    montant_estime         NUMERIC(18,2),           -- quantification humaine
    penalites_estimees     NUMERIC(18,2),           -- estimation humaine ; ≠ calcul CGI auto
    probabilite            TEXT NOT NULL
                           CHECK (probabilite IN ('probable','possible','faible')),
    statut                 TEXT NOT NULL DEFAULT 'ouvert'
                           CHECK (statut IN (
                             'ouvert', 'en_traitement', 'resolu',
                             'accepte', 'prescrit'
                           )),
    exercice_origine       SMALLINT NOT NULL,
    derniere_revue         DATE,
    motif_acceptation      TEXT,                    -- si statut = accepte
    accepte_le             TIMESTAMPTZ,
    accepte_par            TEXT,                    -- acteur cabinet / client tracé
    prescrit_le            TIMESTAMPTZ,             -- si statut = prescrit
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### II.4 Statuts risque — doctrine

| Statut | Signification | Qui |
|---|---|---|
| `ouvert` | Constat engagé, pas encore d’action active | Cabinet |
| `en_traitement` | Au moins une action non close | Dérivé / cabinet |
| `resolu` | Actions requises **vérifiées** et closes | Cabinet (jamais auto-client) |
| `accepte` | Client **choisit de porter** le risque — tracé et daté | Cabinet + preuve de décision |
| `prescrit` | Clos par écoulement du temps | Auto **uniquement** si délai millésimé sourcé (Lot 5) ; sinon **manuel** |

**Interdit** : inventer un délai de prescription CGI en dur dans le code.

**R5 — état réel** :

| Mode | Statut |
|---|---|
| PATCH manuel `statut=prescrit` (+ `prescrit_le`) | **Actif** (cabinet) |
| Job / `evaluer_prescription` | **Socle présent, non armé** — lit uniquement `parametre_prescription` (table éditoriale **absente** tant que visa Lot 5) ; sinon no-op + log `attente_visa_lot5` |
| Calcul de dates / filtre « exercice encore repris » | **Interdit** sans paramètres sourcés (délai + point de départ + base légale) |

Ops : `python -m backend.scripts.evaluer_prescription` (dry-run possible). Voir
`docs/15-bloqueurs-humains.md` (Lot 5) et `backend/plateforme/prescription.py`.

### II.5 Probabilité & montants

- `probable | possible | faible` = **jugement humain** (déjà dit dans
  `docs/23` §3.4) — pas un score LLM dans le résultat fiscal.
- `montant_estime` / `penalites_estimees` = estimations de suivi, **distinctes**
  du montant déterministe de la `conclusion` (qui reste l’artefact de calcul).

### II.6 Pont avec `point_ouvert` (R4 livré)

| Avant (`017`) | Après R4 |
|---|---|
| Créé à la clôture depuis anomalies | Clôture → `risque` seulement |
| Statuts `ouvert \| repris \| clos` | Statuts risque (ouvert…prescrit) |
| Bandeau N+1 | Résumé registre risques |

Migration `024` : backfill `point_ouvert` (liés à une conclusion) → `risque`
(statut mappé). `point_ouvert` reste en **lecture legacy** (GET `/points-ouverts`,
table + RLS conservées). **Écritures coupées** : POST/PATCH `/points-ouverts` et
POST `…/conclusions/{id}/point-ouvert` → **410 Gone** — message « utiliser
`/api/v1/risques` ».

---

## III — Suivi des actions

### III.1 Cycle réel (imposé par la pratique)

```text
Constat validé (conclusion / risque)
  → Recommandation acceptée | contestée | différée
  → Action assignée (responsable + échéance)
  → Suivi / relances
  → Preuve déposée
  → VÉRIFICATION cabinet          ← étape que tout le monde saute
  → Close
```

Trois règles non négociables :

1. **Une recommandation peut être refusée** — `refusee` + `motif_refus` +
   date : protège le cabinet au contrôle.
2. **Corrective ≠ préventive** — réparer mars 2024 ≠ empêcher mars 2025.
   Sans préventive, la même anomalie revient et le client demande pourquoi.
3. **Personne ne se clôture soi-même** — le client dépose une preuve ;
   seul le cabinet passe à `verifiee` / `close`. Pas de statut
   « auto-déclaré résolu » opposable.

### III.2 Schéma cible

```sql
CREATE TABLE action_risque (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          BIGINT NOT NULL REFERENCES tenant(id),
    risque_id          BIGINT NOT NULL REFERENCES risque(id) ON DELETE CASCADE,
    nature             TEXT NOT NULL
                       CHECK (nature IN ('corrective', 'preventive')),
    libelle            TEXT NOT NULL,
    responsable_user_id BIGINT REFERENCES utilisateur(id) ON DELETE SET NULL,
    responsable_label  TEXT,                    -- si hors utilisateur cabinet
    echeance           DATE,
    statut             TEXT NOT NULL DEFAULT 'proposee'
                       CHECK (statut IN (
                         'proposee', 'acceptee', 'refusee', 'en_cours',
                         'preuve_deposee', 'verifiee', 'close', 'abandonnee'
                       )),
    motif_refus        TEXT,
    preuve_piece_id    BIGINT REFERENCES piece_mission(id) ON DELETE SET NULL,
    -- ou URI stockage cabinet ; préférer pièce cloisonnée quand possible
    preuve_uri         TEXT,
    preuve_deposee_le  TIMESTAMPTZ,
    verifiee_par       TEXT,
    verifiee_le        TIMESTAMPTZ,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le             TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Nom de table **`action_risque`** (pas `action`) : évite le mot réservé SQL /
confusion avec « action » générique d’audit.

### III.3 Transitions (rappel)

```text
proposee → acceptee | refusee | abandonnee
acceptee → en_cours
en_cours → preuve_deposee | abandonnee
preuve_deposee → verifiee | en_cours   (rejet de preuve)
verifiee → close
```

- `refusee` exige `motif_refus` non vide.
- `close` exige `verifiee_par` + `verifiee_le` (cabinet).
- Portail client (`/client`) : peut déposer preuve / accepter-refuser
  proposition — **jamais** `verifiee` / `close`.

---

## IV — Trois écrans produit

| Écran | Contenu | Pourquoi |
|---|---|---|
| **Registre contribuable** | Risques ouverts par impôt / exercice + cumul montants estimés | Document que le dirigeant veut — absent du rapport de mission |
| **Tableau de bord cabinet** | Actions en retard, tous clients | Fait ouvrir l’outil hors période de mission |
| **Ouverture mission N+1** | « 6 reco, 3 traitées, 2 en retard, 1 refusée » | Justifie la reconduction |

La section N+1 s’appuie sur le résumé `risque` (plus le bandeau
`point_ouvert`, sauf fallback legacy si aucun risque encore).

---

## V — Isolation, pivot, interdits

### Domaine

| Table | Domaine | `tenant_id` | RLS |
|---|---|---|---|
| `risque` | Abonné | OUI NOT NULL | OUI |
| `action_risque` | Abonné | OUI NOT NULL | OUI |

### Format pivot

- `impot` = même taxonomie que le pivot (`docs/02-format-pivot.md`).
- `reference_legale` = citation sourcée (référentiel / conclusion), **pas**
  un article inventé par l’UI.
- Aucun taux / délai de prescription en dur dans le code applicatif.

### Copilote

Peut proposer libellés d’actions, relances, brouillons de motif — file de
validation humaine. **Ne crée pas** un risque « calculé » ni ne clôture.

---

## VI — Lots d’implémentation (après conception)

| Lot | Contenu | Dépendance |
|---|---|---|
| **R0** | Doc + décisions (ce fichier) | — | **Fait** |
| **R1** | Migration `risque` + API registre + écran contribuable | R0 | **Fait** (`020`) |
| **R2** | `action_risque` + transitions + preuves + vérif cabinet | R1 | **Fait** (`021`) |
| **R3** | Dashboard cabinet (retards) + section ouverture N+1 | R2 | **Fait** |
| **R4** | Bascule `point_ouvert` → `risque` + tests isolation | R1–R3 | **Fait** (`024`) |
| **R5** | Auto-`prescrit` | Socle non armé livré ; **armement** bloqué visa Lot 5 | Socle OK / arme Ouvert |

---

## VII — Critères d’acceptation conception

- [x] Appartenance risque = contribuable (décision écrite).
- [x] Enchaînement tâche → conclusion → risque → action documenté.
- [x] Refus tracé ; corrective ≠ préventive ; clôture = vérif cabinet.
- [x] `prescrit` sans délai inventé.
- [x] Trois écrans nommés.
- [ ] Migration + API + UI — **hors R0** (lots R1+).

---

*2AàZ / ZenAPI — conception registre post-mission. Aucun article ni délai CGI inventé.*
