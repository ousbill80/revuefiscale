# En attente — CGI Côte d'Ivoire 2026 (intégral)

**Statut : PARTIEL — scrape cgici.com (brouillon) OU PDF officiel absent**

Chasse PDF : aucun `CGI-CI-2026.pdf` trouvé dans le dépôt.
**Alternative technique** : ingestion HTML depuis https://cgici.com/
(`make ingerer-cgici` — voir `docs/17-ingestion-cgici.md`).

Le scrape **ne remplace pas** un visa fiscaliste ni un PDF DGI pour archive.
Mentions site : Publications DGI / EssiC — tous droits réservés.

## Que déposer (2AàZ) — PDF préféré

| Action | Détail |
|---|---|
| Copier / lier le PDF | `corpus_sources/CGI-CI-2026.pdf` |
| Formats de secours | `CGI-CI-2026.md` ou `.txt` (texte extractible) |
| Puis ingérer | `make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026` |
| Ou scrape HTML | `make ingerer-cgici MILLESIME=2026` → `CGI-CI-2026-cgici.txt` |

## Chemin d’attente exact

```text
revue-fiscale-v5/corpus_sources/CGI-CI-2026.pdf
```

Depuis la racine du monorepo parent (si le PDF arrive ailleurs) :

```bash
cd "revue-fiscale-v5"
ln -sf "/chemin/absolu/vers/CGI-CI-2026.pdf" corpus_sources/CGI-CI-2026.pdf
make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026
```

## Ce que l’ingestion ne fait pas

- Ne valide aucune règle fiscale
- Ne retire aucun `a_confirmer`
- Ne remplace pas le visa fiscaliste (`docs/15-session-fiscaliste-7-seuils.md`)

Sans CGI intégral : **0 purge** des seuils / articles (dont art. 18 G) à partir de l’annexe seule.

## Annexe ≠ CGI

L’Annexe fiscale 2026 est **déjà liée et ingérée** (`TYPE=annexe`). Elle sert à la veille
des amendements de l’année. Elle **ne constitue pas** le corpus CGI article-par-article
requis pour certifier la majorité des `a_confirmer` (taux, plafonds historiques, 18 B/G…).

Rapport de croisement (pistes minoritaires, pièges, blocages) :
`docs/16-annexe-2026-vs-a-confirmer.md`.
