"""Supervision transverse du portefeuille de missions (vue associé).

POURQUOI : le pilotage existant remonte des volets thématiques
(exposition, inactivité, sources, relances) mais l'associé n'a pas de
vue « où en est-on ? » mission par mission. Ce module agrège, pour
chaque mission active du tenant (statut != 'cloturee'), les trois
signaux de supervision disponibles : les temps saisis
(``temps_mission``), les visas hiérarchiques (``visa_mission``) et le
suivi de circularisation (``suivi_demande_renseignements``). Chaque
mission porte des alertes courtes, lisibles d'un coup d'œil.

Module déterministe, aucun appel LLM, RLS stricte via
:func:`contexte_tenant` — trois requêtes agrégées (GROUP BY), jamais de
N+1 par mission. Le calcul des alertes est une fonction pure
(:func:`alertes_mission`) testable sans base.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.missions import STATUT_CADRAGE, STATUT_CLOTUREE
from backend.plateforme.visas_mission import ORDRE_ROLES, PHASES_VISA

# Phase dont le visa complet conditionne la restitution au client.
PHASE_RESTITUTION: Final = "restitution"


def _fmt(d: Decimal) -> str:
    """Décimal → texte stable, sans notation scientifique ni zéros finaux."""
    return format(d.normalize(), "f")


def alertes_mission(
    statut: str,
    heures_totales: Decimal | str,
    total_visas: int,
    visas_restitution_complets: bool,
    items_a_relancer: int,
) -> list[str]:
    """PUR — alertes courtes de supervision d'une mission active.

    Règles métier (ordre stable) :
    - « aucun visa posé » : aucune phase n'est attestée — la supervision
      hiérarchique n'a pas commencé ;
    - « restitution non visée » : mission sortie du cadrage mais la
      phase restitution n'est pas visée aux trois rangs — on ne restitue
      pas au client sans signature complète ;
    - « N item(s) à relancer » : relances de circularisation échues ;
    - « aucun temps saisi » : rentabilité non pilotable sans temps.
    """
    alertes: list[str] = []
    if total_visas == 0:
        alertes.append("aucun visa posé")
    if statut != STATUT_CADRAGE and not visas_restitution_complets:
        alertes.append("restitution non visée")
    if items_a_relancer > 0:
        alertes.append(f"{items_a_relancer} item(s) à relancer")
    if Decimal(str(heures_totales)) == 0:
        alertes.append("aucun temps saisi")
    return alertes


def _heures_par_mission(session: Session) -> dict[int, Decimal]:
    rows = session.execute(
        text(
            "SELECT mission_id, SUM(heures) AS heures "
            "FROM temps_mission GROUP BY mission_id"
        )
    ).mappings().all()
    return {int(r["mission_id"]): Decimal(str(r["heures"])) for r in rows}


def _visas_par_mission(
    session: Session,
) -> dict[int, dict[str, Any]]:
    """{mission_id: {total, phases_completes, restitution_complete}}."""
    rows = session.execute(
        text(
            "SELECT mission_id, phase, COUNT(*) AS n "
            "FROM visa_mission GROUP BY mission_id, phase"
        )
    ).mappings().all()
    etat: dict[int, dict[str, Any]] = {}
    complet = len(ORDRE_ROLES)
    for r in rows:
        mid = int(r["mission_id"])
        phase = str(r["phase"])
        n = int(r["n"])
        e = etat.setdefault(
            mid,
            {"total": 0, "phases_completes": 0,
             "restitution_complete": False},
        )
        e["total"] += n
        if phase in PHASES_VISA and n >= complet:
            e["phases_completes"] += 1
            if phase == PHASE_RESTITUTION:
                e["restitution_complete"] = True
    return etat


def _circularisation_par_mission(
    session: Session,
) -> dict[int, dict[str, int]]:
    """{mission_id: {en_attente, a_relancer}} — relance échue incluse."""
    rows = session.execute(
        text(
            "SELECT mission_id, "
            "COUNT(*) FILTER (WHERE statut = 'en_attente') AS en_attente, "
            "COUNT(*) FILTER (WHERE statut = 'en_attente' "
            "  AND date_relance IS NOT NULL "
            "  AND date_relance <= CURRENT_DATE) AS a_relancer "
            "FROM suivi_demande_renseignements GROUP BY mission_id"
        )
    ).mappings().all()
    return {
        int(r["mission_id"]): {
            "en_attente": int(r["en_attente"]),
            "a_relancer": int(r["a_relancer"]),
        }
        for r in rows
    }


def construire_supervision(
    session: Session, tenant_id: int
) -> dict[str, Any]:
    """Supervision transverse du portefeuille — lecture seule sous RLS.

    Pour chaque mission active du tenant (statut != 'cloturee') :
    temps cumulés, avancement des visas (phases complètes sur 4,
    restitution visée ou non), items de circularisation en attente / à
    relancer, et alertes courtes (:func:`alertes_mission`). La synthèse
    donne à l'associé les compteurs cabinet : missions actives, missions
    sans aucun visa, restitutions non visées hors cadrage, heures
    totales, items à relancer.
    """
    with contexte_tenant(session, tenant_id):
        missions_rows = session.execute(
            text(
                "SELECT m.id AS mission_id, c.denomination, m.exercice, "
                "m.statut "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut <> :clos "
                "ORDER BY c.denomination, m.exercice DESC, m.id"
            ),
            {"clos": STATUT_CLOTUREE},
        ).mappings().all()
        heures = _heures_par_mission(session)
        visas = _visas_par_mission(session)
        circu = _circularisation_par_mission(session)

    missions: list[dict[str, Any]] = []
    total_heures = Decimal("0")
    sans_visa = 0
    restitution_non_visee = 0
    total_a_relancer = 0
    for r in missions_rows:
        mid = int(r["mission_id"])
        statut = str(r["statut"])
        h = heures.get(mid, Decimal("0"))
        v = visas.get(
            mid,
            {"total": 0, "phases_completes": 0,
             "restitution_complete": False},
        )
        c = circu.get(mid, {"en_attente": 0, "a_relancer": 0})
        alertes = alertes_mission(
            statut=statut,
            heures_totales=h,
            total_visas=int(v["total"]),
            visas_restitution_complets=bool(v["restitution_complete"]),
            items_a_relancer=int(c["a_relancer"]),
        )
        total_heures += h
        sans_visa += 1 if int(v["total"]) == 0 else 0
        restitution_non_visee += (
            1 if "restitution non visée" in alertes else 0
        )
        total_a_relancer += int(c["a_relancer"])
        missions.append(
            {
                "mission_id": mid,
                "contribuable": str(r["denomination"]),
                "exercice": int(r["exercice"]),
                "statut": statut,
                "heures_totales": _fmt(h),
                "phases_completes": int(v["phases_completes"]),
                "visas_restitution_complets": bool(
                    v["restitution_complete"]
                ),
                "items_en_attente": int(c["en_attente"]),
                "items_a_relancer": int(c["a_relancer"]),
                "alertes": alertes,
            }
        )
    return {
        "missions": missions,
        "synthese": {
            "missions_actives": len(missions),
            "sans_aucun_visa": sans_visa,
            "restitution_non_visee": restitution_non_visee,
            "heures_totales": _fmt(total_heures),
            "items_a_relancer": total_a_relancer,
        },
    }
