# Fixtures de démo — [DÉMO FICTIF]

Tous les fichiers de ce dossier sont **synthétiques** et **non opposables**.
Ils servent uniquement aux tests, au smoke mission et à l’UI `/app`.
**Ce ne sont pas des clients anonymisés réels.**

| Fichier | Usage |
|---|---|
| `balance_demo.csv` / `.json` | Balance SYSCOHADA labellisée `[FICTIF]` (jeu court) |
| `balance_fictif_commerce.*` | Jeu commerce équilibré — mapping / contrôles |
| `balance_fictif_services.*` | Jeu services équilibré — mapping / contrôles |
| `balance_fictif_desequilibree.*` | Déséquilibre volontaire — test contrôles |
| `etats_financiers_demo.*` | EF synthétiques |
| `grand_livre_demo.csv` / `fec_demo.txt` | Lecteurs formats |
| `demo_exports/rapport-*.pdf` | Exports de démo moteur — **pas** le CGI |

## Interdit

- Présenter ces montants comme une situation réelle ou un client anonymisé
- En déduire un article, taux ou seuil CGI Côte d’Ivoire

## Rejouer

```bash
make seed && make demolot
# UI : make frontend && make dev → /app
# Chip « Connexion démo » (localhost + ENV=dev) — credentials CABINET_DEMO_*
```

Alias : `make demo-mission` ≡ `make demolot`. Smoke API : `make smoke-mission`.
