# Annexe fiscale 2026 × inventaire `a_confirmer`

> Rapport de croisement éditorial — **pas** une validation fiscale.
> Aucun `a_confirmer` retiré des YAML. Aucun taux / seuil / article affirmé hors citation Annexe.
> Statut des propositions : **`a_valider_humain`**.

| | |
|---|---|
| Source | `corpus_sources/Annexe-1-Annexe-Fiscale-2026.pdf` → `../../Annexe-1-Annexe-Fiscale-2026.pdf` |
| Texte juridique | LF n° **2025-987** du 19 décembre 2025 — Annexe 1 |
| Ingestion | `make ingerer-corpus FICHIER=corpus_sources/Annexe-1-Annexe-Fiscale-2026.pdf TYPE=annexe MILLESIME=2026` |
| Résultat ingestion | **443** fragments · **48** découpes « article » · `source_document_id` (ré-ingestion) |
| Qualité texte | **Bonne** — PDF déjà OCR (ABBYY FineReader 15) · ~293 ko caractères · 148 pages · ratio alphabétique ≈ 0,71 · 3 pages quasi vides |
| Inventaire croisé | **121** mentions / **57** fiches (`referentiel/file_validation_a_confirmer.json`) |
| Généré | 2026-07-26 |

---

## Principe : Annexe ≠ CGI intégral

L’**Annexe fiscale** amende, complète ou crée des dispositions pour la gestion / le budget **2026**.
Elle **n’est pas** le Code général des impôts article par article.

Conséquences :

| Besoin | Annexe 2026 | CGI CI 2026 intégral |
|---|---|---|
| Veille des **modifications** de l’année | Oui | Complément |
| Texte **complet** art. 18 B, 18 G, seuils historiques, etc. | Non | **Oui — encore absent** |
| Purge massive des 121 `a_confirmer` | **Interdit / impossible** | Après dépôt + visa fiscaliste |

Dépôt attendu : `corpus_sources/CGI-CI-2026.pdf` — voir `corpus_sources/ATTENTE-CGI-CI-2026.md`.

---

## Verdict chiffré (honnête)

| Classe | Mentions (≈) | Sens |
|---|---:|---|
| **Piste Annexe claire** (élément sourçable → proposition) | **8** | Article CGI réellement aménagé / date Annexe utile au croisement |
| **Veille faible** (même famille d’article touchée, marqueur non confirmé) | **28** | 18-A) 11° nouveau ; foncier Annexe art. 34 ≠ confirmation des fiches FONC seed |
| **Piège / faux ami** | **3** | Apparence numérique ou « art. 18 » ≠ sujet de la fiche |
| **Toujours bloqué CGI / fiscaliste** | **82** | Pas d’élément clair dans l’Annexe pour ce marqueur |

**Minorité** : ~7 % des mentions ont une piste Annexe actionnable.
**0 purge** YAML. **0** fiche certifiée supplémentaire.

Les ~51 mentions `hors_perimetre` (« valeurs issues doc client… ») restent hors Annexe par nature — validation métier / provenance seed, pas lookup Annexe.

---

## A. Pistes claires — `a_valider_humain`

### A1. `PAT-272-PATENTE` — art. 272 CGI modifié

| | |
|---|---|
| Mentions | `PAT-272-PATENTE#0` (date) · `#1` (autre / provenance) |
| Pages | **108–109** (numérotation PDF / `pdftotext`) |
| Extrait | « L’article 272 du Code général des Impôts est modifié comme suit : […] propriétaires de véhicules de transport […] plateformes de mise en relation en ligne […] preuve du paiement de la patente […] » ; abrogation art. **1153** CGI |
| Suggestion | Mettre à jour la description / questions de la fiche pour refléter l’extension plateformes ; **ne pas** purger date ni montants sans CGI + fiscaliste |
| Statut | `a_valider_humain` |

### A2. `RAS-92-NONRESIDENT` — art. 92-1°-e) CGI (réassurance)

| | |
|---|---|
| Mentions | `RAS-92-NONRESIDENT#0` · `#1` |
| Pages | **36** (exposé) · **129** (texte) |
| Extrait | « Les dispositions de l’article 92-1°-e) du Code général des Impôts soumettent […] primes d’assurance […] réassurances non domiciliées […] » ; prorogation exonération CIMA **jusqu’au 30 avril 2027** |
| Suggestion | Si la fiche couvre les primes de réassurance : documenter l’exonération datée. Sinon : hors champ fiche — laisser `a_confirmer` |
| Statut | `a_valider_humain` · **pertinence partielle** |

### A3. `OBL-36-ETII` / `OBL-49BIS-REGISTRES` — dématérialisation (pas la date seed)

| | |
|---|---|
| Mentions | dates (+ évent. autre) sur OBL-36-ETII · OBL-49BIS-REGISTRES (**4** mentions si on compte date+autre) |
| Pages | **86–87**, **96** |
| Extrait | Transmission électronique des états financiers « à partir du **1er janvier 2027** » (microentreprises) ; « **1er janvier 2028** » (taxe d’État de l’entreprenant) ; touche art. **36**, **49 bis**, **82**, **101 bis** CGI |
| Suggestion | Croiser : la date seed `01/01/2026` **n’est pas** confirmée par ces passages. Distinguer date d’effet règle vs échéances démat. **Ne pas** substituer 2027/2028 à 01/01/2026 sans analyse fiscaliste |
| Statut | `a_valider_humain` · **piste de contraste**, pas une confirmation |

---

## B. Veille faible — article touché, marqueurs non couverts

### B1. Famille `BIC-CHG-18A*` / `BIC-CHG-18-MIXTES` — seul ajout : 18-A) **11°**

| | |
|---|---|
| Pages | **132** (Annexe art. 39) |
| Extrait | « À l’article **18-A)** du Code général des impôts, il est créé un **11°** rédigé comme suit : « 11°- Le montant lié à la formation d’un produit non exonéré d’impôt sur le bénéfice. ». » |
| Couvre | Nouvelle **condition de déductibilité** (alignement UEMOA) |
| **Ne couvre pas** | Taux **5 % / 20 %** (frais de siège) · plafond **3 000 000** · BCEAO+2 · sous-capitalisation · autres 1°–10° · date d’effet seed |
| Suggestion | Proposition éditoriale distincte : évaluer une mention / paramètre pour le **11°** nouveau. **Interdit** de purger les `a_confirmer` taux/seuil 18 A sur cette seule page |
| Mentions concernées (veille, non confirmées) | ~**26** sur la famille 18 A / 18-MIXTES |
| Statut | `a_valider_humain` (veille) |

### B2. Fiches `FONC-*` — mesure Annexe « Article 34 » (foncier)

La présentation p. **13** intitule une mesure « (Article 34) » : c’est l’**article 34 de l’Annexe**, pas forcément l’art. 34 CGI de la fiche `FONC-34-PATRIMOINE`. Le dispositif aménage surtout d’autres articles (153, 158, 161, etc., pages ~119–122).

| Suggestion | Revue humaine FONC-34 / FONC-171 contre le bloc foncier Annexe — sans purge auto |
| Statut | `a_valider_humain` (veille connexe) |

---

## C. Pièges — ne pas purger

| Apparence | Pages | Réalité | Mentions |
|---|---|---|---|
| **2,5 %** | 8, 56–57 | Taxe développement **touristique** art. **1140** CGI (1,5 % → 2,5 %) | `BIC-CHG-18G-DONS` [taux] |
| **200 000 000** | 141 | Droit renouvellement autorisation **hydrocarbures** | `BIC-CHG-18G-DONS` [seuil] |
| « Article 18 » p.30 | 30 | **Article 18 de l’Annexe** (corrections techniques), ≠ art. 18 CGI charges | famille BIC-CHG-18* |
| **3 000 000** | 135–136 | Tarifs **Affaires maritimes** | ≠ plafond `BIC-CHG-18A4-ADMIN` |

**Art. 18 G (dons)** : **aucune** occurrence dans le texte extractible. Les 3 mentions 18 G restent **bloquées CGI**.

---

## D. Toujours bloqués (CGI intégral / fiscaliste)

Exemples représentatifs — liste non exhaustive :

- Toute la famille **18 B / 18 D / 18 E / 18 F / 18 G** (amortissements, cadeaux, pénalités, dons, provisions…)
- Seuils **OBL-108** (50 000 / 10 000), **OBL-36BIS** CbCR **250 Md** (absent de l’Annexe)
- **BCEAO + 2** / sous-capitalisation : **0** occurrence BCEAO
- Dates seed **01/01/2026** en masse : l’Annexe ne pose **pas** une clause générale « toutes dispositions au 1er janvier 2026 » extractible pour ces fiches
- Bloqueurs métier (fraction 18 B 1°, définition FRAIS_GENERAUX, assiette 30 %, périmètre 18 E 1°…)
- Mentions `hors_perimetre` provenance seed client

---

## Propositions éditoriales (file humaine)

À traiter dans `/console` → **À confirmer** · filtre **Pistes Annexe**
(checklist imprimable : `docs/18-lot-fiscaliste-annexe-8.md`) :

1. **PAT-272** — noter amendement plateformes (p.108–109) ; statut revue.
2. **RAS-92** — noter exonération réassurance CIMA → 30/04/2027 si périmètre fiche OK.
3. **OBL-36 / 49 bis** — noter contraste dates démat 2027/2028 vs seed 01/01/2026.
4. **Nouvelle veille 18-A) 11°** — ticket éditorial séparé (création éventuelle de paramètre), hors purge des taux/seuils existants.
5. **FONC-*** — revue croisée bloc foncier Annexe.

Seed DB (idempotent) : `make seed-pistes-annexe` → 8 propositions `ouverte` /
`a_valider_humain` (source `annexe_2026_croisement`). Workflow statut ≠ purge YAML.

---

## Qualité d’extraction

- Pas un scan « image muette » : texte **exploitable** pour recherche / corpus.
- OCR d’origine (ABBYY) : quelques artefacts possibles ; toujours vérifier la page PDF avant visa.
- Découpe ingestion « 48 articles » = heuristique de fragmentation, **pas** le décompte officiel des articles de l’Annexe.

---

## Rappels d’architecture

- Domaine **éditorial** (corpus commun) — pas de `tenant_id`.
- L’IA / ce rapport **propose** ; le moteur **ne calcule** rien depuis ce texte ; l’humain **valide**.
- Épinglage de millésime inchangé.

**À confirmer** : toute lecture d’un taux, seuil ou date comme droit positif applicable à une fiche seed reste soumise au fiscaliste 2AàZ + CGI intégral.
