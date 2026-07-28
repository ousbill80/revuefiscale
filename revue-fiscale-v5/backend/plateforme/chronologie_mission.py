"""Chronologie de la mission — traçabilité lisible par le fiscaliste.

POURQUOI : le journal d'audit (table ``journal_audit`` : horodatage,
acteur, action, charge_utile — écriture seule, hash chaîné) trace déjà
qui a fait quoi sur la mission (dépôts de pièces, changements de
statut, décisions du plan d'actions, relances, exports…). Mais ses
codes d'action techniques (``depot_piece_contribuable``,
``maj_suivi_renseignements``…) ne se lisent pas d'un coup d'œil. Ce
module met en forme ces événements en libellés français pour offrir une
« Chronologie de la mission » : qui a fait quoi et quand.

LIMITE ASSUMÉE : restitution strictement CONSULTATIVE et déterministe —
aucune écriture, aucun LLM. Les codes d'action inconnus sont affichés
tels quels (fallback) : la chronologie ne masque jamais un événement.
La consultation de la chronologie est elle-même journalisée
(:data:`ACTION_CONSULTATION`) mais EXCLUE de l'affichage pour ne pas
polluer la chronologie par sa propre consultation. Fonctions pures +
lecture seule sous RLS via ``contexte_tenant``.
"""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# Code journalisé par la route de consultation — jamais affiché.
ACTION_CONSULTATION: Final[str] = "consultation_chronologie_mission"

# Plafond raisonnable d'événements restitués (les plus récents).
PLAFOND_EVENEMENTS: Final[int] = 100

MENTION_NOTE: Final[str] = (
    "Chronologie consultative issue du journal d'audit de la mission "
    "(écriture seule, hash chaîné) — les événements les plus récents "
    "d'abord. Les consultations de la chronologie elle-même n'y "
    "figurent pas."
)

# Libellés français des codes d'action connus du journal d'audit.
# Fallback : un code absent est affiché tel quel (jamais masqué).
LIBELLES_ACTIONS: Final[dict[str, str]] = {
    # Cadrage et vie de la mission
    "creation_mission": "Création de la mission",
    "cadrage_mission": "Cadrage de la mission",
    "objectifs_mission": "Définition des objectifs de la mission",
    "changement_statut": "Changement de statut de la mission",
    "reconduction_mission": (
        "Reconduction de la mission sur l'exercice suivant"
    ),
    "creation_contribuable": "Création du contribuable",
    # Data room et sources
    "depot_piece_contribuable": "Dépôt d'une pièce en data room",
    "import_balance": "Import de la balance",
    "source_mission_depuis_piece": "Alimentation des soldes depuis une pièce",
    # Exécution et travaux
    "execution_moteur": "Exécution de la revue",
    "amendement_tache": "Amendement d'une tâche",
    "amendement_conclusion": "Amendement d'une conclusion",
    "validation_conclusion": "Validation d'une conclusion",
    "coche_diligence_programme": "Pointage d'une diligence du programme",
    "saisie_temps_mission": "Saisie de temps sur la mission",
    "suppression_temps_mission": "Suppression d'un temps saisi",
    # Risques et plan d'actions
    "decision_plan_action": "Décision sur une action du plan d'actions",
    "depot_preuve_resolution": "Dépôt d'une preuve de résolution",
    "resolution_risque_avec_preuve": "Résolution d'un risque avec preuve",
    "ajout_items_demande_depuis_civisme": (
        "Ajout d'items à la demande depuis le civisme fiscal"
    ),
    # Demande de renseignements et relances
    "maj_suivi_renseignements": "Mise à jour du suivi de renseignements",
    "planification_relances": "Planification des relances",
    "relance_effectuee": "Relance effectuée",
    "relances_effectuees_groupees": "Relances effectuées (groupées)",
    "report_relance": "Report d'une relance",
    "saisie_reponse_client": "Saisie d'une réponse du client",
    # Supervision
    "pose_visa_mission": "Pose d'un visa de supervision",
    "revocation_visa_mission": "Révocation d'un visa de supervision",
    # Livrables et exports
    "generation_note_synthese": "Génération de la note de synthèse",
    "generation_commentaire_analytique": (
        "Génération du commentaire analytique"
    ),
    "generation_synthese_client": "Génération de la synthèse client",
    "telechargement_dossier_travail": "Téléchargement du dossier de travail",
    "telechargement_lettre_affirmation": (
        "Téléchargement de la lettre d'affirmation"
    ),
    "telechargement_demande_renseignements": (
        "Téléchargement de la demande de renseignements"
    ),
    "telechargement_courrier_envoi": (
        "Téléchargement du courrier d'envoi du rapport"
    ),
    "telechargement_courrier_relance": "Téléchargement du courrier de relance",
    "telechargement_ordre_du_jour": (
        "Téléchargement de l'ordre du jour de restitution"
    ),
    "enregistrement_compte_rendu": (
        "Enregistrement du compte-rendu de réunion de restitution"
    ),
    "export_rentabilite_csv": "Export CSV de la rentabilité",
    "definition_parametres_rentabilite": (
        "Définition des paramètres de rentabilité"
    ),
    # Mémoire client
    "ajout_memoire_client": "Ajout d'une entrée en mémoire client",
    "retrait_memoire_client": "Retrait d'une entrée de la mémoire client",
    # Consultations tracées
    "consultation_civisme_fiscal": "Consultation du civisme fiscal",
    "consultation_echeancier_fiscal": "Consultation de l'échéancier fiscal",
    "consultation_prescription_risques": (
        "Consultation de la prescription des risques"
    ),
    "consultation_plan_actions": "Consultation du plan d'actions",
    "consultation_pilotage_mission": "Consultation du pilotage de la mission",
    "consultation_delais_mission": (
        "Consultation des délais de traitement"
    ),
    "consultation_rentabilite_mission": (
        "Consultation de la rentabilité de la mission"
    ),
    "consultation_bilan_cloture": "Consultation du bilan de clôture",
    "consultation_comparaison_exercices": (
        "Consultation de la comparaison d'exercices"
    ),
    "consultation_courrier_relance": "Consultation du courrier de relance",
    "consultation_courrier_relance_txt": (
        "Téléchargement du courrier de relance (texte)"
    ),
}


class ErreurChronologieMission(Exception):
    """Échec de la chronologie de mission."""


class ErreurChronologieIntrouvable(ErreurChronologieMission):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def traduire_action(action: Any) -> str:
    """PUR — libellé français d'un code d'action, fallback code brut."""
    code = str(action or "").strip()
    return LIBELLES_ACTIONS.get(code, code)


def mettre_en_forme(
    evenements: list[dict[str, Any]],
    plafond: int = PLAFOND_EVENEMENTS,
) -> list[dict[str, Any]]:
    """PUR — événements bruts du journal → chronologie lisible.

    - exclut les consultations de la chronologie elle-même
      (:data:`ACTION_CONSULTATION`) — pas de boucle d'auto-pollution ;
    - tri antichronologique (horodatage puis id décroissants — l'id
      départage les événements de même horodatage) ;
    - plafonne aux ``plafond`` événements les plus récents ;
    - traduit chaque code d'action en libellé français
      (:func:`traduire_action`, fallback code brut).

    Chaque item : ``{id, horodatage, acteur, action, libelle}``.
    """
    borné = max(1, int(plafond))
    retenus = [
        e
        for e in evenements
        if str(e.get("action") or "") != ACTION_CONSULTATION
    ]
    retenus.sort(
        key=lambda e: (str(e.get("horodatage") or ""), int(e.get("id") or 0)),
        reverse=True,
    )
    chronologie: list[dict[str, Any]] = []
    for e in retenus[:borné]:
        quand = e.get("horodatage")
        chronologie.append(
            {
                "id": int(e.get("id") or 0),
                "horodatage": (
                    quand.isoformat()
                    if hasattr(quand, "isoformat")
                    else str(quand or "")
                ),
                "acteur": str(e.get("acteur") or ""),
                "action": str(e.get("action") or ""),
                "libelle": traduire_action(e.get("action")),
            }
        )
    return chronologie


# ── Lecture par mission (RLS) ────────────────────────────────────────


def chronologie_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> dict[str, Any]:
    """Chronologie de la mission — lecture seule, RLS.

    Lit les événements du journal d'audit rattachés à la mission
    (colonne ``mission_id`` de ``journal_audit``) puis délègue la mise
    en forme à :func:`mettre_en_forme`. Mission hors tenant →
    :class:`ErreurChronologieIntrouvable` (404 côté route).
    """
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text("SELECT id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if mission is None:
            raise ErreurChronologieIntrouvable(
                f"mission {mission_id} introuvable"
            )
        rows = session.execute(
            text(
                "SELECT id, horodatage, acteur, action "
                "FROM journal_audit "
                "WHERE mission_id = :m AND action <> :excl "
                "ORDER BY id DESC LIMIT :lim"
            ),
            {
                "m": mission_id,
                "excl": ACTION_CONSULTATION,
                "lim": PLAFOND_EVENEMENTS,
            },
        ).mappings().all()

    evenements = mettre_en_forme([dict(r) for r in rows])
    return {
        "mission_id": mission_id,
        "evenements": evenements,
        "total_affiche": len(evenements),
        "plafond": PLAFOND_EVENEMENTS,
        "note": MENTION_NOTE,
    }
