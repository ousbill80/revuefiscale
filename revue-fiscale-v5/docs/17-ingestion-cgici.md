# 17 — Ingestion CGI / LPF depuis cgici.com

**Statut : brouillon éditorial sourcé — pas un visa fiscaliste.**

Ingestion déterministe du texte HTML de https://cgici.com/ (édition 2026) vers
`source_document` / `article_corpus` / `fragment_corpus`. Aucune règle fiscale
n’est écrite. Aucun `a_confirmer` n’est retiré automatiquement.

---

## Mentions juridiques (lues sur le site)

Sur la page d’accueil / couverture :

> Édité par Les Publications de la DGI et produit par EssiC Ingénierie —
> tous droits réservés (c) 2015-2026

- Pas de page CGU distincte trouvée (robots.txt / sitemap absents ou 404).
- Le texte présenté est intitulé « Version Officielle 2026 » du CGI + LPF +
  autres textes fiscaux.
- **Usage prévu ici** : corpus **interne** R&D / croisement éditorial
  (`a_confirmer`), pas republication du produit numérique EssiC, pas licence
  commerciale implicite.
- Si 2AàZ doit redistribuer ou commercialiser une copie du CGI numérique :
  obtenir PDF/licence DGI ou accord EssiC — **ne pas** traiter ce scrape comme
  titre de propriété.

---

## Périmètre chargé

| Élément | Détail |
|---|---|
| Source | `https://cgici.com/` dossier `V2026/page-N.html` |
| Index | `js/ArticleLink.js` (**1430** entrées article → page) |
| Périmètre | **CGI + LPF** (pages référencées par ArticleLink) |
| Résultat typique | **357** pages OK · **1** page 404 (`page-184`) · **~1495** articles découpés · **~3437** fragments |
| Collision CGI/LPF | Le HTML LPF reprend `Art. 1…` ; offset **+5000** à l’assemblage (aligné ArticleLink) |
| Hors périmètre volontaire | Notes / doctrine / conventions du sommaire **non** présentes dans ArticleLink |
| Millésime | 2026 |
| `source_document.type` | `cgi` |
| Historiques millésime | Blocs `.historique` / `.histText` **exclus** (texte courant seulement) |

Chiffres exacts après un run : voir `corpus_sources/cgici_2026/meta.json`.

---

## Artefacts locaux

| Chemin | Rôle |
|---|---|
| `corpus_sources/CGI-CI-2026-cgici.txt` | Texte assemblé (re-ingestion sans réseau) |
| `corpus_sources/cgici_2026/pages/*.html` | HTML brut téléchargé |
| `corpus_sources/cgici_2026/journal_urls.jsonl` | Journal URL / statut / octets |
| `corpus_sources/cgici_2026/meta.json` | Compteurs + mention source |

---

## Comment rejouer

```bash
cd revue-fiscale-v5
make db-up   # si besoin

# Scrape + ingestion DB (rate-limit ~0.6 s / page, User-Agent explicite)
make ingerer-cgici MILLESIME=2026

# Dry-run (écrit le texte + journal, pas de DB)
make ingerer-cgici DRY_RUN=1

# Re-ingestion depuis le cache local (pas de HTTP)
make ingerer-cgici DEPUIS_CACHE=1

# Ou CLI directe
python -m backend.scripts.ingerer_cgici --millesime 2026
python -m backend.scripts.ingerer_cgici --depuis-cache
python -m backend.scripts.ingerer_cgici --max-pages 5 --dry-run   # smoke réseau
```

Alternative PDF officiel (si dépôt manuel) :

```bash
make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026
```

---

## Paralléliser le scrape (workers)

Le téléchargement HTTP est le goulot (~0,6 s / page, pause min 0,4 s,
User-Agent `RevueFiscaleIntelligent/1.0 (+corpus-editorial-rd; …)`).
L’**import DB reste une seule passe** à la fin.

### Principes

1. Un scrape « principal » peut tourner ; **ne pas le tuer** s’il avance.
2. Des workers supplémentaires n’écrivent que des `page-N.html` **manquants**
   (`--cache-seulement` implique `--seulement-manquantes`).
3. Chaque worker écrit un journal **partiel**
   (`corpus_sources/cgici_2026/journal_urls.w-*.jsonl`) — il **n’écrase pas**
   `journal_urls.jsonl` du process principal.
4. Écriture HTML atomique (`.html.partial` → rename) pour éviter les lectures
   tronquées entre workers.
5. Quand le cache est complet : **une seule** commande
   `make ingerer-cgici DEPUIS_CACHE=1` (assemble le `.txt` + ingestion DB).

### Découpage

| Option | Effet |
|---|---|
| `--from-page` / `--to-page` | Filtre sur le n° de page HTML (inclusif) |
| `--offset` / `--limit` | Tranche sur la liste **triée** des pages ArticleLink |
| `--max-pages` | Alias historique de `--limit` (smoke) |
| `--seulement-manquantes` | Skip HTTP si `page-N.html` existe déjà |
| `--cache-seulement` | Worker : HTML + journal partiel ; pas de `.txt` / meta / DB |
| `--pause` | Secondes entre requêtes (plancher 0,4) |

Exemple — 2 workers sur des plages disjointes (index déjà en cache) :

```bash
# Terminal A
make ingerer-cgici CACHE_SEULEMENT=1 OFFSET=0 LIMIT=180 PAUSE=0.6

# Terminal B
make ingerer-cgici CACHE_SEULEMENT=1 OFFSET=180 LIMIT=180 PAUSE=0.6

# Ou par n° de page
make ingerer-cgici CACHE_SEULEMENT=1 FROM_PAGE=1 TO_PAGE=400
make ingerer-cgici CACHE_SEULEMENT=1 FROM_PAGE=401 TO_PAGE=973

# Après convergence du cache
make ingerer-cgici DEPUIS_CACHE=1
```

CLI équivalente :

```bash
python -m backend.scripts.ingerer_cgici --cache-seulement --offset 0 --limit 180
python -m backend.scripts.ingerer_cgici --cache-seulement --from-page 500 --to-page 973
```

### Coordination avec un scrape déjà lancé

- Inspecter le cache : `ls corpus_sources/cgici_2026/pages/page-*.html | wc -l`
  et comparer à `pages_depuis_index(ArticleLink.js)` (~358 pages attendues pour
  CGI+LPF 2026, pas 1…973 contigu).
- Lancer des workers uniquement sur des plages encore absentes du cache.
- Ne **pas** lancer un second `DEPUIS_CACHE=1` / ingestion DB tant que des
  workers HTTP tournent (risque d’assembler un corpus incomplet).
- Pages en 404 côté site (ex. absentes de V2026) : **non inventées** ; rester
  dans le journal comme échec.

---

## Limites

1. Découpe `Art.` / `Article` heuristique — pas le décompte officiel DGI.
2. Articles absents de ArticleLink ou pages 404 : **non inventés**.
3. `menuTree.js` du site contient des libellés d’autres juridictions (template) :
   **ignoré** ; seule la cartographie ArticleLink + HTML `V2026` est utilisée.
4. Qualité OCR / HTML variable (espaces, intitulés de section).
5. Ne débloque **pas** automatiquement la session fiscaliste 7 seuils : le croisement
   `a_confirmer` reste humain (`docs/15-session-fiscaliste-7-seuils.md`).

---

## Tests

```bash
pytest tests/corpus/test_cgici.py -q
pytest tests/corpus/test_cgici_db.py -q -m db   # après ingestion
```

---

## Ce qui reste manuel

- Visa fiscaliste / purge `a_confirmer` (console éditoriale)
- Dépôt éventuel du PDF CGI-CI-2026 officiel pour double source
- Licence / accord si usage au-delà du corpus interne
- Ingestion des « autres textes » (notes, arrêtés) si besoin métier
