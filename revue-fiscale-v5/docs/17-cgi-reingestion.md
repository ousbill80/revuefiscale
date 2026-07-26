# Ré-ingestion CGI — procédure (complément)

> L’ingestion **cgici.com** est documentée et outillée par l’agent dédié :
> voir **`docs/17-ingestion-cgici.md`** + `make ingerer-cgici`.
> Ce fichier complète uniquement le **re-run** après dépôt PDF / cache, sans
> contredire ce flux.

## Commandes (ne pas inventer d’autre entrée)

| Cas | Commande |
|---|---|
| CGI depuis cgici.com | `make ingerer-cgici MILLESIME=2026` (détail : `docs/17-ingestion-cgici.md`) |
| Rejeu depuis cache local | `make ingerer-cgici DEPUIS_CACHE=1` |
| Dry-run | `make ingerer-cgici DRY_RUN=1` |
| PDF officiel DGI | `make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026` |

## Après ingestion (quelque soit la source)

1. `make inventaire-a-confirmer`
2. Fiscaliste : lot Annexe d’abord — `docs/18-lot-fiscaliste-annexe-8.md` + filtre **Pistes Annexe** dans `/console` ; puis lot CGI — `docs/19-cgi-vs-a-confirmer.md` + filtre **Pistes CGI** (ou vue **Pistes sourcées**)
3. Puis propositions sourcées CGI → file Propositions — **humain** valide
4. **0** purge YAML automatique

## Interdits (rappel AGENTS.md)

- Scrape ≠ visa fiscaliste
- Pas de purge `a_confirmer` sans citation + décision humaine
- Pas d’écrasement de millésime antérieur

**À confirmer** : conditions d’usage cgici.com avant exploitation commerciale du corpus.
