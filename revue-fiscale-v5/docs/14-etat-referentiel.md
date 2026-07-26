# État du référentiel — vérité opérationnelle

> Généré le `2026-07-26T02:47:12Z`. **Ne pas éditer à la main** — régénérer via `python -m backend.scripts.etat_referentiel` ou `make etat-referentiel`.
>
> État généré par scan des YAML — ne constitue pas une validation fiscale. Les références légales présentes dans les fiches restent à confirmer tant que la liste a_confirmer n'est pas vide. Aucune analogie française. Aucune invention de taux/article/date.

## Chiffres (scan YAML réel)

| Indicateur | Valeur |
|---|---:|
| Fiches `referentiel/*.yaml` | **57** |
| Fiches encore marquées `EMPLACEMENT` | **0** |
| Fichiers dans `referentiel/emplacements/` | **0** |
| Fiches avec au moins un `a_confirmer` | **57** |
| Fiches sans `a_confirmer` (validées fiscaliste) | **0** |
| Mentions `a_confirmer` totales | **121** |
| Empreinte inventaire | `2a38df15f5b2275d814a030c8d497616161b42f7b5a1d8111a1f0cbf1387b4f2` |

### Mentions par catégorie (heuristique éditoriale)

| Catégorie | Nb |
|---|---:|
| `date` | 57 |
| `taux` | 3 |
| `seuil` | 4 |
| `agregat` | 2 |
| `autre` | 55 |

### Répartition par `impot` (libellé fiche, non certifié)

| Impôt (champ YAML) | Nb fiches |
|---|---:|
| `BIC` | 20 |
| `CE` | 2 |
| `ENR` | 2 |
| `FONC` | 2 |
| `IRC` | 1 |
| `IRVM` | 1 |
| `ITS` | 1 |
| `OBL` | 7 |
| `OBNL` | 2 |
| `PAT` | 1 |
| `RA` | 13 |
| `RAS` | 1 |
| `TIMBRE` | 1 |
| `TVA` | 3 |

## Lecture honnête

- Harnais 57 fiches : **oui**
- Plus d'EMPLACEMENT YAML restant : **oui**
- Aucune fiche certifiée (sans `a_confirmer`) : **oui**
- Les 57 fiches sont des brouillons métier opérationnels pour le moteur (expressions + cas de test). Les paramètres numériques / dates / articles cités restent a_confirmer. Ne pas publier comme droit positif certifié. a_confirmer = vérité éditoriale affichée ; ce n'est pas un stop runtime.

## En attente éditeur (pas un stop produit)

- **`bloque_runtime`** : **non** — moteur, missions, inscription, démo tournent sans CGI intégral.
- **`statut_editorial` corpus** : `en_attente_corpus`

1. **Purge des `a_confirmer`** — circuit éditorial humain uniquement (console `/console` → file À confirmer). Jamais seed auto. Sans CGI : la file reste ouverte, la purge reste suspendue.
2. **Validation article / taux / seuil / date** — chaque mention listée dans `referentiel/INVENTAIRE_A_CONFIRMER.md`.
3. **Corpus CGI / annexe** — voir ci-dessous.

## Corpus PDF

**Statut éditorial `en_attente_corpus` (≠ stop runtime) :** CGI CI 2026 intégral absent du dépôt (purge fiscale en attente). Annexe fiscale 2026 liée + ingérée (`type=annexe`, ~443 fragments) — **Annexe ≠ CGI** ; croisement `docs/16-annexe-2026-vs-a-confirmer.md` (minorité de pistes, 0 purge). Dépôt attendu : corpus_sources/CGI-CI-2026.pdf (ou .md/.txt). Le SaaS (moteur, missions, inscription) n'est pas arrêté. Ne pas inventer le CGI.

Ingestion : `make ingerer-corpus FICHIER=… TYPE=cgi|annexe MILLESIME=2026` (voir `corpus_sources/README.md`). L'ingestion crée des fragments corpus — **elle ne génère pas de règles fiscales validées**. Session 7 seuils : `docs/15-session-fiscaliste-7-seuils.md`. Checklist bloqueurs humains : `docs/15-bloqueurs-humains.md` (CGI absent → `corpus_sources/ATTENTE-CGI-CI-2026.md`).

### Sources publiques connues (consultation)

- https://dgi.gouv.ci/ — portail DGI CI — liens CGI / annexe / doctrine
- https://cgici.com/ — viewer HTML CGI+LPF CI (DGI/EssiC) — **ingestion brouillon** :
  `make ingerer-cgici` → `docs/17-ingestion-cgici.md` (scrape ≠ visa ; PDF DGI toujours souhaité)
- https://www.dgi.gouv.ci/assets/documents/ANNEXE_FISCALE_2026/ — annexe fiscale 2026 (DGI) — déjà miroir local possible

### Candidats CGI / annexe

- `corpus_sources/Annexe-1-Annexe-Fiscale-2026.pdf` — _candidat_annexe_

### PDF présents (hors exclusions)

- `corpus_sources/Annexe-1-Annexe-Fiscale-2026.pdf` — _candidat_annexe_
- `fixtures/demo_exports/rapport-170.pdf` — _export_demo_
- `fixtures/demo_exports/rapport-183.pdf` — _export_demo_
- `fixtures/demo_exports/rapport-191.pdf` — _export_demo_

## Commandes

```bash
make etat-referentiel          # régénère ce document
make inventaire-a-confirmer    # MD + file JSON a_confirmer
make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026
make seed                      # charge YAML → millésime publié
make demolot                   # smoke cabinet + 1 mission FICTIF (rejeu OK)
make test-regles               # harnais non-régression
```

Console : `/console` → **À confirmer** (`GET /api/v1/editorial/a-confirmer`).

---

Aucun taux, article ou date inventé ici.
