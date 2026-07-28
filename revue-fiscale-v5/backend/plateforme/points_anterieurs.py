"""Points en suspens des missions antérieures du même contribuable.

POURQUOI : au démarrage (ou à la reprise) d'une mission — typiquement
après une reconduction (:mod:`backend.plateforme.reconduction_mission`)
— le fiscaliste doit voir les points convenus encore « a_faire » nés
des AUTRES missions du même contribuable, sur des exercices
STRICTEMENT antérieurs : rien ne doit se perdre d'une année sur
l'autre.

DOCTRINE : déterministe et STRICTEMENT CONSULTATIF — vue en lecture
seule, AUCUNE écriture : le traitement d'un point (fait / abandonné)
se saisit dans sa mission d'origine
(:mod:`backend.plateforme.points_convenus`). Aucun LLM. Fonctions
pures testables sans base + lecture RLS via ``contexte_tenant`` (même
pattern que :mod:`backend.plateforme.historique_client`).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.points_convenus import STATUT_A_FAIRE, point_en_retard

# Plafond d'affichage : au-delà, la vue perdrait sa lisibilité — les
# points les plus ANCIENS (exercice le plus bas) restent prioritaires.
PLAFOND_POINTS: Final[int] = 50

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_POINTS_ANTERIEURS: Final = (
    "Points encore à faire hérités des missions des exercices "
    "antérieurs de ce contribuable — rappel strictement consultatif : "
    "le traitement (fait ou abandonné) se saisit dans la mission "
    "d'origine du point, l'humain décide."
)


class ErreurPointsAnterieurs(Exception):
    """Échec de la vue des points antérieurs."""


class ErreurPointsAnterieursIntrouvable(ErreurPointsAnterieurs):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def trier_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — tri par exercice CROISSANT puis identifiant de point.

    Les points les plus anciens d'abord : ce sont eux qui risquent le
    plus de se perdre d'une année sur l'autre.
    """
    return sorted(
        points,
        key=lambda p: (int(p["exercice"]), int(p["point_id"])),
    )


def plafonner_points(
    points: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """PUR — au plus :data:`PLAFOND_POINTS` points (déjà triés).

    Le tri croissant garantit que les points les plus anciens sont
    conservés en priorité.
    """
    return points[:PLAFOND_POINTS]


def marquer_en_retard(
    points: list[dict[str, Any]], aujourd_hui: date
) -> list[dict[str, Any]]:
    """PUR — pose « en_retard » sur chaque point (copies).

    Réutilise :func:`backend.plateforme.points_convenus.point_en_retard`
    — tous les points ici sont « a_faire » par construction.
    """
    marques = []
    for p in points:
        copie = dict(p)
        copie["en_retard"] = point_en_retard(
            STATUT_A_FAIRE, p.get("date_cible"), aujourd_hui
        )
        marques.append(copie)
    return marques


def synthese_anterieurs(
    points: list[dict[str, Any]]
) -> dict[str, int]:
    """PUR — synthèse ``{total, en_retard, missions}``.

    ``missions`` : nombre de missions d'origine DISTINCTES concernées.
    """
    return {
        "total": len(points),
        "en_retard": sum(1 for p in points if p.get("en_retard")),
        "missions": len({int(p["mission_id"]) for p in points}),
    }


# ── Lecture par mission (RLS) ────────────────────────────────────────


def points_anterieurs(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Points « a_faire » des missions antérieures — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurPointsAnterieursIntrouvable`
    (404 côté route). Retrouve le contribuable de la mission puis les
    points convenus encore « a_faire » des missions du MÊME
    contribuable dont l'exercice est STRICTEMENT inférieur à celui de
    la mission courante — tous statuts de mission confondus (une
    mission clôturée porte encore des points à suivre). Tri exercice
    croissant puis id, plafond :data:`PLAFOND_POINTS`, marquage
    « en_retard ». AUCUNE écriture.
    """
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT id, exercice, contribuable_id FROM mission "
                "WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurPointsAnterieursIntrouvable(
                f"mission {mission_id} introuvable"
            )
        rows = session.execute(
            text(
                "SELECT pc.id AS point_id, pc.mission_id, m.exercice, "
                "pc.libelle, pc.date_cible "
                "FROM point_convenu pc "
                "JOIN mission m ON m.id = pc.mission_id "
                "WHERE m.contribuable_id = :c "
                "AND m.exercice < :ex "
                "AND pc.statut = :statut "
                "ORDER BY m.exercice, pc.id"
            ),
            {
                "c": int(mission["contribuable_id"]),
                "ex": int(mission["exercice"]),
                "statut": STATUT_A_FAIRE,
            },
        ).mappings().all()

    bruts = []
    for r in rows:
        cible = r["date_cible"]
        bruts.append(
            {
                "point_id": int(r["point_id"]),
                "mission_id": int(r["mission_id"]),
                "exercice": int(r["exercice"]),
                "libelle": str(r["libelle"] or ""),
                "date_cible": (
                    cible.isoformat()
                    if isinstance(cible, date)
                    and not isinstance(cible, datetime)
                    else None
                ),
            }
        )
    points = marquer_en_retard(
        plafonner_points(trier_points(bruts)), date.today()
    )
    return {
        "mission_id": int(mission["id"]),
        "exercice": int(mission["exercice"]),
        "points": points,
        "synthese": synthese_anterieurs(points),
        "note": NOTE_POINTS_ANTERIEURS,
    }
