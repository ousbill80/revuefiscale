"""Suivi des contrôles fiscaux et contentieux — délais de riposte LPF.

POURQUOI : lorsqu'un client entre en contrôle fiscal (vérification de
comptabilité) ou en contentieux, chaque acte de procédure ouvre un
délai de riposte du Livre de Procédures Fiscales ivoirien : 30 jours
pour produire des observations sur une notification (provisoire) de
redressement, régularisation sous 10 jours sur mise en demeure avant
taxation d'office, réclamation contentieuse dans les 6 mois de l'avis
de mise en recouvrement, recours juridictionnel dans les 30 jours de
la décision de rejet… Rater un délai, c'est perdre un droit. Le
fiscaliste consigne les événements (date, type, montant en jeu
éventuel, commentaire) ; le module calcule les échéances et signale
celles proches ou dépassées.

LIMITE ASSUMÉE : les délais sont INDICATIFS — calculés à partir de la
date consignée par le fiscaliste (réception/envoi de l'acte) selon les
délais usuels du LPF ivoirien. Chaque acte doit être vérifié (délai
porté sur l'acte lui-même, suspensions, prorogations, jours fériés) —
seul l'œil humain arbitre.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — les
échéances éclairent, l'humain décide. Fonctions pures testables sans
base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.rapprochement_tva`). Montants sérialisés en
``str`` (Decimal). Contrat stable : clés toujours présentes, note
consultative toujours présente. Écritures uniquement sur clic humain
(POST), journalisées via ``append_journal``.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

# Délais de riposte usuels du LPF ivoirien, par type d'acte. Chaque
# entrée : libellé, délai (jours OU mois calendaires, exclusifs), objet
# du délai (qui doit agir), référence indicative. ``delai_jours`` et
# ``delai_mois`` à None = acte sans délai de riposte calculé (suivi
# purement chronologique).
TYPES_EVENEMENT: Final[dict[str, dict[str, Any]]] = {
    "avis_verification": {
        "libelle": "Avis de vérification de comptabilité",
        "delai_jours": None,
        "delai_mois": None,
        "objet_delai": (
            "Aucun délai de riposte à la charge du contribuable — la "
            "première intervention ne peut intervenir moins de 5 jours "
            "francs après remise de l'avis : préparer le dossier et "
            "l'assistance d'un conseil."
        ),
        "reference": "LPF ivoirien, art. 15",
    },
    "notification_redressement": {
        "libelle": "Notification (provisoire) de redressement",
        "delai_jours": 30,
        "delai_mois": None,
        "objet_delai": (
            "Observations ou acceptation du contribuable à produire "
            "sous 30 jours — le silence vaut acceptation des "
            "redressements notifiés."
        ),
        "reference": "LPF ivoirien, art. 22",
    },
    "mise_en_demeure": {
        "libelle": "Mise en demeure",
        "delai_jours": 10,
        "delai_mois": None,
        "objet_delai": (
            "Régularisation (dépôt de la déclaration ou du document "
            "requis) sous 10 jours avant taxation ou évaluation "
            "d'office."
        ),
        "reference": "LPF ivoirien, art. 27",
    },
    "avis_mise_en_recouvrement": {
        "libelle": "Avis de mise en recouvrement",
        "delai_jours": None,
        "delai_mois": 6,
        "objet_delai": (
            "Réclamation contentieuse à introduire dans les 6 mois — "
            "assortie le cas échéant d'une demande de sursis de "
            "paiement."
        ),
        "reference": "LPF ivoirien, art. 183",
    },
    "reclamation_contentieuse": {
        "libelle": "Réclamation contentieuse",
        "delai_jours": 30,
        "delai_mois": None,
        "objet_delai": (
            "Décision de l'administration attendue sous 30 jours — "
            "au-delà, le silence gardé permet de saisir le juge "
            "(rejet implicite)."
        ),
        "reference": "LPF ivoirien, art. 187",
    },
    "reponse_administration": {
        "libelle": "Réponse de l'administration",
        "delai_jours": 30,
        "delai_mois": None,
        "objet_delai": (
            "En cas de rejet total ou partiel : recours juridictionnel "
            "à introduire dans les 30 jours de la notification de la "
            "décision."
        ),
        "reference": "LPF ivoirien, art. 190",
    },
    "degrevement": {
        "libelle": "Dégrèvement",
        "delai_jours": None,
        "delai_mois": None,
        "objet_delai": (
            "Issue favorable — vérifier l'exécution effective "
            "(ordonnancement, imputation ou remboursement)."
        ),
        "reference": "LPF ivoirien, contentieux de l'impôt",
    },
    "recours_juridictionnel": {
        "libelle": "Recours juridictionnel",
        "delai_jours": None,
        "delai_mois": None,
        "objet_delai": (
            "Procédure devant le juge de l'impôt — suivre le "
            "calendrier fixé par la juridiction."
        ),
        "reference": "LPF ivoirien, art. 190 et s.",
    },
}

# Une échéance à J-7 ou moins est signalée « proche ».
SEUIL_PROCHE_JOURS: Final = 7

STATUT_SANS_DELAI: Final = "sans_delai"
STATUT_A_VENIR: Final = "a_venir"
STATUT_PROCHE: Final = "proche"
STATUT_DEPASSEE: Final = "depassee"

SYNTHESE_AUCUN: Final = "aucun_evenement"
SYNTHESE_A_JOUR: Final = "a_jour"
SYNTHESE_PROCHES: Final = "echeances_proches"
SYNTHESE_DEPASSEES: Final = "echeances_depassees"

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_CONTROLES_FISCAUX: Final = (
    "Suivi consultatif des contrôles fiscaux et contentieux : les "
    "délais de riposte sont calculés selon les délais usuels du Livre "
    "de Procédures Fiscales ivoirien à partir des dates consignées. "
    "Ils sont indicatifs — vérifier chaque acte (délai porté sur "
    "l'acte, suspensions, prorogations) : le fiscaliste apprécie et "
    "décide, rien n'est automatique."
)

# Code journalisé dans le journal d'audit (écriture sur POST uniquement).
ACTION_CONSIGNATION: Final = "consignation_evenement_controle_fiscal"


class ErreurControleFiscal(Exception):
    """Échec du suivi des contrôles fiscaux."""


class ErreurControleFiscalIntrouvable(ErreurControleFiscal):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurControleFiscalInvalide(ErreurControleFiscal):
    """Saisie invalide (type, date, montant) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def valider_type_evenement(type_evenement: object) -> str:
    """PUR — type d'événement connu du référentiel LPF.

    Inconnu → :class:`ErreurControleFiscalInvalide` (422 côté route).
    """
    texte_type = str(type_evenement or "").strip()
    if texte_type not in TYPES_EVENEMENT:
        attendus = ", ".join(sorted(TYPES_EVENEMENT))
        raise ErreurControleFiscalInvalide(
            f"type d'événement inconnu « {texte_type} » — attendus : "
            f"{attendus}"
        )
    return texte_type


def valider_date_evenement(date_evenement: object) -> date:
    """PUR — date ISO « AAAA-MM-JJ » plausible (≥ 1990).

    Invalide → :class:`ErreurControleFiscalInvalide` (422 côté route).
    """
    texte_date = str(date_evenement or "").strip()
    try:
        valeur = date.fromisoformat(texte_date)
    except ValueError as e:
        raise ErreurControleFiscalInvalide(
            f"date invalide « {texte_date} » — format attendu : "
            "AAAA-MM-JJ"
        ) from e
    if valeur.year < 1990:
        raise ErreurControleFiscalInvalide(
            f"date invraisemblable « {texte_date} » — année ≥ 1990 "
            "attendue"
        )
    return valeur


def valider_montant_en_jeu(montant: object) -> Decimal | None:
    """PUR — montant en jeu FCFA ≥ 0 (Decimal) ou ``None`` si absent.

    Illisible ou négatif → :class:`ErreurControleFiscalInvalide`
    (422 côté route).
    """
    if montant is None or str(montant).strip() == "":
        return None
    try:
        valeur = Decimal(str(montant).strip().replace(" ", ""))
    except InvalidOperation as e:
        raise ErreurControleFiscalInvalide(
            f"montant en jeu illisible : {montant!r}"
        ) from e
    if valeur < 0:
        raise ErreurControleFiscalInvalide(
            f"montant en jeu négatif interdit : {valeur}"
        )
    return valeur.quantize(Decimal("0.01"))


def ajouter_mois(depart: date, nb_mois: int) -> date:
    """PUR — ajoute des mois calendaires (fin de mois bornée).

    Ex. 31/08 + 6 mois → 28/02 (ou 29/02 année bissextile) : le
    quantième est borné au dernier jour du mois d'arrivée.
    """
    total = depart.year * 12 + (depart.month - 1) + nb_mois
    annee, mois = divmod(total, 12)
    mois += 1
    jour = min(depart.day, calendar.monthrange(annee, mois)[1])
    return date(annee, mois, jour)


def calculer_delai_riposte(
    type_evenement: str, date_evenement: date
) -> dict[str, Any]:
    """PUR — délai de riposte LPF d'un événement (déterministe).

    Retourne un dict aux clés TOUJOURS présentes : ``duree`` (texte
    « 30 jours » / « 6 mois » ou ``None``), ``echeance`` (date ISO ou
    ``None``), ``objet`` et ``reference`` (textes du référentiel).
    """
    spec = TYPES_EVENEMENT[type_evenement]
    echeance: date | None = None
    duree: str | None = None
    if spec["delai_jours"] is not None:
        from datetime import timedelta

        echeance = date_evenement + timedelta(days=int(spec["delai_jours"]))
        duree = f"{spec['delai_jours']} jours"
    elif spec["delai_mois"] is not None:
        echeance = ajouter_mois(date_evenement, int(spec["delai_mois"]))
        duree = f"{spec['delai_mois']} mois"
    return {
        "duree": duree,
        "echeance": echeance.isoformat() if echeance else None,
        "objet": spec["objet_delai"],
        "reference": spec["reference"],
    }


def statut_echeance(
    echeance: str | None, aujourd_hui: date
) -> dict[str, Any]:
    """PUR — statut d'une échéance vs la date du jour.

    ``sans_delai`` (échéance absente), ``a_venir`` (> J+7), ``proche``
    (entre J et J+7 inclus), ``depassee`` (< J). ``jours_restants`` est
    ``None`` sans échéance, sinon signé (négatif si dépassée).
    """
    if echeance is None:
        return {"statut": STATUT_SANS_DELAI, "jours_restants": None}
    restants = (date.fromisoformat(echeance) - aujourd_hui).days
    if restants < 0:
        statut = STATUT_DEPASSEE
    elif restants <= SEUIL_PROCHE_JOURS:
        statut = STATUT_PROCHE
    else:
        statut = STATUT_A_VENIR
    return {"statut": statut, "jours_restants": restants}


def construire_chronologie(
    evenements: list[dict[str, Any]], aujourd_hui: date
) -> list[dict[str, Any]]:
    """PUR — chronologie triée + délais de riposte calculés.

    ``evenements`` : lignes ``{id?, type_evenement, date_evenement,
    montant_en_jeu?, commentaire?}``. Tri chronologique (date puis id) ;
    montants ``str`` ou ``None`` ; chaque ligne porte ``delai_riposte``
    et ``echeance`` (statut + jours restants). Type inconnu ou date
    illisible → :class:`ErreurControleFiscalInvalide`.
    """
    lignes: list[dict[str, Any]] = []
    for e in evenements:
        type_ok = valider_type_evenement(e.get("type_evenement"))
        date_ok = valider_date_evenement(e.get("date_evenement"))
        montant = e.get("montant_en_jeu")
        montant_txt = (
            None
            if montant is None or str(montant).strip() == ""
            else str(Decimal(str(montant)))
        )
        delai = calculer_delai_riposte(type_ok, date_ok)
        lignes.append(
            {
                "id": int(e["id"]) if e.get("id") is not None else None,
                "type_evenement": type_ok,
                "libelle": TYPES_EVENEMENT[type_ok]["libelle"],
                "date_evenement": date_ok.isoformat(),
                "montant_en_jeu": montant_txt,
                "commentaire": str(e.get("commentaire") or ""),
                "delai_riposte": delai,
                "echeance": statut_echeance(delai["echeance"], aujourd_hui),
            }
        )
    lignes.sort(key=lambda x: (x["date_evenement"], x["id"] or 0))
    return lignes


def synthese_controles(
    chronologie: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — synthèse de la chronologie (clés toujours présentes).

    Montant total en jeu = somme des montants renseignés (``str``).
    Statut global : ``aucun_evenement`` / ``echeances_depassees`` /
    ``echeances_proches`` / ``a_jour`` (priorité au plus grave).
    """
    nb_proches = sum(
        1 for e in chronologie if e["echeance"]["statut"] == STATUT_PROCHE
    )
    nb_depassees = sum(
        1 for e in chronologie if e["echeance"]["statut"] == STATUT_DEPASSEE
    )
    total = sum(
        (
            Decimal(e["montant_en_jeu"])
            for e in chronologie
            if e["montant_en_jeu"] is not None
        ),
        Decimal("0"),
    )
    if not chronologie:
        statut = SYNTHESE_AUCUN
    elif nb_depassees:
        statut = SYNTHESE_DEPASSEES
    elif nb_proches:
        statut = SYNTHESE_PROCHES
    else:
        statut = SYNTHESE_A_JOUR
    dernier = chronologie[-1] if chronologie else None
    return {
        "statut": statut,
        "nb_evenements": len(chronologie),
        "nb_echeances_proches": nb_proches,
        "nb_echeances_depassees": nb_depassees,
        "montant_total_en_jeu": str(total),
        "dernier_evenement": (
            {
                "type_evenement": dernier["type_evenement"],
                "libelle": dernier["libelle"],
                "date_evenement": dernier["date_evenement"],
            }
            if dernier
            else None
        ),
    }


def referentiel_types() -> list[dict[str, Any]]:
    """PUR — référentiel des types d'événements (pour la saisie UI)."""
    return [
        {
            "type_evenement": code,
            "libelle": spec["libelle"],
            "delai": (
                f"{spec['delai_jours']} jours"
                if spec["delai_jours"] is not None
                else (
                    f"{spec['delai_mois']} mois"
                    if spec["delai_mois"] is not None
                    else None
                )
            ),
            "objet_delai": spec["objet_delai"],
            "reference": spec["reference"],
        }
        for code, spec in TYPES_EVENEMENT.items()
    ]


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurControleFiscalIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _evenements_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT id, type_evenement, date_evenement, montant_en_jeu, "
            "commentaire, cree_le "
            "FROM evenement_controle_fiscal WHERE mission_id = :m "
            "ORDER BY date_evenement, id"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def consigner_evenement(
    session: Session,
    tenant_id: int,
    mission_id: int,
    type_evenement: object,
    date_evenement: object,
    montant_en_jeu: object,
    commentaire: object,
    acteur: str,
) -> dict[str, Any]:
    """Consigne un événement de procédure — clic humain (POST).

    Type, date ou montant invalides →
    :class:`ErreurControleFiscalInvalide` (422) ; mission hors tenant →
    :class:`ErreurControleFiscalIntrouvable` (404). Journalise
    :data:`ACTION_CONSIGNATION`. Retourne l'événement enregistré avec
    son délai de riposte calculé + note consultative.
    """
    from backend.moteur.journal import append_journal

    type_ok = valider_type_evenement(type_evenement)
    date_ok = valider_date_evenement(date_evenement)
    montant = valider_montant_en_jeu(montant_en_jeu)
    commentaire_ok = str(commentaire or "").strip()
    with contexte_tenant(session, tenant_id):
        _mission_ou_404(session, mission_id)
        row = session.execute(
            text(
                "INSERT INTO evenement_controle_fiscal (tenant_id, "
                "mission_id, type_evenement, date_evenement, "
                "montant_en_jeu, commentaire) "
                "VALUES (:t, :m, :ty, :d, :mt, :c) "
                "RETURNING id, type_evenement, date_evenement, "
                "montant_en_jeu, commentaire, cree_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "ty": type_ok,
                "d": date_ok,
                "mt": montant,
                "c": commentaire_ok,
            },
        ).mappings().one()
        evenement = construire_chronologie([dict(row)], date.today())[0]
        cree = row.get("cree_le")
        evenement["cree_le"] = (
            cree.isoformat() if isinstance(cree, datetime) else None
        )
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur=acteur,
            action=ACTION_CONSIGNATION,
            charge_utile={
                "type_evenement": type_ok,
                "date_evenement": date_ok.isoformat(),
                "montant_en_jeu": (
                    str(montant) if montant is not None else None
                ),
                "echeance": evenement["delai_riposte"]["echeance"],
            },
        )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "evenement": evenement,
        "note": NOTE_CONTROLES_FISCAUX,
    }


def controles_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Chronologie + délais + synthèse de la mission — lecture seule.

    Mission hors tenant → :class:`ErreurControleFiscalIntrouvable`
    (404 côté route). Se construit toujours : sans événement, la
    chronologie est vide et ``synthese.statut="aucun_evenement"`` —
    les clés restent présentes, note consultative comprise.
    """
    jour = aujourd_hui or date.today()
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        evenements = _evenements_mission(session, mission_id)

    chronologie = construire_chronologie(evenements, jour)
    return {
        "mission_id": mission_id,
        "exercice": int(mission["exercice"]),
        "aujourd_hui": jour.isoformat(),
        "evenements": chronologie,
        "synthese": synthese_controles(chronologie),
        "types_evenement": referentiel_types(),
        "note": NOTE_CONTROLES_FISCAUX,
    }
