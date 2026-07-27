"""Relances à faire du cabinet — items du suivi de circularisation échus.

Vue TRANSVERSE pour le fiscaliste : sur toutes les missions non
clôturées du tenant, les items du suivi de la demande de renseignements
(table ``suivi_demande_renseignements``) encore « à relancer » — même
définition que le pilotage (:mod:`backend.plateforme.pilotage`) et que
les compteurs abonné (``compteurs_suivi_renseignements``) : statut
``en_attente`` AND ``date_relance`` non nulle AND ``date_relance`` échue
(inférieure ou égale au jour de référence). La liste de travail du
cabinet pour piloter les relances quotidiennes, tous clients confondus.

Analyse CONSULTATIVE : un item « à relancer » signale seulement qu'une
relance était planifiée à une date désormais échue — le fiscaliste
décide de la suite (relancer, marquer reçu ou sans objet). Aucun LLM :
lecture seule sous RLS.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

# Plafond d'items retournés — liste opérationnelle, pas un export.
PLAFOND_ITEMS: Final[int] = 50

MENTION_NOTE: Final[str] = (
    "Liste consultative — items du suivi de la demande de "
    "renseignements dont la relance planifiée est échue, sur les "
    "missions non clôturées. Le fiscaliste décide de la suite "
    "(relancer le client, marquer reçu ou sans objet)."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def trier_relances(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — tri par date de relance croissante puis client, mission.

    La plus ancienne relance échue en tête (la plus urgente) ; à date
    égale, ordre alphabétique des clients puis mission — stable et
    lisible.
    """
    return sorted(
        items,
        key=lambda i: (
            str(i["date_relance"]),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
        ),
    )


def synthese_relances(items: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs : total, clients distincts, plus ancienne date."""
    clients = {str(i.get("client") or "") for i in items}
    plus_ancienne = min(
        (str(i["date_relance"]) for i in items), default=None
    )
    return {
        "total": len(items),
        "clients": len(clients),
        "plus_ancienne": plus_ancienne,
    }


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def relances_cabinet(
    session: Session,
    tenant_id: int,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Relances à faire du cabinet (lecture seule, RLS stricte).

    Items ``en_attente`` avec ``date_relance`` échue au jour de
    référence, sur les missions non clôturées du tenant, avec mission et
    client (JOIN). Tri par date de relance croissante puis client ;
    liste plafonnée à :data:`PLAFOND_ITEMS` (``total`` reste le compte
    complet). Se construit toujours (tenant sans relance → liste vide,
    sans erreur).
    """
    jour = aujourd_hui or date.today()

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT s.mission_id, s.libelle, s.date_relance, "
                "s.note, m.exercice, c.denomination "
                "FROM suivi_demande_renseignements s "
                "JOIN mission m ON m.id = s.mission_id "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE s.statut = 'en_attente' "
                "AND s.date_relance IS NOT NULL "
                "AND s.date_relance <= :jour "
                "AND COALESCE(m.statut, 'cadrage') <> 'cloturee' "
                "ORDER BY s.date_relance, c.denomination, s.mission_id, s.id"
            ),
            {"jour": jour},
        ).mappings().all()

    items = trier_relances(
        [
            {
                "mission_id": int(r["mission_id"]),
                "client": str(r["denomination"] or ""),
                "exercice": int(r["exercice"]),
                "libelle": str(r["libelle"] or ""),
                "date_relance": r["date_relance"].isoformat(),
                "note": str(r["note"] or "") or None,
            }
            for r in rows
        ]
    )
    return {
        "aujourd_hui": jour.isoformat(),
        "total": len(items),
        "synthese": synthese_relances(items),
        "items": items[:PLAFOND_ITEMS],
        "note": MENTION_NOTE,
    }
