"""Bilan de pré-clôture de mission — consultatif, déterministe.

POURQUOI : avant de clôturer, le fiscaliste veut voir D'UN COUP D'ŒIL ce
qui reste en suspens sur la mission — sans réinstruire chaque module.
Ce bilan agrège des signaux DÉJÀ définis ailleurs (visas de supervision,
temps saisis, circularisation de la demande de renseignements, note de
synthèse, data room, risques ouverts, décisions du plan d'actions) et
les restitue en points « ok »
ou « attention ». Il ne réimplémente aucune règle métier : il réutilise
les définitions exactes des modules existants (mêmes requêtes, mêmes
fonctions de synthèse).

LIMITE ASSUMÉE : bilan strictement CONSULTATIF — aucun statut
« bloquant », aucune écriture, aucun LLM. La clôture reste possible
telle quelle : l'humain décide (le contrôle qualité détaillé existe par
ailleurs dans :mod:`backend.plateforme.controle_cloture`). Fonctions
pures + lecture seule sous RLS via ``contexte_tenant``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.risques import STATUTS_NON_CLOS
from backend.plateforme.visas_mission import ORDRE_ROLES, PHASES_VISA

STATUT_OK: Final[str] = "ok"
STATUT_ATTENTION: Final[str] = "attention"

MENTION_NOTE: Final[str] = (
    "Bilan consultatif — la clôture reste à l'appréciation du fiscaliste."
)


class ErreurBilanCloture(Exception):
    """Échec du bilan de pré-clôture."""


class ErreurBilanIntrouvable(ErreurBilanCloture):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonction pure ────────────────────────────────────────────────────


def _point(code: str, libelle: str, attention: bool) -> dict[str, str]:
    return {
        "code": code,
        "libelle": libelle,
        "statut": STATUT_ATTENTION if attention else STATUT_OK,
    }


def construire_bilan(signaux: dict[str, Any]) -> dict[str, Any]:
    """PUR — points du bilan depuis les signaux collectés.

    ``signaux`` attendu (toutes clés issues des modules existants) :

    - ``phases_visees`` / ``total_phases`` : phases portant au moins un
      visa (registre ``visa_mission``) sur les 4 phases ;
    - ``restitution_visee`` : phase restitution visée aux trois rangs
      (même définition que la supervision cabinet) ;
    - ``total_heures`` : str Decimal de ``recap_temps`` ;
    - ``items_en_attente`` / ``items_a_relancer`` : compteurs de
      ``suivi_renseignements.synthese`` ;
    - ``note_synthese_disponible`` : au moins une version « disponible » ;
    - ``nb_pieces`` : pièces de la data room (``piece_mission``) ;
    - ``risques_ouverts`` : risques du contribuable au statut non clos
      (:data:`backend.plateforme.risques.STATUTS_NON_CLOS`) ;
    - ``plan_actions_disponible`` / ``plan_total_actions`` /
      ``plan_sans_decision`` : synthèse des décisions du plan d'actions
      (:func:`backend.plateforme.plan_actions.analyse_mission`) — signal
      OPTIONNEL : absent (analyse indisponible), le point « Plan
      d'actions » n'apparaît pas (échec silencieux, jamais bloquant) ;
    - ``comparaison_disponible`` / ``comparaison_tendance`` /
      ``comparaison_delta_exposition`` : évolution N vs N-1 du
      contribuable (:func:`backend.plateforme.comparaison_exercices.
      comparaison_contribuable`) — signal OPTIONNEL : absent ou
      indisponible (un seul exercice revu), le point « Évolution
      N/N-1 » n'apparaît pas (échec silencieux, jamais bloquant).

    Retourne ``{points, synthese, note}`` — ``synthese.pret`` est vrai
    quand AUCUN point n'est en attention (simple lecture d'ensemble,
    jamais bloquante).
    """
    phases_visees = int(signaux.get("phases_visees") or 0)
    total_phases = int(signaux.get("total_phases") or len(PHASES_VISA))
    restitution_visee = bool(signaux.get("restitution_visee"))
    heures = Decimal(str(signaux.get("total_heures") or "0"))
    en_attente = int(signaux.get("items_en_attente") or 0)
    a_relancer = int(signaux.get("items_a_relancer") or 0)
    note_dispo = bool(signaux.get("note_synthese_disponible"))
    nb_pieces = int(signaux.get("nb_pieces") or 0)
    risques_ouverts = int(signaux.get("risques_ouverts") or 0)

    points = [
        _point(
            "visas_poses",
            f"Visas posés {phases_visees}/{total_phases} phases"
            if phases_visees
            else f"Aucun visa posé (0/{total_phases} phases)",
            phases_visees == 0,
        ),
        _point(
            "restitution_visee",
            "Restitution visée aux trois rangs"
            if restitution_visee
            else "Restitution non visée aux trois rangs",
            not restitution_visee,
        ),
        _point(
            "temps_saisis",
            f"{signaux.get('total_heures')} h saisies"
            if heures > 0
            else "Aucun temps saisi",
            heures == 0,
        ),
        _point(
            "demande_renseignements",
            "Aucun item de demande de renseignements en attente"
            if en_attente == 0
            else (
                f"{en_attente} item(s) de demande en attente"
                + (f", dont {a_relancer} à relancer" if a_relancer else "")
            ),
            en_attente > 0,
        ),
        _point(
            "note_synthese",
            "Note de synthèse disponible"
            if note_dispo
            else "Note de synthèse absente",
            not note_dispo,
        ),
        _point(
            "data_room",
            f"{nb_pieces} pièce(s) en data room"
            if nb_pieces
            else "Aucune pièce en data room",
            nb_pieces == 0,
        ),
        _point(
            "risques_ouverts",
            "Aucun risque ouvert"
            if risques_ouverts == 0
            else f"{risques_ouverts} risque(s) ouvert(s)",
            risques_ouverts > 0,
        ),
    ]
    # Point « Plan d'actions » — seulement si le signal est disponible
    # (analyse plan_actions réussie) : échec silencieux → point absent.
    if bool(signaux.get("plan_actions_disponible")):
        plan_total = int(signaux.get("plan_total_actions") or 0)
        plan_sans_decision = int(signaux.get("plan_sans_decision") or 0)
        if plan_total == 0:
            libelle = "Plan d'actions vide — aucune action à décider"
        elif plan_sans_decision == 0:
            libelle = (
                f"Plan d'actions : {plan_total} action(s), toutes décidées"
            )
        else:
            libelle = (
                f"Plan d'actions : {plan_sans_decision} action(s) "
                "sans décision"
            )
        points.append(
            _point("plan_actions", libelle, plan_sans_decision > 0)
        )
    # Point « Évolution N/N-1 » — seulement si la comparaison
    # inter-exercices du contribuable est disponible (deux exercices
    # revus) : échec silencieux → point absent, jamais bloquant.
    if bool(signaux.get("comparaison_disponible")):
        tendance = str(signaux.get("comparaison_tendance") or "")
        delta = Decimal(
            str(signaux.get("comparaison_delta_exposition") or "0")
        )
        degradation = tendance == "degradation"
        if degradation and delta > 0:
            libelle = (
                "Exposition en hausse vs exercice précédent "
                f"(+{delta} FCFA)"
            )
        elif degradation:
            # Dégradation par le nombre de risques (exposition non en
            # hausse) — même attention, sans montant trompeur.
            libelle = "Risques ouverts en hausse vs exercice précédent"
        else:
            libelle = "Exposition stable ou en baisse vs exercice précédent"
        points.append(_point("evolution_exercices", libelle, degradation))
    points_ok = sum(1 for p in points if p["statut"] == STATUT_OK)
    points_attention = len(points) - points_ok
    return {
        "points": points,
        "synthese": {
            "points_ok": points_ok,
            "points_attention": points_attention,
            "pret": points_attention == 0,
        },
        "note": MENTION_NOTE,
    }


# ── Collecte des signaux (RLS) ───────────────────────────────────────


def bilan_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Bilan de pré-clôture de la mission — lecture seule, RLS.

    Collecte les signaux via les définitions EXACTES des modules
    existants puis délègue à :func:`construire_bilan`. Mission hors
    tenant → :class:`ErreurBilanIntrouvable` (404 côté route). Mission
    déjà clôturée : le bilan est renvoyé quand même (``statut_mission``
    l'indique) — consultatif, jamais bloquant.
    """
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT id, contribuable_id, statut FROM mission "
                "WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurBilanIntrouvable(f"mission {mission_id} introuvable")
        contribuable_id = int(mission["contribuable_id"])

        # Note de synthèse — même définition que controle_cloture.
        nb_notes = int(
            session.execute(
                text(
                    "SELECT count(*) FROM note_synthese_mission "
                    "WHERE mission_id = :m AND statut = 'disponible'"
                ),
                {"m": mission_id},
            ).scalar_one()
        )
        # Pièces de la data room — même table que civisme_fiscal.
        nb_pieces = int(
            session.execute(
                text(
                    "SELECT count(*) FROM piece_mission "
                    "WHERE mission_id = :m"
                ),
                {"m": mission_id},
            ).scalar_one()
        )
        # Risques ouverts — STATUTS_NON_CLOS de risques.py, périmètre
        # contribuable (même définition que le contrôle de pré-clôture).
        risques_ouverts = int(
            session.execute(
                text(
                    "SELECT count(*) FROM risque "
                    "WHERE contribuable_id = :c AND statut = ANY(:st)"
                ),
                {"c": contribuable_id, "st": sorted(STATUTS_NON_CLOS)},
            ).scalar_one()
        )

    # Les fonctions suivantes ouvrent leur PROPRE contexte_tenant :
    # appels HORS de tout with (cf. pilotage_mission).
    from backend.plateforme.suivi_renseignements import synthese
    from backend.plateforme.temps_mission import recap_temps
    from backend.plateforme.visas_mission import etat_visas

    visas = etat_visas(session, tenant_id, mission_id)
    temps = recap_temps(session, tenant_id, mission_id)
    circularisation = synthese(session, tenant_id, mission_id)

    # Plan d'actions — décisions retenue / écartée / faite (analyse
    # consultative). Échec silencieux : le point est simplement absent.
    plan_signaux: dict[str, Any] = {}
    try:
        from backend.plateforme.plan_actions import (
            ErreurPlanActions,
            analyse_mission as analyse_plan_mission,
        )

        plan_act = analyse_plan_mission(session, tenant_id, mission_id)
        decisions = plan_act["synthese"]["decisions"]
        plan_signaux = {
            "plan_actions_disponible": True,
            "plan_total_actions": int(
                plan_act["synthese"]["total_actions"]
            ),
            "plan_sans_decision": int(decisions["sans_decision"]),
        }
    except ErreurPlanActions:
        plan_signaux = {}

    # Évolution N vs N-1 du contribuable — comparaison inter-exercices
    # (ouvre son propre contexte_tenant : appel HORS de tout with).
    # Échec ou comparaison indisponible : le point est simplement absent.
    comparaison_signaux: dict[str, Any] = {}
    try:
        from backend.plateforme.comparaison_exercices import (
            ErreurComparaisonExercices,
            comparaison_contribuable,
        )

        comparaison = comparaison_contribuable(
            session, tenant_id, contribuable_id
        )
        if bool(comparaison.get("disponible")):
            comparaison_signaux = {
                "comparaison_disponible": True,
                "comparaison_tendance": str(
                    comparaison["synthese"]["tendance"]
                ),
                "comparaison_delta_exposition": str(
                    comparaison["synthese"]["delta_exposition"]
                ),
            }
    except ErreurComparaisonExercices:
        comparaison_signaux = {}

    restitution = next(
        (p for p in visas["phases"] if p["phase"] == "restitution"), None
    )
    restitution_visee = (
        restitution is not None
        and len(restitution["visas"]) == len(ORDRE_ROLES)
    )
    signaux = {
        "phases_visees": sum(
            1 for p in visas["phases"] if len(p["visas"]) > 0
        ),
        "total_phases": len(PHASES_VISA),
        "restitution_visee": restitution_visee,
        "total_heures": temps["total_heures"],
        "items_en_attente": int(circularisation["en_attente"]),
        "items_a_relancer": int(circularisation["a_relancer"]),
        "note_synthese_disponible": nb_notes > 0,
        "nb_pieces": nb_pieces,
        "risques_ouverts": risques_ouverts,
        **plan_signaux,
        **comparaison_signaux,
    }
    bilan = construire_bilan(signaux)
    return {
        "mission_id": int(mission["id"]),
        "statut_mission": str(mission["statut"]),
        **bilan,
    }
