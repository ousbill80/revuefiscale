# Référentiel fiscal — format pivot YAML

## Contenu

| Emplacement | Rôle |
|---|---|
| `*.yaml` à la racine | **57 fiches métier** (Lots 1–3 + RA). **Toutes** portent `a_confirmer`. |
| `emplacements/` | Vide — plus d’EMPLACEMENT YAML restant. |
| `INVENTAIRE_A_CONFIRMER.md` | **Généré** — inventaire des mentions `a_confirmer` par thème / priorité. |
| `file_validation_a_confirmer.json` | File éditoriale lecture seule (`statut: en_attente`). |
| `docs/14-etat-referentiel.md` | **Vérité opérationnelle** (chiffres scan) — `make etat-referentiel`. |

Régénération seed : `make seed` (Lot1 puis Lots 2/3/RA → millésime `v2026.7-complet`).

## Purge des `a_confirmer`

**Purge = circuit éditorial 2AàZ, pas seed auto.**

- L'IA / le seed **proposent** des brouillons sourcés ; ils ne valident pas un taux, un seuil,
  une date d'effet ni un article CGI.
- Retirer un `a_confirmer` sans validation humaine (ou en comblant par analogie française)
  est interdit — cf. `AGENTS.md`.
- Inventaire (lecture seule) :

```bash
make inventaire-a-confirmer
# → referentiel/INVENTAIRE_A_CONFIRMER.md
# → referentiel/file_validation_a_confirmer.json

make etat-referentiel
# → docs/14-etat-referentiel.md
```

Console : `/console` → section « À confirmer » (`GET /api/v1/editorial/a-confirmer`).
Colonnes : **rule_id**, index, priorité, catégorie, **champ à valider**.

## Seed / démos

```bash
make seed
make demolot        # admin@demo.local + 1 mission balance FICTIF (rejeu OK)
make demolot1       # parcours technique Lot 1 (moteur)
make demolot234     # multi-domaines + exports Word/PDF
```
