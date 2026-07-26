# Architecture

**Plateforme SaaS multi-cabinets.** 2AàZ SAS édite et commercialise ; les cabinets abonnés
conduisent leurs missions sur leurs propres clients.

## Les deux domaines

| Domaine éditorial (2AàZ) | Domaine abonné (chaque cabinet) |
|---|---|
| Référentiel des 57 règles, versionné et publié | Missions, balances, conclusions, rapports |
| Corpus réglementaire indexé | Contribuables suivis |
| Table de sanctions | Utilisateurs et rôles |
| File de propositions du copilote | Contestations remontées |
| **Commun à tous, sans `tenant_id`** | **Cloisonné, `tenant_id NOT NULL` + RLS forcée** |

## Les six couches

| Couche | Rôle | Dossier |
|---|---|---|
| 0 — Plateforme | Tenants, abonnements, utilisateurs, quotas, métrage | `backend/plateforme/` |
| 1 — Données d'entrée | Import et fiabilisation : balance SYSCOHADA, états financiers, grand livre, déclarations | `backend/socle/` |
| 2 — Référentiel | Lecture des règles, millésimes, expressions, sanctions, effets croisés | `backend/referentiel/` |
| 3 — Profil | Régime, secteur, forme juridique, transfrontalier. Filtre amont. Bloquant. | `backend/profil/` |
| 4 — Moteur | Déclenchement, questionnement, calcul, propagation, journalisation. **Déterministe.** | `backend/moteur/` |
| 5 — Restitution | Passage comptable / fiscal, risques chiffrés, rapport, traçabilité | `backend/restitution/` |
| 6 — Intelligence | Corpus indexé, recherche, agent, garde-fous | `backend/corpus/`, `backend/agent/` |

Et, transversal à l'éditeur : `backend/editorial/` — versions du référentiel, publication,
contestations.

## Le flux d'une mission

```
Cabinet authentifié → contexte de tenant posé (SET LOCAL)
        ↓
Profil du contribuable validé (bloquant)
        ↓
Mission créée → ÉPINGLE la version publiée du référentiel
        ↓
Import balance + états financiers → fiabilisation → soldes normalisés
        ↓
Filtrage du référentiel épinglé, par profil et par exercice
        ↓
Pour chaque règle : déclenchement → questionnement → calcul → propagation
        ↓
Conclusions (chacune reliée à son article et à sa version de règle)
        ↓
Passage comptable / fiscal + risques chiffrés + rapport
```

## Le flux éditorial

```
Nouvelle annexe fiscale déposée dans le corpus
        ↓
Copilote : différentiel → règles impactées → propositions sourcées
        ↓
Fiscaliste 2AàZ : accepte, corrige, rejette
        ↓
Publication d'une version : v2026.3
        ↓
Notification aux abonnés — les missions en cours restent épinglées
```

## La frontière déterministe / IA

| | Couche 4 — Moteur | Couche 6 — Agent |
|---|---|---|
| Nature | Déterministe | Probabiliste |
| Produit | Montants, conclusions | **Propositions** sourcées |
| Rejouable à l'identique | Oui | Non |
| Entre au rapport | Directement | Jamais sans validation |
| Écrit dans le référentiel | Non | Non — dépose en file éditoriale |

Quand l'agent a besoin d'un chiffre, il appelle `simuler_regle`, qui invoque le moteur. Il ne
calcule jamais lui-même : la frontière tient dans le code, pas seulement dans une consigne.

## Arborescence

```
backend/
  plateforme/
    tenants/          création, paliers, provisionnement
    utilisateurs/     comptes, rôles, invitations
    quotas/           plafonds par palier, alertes
    metrage/          consommation IA par tenant
    contexte.py       SET LOCAL — le point de passage obligé
  editorial/
    versions/         versions du référentiel, publication
    propositions/     file issue du copilote
    contestations/    remontées des cabinets
  socle/
    import/ mapping/ controles/
  referentiel/
    modeles/ expressions/ millesimes/
  profil/
  moteur/
    selection.py declenchement.py questionnement.py
    calcul.py propagation.py journal.py
  restitution/
    passage.py risques.py rapport/
  corpus/
    ingestion/ index/ recherche/
  agent/
    outils/ boucle.py ancrage.py cache.py
frontend/
  landing/            landing marketing publique (`/`)
  app/                application cabinet
  admin/              console éditoriale 2AàZ
  ui/                 bibliothèque partagée
tests/
  regles/ isolation/ eval/
migrations/
```

## Pile technique

Python 3.12 / FastAPI · PostgreSQL 16 avec RLS · React 18 / TypeScript · moteur de règles
développé sur mesure · orchestration LLM agnostique du fournisseur.

## Hors périmètre

Télétransmission aux téléprocédures DGI · calcul de la paie et des cotisations · tenue de
comptabilité · avis fiscal automatique · garantie de l'exactitude du référentiel, qui relève de
la responsabilité éditoriale de 2AàZ.
