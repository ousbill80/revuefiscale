# Lot fiscaliste — 8 pistes Annexe 2026

> Checklist **imprimable / export** pour le fiscaliste 2AàZ.
> Outillage uniquement — **pas** un visa. Aucune purge `a_confirmer` YAML.
> Source : `docs/16-annexe-2026-vs-a-confirmer.md` · catalogue
> `referentiel/propositions_annexe_2026_pistes.json`.

| | |
|---|---|
| Console | `/console` → **À confirmer** |
| Compte démo | `editorial@2aaz.ci` / `EditorialDemo2026!` |
| Filtre | Vue → **Pistes Annexe (~8)** |
| Propositions | `/console` → **Propositions** (source `annexe_2026_croisement`) |
| Seed DB | `make seed-pistes-annexe` (ou `make seed-editorial-pistes`) |

---

## Comment ouvrir la file

1. Lancer l’API (`make dev`) + ouvrir **http://localhost:8000/console**
2. Se connecter en staff **editorial**
3. Menu **À confirmer**
4. Dans **Vue**, choisir **Pistes Annexe (~8)**
5. Cliquer une ligne → panneau détail : extrait Annexe, suggestion, bouton **Voir proposition #…**
6. Action possible sans purge : **Marquer en revue** + note (ex. « croisé Annexe p.108 — en attente CGI »)
7. Sur la proposition : **Préparer patch** (aperçu / téléchargement) **avant** toute écriture ; **Appliquer au YAML** seulement après confirmation (garde-fou `a_confirmer`). Accepter (statut) / corriger / rejeter = workflow file, **pas** validation du fond fiscal.

Interdit : retirer un `a_confirmer` du YAML sans source CGI certaine + décision humaine.

---

## Les 8 actions concrètes

Cocher après revue humaine. Colonne « Décision » = note éditeur / statut proposition.

| # | Entrée file | rule_id | Pages Annexe | Action fiscaliste | Décision |
|---|---|---|---|---|---|
| 1 | `PAT-272-PATENTE#0` | PAT-272-PATENTE | 108–109 | Lire amendement art. 272 (plateformes). **Ne pas** purger date `01/01/2026` sur la seule Annexe. Noter en revue. | ☐ |
| 2 | `PAT-272-PATENTE#1` | PAT-272-PATENTE | 108–109 | Évaluer MAJ description / questions (plateformes). Laisser hors_perimetre si seed client. | ☐ |
| 3 | `RAS-92-NONRESIDENT#0` | RAS-92-NONRESIDENT | 36, 129 | Si fiche = réassurance : documenter exonération CIMA → **30/04/2027**. Sinon hors champ. Ne pas substituer à la date seed. | ☐ |
| 4 | `RAS-92-NONRESIDENT#1` | RAS-92-NONRESIDENT | 36, 129 | Croiser périmètre fiche × extrait Annexe (pertinence partielle). | ☐ |
| 5 | `OBL-36-ETII#0` | OBL-36-ETII | 86–87, 96 | Contraste : seed `01/01/2026` ≠ démat. **2027/2028**. Distinguer date d’effet règle vs échéance démat. **Ne pas** remplacer. | ☐ |
| 6 | `OBL-36-ETII#1` | OBL-36-ETII | 86–87, 96 | Même famille — note croisée, pas purge. | ☐ |
| 7 | `OBL-49BIS-REGISTRES#0` | OBL-49BIS-REGISTRES | 86–87, 96 | Idem contraste dates (art. 49 bis touché par démat.). | ☐ |
| 8 | `OBL-49BIS-REGISTRES#1` | OBL-49BIS-REGISTRES | 86–87, 96 | Revue description vs dispositions démat. Annexe. | ☐ |

---

## Hors lot (rappel docs/16)

| Classe | Action |
|---|---|
| Veille 18-A) **11°** (p.132) | Ticket éditorial séparé — **interdit** de purger taux/seuils 18 A |
| FONC-* / Article 34 Annexe | Revue croisée humaine — pas purge auto |
| Pièges 2,5 % / 200 M / 3 M | **Ne pas** croiser avec 18 G / 18 A4 |
| ~82 mentions bloquées CGI | Attendre CGI intégral + visa |

---

## Après le lot

- Toujours bloqué pour certification massive : PDF CGI CI 2026 (`corpus_sources/CGI-CI-2026.pdf` ou ingestion cgici — voir `docs/17-cgi-reingestion.md`)
- Purge YAML = acte humain sourcé uniquement

**À confirmer** : toute lecture d’un taux, seuil ou date Annexe comme droit positif applicable à une fiche seed reste soumise au fiscaliste + CGI intégral.
