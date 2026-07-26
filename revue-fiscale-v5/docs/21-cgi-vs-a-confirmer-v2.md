# CGI CI 2026 × inventaire `a_confirmer` (v2)

> Rapport de croisement éditorial **automatisé** — pas une validation fiscale.
> Aucun `a_confirmer` retiré des YAML. Matching article / numéro / libellé / alinéa.
> Classes : **claire** · **contraste** · **faible** · **bloque**.

| | |
|---|---|
| Source corpus | `source_document_id=211` · **1495** articles |
| Inventaire | **121** mentions |
| Généré | 2026-07-26T03:42:36Z |
| Script | `make croiser-cgi` → `backend.scripts.croiser_cgi_a_confirmer` |

---

## Verdict chiffré

| Classe | Mentions | Sens |
|---|---:|---|
| **Claire** | **6** | Marqueur taux/seuil sous l'article allégué (+ libellé si connu) |
| **Contraste** | **2** | Chiffre trouvé mais alinéa / libellé / bloqueur d'assiette conflictuel |
| **Faible** | **43** | Article présent sans preuve du marqueur (surtout dates 01/01/2026) |
| **Bloqué** | **70** | Hors périmètre, bloqueur, article absent |

**0 purge** YAML. Ne pas forcer un match douteux.

---

## A. Pistes claires

### `BIC-CHG-18A4-ADMIN#1` — art. 18

- Mention : plafond 3 000 000 FCFA / beneficiaire / an
- Extrait : « par l'assemblée générale ordinaire desdites sociétés, sont déductibles dans la limite de 3 000 000 de francs par an et par bénéficiaire. Ord. n°- 2011-480 du 28 décembre 2 »
- Raison : marqueur_chiffre_sous_article_allege ; faux_amis_potentiels=['39', '53', '5169', '5170 undecies', '269']
- Statut : `a_valider_humain`

### `BIC-CHG-18A6-SOUSCAP#3` — art. 18

- Mention : taux BCEAO + 2
- Extrait : « tat de l'entreprise avant impôt, intérêts, dotations aux amortissements sur immobilisations et provisions ; - le taux des intérêts servis ne peut excéder le taux moyen des ava »
- Raison : marqueur_chiffre_sous_article_allege
- Statut : `a_valider_humain`

### `BIC-CHG-18G-DONS#0` — art. 18

- Mention : taux 2,5 % — verifier art. 18 G / annexe fiscale
- Extrait : « La valeur des dons et libéralités consentis est déductible dans la double limite de 2,5 % du chiffre d'affaires et de 200 millions de francs par an. Loi n°- 2003-206 »
- Raison : marqueur_chiffre_sous_article_allege ; faux_amis_potentiels=['61', '713', '729', '735', '1140', '1134']
- Statut : `a_valider_humain`

### `BIC-CHG-18G-DONS#1` — art. 18

- Mention : plafond 200 000 000 FCFA — verifier art. 18 G
- Extrait : « nancement, de construction, de réhabilitation ou d'équipement d'écoles, de centres de santé ou de centres polyvalents au profit d'une collectivité; Ord. n°- 2009-382 du 26 nove »
- Raison : marqueur_chiffre_sous_article_allege ; faux_amis_potentiels=['71 bis', '5002 bis', '269']
- Statut : `a_valider_humain`

### `OBL-108-HONORAIRES#1` — art. 108

- Mention : seuils 50 000 / 10 000
- Extrait : « déclarer ces sommes dans les conditions prévues par l'article 127 lorsqu'elles dépassent 50 000 francs par an pour un même bénéficiaire. Loi n° 2002-156 du 15 mars 2002, an. f »
- Raison : marqueur_chiffre_sous_article_allege ; faux_amis_potentiels=['126', '244', '533', '709 bis', '766', '786', '837', '903']
- Statut : `a_valider_humain`

### `OBL-36BIS-CBCR#2` — art. 36 bis

- Mention : seuil 250 Md FCFA a confirmer
- Extrait : « scal soumis à déclaration, un chiffre d'affaires hors taxes consolidé égal ou supérieur à 250 000 000 000 de francs ; Loi n° 2019-1080 du 18 décembre 2019, an. fiscale, art. 23 »
- Raison : marqueur_chiffre_sous_article_allege
- Statut : `a_valider_humain`

## B. Contrastes

### `BIC-CHG-18A3-FRAISSIEGE#2`

- Le plafond 5 %/20 % est sous art. 18 A) 5°, pas sous 3° (3° = salaire du conjoint). « frais de siège » absent du texte art. 18.
- Extrait : « lles ne présentent pas un caractère anormal ou exagéré. La déduction est plafonnée à 5 % du chiffre d'affaires dans la limite de 20 % des frais généraux de l'entreprise débitr »

### `BIC-CHG-18A6-SOUSCAP#1`

- chiffre présent dans l'article allégué, mais mention bloqueur (assiette / agrégat à figer) — pas une piste claire de purge
- Extrait : « - le montant total des intérêts servis au titre des sommes susvisées ne peut excéder 30 % du résultat de l'entreprise avant impôt, intérêts, dotations aux amortissements sur i »

## C. Faibles (échantillon)

Article présent ≠ confirmation de date / marqueur non extractible.

- `BIC-AMORT-18B-GENERAL#0` — article_present_date_non_prouvee (art. 18)
- `BIC-AMORT-18B-INFO#0` — article_present_date_non_prouvee (art. 18)
- `BIC-AMORT-18B-VEHICULES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18-MIXTES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A-ASSURANCES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A1-EXPATRIES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A1-SALAIRES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A2-LOYERS#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A3-FRAISSIEGE#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A4-ADMIN#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A5-INTERETS#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A6-CCATAUX#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18A6-SOUSCAP#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18B-CREDITBAILVT#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18D-IMPOTS#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18E-CADEAUX#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18F-PENALITES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-CHG-18G-DONS#2` — article_present_date_non_prouvee (art. 18)
- `BIC-PROV-18E1-CREANCES#0` — article_present_date_non_prouvee (art. 18)
- `BIC-PROV-18E1-RISQUES#0` — article_present_date_non_prouvee (art. 18)
- `CE-143-APPRENTISSAGE#0` — article_present_date_non_prouvee (art. 143)
- `CE-146-EMPLOYEUR#0` — article_present_date_non_prouvee (art. 146)
- `ENR-29-CONDAMNATION#0` — article_present_date_non_prouvee (art. 29)
- `ENR-666-ACTES#0` — article_present_date_non_prouvee (art. 666)
- `FONC-171-ACOMPTELOYER#0` — article_present_date_non_prouvee (art. 171)
- … +18 autres

## D. Bloqués (échantillon)

- `BIC-AMORT-18B-GENERAL#1` — hors_perimetre (doc client / validation métier)
- `BIC-AMORT-18B-INFO#1` — bloqueur sémantique (périmètre / définition)
- `BIC-AMORT-18B-VEHICULES#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18-MIXTES#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A-ASSURANCES#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A1-EXPATRIES#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A1-SALAIRES#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A2-LOYERS#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A3-FRAISSIEGE#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A3-FRAISSIEGE#3` — bloqueur_agregat_sans_chiffre_confirme
- `BIC-CHG-18A5-INTERETS#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A6-CCATAUX#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18A6-SOUSCAP#2` — bloqueur sémantique (périmètre / définition)
- `BIC-CHG-18B-CREDITBAILVT#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18D-IMPOTS#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18E-CADEAUX#1` — hors_perimetre (doc client / validation métier)
- `BIC-CHG-18F-PENALITES#1` — hors_perimetre (doc client / validation métier)
- `BIC-PROV-18E1-CREANCES#1` — hors_perimetre (doc client / validation métier)
- `BIC-PROV-18E1-RISQUES#1` — bloqueur sémantique (périmètre / définition)
- `CE-143-APPRENTISSAGE#1` — hors_perimetre (doc client / validation métier)
- … +50 autres

---

## Seed propositions

```bash
make croiser-cgi          # régénère ce rapport + catalogue pistes claires
make seed-pistes-cgi      # dépose seulement les NOUVELLES pistes (idempotent)
```

Catalogue : `referentiel/propositions_cgi_2026_pistes.json`.

**À confirmer** : toute lecture d'un taux / seuil / date comme droit positif reste soumise au fiscaliste 2AàZ.
