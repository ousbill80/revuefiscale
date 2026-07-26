# Engagement cabinet — conception

> Aligner le produit sur la vie réelle d’un cabinet d’expertise / audit /
> conseil en Côte d’Ivoire. **Conception** : décisions figées + lots.
> Aucun délai de prescription CGI inventé. Aucun taux en dur.

Voir aussi : `AGENTS.md`, `docs/02-format-pivot.md`, `docs/03-schema-donnees.md`,
`docs/25-registre-risques-actions.md` (registre post-mission — conception avant
runtime), analyse des 6 manques (conversation produit).

---

## 1. Ce qu’est une revue dans la vraie vie

Une revue fiscale n’existe presque jamais seule. Quatre portes d’entrée :

| Contexte | Déclencheur | Périmètre typique |
|---|---|---|
| Revue préventive | État des lieux avant éventuel contrôle | Tous impôts, exercices non prescrits |
| Commissariat aux comptes | CAC — risque fiscal / provisions | Ciblé sur ce qui affecte les comptes |
| Due diligence | Acquisition — passif latent | Exhaustif, orienté quantification |
| Assistance à contrôle | Notification reçue | Limité aux points notifiés |

**Le cas le plus fréquent n’est pas la revue complète** : c’est la revue
partielle (« faites-nous la TVA »), parce que c’est ce que le client paie.

Déroulement métier (rappel) : lettre de mission → collecte (vrai goulot) →
revue analytique → contrôles par impôt → entretiens → quantification →
restitution négociée.

Ce qu’aucun guide ne dit assez fort :

- le **seuil de signification** gouverne tout (sinon bruit → outil ignoré) ;
- **« impossible de conclure »** est une conclusion (pièce manquante ≠ conforme) ;
- le **dossier de travail** est contrôlé (Ordre / superviseur) — le journal d’audit vaut cher ;
- le **prix est forfaitaire** — le dépassement mange la marge (moteur économique du SaaS).

---

## 2. Six manques du modèle actuel (qualifiés)

| # | Manque | Statut code | Domaine |
|---|---|---|---|
| ① | Seuil de signification / `sous_seuil` | **Partiel** — colonne `015` + brouillon moteur `sous_seuil` ; pas de UI réviseur dédiée Lot 3 | Abonné (mission / conclusion) |
| ② | Prescription (exercice encore repris ?) | **Absent** — **À confirmer** délais CGI CI | Éditorial (param. millésimé) + mission |
| ③ | Statut conclusion étendu | **Fait (Lot 2)** — `016` + INSERT moteur + PATCH humain + UI restitution | Abonné (conclusion) |
| ④ | Lien conclusion → pièce dossier de travail | **Fait (Lot 2)** — FK `016` + trigger + API/UI rattachement | Abonné |
| ⑤ | Mission partielle + « non examiné » au rapport | **Fait (Lot 1)** — `015` + filtre + rapport + UI `/app` | Abonné (mission) + restitution |
| ⑥ | Suivi inter-exercices (recommandations N→N+1) | **Fait (R4)** — clôture → `risque` ; `point_ouvert` GET legacy, écritures 410 — `docs/25` | Abonné |

**Architecture tâches (`019`)** : `objectif` (fiscal) + `tache` (8 statuts) —
plan dérivé déterministe à l’exécution ; `mission_objectif` reste narratif (lettre).

**Après le rapport** : conception unifiée registre / actions —
[`docs/25-registre-risques-actions.md`](25-registre-risques-actions.md)
(risque ∈ contribuable ; pas encore de migration).

Les **contextes d’engagement** (tableau §1) : **modélisés (Lot 1)** via
`mission.type_engagement` + cycle `cadrage` → `en_cours` → `cloturee`
(cadrage gelé dès `en_cours`, y compris `seuil_signification`).

---

## 3. Décisions de conception (figées)

### 3.1 Doctrine (rappel)

1. Calcul fiscal **déterministe** — pas de LLM dans le montant.
2. L’IA propose, le moteur calcule, **l’humain valide**.
3. Aucune règle fiscale en dur dans le code applicatif.
4. Traçabilité intégrale + journal écriture seule.
5. Millésimes + **épinglage** de version référentiel.
6. Isolation stricte cabinets (`tenant_id` + RLS + `SET LOCAL`).

### 3.2 Choix produit

| Concept | Décision | Pourquoi |
|---|---|---|
| Nature d’engagement | `mission.type_engagement` ∈ `preventive` · `cac` · `due_diligence` · `assistance_controle` · `autre` | Les 4 portes + échappatoire. **N’altère aucune formule** — UX, libellés rapport, défauts de cadrage. |
| Périmètre | `mission.perimetre_impots` = liste de codes du champ pivot `impot` | Réutilise le format pivot — pas de nouvelle taxonomie. |
| Complet vs partiel | `NULL` = **tous** les impôts (rétrocompat) ; liste non vide = filtre strict | « TVA seule » sans casser les missions existantes. Liste `[]` **refusée** (ambiguë). |
| Exclusions narratives | `mission.exclusions_declarees` TEXT | Lettre de mission : hors codes (ex. « hors contrôles sur place »). |
| Gel du cadrage | Type / périmètre / exclusions / **seuil** / **objectifs** modifiables en `cadrage` ; figés dès `en_cours` | Une mission ouverte lundi / close vendredi ne change pas de cadrage en silence. |
| Objectifs (lettre) | Table enfant `mission_objectif` (`tenant_id`, `mission_id`, `ordre`, `libelle`) — **plusieurs** libellés libres | Lettre de mission : plusieurs buts. N’altère **pas** `selectionner_regles`. |
| Objectifs fiscaux | Table `objectif` (`impot`, `exercices[]`, `dans_perimetre`, `motif_exclusion`) — sync → `perimetre_impots` | Unité fiscale ; revue partielle native. |
| Tâches | Table `tache` (8 statuts) matérialisée à l’`executer` depuis `selectionner_regles` | Plan **dérivé**, jamais choisi par un LLM. |
| Filtrage moteur | `selectionner_regles` : si périmètre non vide, `regle.impot ∈ perimetre` | Déterministe, testable. |
| Rapport | Section obligatoire « Périmètre et non examiné » | Silence = mensonge d’engagement. |
| Statut conclusion (lot 2) | Humain valide ; moteur **propose** brouillon seulement | Doctrine « IA propose, humain valide ». |
| Seuil (lot 3) | Montant **cabinet** sur la mission — jamais un seuil CGI en dur | Materialité ≠ barème fiscal. |
| Prescription (lot 5) | Paramètres **millésimés du référentiel**, sourcés | **À confirmer** articles / délais / point de départ CGI CI avant runtime. |

### 3.3 Statuts de conclusion cibles (lot 2)

```
conforme | anomalie | sous_seuil | non_verifiable | hors_perimetre
```

- `non_verifiable` : pièce manquante / réponse absente — **pas** « conforme ».
- `sous_seuil` : montant &lt; seuil de signification de la mission (lot 3).
- `hors_perimetre` : règle hors périmètre déclaré (ne devrait plus être exécutée si lot 1 OK ; utile pour amendements humains / historique).

### 3.4 Ce que le produit ne remplace pas

- La lettre de mission Word / PDF du cabinet (on **cadre** l’outil).
- Le jugement de quantification probable / possible / faible (humain).
- La négociation finale du rapport avec le client.

---

## 4. Lots de construction

### Lot 1 — Cadrage d’engagement + périmètre *(priorité économique)* — **FAIT**

**Pourquoi en premier** : cas le plus fréquent = revue partielle ; sans ça, le
rapport prétend une exhaustivité fausse.

Livrables (en code) :

1. Migration `015_mission_engagement.sql` — colonnes abonnées + CHECK (+ `seuil_signification` colonnaire pour Lot 3).
2. API / service mission : lecture + PATCH cadrage (gel à `en_cours`).
3. `selectionner_regles(..., perimetre_impots=...)`.
4. Rapport : identification type d’engagement + section non examiné.
5. UI `/app` : type + multi-select impôts + **objectifs (liste)** + exclusions + seuil ; badge « Revue partielle ».
6. Tests sélection + API (`tests/moteur/test_perimetre_engagement.py`).
7. **Objectifs multi** (`018_mission_objectif.sql`) — table enfant RLS + GET/PUT + gel cadrage.

Schéma cible (extrait) :

```sql
ALTER TABLE mission
  ADD COLUMN type_engagement TEXT NOT NULL DEFAULT 'autre'
    CHECK (type_engagement IN (
      'preventive', 'cac', 'due_diligence', 'assistance_controle', 'autre'
    )),
  ADD COLUMN perimetre_impots JSONB,  -- NULL = tous
  ADD COLUMN exclusions_declarees TEXT,
  ADD COLUMN seuil_signification NUMERIC(18, 2);  -- matérialité cabinet (lot 3)
-- Voir migrations/015_mission_engagement.sql (livré).
-- Objectifs : migrations/018_mission_objectif.sql (table enfant).
```

Codes `impot` autorisés (pivot) :

`BIC`, `TVA`, `RAS`, `ITS`, `CE`, `IRC`, `IRVM`, `PAT`, `FONC`, `ENR`, `TIMBRE`, `OBL`, `OBNL`, `RA`.

### Lot 2 — Statuts conclusion + pièce de travail — **FAIT**

Livrables (en code) :

1. Migration `016_conclusion_statut_piece.sql` — `statut` CHECK §3.3 + FK `piece_mission_id` + trigger cohérence.
2. Service `backend/plateforme/conclusions.py` + GET/PATCH `/missions/{id}/conclusions/{id}`.
3. RBAC : lecteur lecture seule ; réviseur/admin amendement (`executer_mission`).
4. UI restitution : select statut + pièce dossier ; notes d’instruction restent en `localStorage`.
5. Tests isolation : happy path, lecteur 403, RLS inter-cabinets, pièce hors mission.

### Lot 3 — Seuil de signification *(livré — colonne `015` + brouillon moteur)*

- `mission.seuil_signification NUMERIC(18,2)` nullable — API, UI, gel cadrage.
- Post-calcul déterministe : brouillon `sous_seuil` si `|montant| < seuil` (NULL = pas de classification auto).
- Pas de seuil par défaut inventé dans le code.

### Lot 4 — Points ouverts inter-missions *(livré — `017` ; écritures coupées post-R4)*

- Table abonnée `point_ouvert` (`tenant_id NOT NULL`, RLS) — **conservée** pour
  lecture historique.
- API : **GET** `/points-ouverts` (legacy) ; POST/PATCH → **410 Gone**
  (utiliser `/risques`). Bandeau N+1 = registre `risque` (+ fallback legacy).
- **Hors** recalcul fiscal.

### Lot 5 — Ouverture au contrôle (prescription)

Une erreur plausible sur la prescription est plus dangereuse qu’une absence de
filtre. **Aucun délai CGI inventé.**

**Déjà livré (R5 socle, non armé)** — `backend/plateforme/prescription.py` :
`evaluer_prescription` lit **uniquement** une future table éditoriale
`parametre_prescription` ; absente aujourd’hui → no-op (`attente_visa_lot5`).
PATCH manuel `prescrit` inchangé. Pas de filtre UX « exercice encore repris ».

Cible produit (après visa + seed sourcé) :

- Paramètres **millésimés** du référentiel (délais + point de départ sourcés).
- Armement du calcul de dates dans `_date_limite_si_armee` **uniquement** pour
  les codes `point_depart` visés.
- Filtre UX « exercice encore repris ? » — **interdit** avant visa.

#### Checklist bloquante — **À confirmer** (CGI CI / LPF)

| # | Point | Attendu du fiscaliste | Interdit |
|---|---|---|---|
| 1 | **Base légale** | Articles exacts CGI CI et/ou LPF applicables à l’ouverture au contrôle (par impôt si distinct) — citation sourcée | Inventer un article, un alinéa, un renvoi |
| 2 | **Point de départ** | Date à partir de laquelle le délai court (ex. déclaration, notification, fin d’exercice — **à sourcer**, pas à déduire) | Fixer une date de départ dans le code ou un commentaire « comme en France » |
| 3 | **Suspensions** | Cas qui suspendent / interrompent le délai (contrôle en cours, contentieux, etc.) — liste sourcée ou « néant confirmé » | Coder une suspension non visée |
| 4 | **Exceptions** | Au minimum : **reports déficitaires**, **crédits TVA** (et tout autre régime dérogatoire) — durée / point de départ / impôt concernés | Assimiler ces cas au délai général sans source |

**Règle d’arrêt** : tant qu’une case n’est pas visée + sourcée → pas d’armement
auto, pas de migration `parametre_prescription` peuplée, pas de filtre moteur.
Socle no-op autorisé (réduit la dette d’intégration sans fragiliser le calcul).

---


## 5. Flux cible (lot 1)

```text
Lettre de mission (hors outil)
        │
        ▼
Cadrage /app : type_engagement + perimetre_impots + objectifs[] + exclusions
        │
        ▼
en_cours (périmètre / objectifs gelés) + version référentiel épinglée
        │
        ▼
selectionner_regles (profil ∩ comptes ∩ perimetre_impots)
        │
        ▼
Exécution / conclusions
        │
        ▼
Rapport : « Périmètre déclaré » (+ objectifs) + « Non examiné »
```

---

## 6. Interdits

- Inventer un délai de prescription, un taux, un seuil CGI.
- Filtrer le périmètre par du code applicatif *ad hoc* hors liste pivot `impot`.
- Laisser le LLM écrire un montant de conclusion.
- Omettre la section « non examiné » sur une mission partielle.
- Confondre `hors_perimetre` éditorial (`a_confirmer`) avec `hors_perimetre` conclusion de mission.

---

## 7. Critères d’acceptation lot 1

- [x] Mission sans `perimetre_impots` : comportement identique à aujourd’hui.
- [x] Mission `perimetre_impots = ["TVA"]` : aucune règle `BIC` sélectionnée.
- [x] Rapport TVA-only énonce explicitement les impôts non examinés.
- [x] PATCH cadrage (périmètre / seuil / …) refusé si `statut ≠ cadrage`.
- [x] Isolation RLS inchangée (`tenant_id` sur `mission`).

---

## 8. Critères d’acceptation lot 2

- [x] `conclusion.statut` ∈ §3.3 ; brouillon moteur à l’INSERT ; PATCH humain persistant.
- [x] `piece_mission_id` nullable ; pièce d’une autre mission refusée (API + trigger).
- [x] Lecteur : GET OK, PATCH → 403 ; réviseur/admin : PATCH OK.
- [x] Cabinet B ne lit / n’amende pas une conclusion du cabinet A (RLS).
- [x] UI restitution : statut + rattachement pièce (hors notes locales `localStorage`).

---

**À confirmer** (lot 5) : voir checklist bloquante § Lot 5 — base légale, point de
départ, suspensions, exceptions. Aucun runtime sans source + visa fiscaliste.
