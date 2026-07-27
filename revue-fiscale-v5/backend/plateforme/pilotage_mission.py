"""Pilotage de mission — synthèse transverse pour le chef de mission.

POURQUOI : le chef de mission et l'associé disposent de vues détaillées
par module (programme de travail, contrôle de pré-clôture, temps passés,
rentabilité, visas, conclusions) mais aucune ne donne, en UN appel, la
lecture d'ensemble : où en est la mission, que reste-t-il à faire, la
mission est-elle rentable, la clôture est-elle envisageable ? Ce module
agrège les SYNTHÈSES des modules existants — il ne réimplémente aucune
logique métier, il appelle leurs fonctions — pour offrir cette lecture
de pilotage, complément des vues détaillées.

Module déterministe, lecture seule, aucun appel LLM, RLS stricte via
:func:`contexte_tenant`. ATTENTION : les fonctions agrégées ouvrent leur
propre ``with contexte_tenant(...)`` — elles sont donc appelées HORS de
tout bloc imbriqué (même pattern que ``evaluer_cloture`` appelant
``etat_programme``).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant


class ErreurPilotageMission(Exception):
    """Échec du pilotage de mission (mission hors tenant…) — 404."""


def _derniere_execution(
    session: Session, mission_id: int
) -> dict[str, Any] | None:
    """Conclusions par statut de la dernière exécution — None si aucune.

    Mêmes requêtes de base que :mod:`comparatif_executions` : dernière
    exécution par id décroissant, comptage sur ``conclusion``.
    """
    exec_id = session.execute(
        text(
            "SELECT id FROM execution WHERE mission_id = :m "
            "ORDER BY id DESC LIMIT 1"
        ),
        {"m": mission_id},
    ).scalar_one_or_none()
    if exec_id is None:
        return None
    rows = session.execute(
        text(
            "SELECT statut, count(*) AS nb FROM conclusion "
            "WHERE execution_id = :e GROUP BY statut ORDER BY statut"
        ),
        {"e": int(exec_id)},
    ).mappings().all()
    par_statut = {str(r["statut"]): int(r["nb"]) for r in rows}
    return {
        "execution_id": int(exec_id),
        "conclusions_par_statut": par_statut,
        "total_conclusions": sum(par_statut.values()),
    }


def pilotage_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """État de pilotage complet d'une mission — synthèses agrégées.

    Retourne ``{mission, programme, controle_cloture, temps, rentabilite,
    visas, derniere_execution}`` :

    - ``programme`` : synthèse {faites, total, avancement_pct} et
      avancement par phase (sans le détail des diligences) ;
    - ``controle_cloture`` : synthèse {ok, attention, bloquant} et
      ``cloture_recommandee`` (sans le détail des points) ;
    - ``temps`` : ``total_heures`` et ``par_phase`` ;
    - ``rentabilite`` : {honoraires, cout_estime, marge_estimee,
      taux_marge_pct} — ``None`` si aucun paramètre renseigné ;
    - ``visas`` : synthèse seulement ;
    - ``derniere_execution`` : conclusions par statut — ``None`` si
      aucune exécution.

    Mission hors périmètre du tenant → :class:`ErreurPilotageMission`
    « introuvable » (404 côté API).
    """
    # Identité de la mission + dernière exécution : nos propres requêtes,
    # sous notre propre contexte tenant (RLS).
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT m.id, m.exercice, m.statut, "
                "c.denomination AS contribuable "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurPilotageMission(f"mission {mission_id} introuvable")
        derniere_execution = _derniere_execution(session, mission_id)

    # Les fonctions agrégées gèrent leur PROPRE contexte_tenant — appels
    # hors de tout with imbriqué (cf. evaluer_cloture → etat_programme).
    from backend.plateforme.controle_cloture import evaluer_cloture
    from backend.plateforme.programme_travail import etat_programme
    from backend.plateforme.rentabilite_mission import rentabilite_mission
    from backend.plateforme.temps_mission import recap_temps
    from backend.plateforme.visas_mission import etat_visas

    programme = etat_programme(session, tenant_id, mission_id)
    cloture = evaluer_cloture(session, tenant_id, mission_id)
    temps = recap_temps(session, tenant_id, mission_id)
    rentabilite = rentabilite_mission(session, tenant_id, mission_id)
    visas = etat_visas(session, tenant_id, mission_id)

    # Paramètres non renseignés → bloc null (pas d'erreur) : on ne fait
    # pas croire à une marge sans base convenue.
    bloc_rentabilite: dict[str, Any] | None = None
    if (
        rentabilite["honoraires"] is not None
        or rentabilite["taux_horaire"] is not None
    ):
        bloc_rentabilite = {
            "honoraires": rentabilite["honoraires"],
            "cout_estime": rentabilite["cout_estime"],
            "marge_estimee": rentabilite["marge_estimee"],
            "taux_marge_pct": rentabilite["taux_marge_pct"],
        }

    return {
        "mission": {
            "id": int(mission["id"]),
            "exercice": int(mission["exercice"]),
            "statut": str(mission["statut"]),
            "contribuable": str(mission["contribuable"]),
        },
        "programme": {
            "synthese": programme["synthese"],
            "phases": [
                {
                    "phase": p["phase"],
                    "faites": p["faites"],
                    "total": p["total"],
                    "avancement_pct": p["avancement_pct"],
                }
                for p in programme["phases"]
            ],
        },
        "controle_cloture": {
            "synthese": cloture["synthese"],
            "cloture_recommandee": cloture["cloture_recommandee"],
        },
        "temps": {
            "total_heures": temps["total_heures"],
            "par_phase": temps["par_phase"],
        },
        "rentabilite": bloc_rentabilite,
        "visas": visas["synthese"],
        "derniere_execution": derniere_execution,
    }
