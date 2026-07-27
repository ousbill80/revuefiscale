"""Ordre du jour de la réunion de restitution — texte brut déterministe.

En fin de mission, le fiscaliste anime une réunion de restitution avec
le client. Ce module prépare l'« Ordre du jour » de cette réunion en
AGRÉGEANT des analyses DÉJÀ définies ailleurs — il ne réimplémente
aucune règle métier :

- risques de la mission (table ``risque`` via ``origine_mission_id``,
  exposition = montant + pénalités comme
  :func:`backend.plateforme.plan_actions._exposition`) ;
- plan d'actions et décisions humaines
  (:func:`backend.plateforme.plan_actions.analyse_mission` — décisions
  ``retenue`` / ``ecartee`` / ``faite`` de ``suivi_plan_actions``) ;
- civisme déclaratif
  (:func:`backend.plateforme.civisme_fiscal.analyse_mission`) ;
- échéancier fiscal théorique
  (:func:`backend.plateforme.echeancier_fiscal.echeancier_mission`).

Document CONSULTATIF : assemblage entièrement déterministe (aucun LLM),
document de travail interne préparatoire — chaque section chiffrée
seulement si les données existent, sinon mention « à compléter en
séance ». Fonctions pures + lecture seule sous RLS.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.plan_actions import _exposition

#: Nombre de risques mis en avant dans la synthèse (top exposition).
NB_TOP_RISQUES: Final[int] = 5

#: Nombre d'échéances fiscales à venir rappelées en réunion.
NB_ECHEANCES_A_VENIR: Final[int] = 3

#: Mention utilisée quand une section n'a pas de données chiffrées.
A_COMPLETER_EN_SEANCE: Final[str] = "À compléter en séance."

MENTION_ORDRE_DU_JOUR: Final[str] = (
    "Document de travail interne préparatoire à la réunion de "
    "restitution — consultatif : il ne constitue pas un avis fiscal."
)

_LIBELLES_REGIME: Final[dict[str, str]] = {
    "reel": "réel normal",
    "reel_simplifie": "réel simplifié",
    "microentreprise": "microentreprise",
    "entreprenant": "taxe de l'entreprenant",
}

_LIBELLES_DECISION: Final[dict[str, str]] = {
    "retenue": "retenue",
    "ecartee": "écartée",
    "faite": "faite",
}


class ErreurOrdreDuJour(Exception):
    """Échec de génération de l'ordre du jour."""


class ErreurOrdreDuJourIntrouvable(ErreurOrdreDuJour):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures — sections numérotées ────────────────────────────


def _date_fr(iso: object | None) -> str:
    """« JJ/MM/AAAA » depuis une date ISO — chaîne vide si invalide."""
    brut = str(iso or "").strip()
    if not brut:
        return ""
    try:
        return date.fromisoformat(brut[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def section_introduction(
    exercice: object | None, regime: object | None
) -> list[str]:
    """PUR — 1. Introduction et rappel du périmètre de la mission."""
    lignes = ["1. Introduction et rappel du périmètre de la mission"]
    exo = str(exercice or "").strip()
    reg = str(regime or "").strip()
    if exo or reg:
        detail = f"   Exercice revu : {exo or '[à compléter]'}"
        if reg:
            detail += (
                f" — régime d'imposition : {_LIBELLES_REGIME.get(reg, reg)}"
            )
        lignes.append(detail + ".")
    else:
        lignes.append(f"   {A_COMPLETER_EN_SEANCE}")
    lignes.append(
        "   Rappel du calendrier des travaux et des livrables remis."
    )
    return lignes


def section_risques(risques: list[dict[str, Any]]) -> list[str]:
    """PUR — 2. Synthèse des risques identifiés au cours de la mission.

    ``risques`` : lignes de la table ``risque`` (libelle, impot,
    probabilite, montant_estime, penalites_estimees). Nombre, exposition
    totale chiffrée (str Decimal) et top ``NB_TOP_RISQUES`` par
    exposition décroissante. Sans risque : mention « à compléter ».
    """
    lignes = ["2. Synthèse des risques identifiés"]
    if not risques:
        lignes.append(
            "   Aucun risque enregistré sur la mission. "
            + A_COMPLETER_EN_SEANCE
        )
        return lignes
    expositions = [(r, _exposition(r)) for r in risques]
    total = sum(
        (e for _, e in expositions if e is not None), Decimal("0")
    )
    nb_chiffres = sum(1 for _, e in expositions if e is not None)
    lignes.append(
        f"   Nombre de risques identifiés : {len(risques)} "
        f"(dont {nb_chiffres} à exposition chiffrée)."
    )
    lignes.append(f"   Exposition totale estimée : {total} FCFA.")
    # Top par exposition décroissante — les chiffrés d'abord, puis les
    # non chiffrés (exposition traitée comme -1 pour le tri stable).
    classes = sorted(
        expositions,
        key=lambda re_: re_[1] if re_[1] is not None else Decimal("-1"),
        reverse=True,
    )[:NB_TOP_RISQUES]
    lignes.append(
        f"   Principaux risques (top {len(classes)} par exposition) :"
    )
    for rang, (r, expo) in enumerate(classes, start=1):
        libelle = str(r.get("libelle") or "").strip() or "[sans libellé]"
        impot = str(r.get("impot") or "").strip().upper()
        montant = (
            f"{expo} FCFA" if expo is not None else "exposition non chiffrée"
        )
        prefixe = f"   {rang}) {libelle}"
        if impot:
            prefixe += f" ({impot})"
        lignes.append(f"{prefixe} — {montant}.")
    return lignes


def section_actions(plan: list[dict[str, Any]]) -> list[str]:
    """PUR — 3. Actions proposées et décisions du fiscaliste.

    ``plan`` : items du plan d'actions fusionnés avec les décisions
    (:func:`backend.plateforme.plan_actions.fusionner_decisions`).
    Compte retenues / écartées / faites / sans décision et liste les
    actions décidées avec leur note éventuelle.
    """
    lignes = ["3. Actions proposées et décisions"]
    if not plan:
        lignes.append(
            "   Aucune action au plan d'actions. " + A_COMPLETER_EN_SEANCE
        )
        return lignes
    compte = {"retenue": 0, "ecartee": 0, "faite": 0, "sans": 0}
    for item in plan:
        decision = str(item.get("decision") or "")
        compte[decision if decision in _LIBELLES_DECISION else "sans"] += 1
    lignes.append(
        f"   Plan d'actions : {len(plan)} action(s) — "
        f"{compte['retenue']} retenue(s), {compte['ecartee']} écartée(s), "
        f"{compte['faite']} faite(s), {compte['sans']} sans décision."
    )
    decidees = [
        i for i in plan if str(i.get("decision") or "") in _LIBELLES_DECISION
    ]
    if decidees:
        lignes.append("   Décisions à passer en revue avec le client :")
        for item in decidees:
            action = str(item.get("action") or "").strip() or "[action]"
            decision = _LIBELLES_DECISION[str(item["decision"])]
            ligne = f"   - {action} — décision : {decision}"
            note = str(item.get("decision_note") or "").strip()
            if note:
                ligne += f" (note : {note})"
            lignes.append(ligne + ".")
    else:
        lignes.append(
            "   Aucune décision enregistrée à ce jour. "
            + A_COMPLETER_EN_SEANCE
        )
    return lignes


def section_civisme(civisme: dict[str, Any] | None) -> list[str]:
    """PUR — 4. Civisme déclaratif (taux et échéances manquantes).

    ``civisme`` : synthèse de
    :func:`backend.plateforme.civisme_fiscal.synthese_rapprochement`
    (``taux_civisme``, ``couvertes``, ``manquantes``, ``en_attente``) —
    None si l'analyse est indisponible.
    """
    lignes = ["4. Civisme déclaratif"]
    if not civisme:
        lignes.append(f"   {A_COMPLETER_EN_SEANCE}")
        return lignes
    lignes.append(
        f"   Taux de civisme déclaratif : {civisme.get('taux_civisme')} % "
        f"({int(civisme.get('couvertes') or 0)} échéance(s) couverte(s), "
        f"{int(civisme.get('manquantes') or 0)} manquante(s), "
        f"{int(civisme.get('en_attente') or 0)} en attente)."
    )
    if int(civisme.get("manquantes") or 0) > 0:
        lignes.append(
            "   Échéances sans pièce collectée : à vérifier avec le "
            "client avant toute conclusion."
        )
    return lignes


def section_echeances(
    echeances: list[dict[str, Any]], aujourd_hui: date
) -> list[str]:
    """PUR — 5. Prochaines échéances fiscales (3 prochaines à venir).

    ``echeances`` : items de ``construire_echeancier`` (impot,
    obligation, periode, date_limite ISO), déjà triés par date. Seules
    les échéances de date limite >= ``aujourd_hui`` sont retenues.
    """
    lignes = ["5. Prochaines échéances fiscales"]
    a_venir = [
        e
        for e in echeances
        if str(e.get("date_limite") or "") >= aujourd_hui.isoformat()
    ][:NB_ECHEANCES_A_VENIR]
    if not a_venir:
        lignes.append(
            "   Aucune échéance théorique à venir sur l'exercice revu. "
            + A_COMPLETER_EN_SEANCE
        )
        return lignes
    for e in a_venir:
        lignes.append(
            f"   - {_date_fr(e.get('date_limite'))} : "
            f"{str(e.get('impot') or '')} — "
            f"{str(e.get('obligation') or '')} "
            f"({str(e.get('periode') or '')})."
        )
    return lignes


def section_questions() -> list[str]:
    """PUR — 6. Questions diverses (points libres du client)."""
    return [
        "6. Questions diverses",
        f"   {A_COMPLETER_EN_SEANCE}",
    ]


def construire_ordre_du_jour(contexte: dict[str, Any]) -> str:
    """PUR — ordre du jour complet en texte brut, déterministe.

    ``contexte`` : {cabinet, contribuable, exercice, regime,
    aujourd_hui (date), risques, plan, civisme, echeances}. En-tête
    cabinet / client / exercice / date du jour, six sections numérotées,
    pied :data:`MENTION_ORDRE_DU_JOUR`. La date vient du paramètre
    ``aujourd_hui`` (aucun ``date.today()`` ici).
    """
    cabinet = str(contexte.get("cabinet") or "[cabinet à compléter]")
    contribuable = str(
        contexte.get("contribuable") or "[client à compléter]"
    )
    exercice = str(contexte.get("exercice") or "[à compléter]")
    jour: date = contexte["aujourd_hui"]

    lignes: list[str] = [
        "ORDRE DU JOUR — RÉUNION DE RESTITUTION",
        "",
        f"Cabinet : {cabinet.upper()}",
        f"Client : {contribuable}",
        f"Mission de revue fiscale — exercice {exercice}",
        f"Date d'édition : {jour.strftime('%d/%m/%Y')}",
        "",
    ]
    for section in (
        section_introduction(
            contexte.get("exercice"), contexte.get("regime")
        ),
        section_risques(list(contexte.get("risques") or [])),
        section_actions(list(contexte.get("plan") or [])),
        section_civisme(contexte.get("civisme")),
        section_echeances(list(contexte.get("echeances") or []), jour),
        section_questions(),
    ):
        lignes += section
        lignes.append("")
    lignes.append(MENTION_ORDRE_DU_JOUR)
    return "\n".join(lignes) + "\n"


# ── Lecture par mission (RLS) ────────────────────────────────────────


def ordre_du_jour_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Ordre du jour de restitution de la mission (lecture seule, RLS).

    Mission hors tenant → :class:`ErreurOrdreDuJourIntrouvable` (404
    côté route). Les analyses agrégées (plan d'actions, civisme,
    échéancier) sont OPTIONNELLES : en cas d'échec, la section porte la
    mention « à compléter en séance » — jamais bloquant.
    """
    jour = aujourd_hui or date.today()
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.exercice, c.denomination "
                "FROM mission m JOIN contribuable c "
                "ON c.id = m.contribuable_id WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurOrdreDuJourIntrouvable(
                f"mission {mission_id} introuvable"
            )
        # Risques attachés à LA mission (origine_mission_id) — même
        # colonne que la comparaison inter-exercices.
        risques = session.execute(
            text(
                "SELECT id, libelle, impot, statut, probabilite, "
                "montant_estime, penalites_estimees "
                "FROM risque WHERE origine_mission_id = :m "
                "ORDER BY id ASC"
            ),
            {"m": mission_id},
        ).mappings().all()

    # Identité du cabinet (table tenant, sans RLS) — même garde que
    # /api/v1/auth/connexion.
    cabinet = session.execute(
        text("SELECT denomination FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).scalar_one_or_none()

    # Analyses agrégées — chaque fonction ouvre son PROPRE
    # contexte_tenant : appels HORS de tout with contexte_tenant.
    # Échec silencieux → section « à compléter en séance ».
    regime: str | None = None
    echeances: list[dict[str, Any]] = []
    try:
        from backend.plateforme.echeancier_fiscal import (
            ErreurEcheancierIntrouvable,
            echeancier_mission,
        )

        echeancier = echeancier_mission(session, tenant_id, mission_id)
        regime = str(echeancier["regime"])
        echeances = list(echeancier["echeances"])
    except ErreurEcheancierIntrouvable:
        pass

    plan: list[dict[str, Any]] = []
    try:
        from backend.plateforme.plan_actions import (
            ErreurPlanActions,
            analyse_mission as analyse_plan_mission,
        )

        plan = list(
            analyse_plan_mission(
                session, tenant_id, mission_id, aujourd_hui=jour
            )["plan"]
        )
    except ErreurPlanActions:
        plan = []

    civisme: dict[str, Any] | None = None
    try:
        from backend.plateforme.civisme_fiscal import (
            ErreurCivismeFiscal,
            analyse_mission as analyse_civisme_mission,
        )

        civisme = analyse_civisme_mission(
            session, tenant_id, mission_id, aujourd_hui=jour
        )["synthese"]
    except ErreurCivismeFiscal:
        civisme = None

    ordre = construire_ordre_du_jour(
        {
            "cabinet": cabinet,
            "contribuable": row["denomination"],
            "exercice": row["exercice"],
            "regime": regime,
            "aujourd_hui": jour,
            "risques": [dict(r) for r in risques],
            "plan": plan,
            "civisme": civisme,
            "echeances": echeances,
        }
    )
    return {
        "mission_id": mission_id,
        "contribuable": row["denomination"],
        "exercice": row["exercice"],
        "nb_risques": len(risques),
        "ordre_du_jour": ordre,
        "note": MENTION_ORDRE_DU_JOUR,
    }
