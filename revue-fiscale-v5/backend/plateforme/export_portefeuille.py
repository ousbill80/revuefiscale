"""Export téléchargeable du portefeuille déclaratif — texte + CSV.

POURQUOI : la relance des clients s'organise avec un support
diffusable en interne — le collaborateur veut EMPORTER le suivi
déclaratif du portefeuille (imprimé pour la réunion ou trié sous
Excel pour appeler les clients), pas seulement le consulter à
l'écran. Ce module REND le corps DÉJÀ assemblé par
:func:`backend.plateforme.portefeuille_declaratif.portefeuille_declaratif_cabinet`
en deux formats : texte français lisible (réunion) et CSV
point-virgule (tri sous Excel FR).

Aucun recalcul et AUCUNE duplication : le texte RÉUTILISE TEL QUEL
:func:`backend.plateforme.brief_cabinet.rendre_portefeuille_texte`
(déjà éprouvé par le brief du cabinet) — seul le rendu CSV s'ajoute
ici, fonction PURE de mise en forme, mêmes données que
GET /cabinet/portefeuille-declaratif. Assemblage déterministe et
CONSULTATIF (aucun LLM, aucun email). Pattern :
:mod:`backend.plateforme.export_alertes` et
:mod:`backend.plateforme.export_journal_cabinet`.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Final

# Réutilisé TEL QUEL pour l'export .txt — AUCUNE duplication du rendu.
from backend.plateforme.brief_cabinet import (  # noqa: F401
    rendre_portefeuille_texte,
)

#: Libellés français des statuts — MÊME mapping que le frontend
#: (PortefeuilleDeclaratifVue.tsx, constante LIBELLES_STATUT) : ce qui
#: est lu dans l'export est ce qui est affiché à l'écran.
LIBELLES_STATUT: Final[dict[str, str]] = {
    "a_completer": "périodes à saisir",
    "a_jour": "à jour",
    "indisponible": "indisponible",
}

#: Colonnes du CSV — ordre stable, tri naturel sous Excel (client en
#: première colonne : la liste d'appel des relances se trie par client).
COLONNES_CSV: Final[tuple[str, ...]] = (
    "client", "exercice", "mission", "statut",
    "tva_saisies", "tva_attendues", "tva_manquantes",
    "salaires_saisies", "salaires_attendues", "salaires_manquantes",
)


def _libelle_statut(statut: object) -> str:
    """Libellé français du statut — le code brut si statut inconnu."""
    brut = str(statut or "")
    return LIBELLES_STATUT.get(brut, brut)


def _periodes_compactes(bloc: dict[str, Any] | None) -> str:
    """PUR — périodes manquantes « AAAA-MM, AAAA-MM » d'un bloc.

    Périodes ISO conservées telles quelles (tri chronologique naturel
    sous Excel), séparées par une virgule — cellule vide si aucune.
    """
    manquantes = list((bloc or {}).get("manquantes") or [])
    return ", ".join(str(p) for p in manquantes)


def rendre_portefeuille_csv(corps: dict[str, Any]) -> str:
    """PUR — portefeuille déclaratif en CSV point-virgule pour Excel FR.

    BOM UTF-8 en tête (encodage reconnu par Excel), délimiteur « ; »,
    échappement délégué au module :mod:`csv` de la stdlib — jamais de
    concaténation manuelle. Colonnes stables :data:`COLONNES_CSV`,
    toutes valeurs en ``str`` — une ligne par mission, dans l'ordre du
    corps (collecte à organiser d'abord, puis alphabétique client).
    Tolérant : un corps vide produit l'en-tête seule.
    """
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(COLONNES_CSV)
    for m in list(corps.get("missions") or []):
        tva = dict(m.get("tva") or {})
        salaires = dict(m.get("salaires") or {})
        mission = m.get("mission_id")
        exercice = m.get("exercice")
        ecrivain.writerow([
            str(m.get("client") or ""),
            "" if exercice is None else str(exercice),
            "" if mission is None else str(mission),
            _libelle_statut(m.get("statut")),
            str(int(tva.get("saisies") or 0)),
            str(int(tva.get("attendues") or 0)),
            _periodes_compactes(tva),
            str(int(salaires.get("saisies") or 0)),
            str(int(salaires.get("attendues") or 0)),
            _periodes_compactes(salaires),
        ])
    return "\ufeff" + tampon.getvalue()
