# Inventaire `a_confirmer` — généré

> **Ne pas éditer à la main.** Régénérer via `python -m backend.scripts.inventaire_a_confirmer`.
>
> Inventaire généré — ne constitue pas une validation fiscale. Purge = circuit éditorial 2AàZ (humain), jamais seed auto. Aucune mention n'est retirée sans source CGI CI 2026 certaine. a_confirmer et en_attente_corpus ne bloquent pas le runtime SaaS.

- Généré le : `2026-07-26T02:47:12Z`
- Total mentions : **121**
- Règles concernées : **57**
- Empreinte : `2a38df15f5b2275d814a030c8d497616161b42f7b5a1d8111a1f0cbf1387b4f2`

## Comptes par catégorie

| Catégorie | Nb |
|---|---:|
| `date` | 57 |
| `taux` | 3 |
| `seuil` | 4 |
| `agregat` | 2 |
| `autre` | 55 |

## Priorité éditoriale

| Priorité | Nb | Sens |
|---|---:|---|
| `sourcable` | 65 | Déjà sourçable — chemin CGI / annexe clair ; validation humaine 2AàZ requise avant purge |
| `bloqueur` | 5 | Bloqueur — définition / périmètre à figer avant certification (pas un simple lookup de montant) |
| `hors_perimetre` | 51 | Hors périmètre immédiat — note de provenance seed / validation métier en lot, pas une purge fiscale prioritaire |

> **Sources :** Annexe fiscale 2026 (LF 2025-987) liée dans corpus_sources/ : texte extractible, aucune occurrence « 18 G » ; le 2,5 % trouvé est la taxe touristique ≠ dons. CGI intégral absent → statut_editorial=en_attente_corpus (déposer corpus_sources/CGI-CI-2026.pdf) — 0 purge auto ; bloque_runtime=non. Fiche session : docs/15-session-fiscaliste-7-seuils.md.


## Par priorité

### `sourcable` (65)

- `BIC-AMORT-18B-GENERAL` [date] — date d effet 01/01/2026
- `BIC-AMORT-18B-INFO` [date] — date d effet
- `BIC-AMORT-18B-VEHICULES` [date] — date d effet 01/01/2026
- `BIC-CHG-18-MIXTES` [date] — date d effet 01/01/2026
- `BIC-CHG-18A-ASSURANCES` [date] — date d effet 01/01/2026
- `BIC-CHG-18A1-EXPATRIES` [date] — date d effet 01/01/2026
- `BIC-CHG-18A1-SALAIRES` [date] — date d effet 01/01/2026
- `BIC-CHG-18A2-LOYERS` [date] — date d effet 01/01/2026
- `BIC-CHG-18A3-FRAISSIEGE` [date] — date d effet 01/01/2026
- `BIC-CHG-18A3-FRAISSIEGE` [taux] — taux 5%/20%
- `BIC-CHG-18A4-ADMIN` [date] — date d effet
- `BIC-CHG-18A4-ADMIN` [seuil] — plafond 3 000 000 FCFA / beneficiaire / an
- `BIC-CHG-18A5-INTERETS` [date] — date d effet 01/01/2026
- `BIC-CHG-18A6-CCATAUX` [date] — date d effet 01/01/2026
- `BIC-CHG-18A6-SOUSCAP` [date] — date d effet
- `BIC-CHG-18A6-SOUSCAP` [taux] — taux BCEAO + 2
- `BIC-CHG-18B-CREDITBAILVT` [date] — date d effet 01/01/2026
- `BIC-CHG-18D-IMPOTS` [date] — date d effet 01/01/2026
- `BIC-CHG-18E-CADEAUX` [date] — date d effet 01/01/2026
- `BIC-CHG-18F-PENALITES` [date] — date d effet 01/01/2026
- `BIC-CHG-18G-DONS` [taux] — taux 2,5 % — verifier art. 18 G / annexe fiscale
- `BIC-CHG-18G-DONS` [seuil] — plafond 200 000 000 FCFA — verifier art. 18 G
- `BIC-CHG-18G-DONS` [date] — date d effet 01/01/2026
- `BIC-PROV-18E1-CREANCES` [date] — date d effet 01/01/2026
- `BIC-PROV-18E1-RISQUES` [date] — date d effet
- `CE-143-APPRENTISSAGE` [date] — date d effet 01/01/2026
- `CE-146-EMPLOYEUR` [date] — date d effet 01/01/2026
- `ENR-29-CONDAMNATION` [date] — date d effet 01/01/2026
- `ENR-666-ACTES` [date] — date d effet 01/01/2026
- `FONC-171-ACOMPTELOYER` [date] — date d effet 01/01/2026
- `FONC-34-PATRIMOINE` [date] — date d effet 01/01/2026
- `IRC-194-CREANCES` [date] — date d effet 01/01/2026
- `IRVM-182-DISTRIB` [date] — date d effet 01/01/2026
- `ITS-119-MASSESAL` [date] — date d effet 01/01/2026
- `OBL-108-HONORAIRES` [date] — date d effet
- `OBL-108-HONORAIRES` [seuil] — seuils 50 000 / 10 000
- `OBL-108-HONORAIRES` [autre] — comptes 622/628
- `OBL-338-REEVALUATION` [date] — date d effet 01/01/2026
- `OBL-36-ETII` [date] — date d effet 01/01/2026
- `OBL-36BIS-CBCR` [date] — date d effet 01/01/2026
- `OBL-36BIS-CBCR` [seuil] — seuil 250 Md FCFA a confirmer
- `OBL-49BIS-REGISTRES` [date] — date d effet 01/01/2026
- `OBL-49TER-RBE` [date] — date d effet 01/01/2026
- `OBL-ACOMPTES-IMPUTATION` [date] — date d effet 01/01/2026
- `OBNL-339-NONLUCRATIF` [date] — date d effet 01/01/2026
- `OBNL-35-STARTUP` [date] — date d effet 01/01/2026
- `PAT-272-PATENTE` [date] — date d effet 01/01/2026
- `RA-CIE-01` [date] — date d effet 01/01/2026
- `RA-CNX-01` [date] — date d effet 01/01/2026
- `RA-CNX-02` [date] — date d effet 01/01/2026
- `RA-FISC-01` [date] — date d effet 01/01/2026
- `RA-FISC-02` [date] — date d effet 01/01/2026
- `RA-FISC-03` [date] — date d effet 01/01/2026
- `RA-FISC-04` [date] — date d effet 01/01/2026
- `RA-FISC-05` [date] — date d effet 01/01/2026
- `RA-IMMO-01` [date] — date d effet 01/01/2026
- `RA-IMMO-02` [date] — date d effet 01/01/2026
- `RA-RECON-01` [date] — date d effet 01/01/2026
- `RA-STOCK-01` [date] — date d effet 01/01/2026
- `RA-TRANSF-01` [date] — date d effet 01/01/2026
- `RAS-92-NONRESIDENT` [date] — date d effet 01/01/2026
- `TIMBRE-805-DOCS` [date] — date d effet 01/01/2026
- `TVA-COL-RAPPRO-CA` [date] — date d effet 01/01/2026
- `TVA-DED-PRORATA` [date] — date d effet 01/01/2026
- `TVA-TIERS-NONRESIDENT` [date] — date d effet 01/01/2026

### `bloqueur` (5)

- `BIC-AMORT-18B-INFO` [autre] — fraction recalculee vs dotation entiere
- `BIC-CHG-18A3-FRAISSIEGE` [agregat] — definition FRAIS_GENERAUX
- `BIC-CHG-18A6-SOUSCAP` [agregat] — assiette 30 % — RESULTAT_AVANT_IMPOT a figer
- `BIC-CHG-18A6-SOUSCAP` [autre] — limites (a)(c)(d)(e)
- `BIC-PROV-18E1-RISQUES` [autre] — perimetre exclusions 18 E 1°

### `hors_perimetre` (51)

- `BIC-AMORT-18B-GENERAL` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-AMORT-18B-VEHICULES` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18-MIXTES` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A-ASSURANCES` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A1-EXPATRIES` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A1-SALAIRES` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A2-LOYERS` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A3-FRAISSIEGE` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A5-INTERETS` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A6-CCATAUX` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18B-CREDITBAILVT` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18D-IMPOTS` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18E-CADEAUX` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18F-PENALITES` [autre] — valeurs issues doc client 5 — a valider metier
- `BIC-PROV-18E1-CREANCES` [autre] — valeurs issues doc client 5 — a valider metier
- `CE-143-APPRENTISSAGE` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `CE-146-EMPLOYEUR` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `ENR-29-CONDAMNATION` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `ENR-666-ACTES` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `FONC-171-ACOMPTELOYER` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `FONC-34-PATRIMOINE` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `IRC-194-CREANCES` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `IRVM-182-DISTRIB` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `ITS-119-MASSESAL` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-338-REEVALUATION` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-36-ETII` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-36BIS-CBCR` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-49BIS-REGISTRES` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-49TER-RBE` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-ACOMPTES-IMPUTATION` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBNL-339-NONLUCRATIF` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBNL-35-STARTUP` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `PAT-272-PATENTE` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-CIE-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-CNX-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-CNX-02` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-02` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-03` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-04` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-05` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-IMMO-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-IMMO-02` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-RECON-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-STOCK-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-TRANSF-01` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `RAS-92-NONRESIDENT` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `TIMBRE-805-DOCS` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `TVA-COL-RAPPRO-CA` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `TVA-DED-PRORATA` [autre] — valeurs issues docs client 6/9/10 — a valider metier
- `TVA-TIERS-NONRESIDENT` [autre] — valeurs issues docs client 6/9/10 — a valider metier


## Par thème

### Dates (57)

- `BIC-AMORT-18B-GENERAL` [date/sourcable] — date d effet 01/01/2026
- `BIC-AMORT-18B-INFO` [date/sourcable] — date d effet
- `BIC-AMORT-18B-VEHICULES` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18-MIXTES` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A-ASSURANCES` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A1-EXPATRIES` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A1-SALAIRES` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A2-LOYERS` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A3-FRAISSIEGE` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A4-ADMIN` [date/sourcable] — date d effet
- `BIC-CHG-18A5-INTERETS` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A6-CCATAUX` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18A6-SOUSCAP` [date/sourcable] — date d effet
- `BIC-CHG-18B-CREDITBAILVT` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18D-IMPOTS` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18E-CADEAUX` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18F-PENALITES` [date/sourcable] — date d effet 01/01/2026
- `BIC-CHG-18G-DONS` [date/sourcable] — date d effet 01/01/2026
- `BIC-PROV-18E1-CREANCES` [date/sourcable] — date d effet 01/01/2026
- `BIC-PROV-18E1-RISQUES` [date/sourcable] — date d effet
- `CE-143-APPRENTISSAGE` [date/sourcable] — date d effet 01/01/2026
- `CE-146-EMPLOYEUR` [date/sourcable] — date d effet 01/01/2026
- `ENR-29-CONDAMNATION` [date/sourcable] — date d effet 01/01/2026
- `ENR-666-ACTES` [date/sourcable] — date d effet 01/01/2026
- `FONC-171-ACOMPTELOYER` [date/sourcable] — date d effet 01/01/2026
- `FONC-34-PATRIMOINE` [date/sourcable] — date d effet 01/01/2026
- `IRC-194-CREANCES` [date/sourcable] — date d effet 01/01/2026
- `IRVM-182-DISTRIB` [date/sourcable] — date d effet 01/01/2026
- `ITS-119-MASSESAL` [date/sourcable] — date d effet 01/01/2026
- `OBL-108-HONORAIRES` [date/sourcable] — date d effet
- `OBL-338-REEVALUATION` [date/sourcable] — date d effet 01/01/2026
- `OBL-36-ETII` [date/sourcable] — date d effet 01/01/2026
- `OBL-36BIS-CBCR` [date/sourcable] — date d effet 01/01/2026
- `OBL-49BIS-REGISTRES` [date/sourcable] — date d effet 01/01/2026
- `OBL-49TER-RBE` [date/sourcable] — date d effet 01/01/2026
- `OBL-ACOMPTES-IMPUTATION` [date/sourcable] — date d effet 01/01/2026
- `OBNL-339-NONLUCRATIF` [date/sourcable] — date d effet 01/01/2026
- `OBNL-35-STARTUP` [date/sourcable] — date d effet 01/01/2026
- `PAT-272-PATENTE` [date/sourcable] — date d effet 01/01/2026
- `RA-CIE-01` [date/sourcable] — date d effet 01/01/2026
- `RA-CNX-01` [date/sourcable] — date d effet 01/01/2026
- `RA-CNX-02` [date/sourcable] — date d effet 01/01/2026
- `RA-FISC-01` [date/sourcable] — date d effet 01/01/2026
- `RA-FISC-02` [date/sourcable] — date d effet 01/01/2026
- `RA-FISC-03` [date/sourcable] — date d effet 01/01/2026
- `RA-FISC-04` [date/sourcable] — date d effet 01/01/2026
- `RA-FISC-05` [date/sourcable] — date d effet 01/01/2026
- `RA-IMMO-01` [date/sourcable] — date d effet 01/01/2026
- `RA-IMMO-02` [date/sourcable] — date d effet 01/01/2026
- `RA-RECON-01` [date/sourcable] — date d effet 01/01/2026
- `RA-STOCK-01` [date/sourcable] — date d effet 01/01/2026
- `RA-TRANSF-01` [date/sourcable] — date d effet 01/01/2026
- `RAS-92-NONRESIDENT` [date/sourcable] — date d effet 01/01/2026
- `TIMBRE-805-DOCS` [date/sourcable] — date d effet 01/01/2026
- `TVA-COL-RAPPRO-CA` [date/sourcable] — date d effet 01/01/2026
- `TVA-DED-PRORATA` [date/sourcable] — date d effet 01/01/2026
- `TVA-TIERS-NONRESIDENT` [date/sourcable] — date d effet 01/01/2026

### Taux et seuils (7)

- `BIC-CHG-18A3-FRAISSIEGE` [taux/sourcable] — taux 5%/20%
- `BIC-CHG-18A6-SOUSCAP` [taux/sourcable] — taux BCEAO + 2
- `BIC-CHG-18G-DONS` [taux/sourcable] — taux 2,5 % — verifier art. 18 G / annexe fiscale
- `BIC-CHG-18A4-ADMIN` [seuil/sourcable] — plafond 3 000 000 FCFA / beneficiaire / an
- `BIC-CHG-18G-DONS` [seuil/sourcable] — plafond 200 000 000 FCFA — verifier art. 18 G
- `OBL-108-HONORAIRES` [seuil/sourcable] — seuils 50 000 / 10 000
- `OBL-36BIS-CBCR` [seuil/sourcable] — seuil 250 Md FCFA a confirmer

### Agrégats (FRAIS_GENERAUX / RESULTAT_AVANT_IMPOT / assiette) (2)

- `BIC-CHG-18A3-FRAISSIEGE` [agregat/bloqueur] — definition FRAIS_GENERAUX
- `BIC-CHG-18A6-SOUSCAP` [agregat/bloqueur] — assiette 30 % — RESULTAT_AVANT_IMPOT a figer

### Autre (sources docs, périmètre, comptes…) (55)

- `BIC-AMORT-18B-GENERAL` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-AMORT-18B-INFO` [autre/bloqueur] — fraction recalculee vs dotation entiere
- `BIC-AMORT-18B-VEHICULES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18-MIXTES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A-ASSURANCES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A1-EXPATRIES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A1-SALAIRES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A2-LOYERS` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A3-FRAISSIEGE` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A5-INTERETS` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A6-CCATAUX` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18A6-SOUSCAP` [autre/bloqueur] — limites (a)(c)(d)(e)
- `BIC-CHG-18B-CREDITBAILVT` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18D-IMPOTS` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18E-CADEAUX` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-CHG-18F-PENALITES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-PROV-18E1-CREANCES` [autre/hors_perimetre] — valeurs issues doc client 5 — a valider metier
- `BIC-PROV-18E1-RISQUES` [autre/bloqueur] — perimetre exclusions 18 E 1°
- `CE-143-APPRENTISSAGE` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `CE-146-EMPLOYEUR` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `ENR-29-CONDAMNATION` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `ENR-666-ACTES` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `FONC-171-ACOMPTELOYER` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `FONC-34-PATRIMOINE` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `IRC-194-CREANCES` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `IRVM-182-DISTRIB` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `ITS-119-MASSESAL` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-108-HONORAIRES` [autre/sourcable] — comptes 622/628
- `OBL-338-REEVALUATION` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-36-ETII` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-36BIS-CBCR` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-49BIS-REGISTRES` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-49TER-RBE` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBL-ACOMPTES-IMPUTATION` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBNL-339-NONLUCRATIF` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `OBNL-35-STARTUP` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `PAT-272-PATENTE` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-CIE-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-CNX-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-CNX-02` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-02` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-03` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-04` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-FISC-05` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-IMMO-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-IMMO-02` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-RECON-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-STOCK-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RA-TRANSF-01` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `RAS-92-NONRESIDENT` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `TIMBRE-805-DOCS` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `TVA-COL-RAPPRO-CA` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `TVA-DED-PRORATA` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier
- `TVA-TIERS-NONRESIDENT` [autre/hors_perimetre] — valeurs issues docs client 6/9/10 — a valider metier

## Par règle

### `BIC-AMORT-18B-GENERAL` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-AMORT-18B-INFO` (2)

- [date/sourcable] date d effet
- [autre/bloqueur] fraction recalculee vs dotation entiere

### `BIC-AMORT-18B-VEHICULES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18-MIXTES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A-ASSURANCES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A1-EXPATRIES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A1-SALAIRES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A2-LOYERS` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A3-FRAISSIEGE` (4)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier
- [taux/sourcable] taux 5%/20%
- [agregat/bloqueur] definition FRAIS_GENERAUX

### `BIC-CHG-18A4-ADMIN` (2)

- [date/sourcable] date d effet
- [seuil/sourcable] plafond 3 000 000 FCFA / beneficiaire / an

### `BIC-CHG-18A5-INTERETS` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A6-CCATAUX` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18A6-SOUSCAP` (4)

- [date/sourcable] date d effet
- [agregat/bloqueur] assiette 30 % — RESULTAT_AVANT_IMPOT a figer
- [autre/bloqueur] limites (a)(c)(d)(e)
- [taux/sourcable] taux BCEAO + 2

### `BIC-CHG-18B-CREDITBAILVT` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18D-IMPOTS` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18E-CADEAUX` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18F-PENALITES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-CHG-18G-DONS` (3)

- [taux/sourcable] taux 2,5 % — verifier art. 18 G / annexe fiscale
- [seuil/sourcable] plafond 200 000 000 FCFA — verifier art. 18 G
- [date/sourcable] date d effet 01/01/2026

### `BIC-PROV-18E1-CREANCES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues doc client 5 — a valider metier

### `BIC-PROV-18E1-RISQUES` (2)

- [date/sourcable] date d effet
- [autre/bloqueur] perimetre exclusions 18 E 1°

### `CE-143-APPRENTISSAGE` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `CE-146-EMPLOYEUR` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `ENR-29-CONDAMNATION` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `ENR-666-ACTES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `FONC-171-ACOMPTELOYER` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `FONC-34-PATRIMOINE` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `IRC-194-CREANCES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `IRVM-182-DISTRIB` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `ITS-119-MASSESAL` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBL-108-HONORAIRES` (3)

- [date/sourcable] date d effet
- [seuil/sourcable] seuils 50 000 / 10 000
- [autre/sourcable] comptes 622/628

### `OBL-338-REEVALUATION` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBL-36-ETII` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBL-36BIS-CBCR` (3)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier
- [seuil/sourcable] seuil 250 Md FCFA a confirmer

### `OBL-49BIS-REGISTRES` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBL-49TER-RBE` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBL-ACOMPTES-IMPUTATION` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBNL-339-NONLUCRATIF` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `OBNL-35-STARTUP` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `PAT-272-PATENTE` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-CIE-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-CNX-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-CNX-02` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-FISC-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-FISC-02` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-FISC-03` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-FISC-04` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-FISC-05` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-IMMO-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-IMMO-02` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-RECON-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-STOCK-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RA-TRANSF-01` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `RAS-92-NONRESIDENT` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `TIMBRE-805-DOCS` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `TVA-COL-RAPPRO-CA` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `TVA-DED-PRORATA` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

### `TVA-TIERS-NONRESIDENT` (2)

- [date/sourcable] date d effet 01/01/2026
- [autre/hors_perimetre] valeurs issues docs client 6/9/10 — a valider metier

---

Purge = circuit éditorial 2AàZ, pas seed auto. L'IA propose, l'humain valide. Aucun taux/article inventé ici.
