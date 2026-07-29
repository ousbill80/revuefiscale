"""Journal d'activité du cabinet — consultation paginée du journal d'audit.

POURQUOI : le journal d'audit (``journal_audit``, écriture seule via
:func:`backend.moteur.journal.append_journal`) n'était consultable que
MISSION par mission (restitution, chronologie). Pour la traçabilité
PROFESSIONNELLE du cabinet — qui a consulté ou fait quoi, et quand,
toutes missions confondues — l'admin veut une vue d'ensemble paginée,
sans ouvrir chaque dossier.

POSTURE : vue DÉTERMINISTE et CONSULTATIVE (aucun LLM, aucun email).
Le journal DÉCRIT l'activité réalisée dans l'outil — il ne surveille
personne : les libellés sont neutres et factuels (« Consultation du
dossier de mission », jamais un jugement). Lecture seule sous RLS via
``contexte_tenant`` — AUCUNE écriture, AUCUNE migration.

TOLÉRANCE : une action inconnue du mapping est restituée avec son
libellé brut (le journal reste lisible même si le code évolue) ; des
``details`` illisibles sont condensés défensivement, jamais bloquants.
"""
from __future__ import annotations

from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

#: Taille de page par défaut.
TAILLE_DEFAUT: Final[int] = 50

#: Taille de page maximale — consultation, pas un export.
TAILLE_MAX: Final[int] = 100

#: Longueur maximale d'une valeur de détail (texte condensé).
LONGUEUR_DETAIL_MAX: Final[int] = 120

#: Nombre maximal de clés de détails restituées par entrée.
NB_DETAILS_MAX: Final[int] = 8

#: Libellés français NEUTRES des actions journalisées — le journal
#: décrit l'activité de l'outil, il ne juge personne. Action absente
#: du mapping → libellé brut (tolérant, jamais bloquant).
LIBELLES_ACTION: Final[dict[str, str]] = {
    # Cycle de vie des dossiers
    "creation_contribuable": "Création d'un client",
    "creation_mission": "Création d'une mission",
    "reconduction_mission": "Reconduction d'une mission",
    "changement_statut": "Changement de statut de mission",
    "cadrage_mission": "Cadrage de la mission",
    "objectifs_mission": "Définition des objectifs de mission",
    "affectation_responsable_mission": "Affectation du responsable de mission",
    "import_balance": "Import d'une balance",
    "execution_moteur": "Exécution de la revue",
    "depot_piece_contribuable": "Dépôt d'une pièce par le client",
    "source_mission_depuis_piece": "Création de mission depuis une pièce",
    # Travaux de revue
    "amendement_conclusion": "Amendement d'une conclusion",
    "validation_conclusion": "Validation d'une conclusion",
    "amendement_tache": "Amendement d'une tâche",
    "coche_diligence_programme": "Pointage d'une diligence du programme",
    "pose_visa_mission": "Pose d'un visa de mission",
    "revocation_visa_mission": "Retrait d'un visa de mission",
    "decision_plan_action": "Décision sur un point du plan d'actions",
    "depot_preuve_resolution": "Dépôt d'une preuve de résolution",
    "resolution_risque_avec_preuve": "Résolution d'un risque avec preuve",
    # Relation client
    "saisie_reponse_client": "Saisie d'une réponse client",
    "maj_suivi_renseignements": "Mise à jour du suivi de renseignements",
    "ajout_items_demande_depuis_civisme": (
        "Ajout d'items à la demande de renseignements"
    ),
    "planification_relances": "Planification de relances",
    "relance_effectuee": "Relance notée comme effectuée",
    "relances_effectuees_groupees": "Relances notées comme effectuées",
    "report_relance": "Report d'une relance",
    "enregistrement_compte_rendu": "Enregistrement d'un compte rendu",
    "ajout_memoire_client": "Ajout à la mémoire client",
    "retrait_memoire_client": "Retrait de la mémoire client",
    # Temps et rentabilité
    "saisie_temps_mission": "Saisie de temps sur la mission",
    "suppression_temps_mission": "Suppression d'une saisie de temps",
    "definition_parametres_rentabilite": (
        "Définition des paramètres de rentabilité"
    ),
    # Consultations de mission
    "consultation_dossier_mission": "Consultation du dossier de mission",
    "consultation_pilotage_mission": "Consultation du pilotage de mission",
    "consultation_chronologie_mission": (
        "Consultation de la chronologie de mission"
    ),
    "consultation_delais_mission": "Consultation des délais de mission",
    "consultation_echeancier_fiscal": "Consultation de l'échéancier fiscal",
    "consultation_prescription_risques": (
        "Consultation de la prescription des risques"
    ),
    "consultation_civisme_fiscal": "Consultation du civisme fiscal",
    "consultation_completude_data_room": (
        "Consultation de la complétude de la data room"
    ),
    "consultation_charge_fiscale": "Consultation de la charge fiscale",
    "consultation_panorama_conformite": (
        "Consultation du panorama de conformité"
    ),
    "consultation_fil_conducteur": "Consultation du fil conducteur",
    "consultation_lettre_mission": "Consultation de la lettre de mission",
    "consultation_plan_actions": "Consultation du plan d'actions",
    "consultation_bilan_cloture": "Consultation du bilan de clôture",
    "consultation_rentabilite_mission": (
        "Consultation de la rentabilité de mission"
    ),
    "consultation_points_anterieurs": (
        "Consultation des points antérieurs"
    ),
    "consultation_courrier_relance": "Consultation du courrier de relance",
    "consultation_courrier_relance_txt": (
        "Consultation du courrier de relance (texte)"
    ),
    "consultation_acomptes_is": "Consultation des acomptes IS",
    "consultation_coherence_ca": (
        "Consultation de la cohérence du chiffre d'affaires"
    ),
    "consultation_completude_declarative": (
        "Consultation de la complétude déclarative"
    ),
    "consultation_deductibilite": "Consultation de la déductibilité",
    "consultation_deficits_reportables": (
        "Consultation des déficits reportables"
    ),
    "consultation_evolution_charge_fiscale": (
        "Consultation de l'évolution de la charge fiscale"
    ),
    "consultation_materialite": "Consultation de la matérialité",
    "consultation_patente": "Consultation de la patente",
    "consultation_programme_propose": (
        "Consultation du programme de travail proposé"
    ),
    "consultation_qualite_balance": "Consultation de la qualité de la balance",
    "consultation_rapprochement_acomptes": (
        "Consultation du rapprochement des acomptes"
    ),
    "consultation_rapprochement_salaires": (
        "Consultation du rapprochement des salaires"
    ),
    "consultation_rapprochement_tva": (
        "Consultation du rapprochement de la TVA"
    ),
    "consultation_resultat_fiscal": "Consultation du résultat fiscal",
    "consultation_retenue_honoraires": (
        "Consultation de la retenue sur honoraires"
    ),
    "consultation_retenue_loyers": "Consultation de la retenue sur loyers",
    # Consultations client
    "consultation_fiche_client": "Consultation de la fiche client",
    "consultation_historique_client": "Consultation de l'historique client",
    "consultation_comparaison_exercices": (
        "Consultation de la comparaison d'exercices"
    ),
    # Consultations cabinet
    "consultation_agenda_cabinet": "Consultation de l'agenda du cabinet",
    "consultation_agenda_cabinet_ics": (
        "Export de l'agenda du cabinet (ICS)"
    ),
    "consultation_agenda_cabinet_csv": (
        "Export de l'agenda du cabinet (CSV)"
    ),
    "consultation_relances_cabinet": (
        "Consultation des relances du cabinet"
    ),
    "consultation_relances_cabinet_csv": (
        "Export des relances du cabinet (CSV)"
    ),
    "consultation_actions_retenues_cabinet": (
        "Consultation des actions retenues du cabinet"
    ),
    "consultation_actions_retenues_cabinet_csv": (
        "Export des actions retenues du cabinet (CSV)"
    ),
    "consultation_rentabilite_cabinet": (
        "Consultation de la rentabilité du cabinet"
    ),
    "consultation_delais_cabinet": "Consultation des délais du cabinet",
    "consultation_preparation_cloture_cabinet": (
        "Consultation de la préparation de clôture"
    ),
    "consultation_preparation_cloture_cabinet_csv": (
        "Export de la préparation de clôture (CSV)"
    ),
    "consultation_echeances_cabinet": (
        "Consultation des échéances du cabinet"
    ),
    "consultation_echeances_cabinet_csv": (
        "Export des échéances du cabinet (CSV)"
    ),
    "consultation_points_convenus_cabinet": (
        "Consultation des points convenus du cabinet"
    ),
    "consultation_points_convenus_cabinet_csv": (
        "Export des points convenus du cabinet (CSV)"
    ),
    "consultation_centre_alertes_cabinet": (
        "Consultation du centre d'alertes"
    ),
    "consultation_calendrier_cabinet": (
        "Consultation du calendrier fiscal du cabinet"
    ),
    "consultation_portefeuille_declaratif": (
        "Consultation du portefeuille déclaratif"
    ),
    # Documents produits / téléchargés
    "generation_synthese_client": "Génération de la synthèse client",
    "generation_note_synthese": "Génération de la note de synthèse",
    "generation_commentaire_analytique": (
        "Génération du commentaire analytique"
    ),
    "telechargement_demande_renseignements": (
        "Téléchargement de la demande de renseignements"
    ),
    "telechargement_courrier_relance": (
        "Téléchargement du courrier de relance"
    ),
    "telechargement_ordre_du_jour": "Téléchargement de l'ordre du jour",
    "telechargement_courrier_envoi": (
        "Téléchargement du courrier d'envoi du rapport"
    ),
    "telechargement_lettre_affirmation": (
        "Téléchargement de la lettre d'affirmation"
    ),
    "telechargement_dossier_travail": (
        "Téléchargement du dossier de travail"
    ),
    # Exports cabinet
    "export_alertes": "Export des alertes du cabinet",
    "export_calendrier": "Export du calendrier fiscal",
    "export_brief": "Export du brief du cabinet",
    "export_portefeuille_declaratif": (
        "Export du portefeuille déclaratif"
    ),
    "export_rentabilite_csv": "Export de la rentabilité (CSV)",
    "export_rapport_activite": "Export du rapport d'activité du cabinet",
}

MENTION_NOTE: Final[str] = (
    "Journal de traçabilité professionnelle du cabinet — consultation "
    "chronologique des événements enregistrés par l'application "
    "(consultations, exécutions, documents produits). Ce journal "
    "DÉCRIT l'activité réalisée dans l'outil, à des fins de "
    "traçabilité des diligences : il ne constitue ni une évaluation "
    "ni un dispositif de surveillance des personnes. Lecture seule, "
    "aucun email."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def borner_page(page: Any) -> int:
    """PUR — numéro de page ≥ 1 (valeur illisible → 1, jamais bloquant)."""
    try:
        return max(1, int(page))
    except (TypeError, ValueError):
        return 1


def borner_taille(taille: Any) -> int:
    """PUR — taille de page dans [1, TAILLE_MAX] (défensif)."""
    try:
        t = int(taille)
    except (TypeError, ValueError):
        return TAILLE_DEFAUT
    return max(1, min(t, TAILLE_MAX))


def libelle_action(action: str) -> str:
    """PUR — libellé français neutre ; action inconnue → libellé brut."""
    return LIBELLES_ACTION.get(str(action or ""), str(action or ""))


def condenser_details(charge: Any) -> dict[str, Any]:
    """PUR — condense la charge utile pour l'affichage tabulaire.

    Seules les valeurs scalaires sont gardées (texte tronqué à
    :data:`LONGUEUR_DETAIL_MAX`) ; une liste est résumée par son
    nombre d'éléments ; un dictionnaire imbriqué est écarté. Clés
    triées (déterminisme) et plafonnées à :data:`NB_DETAILS_MAX`.
    Charge illisible → détails vides, jamais bloquant.
    """
    if not isinstance(charge, dict):
        return {}
    details: dict[str, Any] = {}
    for cle in sorted(charge, key=str):
        if len(details) >= NB_DETAILS_MAX:
            break
        valeur = charge[cle]
        if valeur is None or isinstance(valeur, (bool, int, float)):
            details[str(cle)] = valeur
        elif isinstance(valeur, str):
            details[str(cle)] = (
                valeur
                if len(valeur) <= LONGUEUR_DETAIL_MAX
                else valeur[: LONGUEUR_DETAIL_MAX - 1] + "…"
            )
        elif isinstance(valeur, list):
            details[str(cle)] = f"{len(valeur)} élément(s)"
        # dict imbriqué (ou autre) → écarté : la vue reste lisible.
    return details


def serialiser_entree(row: dict[str, Any]) -> dict[str, Any]:
    """PUR — entrée au contrat stable (horodatage ISO, libellé, détails)."""
    horodatage = row.get("horodatage")
    if hasattr(horodatage, "isoformat"):
        horodatage = horodatage.isoformat()
    action = str(row.get("action") or "")
    mission = row.get("mission_id")
    return {
        "horodatage": str(horodatage or ""),
        "acteur": str(row.get("acteur") or ""),
        "action": action,
        "libelle_action": libelle_action(action),
        "mission_id": int(mission) if mission is not None else None,
        "details": condenser_details(row.get("charge_utile")),
    }


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def journal_cabinet(
    session: Session,
    tenant_id: int,
    page: int = 1,
    taille: int = TAILLE_DEFAUT,
    action: str | None = None,
    acteur: str | None = None,
) -> dict[str, Any]:
    """Journal d'activité du cabinet — LECTURE SEULE, RLS, paginé.

    Tri chronologique DÉCROISSANT (le plus récent d'abord — ordre
    d'insertion ``id``, fiable même à horodatages identiques).
    Filtres optionnels exacts par ``action`` et par ``acteur``
    (email). AUCUNE écriture : consulter le journal n'ajoute pas de
    bruit auto-référentiel au journal lui-même.
    """
    p = borner_page(page)
    t = borner_taille(taille)
    filtres_sql = ""
    params: dict[str, Any] = {"lim": t, "off": (p - 1) * t}
    if action:
        filtres_sql += " AND action = :action"
        params["action"] = str(action)
    if acteur:
        filtres_sql += " AND acteur = :acteur"
        params["acteur"] = str(acteur)

    with contexte_tenant(session, tenant_id):
        total = session.execute(
            text(
                "SELECT COUNT(*) FROM journal_audit "
                "WHERE TRUE" + filtres_sql
            ),
            {k: v for k, v in params.items() if k not in ("lim", "off")},
        ).scalar_one()
        rows = session.execute(
            text(
                "SELECT id, horodatage, acteur, action, mission_id, "
                "charge_utile "
                "FROM journal_audit WHERE TRUE" + filtres_sql +
                " ORDER BY id DESC LIMIT :lim OFFSET :off"
            ),
            params,
        ).mappings().all()

    return {
        "total": int(total),
        "page": p,
        "taille": t,
        "entrees": [serialiser_entree(dict(r)) for r in rows],
        "filtres": {"action": action or None, "acteur": acteur or None},
        "note": MENTION_NOTE,
    }
