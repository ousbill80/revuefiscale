# Dépôt des sources corpus (domaine éditorial)

Zone d’atterrissage des textes réglementaires à indexer. **Pas** de règles fiscales ici —
l’ingestion crée des fragments consultables ; la purge des `a_confirmer` reste un acte
humain 2AàZ (console `/console`).

## Quoi déposer

| Source | Nom de fichier suggéré | `type` CLI | Débloque |
|---|---|---|---|
| **CGI CI 2026 (intégral)** | `CGI-CI-2026.pdf` ou `CGI-CI-2026.md` / `.txt` | `cgi` | Session 7 taux/seuils (dont **art. 18 G**) |
| Annexe fiscale 2026 | `Annexe-1-Annexe-Fiscale-2026.pdf` | `annexe` | Recherche / veille ; **ne remplace pas** le CGI pour les seuils 18 G |
| Note DGI / circulaire | `NOTE-….pdf` | `note_dgi` | Doctrine datée |

Formats acceptés : **PDF** (extraction via `pdftotext`), **Markdown**, **texte brut**.

## Comment ingérer

```bash
# Prérequis : make db-up ; pdftotext (poppler) pour les PDF
make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026

# Ou chemin absolu hors dépôt
python -m backend.scripts.ingerer_corpus \
  --fichier "/chemin/vers/CGI-CI-2026.pdf" \
  --type cgi \
  --millesime 2026 \
  --titre "CGI Côte d'Ivoire 2026"

# Dry-run (extrait + stats, aucune écriture DB)
python -m backend.scripts.ingerer_corpus --fichier … --type cgi --dry-run
```

## État actuel (audit chasse PDF + cgici)

- **CGI intégral PDF** : **ABSENT** (chassé dans le dépôt / parent).
  → Instruction : **`ATTENTE-CGI-CI-2026.md`**
  → Chemin PDF cible : **`corpus_sources/CGI-CI-2026.pdf`**
- **CGI + LPF HTML (cgici.com)** : ingestion brouillon possible —
  `make ingerer-cgici` → `CGI-CI-2026-cgici.txt` + journal URLs.
  Doc : **`docs/17-ingestion-cgici.md`**. Scrape ≠ visa ; **ne purger aucun**
  `a_confirmer` automatiquement.
- **Annexe fiscale 2026** (LF 2025-987) : lien local + **ré-ingestion brouillon**
  (`type=annexe`, ~443 fragments). Texte extractible (OCR ABBYY) de bonne qualité.
  **Annexe ≠ CGI intégral** : elle amende / complète pour 2026 ; elle ne remplace pas
  le dépôt article-par-article. Croisement inventaire : `docs/16-annexe-2026-vs-a-confirmer.md`
  (~8 pistes claires / 121 ; piège 2,5 % = taxe touristique art. 1140 ≠ dons 18 G).
  → **0 purge** YAML depuis l’annexe seule.
- Corpus indexé : annexe (brouillon) + seed **`[DÉMO FICTIF]`** éventuel
  (`POST /api/v1/editorial/corpus/seed-demo`).

## Après dépôt du CGI

1. Copier ou lier → `corpus_sources/CGI-CI-2026.pdf`
2. `make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026`
3. Session fiscaliste : `docs/15-session-fiscaliste-7-seuils.md` (priorité art. 18 G)
4. Propositions de purge → file éditoriale (`workflow_a_confirmer.json` /
   `/console`) — **jamais** hardcode dans le moteur

Aucun taux, article ou date inventé ici.
