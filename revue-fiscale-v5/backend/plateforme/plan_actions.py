"""Plan d'actions post-revue — dérivation consultative depuis les risques.

À l'issue de la revue, le fiscaliste doit transformer les risques non
clos du client en actions concrètes. Ce module dérive, de façon
DÉTERMINISTE, une action suggérée par risque non clos (statuts
« ouvert » / « en_traitement ») du contribuable de la mission :

- ``declaration_rectificative`` : risque probable ET exposition chiffrée
  — l'anomalie est vraisemblable et son montant connu, une régularisation
  spontanée est à envisager ;
- ``provision_a_documenter`` : risque possible ET exposition chiffrée —
  documenter une provision pour risque fiscal dans les comptes ;
- ``justificatif_a_collecter`` : exposition non chiffrée (probable ou
  possible) — collecter les pièces permettant de chiffrer l'exposition ;
- ``point_a_discuter`` : probabilité faible — simple point d'attention à
  évoquer avec le client.

Priorité déterministe :

- ``haute`` : exposition ≥ ``SEUIL_EXPOSITION_HAUTE`` (5 000 000 FCFA) OU
  prescription de droit commun dans les 12 mois (réutilise
  :func:`backend.plateforme.prescription_risques.date_prescription`) ;
- ``moyenne`` : exposition chiffrée > 0 ou probabilité « probable » ;
- ``basse`` : le reste.

Analyse CONSULTATIVE : aucune écriture, aucun LLM — le plan est une
suggestion déterministe que le fiscaliste et le client restent seuls à
décider d'appliquer. Fonctions pures + lecture seule sous RLS.

Suivi du plan : le fiscaliste peut marquer chaque action « retenue »,
« écartée » ou « faite » (décision HUMAINE persistée dans la table
``suivi_plan_actions`` par-dessus le plan dérivé, sur clic explicite —
:func:`decider_action`). Le plan reste reconstruit à chaque lecture ;
seules les décisions sont stockées, avec ``cle_action`` stable
(``risque:{risque_id}``) comme identifiant de fusion.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.prescription_risques import (
    _dans_un_an,
    date_prescription,
)
from backend.plateforme.risques import STATUTS_NON_CLOS

# ── Constantes ───────────────────────────────────────────────────────

PRIORITE_HAUTE: Final[str] = "haute"
PRIORITE_MOYENNE: Final[str] = "moyenne"
PRIORITE_BASSE: Final[str] = "basse"
PRIORITES: Final[tuple[str, ...]] = (
    PRIORITE_HAUTE,
    PRIORITE_MOYENNE,
    PRIORITE_BASSE,
)

TYPE_DECLARATION_RECTIFICATIVE: Final[str] = "declaration_rectificative"
TYPE_PROVISION_A_DOCUMENTER: Final[str] = "provision_a_documenter"
TYPE_JUSTIFICATIF_A_COLLECTER: Final[str] = "justificatif_a_collecter"
TYPE_POINT_A_DISCUTER: Final[str] = "point_a_discuter"

_LIBELLES_TYPE: Final[dict[str, str]] = {
    TYPE_DECLARATION_RECTIFICATIVE: (
        "Préparer une déclaration rectificative (régularisation spontanée)"
    ),
    TYPE_PROVISION_A_DOCUMENTER: (
        "Documenter une provision pour risque fiscal dans les comptes"
    ),
    TYPE_JUSTIFICATIF_A_COLLECTER: (
        "Collecter les justificatifs pour chiffrer l'exposition"
    ),
    TYPE_POINT_A_DISCUTER: (
        "Point d'attention à discuter avec le client"
    ),
}

# Exposition (montant + pénalités) à partir de laquelle la priorité
# passe en « haute » quel que soit le reste.
SEUIL_EXPOSITION_HAUTE: Final[Decimal] = Decimal("5000000")

# Décisions humaines possibles sur une action du plan.
DECISION_RETENUE: Final[str] = "retenue"
DECISION_ECARTEE: Final[str] = "ecartee"
DECISION_FAITE: Final[str] = "faite"
DECISIONS: Final[tuple[str, ...]] = (
    DECISION_RETENUE,
    DECISION_ECARTEE,
    DECISION_FAITE,
)

# Préfixe de la clé stable d'une action dérivée d'un risque.
PREFIXE_CLE_RISQUE: Final[str] = "risque:"

MENTION_NOTE: Final[str] = (
    "Plan d'actions consultatif dérivé de façon déterministe des risques "
    "non clos du client — chaque action est une suggestion : le "
    "fiscaliste apprécie sa pertinence et le client décide de sa mise en "
    "œuvre. Aucune écriture n'est effectuée par cette analyse."
)


class ErreurPlanActions(Exception):
    """Échec de la dérivation du plan d'actions."""


class ErreurPlanActionsIntrouvable(ErreurPlanActions):
    """Mission ou action hors périmètre du tenant — 404 côté route."""


class ErreurPlanActionsDecisionInvalide(ErreurPlanActions):
    """Décision hors « retenue / ecartee / faite » — 422 côté route."""


class ErreurPlanActionsMissionCloturee(ErreurPlanActions):
    """Mission clôturée — écriture refusée (409 côté route)."""


# ── Fonctions pures ──────────────────────────────────────────────────


def _exposition(risque: dict[str, Any]) -> Decimal | None:
    """Exposition brute : montant_estime + penalites_estimees (Decimal).

    None si aucun des deux montants n'est renseigné.
    """
    montant = risque.get("montant_estime")
    penalites = risque.get("penalites_estimees")
    if (montant is None or montant == "") and (
        penalites is None or penalites == ""
    ):
        return None
    total = Decimal("0")
    if montant is not None and montant != "":
        total += Decimal(str(montant))
    if penalites is not None and penalites != "":
        total += Decimal(str(penalites))
    return total


def _type_action(probabilite: str, exposition: Decimal | None) -> str:
    """PUR — type d'action suggérée selon probabilité / exposition."""
    if probabilite == "faible":
        return TYPE_POINT_A_DISCUTER
    if exposition is None:
        return TYPE_JUSTIFICATIF_A_COLLECTER
    if probabilite == "probable":
        return TYPE_DECLARATION_RECTIFICATIVE
    return TYPE_PROVISION_A_DOCUMENTER


def deriver_action(
    risque: dict[str, Any], aujourd_hui: date
) -> dict[str, Any]:
    """PUR — action suggérée pour UN risque non clos.

    ``risque`` : {id, libelle, impot, exercice_origine, statut,
    probabilite, montant_estime, penalites_estimees}. Retourne un item
    du plan : type d'action, libellé, priorité et motifs traçables.
    """
    probabilite = str(risque.get("probabilite") or "possible").lower()
    exposition = _exposition(risque)
    limite = date_prescription(int(risque["exercice_origine"]))
    horizon = _dans_un_an(aujourd_hui)
    prescription_proche = limite <= horizon

    type_action = _type_action(probabilite, exposition)

    motifs: list[str] = []
    if exposition is not None and exposition >= SEUIL_EXPOSITION_HAUTE:
        motifs.append(
            "exposition chiffrée élevée "
            f"(≥ {SEUIL_EXPOSITION_HAUTE} FCFA)"
        )
    if prescription_proche:
        if limite < aujourd_hui:
            motifs.append(
                "prescription de droit commun dépassée "
                f"({limite.isoformat()}) — vérifier le statut du risque"
            )
        else:
            motifs.append(
                "prescription de droit commun dans les 12 mois "
                f"({limite.isoformat()})"
            )
    if motifs:
        priorite = PRIORITE_HAUTE
    elif (exposition is not None and exposition > 0) or (
        probabilite == "probable"
    ):
        priorite = PRIORITE_MOYENNE
        motifs.append(
            "exposition chiffrée"
            if exposition is not None and exposition > 0
            else "probabilité « probable »"
        )
    else:
        priorite = PRIORITE_BASSE
        motifs.append("exposition non chiffrée ou probabilité faible")

    return {
        "cle_action": f"{PREFIXE_CLE_RISQUE}{int(risque['id'])}",
        "risque_id": int(risque["id"]),
        "libelle_risque": str(risque.get("libelle") or ""),
        "impot": str(risque.get("impot") or "").upper(),
        "exercice_origine": int(risque["exercice_origine"]),
        "statut_risque": str(risque.get("statut") or "ouvert"),
        "probabilite": probabilite,
        "exposition": str(exposition) if exposition is not None else None,
        "date_prescription": limite.isoformat(),
        "type_action": type_action,
        "action": _LIBELLES_TYPE[type_action],
        "priorite": priorite,
        "motifs": motifs,
        # Décision humaine (fusionnée depuis suivi_plan_actions) — null
        # tant que le fiscaliste n'a pas tranché.
        "decision": None,
        "decision_note": None,
        "decision_maj_le": None,
    }


def deriver_plan(
    risques: list[dict[str, Any]], aujourd_hui: date
) -> list[dict[str, Any]]:
    """PUR — plan d'actions ordonné par priorité (haute → basse).

    Seuls les risques NON CLOS (« ouvert », « en_traitement ») donnent
    lieu à une action ; à priorité égale, l'ordre suit l'exercice
    d'origine croissant (le plus ancien d'abord — prescrit plus tôt)
    puis l'identifiant du risque.
    """
    items = [
        deriver_action(r, aujourd_hui)
        for r in risques
        if str(r.get("statut") or "ouvert").lower() in STATUTS_NON_CLOS
    ]
    rang = {p: i for i, p in enumerate(PRIORITES)}
    items.sort(
        key=lambda i: (
            rang[i["priorite"]],
            i["exercice_origine"],
            i["risque_id"],
        )
    )
    return items


def fusionner_decisions(
    plan: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """PUR — recopie la décision persistée sur chaque action du plan.

    ``decisions`` : {cle_action: {decision, note, maj_le}}. Une clé
    persistée absente du plan courant (risque clos depuis) est ignorée —
    le plan dérivé fait foi.
    """
    for item in plan:
        d = decisions.get(str(item.get("cle_action") or ""))
        if d is None:
            continue
        item["decision"] = str(d["decision"])
        item["decision_note"] = (d.get("note") or None) or None
        maj = d.get("maj_le")
        item["decision_maj_le"] = (
            maj.isoformat() if maj is not None else None
        )
    return plan


def synthese_decisions(plan: list[dict[str, Any]]) -> dict[str, int]:
    """PUR — compteurs {retenues, ecartees, faites, sans_decision}."""
    compte = {"retenues": 0, "ecartees": 0, "faites": 0, "sans_decision": 0}
    cle = {
        DECISION_RETENUE: "retenues",
        DECISION_ECARTEE: "ecartees",
        DECISION_FAITE: "faites",
    }
    for item in plan:
        compte[cle.get(str(item.get("decision")), "sans_decision")] += 1
    return compte


def synthese_plan(plan: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs par priorité + exposition totale (str Decimal)."""
    par_priorite = {p: 0 for p in PRIORITES}
    exposition = Decimal("0")
    for item in plan:
        par_priorite[item["priorite"]] += 1
        if item.get("exposition") is not None:
            exposition += Decimal(str(item["exposition"]))
    return {
        "total_actions": len(plan),
        "par_priorite": par_priorite,
        "exposition_totale": str(exposition),
        "decisions": synthese_decisions(plan),
    }


# ── Lecture par mission (RLS) ────────────────────────────────────────


def _decisions_enregistrees(
    session: Session, mission_id: int
) -> dict[str, dict[str, Any]]:
    """Décisions persistées de la mission — {cle_action: {decision, note,
    maj_le}}. Contexte tenant déjà posé par l'appelant."""
    rows = session.execute(
        text(
            "SELECT cle_action, decision, note, maj_le "
            "FROM suivi_plan_actions WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).mappings().all()
    return {str(r["cle_action"]): dict(r) for r in rows}


def analyse_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Plan d'actions post-revue de la mission (lecture seule, RLS).

    Risques non clos du contribuable de la mission → plan déterministe.
    Mission hors tenant → :class:`ErreurPlanActionsIntrouvable` (404
    côté route).
    """
    jour = aujourd_hui or date.today()
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text("SELECT id, contribuable_id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurPlanActionsIntrouvable(
                f"mission {mission_id} introuvable"
            )
        contribuable_id = int(mission["contribuable_id"])
        rows = session.execute(
            text(
                "SELECT id, libelle, impot, exercice_origine, statut, "
                "probabilite, montant_estime, penalites_estimees "
                "FROM risque WHERE contribuable_id = :c "
                "AND statut = ANY(:sts) "
                "ORDER BY exercice_origine ASC, id ASC"
            ),
            {"c": contribuable_id, "sts": list(STATUTS_NON_CLOS)},
        ).mappings().all()
        decisions = _decisions_enregistrees(session, mission_id)

    plan = fusionner_decisions(
        deriver_plan([dict(r) for r in rows], jour), decisions
    )
    return {
        "mission_id": mission_id,
        "contribuable_id": contribuable_id,
        "date_analyse": jour.isoformat(),
        "plan": plan,
        "synthese": synthese_plan(plan),
        "note": MENTION_NOTE,
    }


# ── Décision humaine sur une action (écriture explicite) ─────────────


def decider_action(
    session: Session,
    tenant_id: int,
    mission_id: int,
    cle_action: str,
    decision: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Persiste la DÉCISION du fiscaliste sur une action du plan (UPSERT).

    Déclenché par un clic explicite — le plan reste dérivé, seule la
    décision humaine est stockée. Décision hors ``retenue / ecartee /
    faite`` → :class:`ErreurPlanActionsDecisionInvalide` (422) ; mission
    hors tenant ou ``cle_action`` absente du plan dérivé courant →
    :class:`ErreurPlanActionsIntrouvable` (404) ; mission clôturée →
    :class:`ErreurPlanActionsMissionCloturee` (409).

    Retourne l'action fusionnée à jour (avec sa décision).
    """
    decision = str(decision or "").strip().lower()
    if decision not in DECISIONS:
        raise ErreurPlanActionsDecisionInvalide(
            f"décision invalide « {decision} » — attendues : "
            + ", ".join(DECISIONS)
        )
    cle_action = str(cle_action or "").strip()
    jour = date.today()
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text(
                "SELECT statut, contribuable_id FROM mission WHERE id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if mission is None:
            raise ErreurPlanActionsIntrouvable(
                f"mission {mission_id} introuvable"
            )
        if str(mission["statut"] or "").lower() == "cloturee":
            raise ErreurPlanActionsMissionCloturee(
                f"mission {mission_id} clôturée — réouvrez-la avant de "
                "décider du plan d'actions"
            )
        rows = session.execute(
            text(
                "SELECT id, libelle, impot, exercice_origine, statut, "
                "probabilite, montant_estime, penalites_estimees "
                "FROM risque WHERE contribuable_id = :c "
                "AND statut = ANY(:sts) "
                "ORDER BY exercice_origine ASC, id ASC"
            ),
            {
                "c": int(mission["contribuable_id"]),
                "sts": list(STATUTS_NON_CLOS),
            },
        ).mappings().all()
        plan = deriver_plan([dict(r) for r in rows], jour)
        par_cle = {i["cle_action"]: i for i in plan}
        if cle_action not in par_cle:
            raise ErreurPlanActionsIntrouvable(
                f"action « {cle_action} » inconnue du plan de la "
                f"mission {mission_id}"
            )
        row = session.execute(
            text(
                "INSERT INTO suivi_plan_actions "
                "(tenant_id, mission_id, cle_action, decision, note) "
                "VALUES (:t, :m, :c, :d, :n) "
                "ON CONFLICT (tenant_id, mission_id, cle_action) "
                "DO UPDATE SET decision = EXCLUDED.decision, "
                "note = EXCLUDED.note, maj_le = now() "
                "RETURNING cle_action, decision, note, maj_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": cle_action,
                "d": decision,
                "n": (note or "").strip() or None,
            },
        ).mappings().one()
    # Pas de commit ici : get_session committe en fin de requête.
    return fusionner_decisions(
        [par_cle[cle_action]], {cle_action: dict(row)}
    )[0]
