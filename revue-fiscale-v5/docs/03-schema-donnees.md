# Schéma de données

PostgreSQL 16. Deux domaines : **éditorial** (commun) et **abonné** (cloisonné par RLS).

---

## 0. Plateforme — tenants et abonnements

```sql
CREATE TABLE tenant (
    id             BIGSERIAL PRIMARY KEY,
    denomination   TEXT NOT NULL,
    type           TEXT NOT NULL,          -- cabinet | entreprise
    palier         TEXT NOT NULL,          -- essentiel | standard | premium | souverain
    statut         TEXT NOT NULL DEFAULT 'actif',
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Identité légale abonné (026) — optionnelle, éditable via /compte
    ncc            TEXT,
    rccm           TEXT,
    dfe            TEXT,
    forme_juridique TEXT,
    siege_social   TEXT,
    commune        TEXT,
    centre_impots  TEXT,
    capital_social NUMERIC(18, 2)
);

CREATE TABLE utilisateur (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    email      TEXT NOT NULL UNIQUE,
    role       TEXT NOT NULL,              -- admin | reviseur | lecteur
    actif      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE quota (
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    periode          DATE   NOT NULL,      -- premier jour du mois
    missions_incluses INT   NOT NULL,
    missions_utilisees INT  NOT NULL DEFAULT 0,
    appels_modele    INT    NOT NULL DEFAULT 0,
    tokens_entree    BIGINT NOT NULL DEFAULT 0,
    tokens_sortie    BIGINT NOT NULL DEFAULT 0,
    cout_estime      NUMERIC(12,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, periode)
);
```

---

## 1. Domaine éditorial — commun, **sans `tenant_id`**

```sql
CREATE TABLE version_referentiel (
    id           BIGSERIAL PRIMARY KEY,
    libelle      TEXT NOT NULL UNIQUE,     -- 'v2026.3'
    publiee_le   TIMESTAMPTZ,              -- NULL = brouillon
    publiee_par  TEXT,
    note         TEXT
);

CREATE TABLE regle (
    identifiant TEXT PRIMARY KEY,          -- BIC-CHG-18G-DONS
    impot       TEXT NOT NULL,
    categorie   TEXT,
    libelle     TEXT NOT NULL,
    actif       BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE regle_version (
    id                      BIGSERIAL PRIMARY KEY,
    regle_id                TEXT NOT NULL REFERENCES regle(identifiant),
    version_referentiel_id  BIGINT NOT NULL REFERENCES version_referentiel(id),
    reference_article       TEXT NOT NULL,
    reference_source        TEXT NOT NULL,
    millesime               SMALLINT NOT NULL,
    date_effet              DATE NOT NULL,
    date_fin                DATE,
    profils_applicables     JSONB NOT NULL,
    comptes_declencheurs    TEXT[] NOT NULL,
    nature                  TEXT NOT NULL,
    condition_declenchement TEXT NOT NULL,
    conditions_fond         TEXT,
    formule_plafonnement    TEXT,
    questions               JSONB NOT NULL DEFAULT '[]',
    expression_resultat     TEXT NOT NULL,
    niveau_risque           TEXT NOT NULL,
    a_confirmer             JSONB NOT NULL DEFAULT '[]',
    CHECK (date_fin IS NULL OR date_fin > date_effet),
    CHECK (niveau_risque IN ('faible','moyen','eleve'))
);
CREATE INDEX ON regle_version (version_referentiel_id, regle_id);
CREATE INDEX ON regle_version (regle_id, date_effet, date_fin);
CREATE INDEX ON regle_version USING GIN (comptes_declencheurs);

CREATE TABLE effet_croise (
    source_id   BIGINT NOT NULL REFERENCES regle_version(id),
    cible_regle TEXT   NOT NULL REFERENCES regle(identifiant),
    type        TEXT   NOT NULL,           -- declenche | remet_en_cause | alimente | neutralise
    commentaire TEXT,
    PRIMARY KEY (source_id, cible_regle, type)
);

CREATE TABLE sanction (
    id           BIGSERIAL PRIMARY KEY,
    reference    TEXT NOT NULL,
    type         TEXT NOT NULL,            -- amende_fixe | majoration | interet_retard
    montant_fixe NUMERIC(18,2),
    taux         NUMERIC(6,4),
    base         TEXT,
    date_effet   DATE NOT NULL,
    date_fin     DATE
);
```

Le corpus réglementaire — `source_document`, `article`, `version_article`,
`relation_normative`, `fragment` — appartient également au domaine éditorial. Voir
`docs/04-cerveau-memoire-reglementaire.md`.

---

## 2. Domaine abonné — cloisonné

```sql
CREATE TABLE contribuable (
    id                   BIGSERIAL PRIMARY KEY,
    tenant_id            BIGINT NOT NULL REFERENCES tenant(id),
    denomination         TEXT NOT NULL,
    ncc                  TEXT,                 -- n° compte contribuable DGI (= n° sur DFE)
    rccm                 TEXT,
    forme                TEXT,                 -- pm | pp
    dfe                  TEXT,                 -- réf. DFE optionnelle (≠ 2e saisie du NCC)
    regime_fiscal        TEXT,                 -- défaut profil mission
    forme_juridique      TEXT,                 -- SA, SARL… (≠ forme pm|pp)
    siege_social         TEXT,                 -- adresse / quartier (siège effectif)
    commune              TEXT,                 -- ville / commune (rattachement)
    centre_impots        TEXT,                 -- centre DGI (libellé libre)
    capital_social       NUMERIC(18,2),        -- XOF — identité, pas seuil moteur
    mois_cloture         SMALLINT,             -- 1–12 (défaut pratique : 12)
    activite_principale  TEXT,                 -- secteur + précision → défaut profil
    date_immatriculation   DATE                   -- identité DGI
);

CREATE TABLE mission (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id        BIGINT NOT NULL REFERENCES contribuable(id),
    exercice               SMALLINT NOT NULL,
    profil                 JSONB NOT NULL,
    version_referentiel_id BIGINT NOT NULL REFERENCES version_referentiel(id),  -- ÉPINGLAGE
    statut                 TEXT NOT NULL DEFAULT 'cadrage',
    -- Cadrage d'engagement (lot 1) — gelé dès statut ≠ cadrage
    type_engagement        TEXT NOT NULL DEFAULT 'autre'
                           CHECK (type_engagement IN (
                             'preventive', 'cac', 'due_diligence',
                             'assistance_controle', 'autre'
                           )),
    perimetre_impots       JSONB,              -- NULL = tous ; [] rejeté en API
    exclusions_declarees   TEXT,               -- hors codes (lettre de mission)
    seuil_signification    NUMERIC(18,2),      -- matérialité cabinet (lot 3, colonne en 015)
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Codes perimetre_impots = pivot impot :
-- BIC, TVA, RAS, ITS, CE, IRC, IRVM, PAT, FONC, ENR, TIMBRE, OBL, OBNL, RA.

-- Objectifs narratifs (plusieurs par mission) — libellés libres, hors moteur
CREATE TABLE mission_objectif (
    id          BIGSERIAL PRIMARY KEY,
    tenant_id   BIGINT NOT NULL REFERENCES tenant(id),
    mission_id  BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    ordre       INT NOT NULL DEFAULT 0,
    libelle     TEXT NOT NULL,               -- libre cabinet — pas de catalogue CGI
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Objectifs fiscaux (impôt + exercices) — source de vérité du périmètre
CREATE TABLE objectif (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    mission_id       BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    impot            TEXT NOT NULL,
    exercices        SMALLINT[] NOT NULL,
    dans_perimetre   BOOLEAN NOT NULL DEFAULT TRUE,
    motif_exclusion  TEXT,
    UNIQUE (tenant_id, mission_id, impot)
);

-- Tâches — plan dérivé déterministe (hors LLM) ; conclusion = montants
CREATE TABLE tache (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    objectif_id      BIGINT NOT NULL REFERENCES objectif(id) ON DELETE CASCADE,
    regle_version_id BIGINT REFERENCES regle_version(id),
    statut           TEXT NOT NULL DEFAULT 'a_faire',
    assignee_a       BIGINT REFERENCES utilisateur(id),
    bloquee_par      BIGINT[] NOT NULL DEFAULT '{}',
    piece_attendue   TEXT,
    conclusion_id    BIGINT REFERENCES conclusion(id),
    UNIQUE (objectif_id, regle_version_id)
);

CREATE TABLE solde_compte (
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    mission_id BIGINT NOT NULL REFERENCES mission(id),
    compte     TEXT   NOT NULL,
    libelle    TEXT,
    debit      NUMERIC(18,2) NOT NULL DEFAULT 0,
    credit     NUMERIC(18,2) NOT NULL DEFAULT 0,
    PRIMARY KEY (mission_id, compte)
);

-- Pièces dossier : une source_active alimente solde_compte ; les annexes
-- sont des pièces jointes (traçabilité) sans écrasement des soldes.
CREATE TABLE piece_mission (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    mission_id       BIGINT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
    type_piece       TEXT NOT NULL,   -- balance | etats_financiers | grand_livre | fec | autre
    role             TEXT NOT NULL,   -- source_active | annexe
    nom_fichier      TEXT NOT NULL,
    chemin_stockage  TEXT NOT NULL,   -- relatif sous var/pieces/ (local/dev)
    taille_octets    BIGINT,
    content_type     TEXT,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- UNIQUE partiel : une seule source_active par mission (voir migration 010).

CREATE TABLE execution (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  BIGINT NOT NULL REFERENCES tenant(id),
    mission_id BIGINT NOT NULL REFERENCES mission(id),
    lancee_le  TIMESTAMPTZ NOT NULL DEFAULT now(),
    lancee_par TEXT NOT NULL
);

CREATE TABLE conclusion (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        BIGINT NOT NULL REFERENCES tenant(id),
    execution_id     BIGINT NOT NULL REFERENCES execution(id),
    regle_version_id BIGINT NOT NULL REFERENCES regle_version(id),
    montant          NUMERIC(18,2),
    sens             TEXT,                 -- reintegration | deduction
    niveau_risque    TEXT NOT NULL,
    reponses         JSONB NOT NULL,
    amendee_par      TEXT,
    commentaire      TEXT,
    -- Statut revue (lot 2) — brouillon moteur, validation humaine
    statut           TEXT NOT NULL DEFAULT 'anomalie'
                     CHECK (statut IN (
                       'conforme', 'anomalie', 'sous_seuil',
                       'non_verifiable', 'hors_perimetre'
                     )),
    piece_mission_id BIGINT REFERENCES piece_mission(id) ON DELETE SET NULL
    -- cohérence pièce ↔ mission/tenant : trigger + contrôle API (016)
);

-- Points ouverts inter-missions (lot 4) — LEGACY après R4 (`024`)
-- Lecture seule recommandée ; source N+1 = risque
CREATE TABLE point_ouvert (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id    BIGINT NOT NULL REFERENCES contribuable(id),
    mission_source_id  BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    conclusion_id      BIGINT REFERENCES conclusion(id) ON DELETE SET NULL,
    texte              TEXT NOT NULL,
    statut             TEXT NOT NULL DEFAULT 'ouvert'
                       CHECK (statut IN ('ouvert', 'repris', 'clos')),
    mission_reprise_id BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le             TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Registre risques / actions (docs/25, R1–R4) — appartient au contribuable
CREATE TABLE risque (
    id                     BIGSERIAL PRIMARY KEY,
    tenant_id              BIGINT NOT NULL REFERENCES tenant(id),
    contribuable_id        BIGINT NOT NULL REFERENCES contribuable(id),
    origine_conclusion_id  BIGINT REFERENCES conclusion(id) ON DELETE SET NULL,
    origine_mission_id     BIGINT REFERENCES mission(id) ON DELETE SET NULL,
    origine_tache_id       BIGINT REFERENCES tache(id) ON DELETE SET NULL,
    impot                  TEXT NOT NULL,
    reference_legale       TEXT,
    libelle                TEXT NOT NULL,
    montant_estime         NUMERIC,
    penalites_estimees     NUMERIC,
    probabilite            TEXT NOT NULL DEFAULT 'possible'
                           CHECK (probabilite IN ('probable', 'possible', 'faible')),
    statut                 TEXT NOT NULL DEFAULT 'ouvert'
                           CHECK (statut IN (
                             'ouvert', 'en_traitement', 'resolu', 'accepte', 'prescrit'
                           )),
    exercice_origine       INTEGER NOT NULL,
    derniere_revue         DATE,
    motif_acceptation      TEXT,
    accepte_le             TIMESTAMPTZ,
    accepte_par            TEXT,
    prescrit_le            TIMESTAMPTZ,
    cree_le                TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE action_risque (
    id                 BIGSERIAL PRIMARY KEY,
    tenant_id          BIGINT NOT NULL REFERENCES tenant(id),
    risque_id          BIGINT NOT NULL REFERENCES risque(id) ON DELETE CASCADE,
    type_action        TEXT NOT NULL
                       CHECK (type_action IN ('corrective', 'preventive')),
    libelle            TEXT NOT NULL,
    responsable_id     BIGINT REFERENCES utilisateur(id) ON DELETE SET NULL,
    echeance           DATE,
    statut             TEXT NOT NULL DEFAULT 'proposee'
                       CHECK (statut IN (
                         'proposee', 'acceptee', 'refusee', 'en_cours',
                         'preuve_deposee', 'verifiee', 'close', 'abandonnee'
                       )),
    motif_refus        TEXT,
    preuve_piece_id    BIGINT REFERENCES piece_mission(id) ON DELETE SET NULL,
    preuve_uri         TEXT,
    preuve_deposee_le  TIMESTAMPTZ,
    verifiee_par       TEXT,
    verifiee_le        TIMESTAMPTZ,
    cree_le            TIMESTAMPTZ NOT NULL DEFAULT now(),
    maj_le             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE journal_audit (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenant(id),
    mission_id   BIGINT REFERENCES mission(id),
    horodatage   TIMESTAMPTZ NOT NULL DEFAULT now(),
    acteur       TEXT NOT NULL,
    action       TEXT NOT NULL,
    charge_utile JSONB NOT NULL,
    hash_prec    TEXT,
    hash         TEXT NOT NULL
);

CREATE TABLE contestation (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenant(id),
    regle_id     TEXT   NOT NULL REFERENCES regle(identifiant),
    version_ref  TEXT   NOT NULL,
    motif        TEXT   NOT NULL,
    statut       TEXT   NOT NULL DEFAULT 'ouverte',
    reponse      TEXT,
    traitee_le   TIMESTAMPTZ
);
```

---

## 3. Les politiques RLS

À créer **dans la même migration** que la table. Une table cloisonnée sans politique est une fuite
en attente.

```sql
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['contribuable','mission','mission_objectif','objectif','tache','solde_compte','piece_mission','execution',
                           'conclusion','point_ouvert','risque','action_risque','journal_audit','contestation','utilisateur',
                           'facture','demande_paiement','demande_palier']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE  ROW LEVEL SECURITY', t);
    EXECUTE format($f$
      CREATE POLICY %1$I_tenant ON %1$I
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::BIGINT)
    $f$, t);
  END LOOP;
END $$;
```

`USING` filtre les lectures, `WITH CHECK` empêche d'écrire une ligne portant le `tenant_id` d'un
autre. Les deux sont nécessaires. `NULLIF(..., '')` évite qu'une chaîne vide (GUC remis à zéro)
fasse planter le cast au lieu de refuser.

**Contexte absent ou vide → comparaison fausse → zéro ligne.** C'est le refus par défaut, et c'est
voulu.

### Facture commerciale et demandes (migration `022`)

`facture` porte `tenant_id NOT NULL` et est soumise à **FORCE RLS** (règle 6). Lecture staff
cross-tenant via `billing_lire_facture` / `billing_lister_factures` (`SECURITY DEFINER`).
Mutations applicatives sous `SET LOCAL` (`contexte_tenant`).

`demande_paiement` : trigger `trg_demande_paiement_tenant_facture` exige
`NEW.tenant_id = facture.tenant_id`. Clôture staff uniquement via
`billing_clore_demande_paiement` / `billing_clore_demande_palier` (`SECURITY DEFINER`) —
`UPDATE` / `DELETE` révoqués pour `app_revue` (INSERT + SELECT conservés).

### Le rôle applicatif

```sql
CREATE ROLE app_revue LOGIN PASSWORD :'mdp';
-- ni SUPERUSER, ni BYPASSRLS, ni propriétaire des tables
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_revue;
REVOKE UPDATE, DELETE ON journal_audit FROM app_revue;   -- écriture seule
REVOKE UPDATE, DELETE ON demande_paiement, demande_palier FROM app_revue;
```

---

## 4. Couche d'intelligence

```sql
CREATE TABLE proposition (
    id             BIGSERIAL PRIMARY KEY,
    type           TEXT NOT NULL,          -- regle | maj_regle | mapping | redaction
    contenu        JSONB NOT NULL,
    citations      BIGINT[] NOT NULL,
    statut         TEXT NOT NULL DEFAULT 'en_attente',
    modele         TEXT NOT NULL,
    version_prompt TEXT NOT NULL,
    cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
    valide_par     TEXT,
    valide_le      TIMESTAMPTZ,
    commentaire    TEXT,
    CHECK (cardinality(citations) > 0),    -- pas de proposition sans source
    CHECK (statut IN ('en_attente','acceptee','corrigee','rejetee'))
);

CREATE TABLE appel_modele (
    id             BIGSERIAL PRIMARY KEY,
    tenant_id      BIGINT REFERENCES tenant(id),   -- NULL = usage éditorial mutualisé
    horodatage     TIMESTAMPTZ NOT NULL DEFAULT now(),
    modele         TEXT NOT NULL,
    version_prompt TEXT NOT NULL,
    usage          TEXT NOT NULL,          -- veille | conversion | mapping | grand_livre | redaction
    tokens_entree  INT NOT NULL,
    tokens_sortie  INT NOT NULL,
    cout_estime    NUMERIC(12,4) NOT NULL,
    cache_touche   BOOLEAN NOT NULL DEFAULT FALSE,
    fragments      BIGINT[] NOT NULL
);

CREATE TABLE cas_evaluation (
    id                   BIGSERIAL PRIMARY KEY,
    question             TEXT NOT NULL,
    exercice             SMALLINT NOT NULL,
    articles_attendus    TEXT[],
    reponse_attendue     TEXT,
    est_piege            BOOLEAN NOT NULL DEFAULT FALSE,
    comportement_attendu TEXT NOT NULL     -- repondre | sabstenir
);
```

`appel_modele.tenant_id NULL` distingue l'usage **éditorial mutualisé** — la veille, amortie sur
tous les abonnés — de l'usage **par cabinet**, imputé à son quota.

---

## Les quatre contraintes à remarquer

| Contrainte | Ce qu'elle empêche |
|---|---|
| `CHECK (cardinality(citations) > 0)` | Une proposition non sourcée |
| `CHECK (date_fin IS NULL OR date_fin > date_effet)` | Un millésime incohérent |
| `WITH CHECK (tenant_id = ...)` | Écrire chez un autre cabinet |
| `REVOKE UPDATE, DELETE ON journal_audit` | Réécrire l'histoire d'une mission |

Le garde-fou est dans le schéma, pas seulement dans le prompt. Un prompt se contourne ; une
contrainte de base de données non.
