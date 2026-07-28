"""Suivi déclaratif du portefeuille — complétude consolidée du cabinet.

POURQUOI : la complétude déclarative existe MISSION PAR MISSION
(:mod:`backend.plateforme.completude_declarative` — périodes
mensuelles échues comparées aux déclarations saisies TVA et impôts
sur salaires), mais l'associé qui organise la COLLECTE veut la voir
d'un coup d'œil sur TOUT le portefeuille : pour chaque mission
ouverte, où en est la saisie, quelles périodes restent à saisir —
sans ouvrir chaque mission.

Assemblage DÉTERMINISTE et CONSULTATIF (aucun LLM, AUCUN email) : la
vue par mission est celle DÉJÀ construite par
:func:`backend.plateforme.completude_declarative.completude_declarative_mission`
— AUCUN recalcul métier ici, seules des fonctions PURES de résumé,
tri et synthèse s'ajoutent. Formulations factuelles, jamais
accusatoires : « périodes à saisir », pas de score ni de classement
stigmatisant des clients — le tri met simplement en tête les
missions où la collecte est à organiser.

TOLÉRANCE : une mission dont la vue échoue est restituée avec le
statut ``indisponible`` (clés stables) — jamais bloquant, pattern
:mod:`backend.plateforme.calendrier_cabinet`. Lecture seule sous RLS
via ``contexte_tenant`` — AUCUNE écriture, AUCUNE migration.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

#: Plafond de missions consolidées — vue de pilotage, pas un export.
PLAFOND_MISSIONS: Final[int] = 200

# Statuts par mission — vocabulaire fermé, factuel, non accusatoire.
STATUT_A_COMPLETER: Final = "a_completer"
STATUT_A_JOUR: Final = "a_jour"
STATUT_INDISPONIBLE: Final = "indisponible"

#: Note consultative — TOUJOURS présente dans la restitution.
NOTE_PORTEFEUILLE_DECLARATIF: Final = (
    "Suivi consultatif de la complétude déclarative du portefeuille : "
    "pour chaque mission ouverte, les périodes mensuelles échues de "
    "l'exercice sont comparées aux déclarations saisies dans l'outil "
    "(TVA et impôts sur salaires). Les périodes à saisir signalent où "
    "prioriser la collecte des pièces avec le client — la saisie dans "
    "l'outil ne prouve pas le dépôt effectif à la DGI, ni l'inverse : "
    "l'humain vérifie les quittances et décide."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def _resume_bloc(bloc: dict[str, Any] | None) -> dict[str, Any]:
    """PUR — résumé compact d'un bloc impôt de la vue mission.

    Reprend fidèlement les clés de
    :func:`backend.plateforme.completude_declarative.comparer` :
    ``nb_saisies`` / ``nb_attendues`` / ``manquantes`` — bloc absent
    ou illisible (``disponible=false``) → compteurs à zéro, clés
    stables, jamais bloquant.
    """
    bloc = bloc or {}
    disponible = bool(bloc.get("disponible"))
    if not disponible:
        return {
            "disponible": False,
            "saisies": 0,
            "attendues": 0,
            "manquantes": [],
        }
    return {
        "disponible": True,
        "saisies": int(bloc.get("nb_saisies") or 0),
        "attendues": int(bloc.get("nb_attendues") or 0),
        "manquantes": [str(p) for p in (bloc.get("manquantes") or [])],
    }


def resumer_mission(vue: dict[str, Any]) -> dict[str, Any]:
    """PUR — entrée portefeuille d'UNE mission, clés TOUJOURS stables.

    ``vue`` : ``{client, mission_id, exercice, completude}`` où
    ``completude`` est la vue déjà construite par
    :func:`backend.plateforme.completude_declarative.completude_declarative_mission`
    (``None`` si sa construction a échoué — tolérance par mission).

    Statut factuel : ``indisponible`` (vue absente ou aucun bloc
    lisible), ``a_jour`` (aucune période manquante sur les blocs
    lisibles — y compris exercice sans période échue) ou
    ``a_completer`` (des périodes restent à saisir).
    """
    mission = vue.get("mission_id")
    completude = vue.get("completude")
    completude = completude if isinstance(completude, dict) else None

    impots = (completude or {}).get("impots") or {}
    tva = _resume_bloc(impots.get("tva"))
    salaires = _resume_bloc(impots.get("salaires"))

    if completude is None or not bool(completude.get("disponible")):
        statut = STATUT_INDISPONIBLE
    elif tva["manquantes"] or salaires["manquantes"]:
        statut = STATUT_A_COMPLETER
    else:
        statut = STATUT_A_JOUR

    exercice = (completude or {}).get("exercice", vue.get("exercice"))
    try:
        exercice = int(exercice)
    except (TypeError, ValueError):
        exercice = None
    return {
        "client": str(vue.get("client") or ""),
        "mission_id": int(mission) if mission is not None else None,
        "exercice": exercice,
        "tva": tva,
        "salaires": salaires,
        "statut": statut,
    }


def trier_missions(
    entrees: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — les missions à compléter d'abord, puis alphabétique client.

    Le tri est un ordre de LECTURE (où concentrer la collecte), pas
    un classement des clients : au sein de chaque groupe, l'ordre est
    simplement alphabétique (puis mission pour la stabilité).
    """
    def _cle(e: dict[str, Any]) -> tuple:
        return (
            0 if e.get("statut") == STATUT_A_COMPLETER else 1,
            str(e.get("client") or "").casefold(),
            int(e.get("mission_id") or 0),
        )

    return sorted(entrees, key=_cle)


def synthese_portefeuille(
    entrees: list[dict[str, Any]],
) -> dict[str, int]:
    """PUR — compteurs du portefeuille (somme = ``nb_missions``)."""
    nb_a_jour = sum(
        1 for e in entrees if e.get("statut") == STATUT_A_JOUR
    )
    nb_a_completer = sum(
        1 for e in entrees if e.get("statut") == STATUT_A_COMPLETER
    )
    return {
        "nb_missions": len(entrees),
        "nb_a_jour": nb_a_jour,
        "nb_a_completer": nb_a_completer,
        "nb_indisponibles": len(entrees) - nb_a_jour - nb_a_completer,
    }


def assembler_portefeuille(
    vues: list[dict[str, Any]], aujourd_hui: date | None = None
) -> dict[str, Any]:
    """PUR — vue finale : résumé par mission, tri, synthèse, note.

    Se construit toujours (aucune mission → liste vide, compteurs à
    zéro, note présente) — clés stables.
    """
    jour = aujourd_hui or date.today()
    entrees = trier_missions([resumer_mission(v) for v in vues])
    return {
        "aujourd_hui": jour.isoformat(),
        "missions": entrees,
        "synthese": synthese_portefeuille(entrees),
        "note": NOTE_PORTEFEUILLE_DECLARATIF,
    }


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def portefeuille_declaratif_cabinet(
    session: Session, tenant_id: int
) -> dict[str, Any]:
    """Suivi déclaratif du portefeuille — LECTURE SEULE, RLS.

    Missions NON clôturées du tenant (plafond
    :data:`PLAFOND_MISSIONS`, ordre alphabétique client), chacune
    résumée depuis la vue EXISTANTE
    :func:`backend.plateforme.completude_declarative.completude_declarative_mission`
    — aucun recalcul. Tolérance par mission : une vue qui échoue
    devient une entrée ``indisponible``, jamais bloquante.
    """
    from backend.plateforme.completude_declarative import (
        completude_declarative_mission,
    )
    from backend.plateforme.missions import STATUT_CLOTUREE

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, "
                "c.denomination AS client "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut <> :cl "
                "ORDER BY c.denomination, m.id "
                "LIMIT :lim"
            ),
            {"cl": STATUT_CLOTUREE, "lim": PLAFOND_MISSIONS},
        ).mappings().all()

    vues: list[dict[str, Any]] = []
    for r in rows:
        # Tolérance par mission : un échec n'empêche jamais la vue
        # des autres missions — entrée « indisponible ».
        try:
            completude: dict[str, Any] | None = (
                completude_declarative_mission(
                    session, tenant_id, int(r["mission_id"])
                )
            )
        except Exception:  # noqa: BLE001 — mission annexe tolérée
            completude = None
        vues.append(
            {
                "client": str(r["client"] or ""),
                "mission_id": int(r["mission_id"]),
                "exercice": r["exercice"],
                "completude": completude,
            }
        )
    return assembler_portefeuille(vues)
