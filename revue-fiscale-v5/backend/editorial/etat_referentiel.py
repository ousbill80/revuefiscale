"""État réel du référentiel YAML — inventaire honnête, sans invention fiscale.

Ne valide aucun article / taux / seuil. Ne transforme pas EMPLACEMENT en règle sourcée.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from backend.editorial.inventaire_a_confirmer import (
    RACINE_PROJET,
    RACINE_REFERENTIEL,
    construire_inventaire,
    lister_yaml,
)

CHEMIN_DOC_ETAT = RACINE_PROJET / "docs" / "14-etat-referentiel.md"
CHEMIN_EMPLACEMENTS = RACINE_REFERENTIEL / "emplacements"


def _contient_emplacement(obj: Any) -> bool:
    if isinstance(obj, str):
        return "EMPLACEMENT" in obj
    if isinstance(obj, dict):
        return any(_contient_emplacement(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contient_emplacement(v) for v in obj)
    return False


def _mentions_a_confirmer(data: dict[str, Any]) -> list[str]:
    brut = data.get("a_confirmer") or []
    if isinstance(brut, str):
        brut = [brut]
    if not isinstance(brut, list):
        return []
    return [str(x).strip() for x in brut if str(x).strip()]


def _classer_pdf(nom: str, rel: str) -> str:
    """Classe un PDF : cgi / annexe / démo / autre — sans affirmer le contenu juridique."""
    nom_l = nom.lower()
    rel_l = rel.lower()
    if "demo" in rel_l or "rapport" in nom_l:
        return "export_demo"
    if any(k in nom_l for k in ("cgi", "code-general", "code_general", "codegeneral")):
        return "candidat_cgi"
    if "annexe" in nom_l and ("fiscal" in nom_l or "fiscale" in nom_l):
        return "candidat_annexe"
    if "annexe" in nom_l or "fiscal" in nom_l:
        return "candidat_cgi_ou_annexe"
    return "autre"


def scanner_corpus_pdf(racine: Path | None = None) -> dict[str, Any]:
    """Repère les PDF du dépôt utiles (CGI / annexe) — hors node_modules / .venv."""
    base = racine or RACINE_PROJET
    exclus = {".venv", "node_modules", ".git", "dist", "__pycache__"}
    pdfs: list[dict[str, str]] = []
    for chemin in sorted(base.rglob("*.pdf")):
        if any(p in exclus for p in chemin.parts):
            continue
        # Suivre les symlinks (ex. corpus_sources/ → PDF parent workspace)
        if not chemin.exists():
            continue
        rel = str(chemin.relative_to(base))
        indice = _classer_pdf(chemin.name, rel)
        pdfs.append({"chemin": rel, "indice": indice})

    candidats_cgi = [p for p in pdfs if p["indice"] == "candidat_cgi"]
    candidats_annexe = [p for p in pdfs if p["indice"] == "candidat_annexe"]
    candidats_ambigus = [p for p in pdfs if p["indice"] == "candidat_cgi_ou_annexe"]
    candidats = candidats_cgi + candidats_annexe + candidats_ambigus

    cgi_ok = bool(candidats_cgi)
    annexe_ok = bool(candidats_annexe) or bool(candidats_ambigus)

    # Statuts distincts — ne jamais confondre vérité éditoriale et runtime SaaS.
    # bloque_runtime est toujours False ici : le moteur / missions / inscription
    # n'exigent pas le CGI intégral. Seule la purge a_confirmer attend le corpus.
    if cgi_ok:
        statut_editorial = "corpus_cgi_present"
        message_editorial = None
    elif annexe_ok:
        statut_editorial = "en_attente_corpus"
        message_editorial = (
            "CGI CI 2026 intégral absent du dépôt (purge fiscale en attente). "
            "Annexe fiscale détectée : ingestion `type=annexe` possible, "
            "insuffisante pour purger les taux/seuils art. 18 G (dons). "
            "Dépôt attendu : corpus_sources/CGI-CI-2026.pdf (ou .md/.txt). "
            "Le SaaS (moteur, missions, inscription) n'est pas arrêté. "
            "Ne pas inventer le CGI."
        )
    else:
        statut_editorial = "en_attente_corpus"
        message_editorial = (
            "Aucun PDF CGI / annexe fiscale dans le dépôt. "
            "Déposer le CGI dans corpus_sources/CGI-CI-2026.pdf "
            "(voir corpus_sources/README.md) pour indexation éditoriale. "
            "Seuls des exports de démo éventuels. "
            "Statut éditorial en_attente_corpus — pas un stop runtime. "
            "Ne pas inventer le CGI."
        )

    return {
        "pdfs_trouves": pdfs,
        "candidats_cgi": candidats_cgi,
        "candidats_annexe": candidats_annexe,
        "candidats_cgi_annexe": candidats,
        "cgi_extractible": cgi_ok,
        "annexe_extractible": annexe_ok,
        "statut_editorial": statut_editorial,
        "bloque_runtime": False,
        "message_editorial": message_editorial,
        # Alias historique (tests / scripts) — message éditorial, pas un hard-stop produit.
        "blocage": message_editorial,
        "depot_attendu": "corpus_sources/CGI-CI-2026.pdf",
        "sources_publiques_connues": [
            {
                "url": "https://dgi.gouv.ci/",
                "role": "portail DGI CI — liens CGI / annexe / doctrine",
            },
            {
                "url": "https://cgici.com/",
                "role": (
                    "viewer HTML CGI CI (DGI) — consultation humaine ; "
                    "pas un PDF dépôt prêt à make ingerer-corpus"
                ),
            },
            {
                "url": "https://www.dgi.gouv.ci/assets/documents/ANNEXE_FISCALE_2026/",
                "role": "annexe fiscale 2026 (DGI) — déjà miroir local possible",
            },
        ],
    }


def construire_etat(racine: Path | None = None) -> dict[str, Any]:
    """Scan YAML réel + inventaire a_confirmer + corpus."""
    base = racine or RACINE_REFERENTIEL
    inventaire = construire_inventaire(base)
    fiches: list[dict[str, Any]] = []
    emplacement_yaml = 0
    avec_ac = 0
    sans_ac = 0
    par_impot: dict[str, int] = defaultdict(int)

    for chemin in lister_yaml(base):
        data = yaml.safe_load(chemin.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        identifiant = str(data.get("identifiant") or chemin.stem)
        mentions = _mentions_a_confirmer(data)
        est_empl = _contient_emplacement(data)
        if est_empl:
            emplacement_yaml += 1
        if mentions:
            avec_ac += 1
        else:
            sans_ac += 1
        impot = str(data.get("impot") or "non_renseigne")
        par_impot[impot] += 1
        fiches.append(
            {
                "identifiant": identifiant,
                "fichier": chemin.name,
                "impot": impot,
                "reference_legale": data.get("reference_legale"),
                "nb_a_confirmer": len(mentions),
                "champs_a_confirmer": mentions,
                "marque_emplacement": est_empl,
            }
        )

    emplacements_dir = CHEMIN_EMPLACEMENTS if racine is None else (base / "emplacements")
    n_empl_fichiers = (
        len(list(emplacements_dir.glob("*.yaml"))) if emplacements_dir.is_dir() else 0
    )

    corpus = scanner_corpus_pdf(RACINE_PROJET if racine is None else racine.parent)

    return {
        "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "avertissement": (
            "État généré par scan des YAML — ne constitue pas une validation fiscale. "
            "Les références légales présentes dans les fiches restent à confirmer "
            "tant que la liste a_confirmer n'est pas vide. "
            "Aucune analogie française. Aucune invention de taux/article/date."
        ),
        "totaux": {
            "fiches_yaml": len(fiches),
            "fiches_marque_emplacement": emplacement_yaml,
            "fichiers_dans_emplacements_dir": n_empl_fichiers,
            "fiches_avec_a_confirmer": avec_ac,
            "fiches_sans_a_confirmer": sans_ac,
            "mentions_a_confirmer": inventaire["total_mentions"],
            "regles_concernees_a_confirmer": inventaire["total_regles_concernees"],
            # « Validée fiscaliste » = absence de a_confirmer après circuit éditorial.
            "fiches_validees_fiscaliste": sans_ac,
        },
        "comptes_a_confirmer_par_categorie": inventaire["comptes_par_categorie"],
        "par_impot": dict(sorted(par_impot.items())),
        "empreinte_a_confirmer": inventaire["empreinte"],
        "corpus": corpus,
        "fiches": fiches,
        "verite_operationnelle": {
            "harnais_57": len(fiches) == 57,
            "plus_d_emplacement_yaml": emplacement_yaml == 0 and n_empl_fichiers == 0,
            "aucune_fiche_certifiee": sans_ac == 0,
            "note": (
                "Les 57 fiches sont des brouillons métier opérationnels pour le moteur "
                "(expressions + cas de test). Les paramètres numériques / dates / articles "
                "cités restent a_confirmer. Ne pas publier comme droit positif certifié. "
                "a_confirmer = vérité éditoriale affichée ; ce n'est pas un stop runtime."
            ),
            "bloque_runtime": False,
        },
    }


def rendre_markdown(etat: dict[str, Any]) -> str:
    """Markdown pour ``docs/14-etat-referentiel.md``."""
    t = etat["totaux"]
    corpus = etat["corpus"]
    lignes: list[str] = [
        "# État du référentiel — vérité opérationnelle",
        "",
        f"> Généré le `{etat['genere_le']}`. **Ne pas éditer à la main** — "
        "régénérer via `python -m backend.scripts.etat_referentiel` ou `make etat-referentiel`.",
        ">",
        f"> {etat['avertissement']}",
        "",
        "## Chiffres (scan YAML réel)",
        "",
        "| Indicateur | Valeur |",
        "|---|---:|",
        f"| Fiches `referentiel/*.yaml` | **{t['fiches_yaml']}** |",
        f"| Fiches encore marquées `EMPLACEMENT` | **{t['fiches_marque_emplacement']}** |",
        f"| Fichiers dans `referentiel/emplacements/` | **{t['fichiers_dans_emplacements_dir']}** |",
        f"| Fiches avec au moins un `a_confirmer` | **{t['fiches_avec_a_confirmer']}** |",
        f"| Fiches sans `a_confirmer` (validées fiscaliste) | **{t['fiches_sans_a_confirmer']}** |",
        f"| Mentions `a_confirmer` totales | **{t['mentions_a_confirmer']}** |",
        f"| Empreinte inventaire | `{etat['empreinte_a_confirmer']}` |",
        "",
        "### Mentions par catégorie (heuristique éditoriale)",
        "",
        "| Catégorie | Nb |",
        "|---|---:|",
    ]
    for cat, n in etat["comptes_a_confirmer_par_categorie"].items():
        lignes.append(f"| `{cat}` | {n} |")

    lignes.extend(
        [
            "",
            "### Répartition par `impot` (libellé fiche, non certifié)",
            "",
            "| Impôt (champ YAML) | Nb fiches |",
            "|---|---:|",
        ]
    )
    for impot, n in etat["par_impot"].items():
        lignes.append(f"| `{impot}` | {n} |")

    vo = etat["verite_operationnelle"]
    lignes.extend(
        [
            "",
            "## Lecture honnête",
            "",
            f"- Harnais 57 fiches : **{'oui' if vo['harnais_57'] else 'non'}**",
            f"- Plus d'EMPLACEMENT YAML restant : **{'oui' if vo['plus_d_emplacement_yaml'] else 'non'}**",
            f"- Aucune fiche certifiée (sans `a_confirmer`) : **{'oui' if vo['aucune_fiche_certifiee'] else 'non'}**",
            f"- {vo['note']}",
            "",
            "## En attente éditeur (pas un stop produit)",
            "",
            f"- **`bloque_runtime`** : **{'oui' if corpus.get('bloque_runtime') else 'non'}** "
            "— moteur, missions, inscription, démo tournent sans CGI intégral.",
            f"- **`statut_editorial` corpus** : "
            f"`{corpus.get('statut_editorial') or 'inconnu'}`",
            "",
            "1. **Purge des `a_confirmer`** — circuit éditorial humain uniquement "
            "(console `/console` → file À confirmer). Jamais seed auto. "
            "Sans CGI : la file reste ouverte, la purge reste suspendue.",
            "2. **Validation article / taux / seuil / date** — chaque mention listée "
            "dans `referentiel/INVENTAIRE_A_CONFIRMER.md`.",
            "3. **Corpus CGI / annexe** — voir ci-dessous.",
            "",
            "## Corpus PDF",
            "",
        ]
    )
    if corpus.get("message_editorial") or corpus.get("blocage"):
        msg = corpus.get("message_editorial") or corpus.get("blocage")
        lignes.extend(
            [
                f"**Statut éditorial `en_attente_corpus` (≠ stop runtime) :** {msg}",
                "",
                "Ingestion : `make ingerer-corpus FICHIER=… TYPE=cgi|annexe MILLESIME=2026` "
                "(voir `corpus_sources/README.md`). "
                "L'ingestion crée des fragments corpus — **elle ne génère pas de règles "
                "fiscales validées**. Session 7 seuils : "
                "`docs/15-session-fiscaliste-7-seuils.md`.",
                "",
            ]
        )
    else:
        lignes.append("CGI détecté — candidats :")
        for p in corpus.get("candidats_cgi") or []:
            lignes.append(f"- `{p['chemin']}`")
        lignes.append("")
    if corpus.get("sources_publiques_connues"):
        lignes.extend(["### Sources publiques connues (consultation)", ""])
        for s in corpus["sources_publiques_connues"]:
            lignes.append(f"- {s['url']} — {s['role']}")
        lignes.append("")

    if corpus.get("candidats_annexe") or corpus.get("candidats_cgi"):
        lignes.extend(["### Candidats CGI / annexe", ""])
        for p in corpus.get("candidats_cgi_annexe") or []:
            lignes.append(f"- `{p['chemin']}` — _{p['indice']}_")
        lignes.append("")

    if corpus.get("pdfs_trouves"):
        lignes.extend(["### PDF présents (hors exclusions)", ""])
        for p in corpus["pdfs_trouves"]:
            lignes.append(f"- `{p['chemin']}` — _{p['indice']}_")
        lignes.append("")

    lignes.extend(
        [
            "## Commandes",
            "",
            "```bash",
            "make etat-referentiel          # régénère ce document",
            "make inventaire-a-confirmer    # MD + file JSON a_confirmer",
            "make ingerer-corpus FICHIER=corpus_sources/CGI-CI-2026.pdf TYPE=cgi MILLESIME=2026",
            "make seed                      # charge YAML → millésime publié",
            "make demolot                   # smoke cabinet + 1 mission FICTIF",
            "make test-regles               # harnais non-régression",
            "```",
            "",
            "Console : `/console` → **À confirmer** (`GET /api/v1/editorial/a-confirmer`).",
            "",
            "---",
            "",
            "Aucun taux, article ou date inventé ici.",
            "",
        ]
    )
    return "\n".join(lignes)


def ecrire_doc(racine: Path | None = None, *, chemin_doc: Path | None = None) -> dict[str, Any]:
    """Écrit ``docs/14-etat-referentiel.md``."""
    etat = construire_etat(racine)
    cible = chemin_doc or CHEMIN_DOC_ETAT
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(rendre_markdown(etat), encoding="utf-8")
    etat["chemin_doc"] = str(cible)
    return etat
