"""Pont consultatif matérialité / risques → programme de travail.

POURQUOI : le ciblage de matérialité (:mod:`backend.plateforme.materialite`)
désigne les comptes qui méritent une revue détaillée, et le registre des
risques (:mod:`backend.plateforme.risques`) porte les risques fiscaux
encore ouverts du contribuable — mais le programme de travail
(:mod:`backend.plateforme.programme_travail`) reste un référentiel
standard. Ce module fait le PONT : il PROPOSE des diligences
complémentaires déterministes, déduites :

a) des COMPTES CIBLÉS par le seuil de matérialité retenu, via un
   mapping documenté préfixe SYSCOHADA → diligence type de revue
   fiscale (:data:`REGLES_MAPPING`) — ex. comptes 70x ciblés → « Revue
   du chiffre d'affaires et des assiettes déclaratives (TVA/IS) »,
   44x → « Revue des comptes d'État et rapprochements déclaratifs »,
   66x/42x/43x → « Revue des rémunérations, ITS et charges sociales »,
   2x → « Revue des immobilisations, amortissements et TVA
   immobilisée »… Le préfixe le plus LONG l'emporte (70x → CA, pas
   « autres produits ») ;

b) des RISQUES NON CLOS (ouvert, en_traitement) du contribuable de la
   mission : une diligence de suivi par impôt concerné, en phase
   « suivi ».

Le fiscaliste ACCEPTE une proposition d'un clic (POST) : elle est alors
créée dans le programme de travail EXISTANT (table ``diligence_mission``)
via :func:`backend.plateforme.programme_travail.inserer_diligence` —
AUCUNE écriture automatique, uniquement sur clic. Les propositions déjà
couvertes par une diligence existante (même code — marqueur d'origine
« PRO- » — ou même libellé) sont signalées ``deja_couverte``.

DOCTRINE (pattern :mod:`backend.plateforme.materialite`) : déterministe,
AUCUN LLM, strictement CONSULTATIF — l'humain décide du programme.
Fonctions pures testables sans base (mapping, déduplication, tri) +
accès RLS via ``contexte_tenant``, 404 hors tenant, 422 saisie
invalide, journalisation ``append_journal``. Clés toujours présentes,
note consultative toujours présente.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

ORIGINE_MATERIALITE: Final = "materialite"
ORIGINE_RISQUES: Final = "risques"

# Marqueur d'origine des diligences proposées puis acceptées : leurs
# codes commencent par « PRO- » — jamais en collision avec le programme
# standard (CAD-, COL-, CTL-, RES-, SUI-).
PREFIXE_CODE_PROPOSE: Final = "PRO-"

# Mapping documenté préfixe SYSCOHADA → diligence type de revue fiscale
# (pratique française transposée au contexte ivoirien). Format :
# (prefixe_compte, code, phase, libelle). Le préfixe le plus LONG
# l'emporte pour un compte donné (ex. 70x → PRO-CA avant la règle
# générique 7x). Plusieurs préfixes peuvent pointer vers la MÊME
# diligence (66x/42x/43x → rémunérations) : dédupliquée par code.
REGLES_MAPPING: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "70", "PRO-CA", "controles",
        "Revue du chiffre d'affaires et des assiettes déclaratives "
        "(TVA/IS)",
    ),
    (
        "44", "PRO-ETAT", "controles",
        "Revue des comptes d'État et rapprochements déclaratifs",
    ),
    (
        "66", "PRO-REMU", "controles",
        "Revue des rémunérations, ITS et charges sociales",
    ),
    (
        "42", "PRO-REMU", "controles",
        "Revue des rémunérations, ITS et charges sociales",
    ),
    (
        "43", "PRO-REMU", "controles",
        "Revue des rémunérations, ITS et charges sociales",
    ),
    (
        "40", "PRO-FRS", "controles",
        "Revue des comptes fournisseurs, retenues à la source et TVA "
        "déductible",
    ),
    (
        "41", "PRO-CLI", "controles",
        "Revue des comptes clients et de l'exhaustivité de la "
        "facturation (TVA collectée)",
    ),
    (
        "4", "PRO-TIERS", "controles",
        "Revue des autres comptes de tiers et comptes courants "
        "(conventions, actes anormaux de gestion)",
    ),
    (
        "2", "PRO-IMMO", "controles",
        "Revue des immobilisations, amortissements et TVA immobilisée",
    ),
    (
        "3", "PRO-STOCK", "controles",
        "Revue des stocks et de la cohérence de la marge déclarée",
    ),
    (
        "1", "PRO-FIN", "controles",
        "Revue des capitaux, emprunts et provisions (IRC, droits "
        "d'enregistrement)",
    ),
    (
        "5", "PRO-TRESO", "controles",
        "Revue de la trésorerie et des rapprochements bancaires",
    ),
    (
        "6", "PRO-CHARGES", "controles",
        "Revue de la déductibilité des charges (IS/BIC)",
    ),
    (
        "7", "PRO-PRODUITS", "controles",
        "Revue des autres produits imposables et subventions",
    ),
)

STATUT_SEUIL_A_RETENIR: Final = "seuil_a_retenir"
STATUT_AUCUNE_PROPOSITION: Final = "aucune_proposition"
STATUT_PROPOSITIONS: Final = "propositions_disponibles"

STATUT_ACCEPTATION_CREEE: Final = "creee"
STATUT_ACCEPTATION_DEJA_COUVERTE: Final = "deja_couverte"

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_PROGRAMME_PROPOSE: Final = (
    "Programme de travail proposé consultatif : les diligences sont "
    "déduites de façon déterministe des comptes ciblés par le seuil de "
    "matérialité retenu (mapping préfixe SYSCOHADA → diligence type) "
    "et des risques non clos du contribuable. Aucune diligence n'est "
    "créée automatiquement : chaque proposition n'entre dans le "
    "programme de travail que sur acceptation explicite du fiscaliste, "
    "qui reste libre de l'ignorer — l'humain décide du programme."
)

# Codes journalisés dans le journal d'audit.
ACTION_ACCEPTATION: Final = "acceptation_diligence_proposee"
ACTION_CONSULTATION: Final = "consultation_programme_propose"


class ErreurProgrammePropose(Exception):
    """Échec du pont matérialité → programme de travail."""


class ErreurProgrammeProposeIntrouvable(ErreurProgrammePropose):
    """Mission hors périmètre du tenant — 404 côté route."""


class ErreurProgrammeProposeInvalide(ErreurProgrammePropose):
    """Saisie invalide (code de proposition inconnu…) — 422 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def regle_pour_compte(compte: str) -> tuple[str, str, str, str] | None:
    """PUR — règle de mapping applicable à un compte (ou None).

    Le préfixe le plus LONG l'emporte (70x → PRO-CA avant la règle
    générique 7x) ; à longueur égale, l'ordre de :data:`REGLES_MAPPING`
    tranche (déterministe).
    """
    compte = str(compte or "").strip()
    if not compte:
        return None
    meilleure: tuple[str, str, str, str] | None = None
    for regle in REGLES_MAPPING:
        prefixe = regle[0]
        if compte.startswith(prefixe) and (
            meilleure is None or len(prefixe) > len(meilleure[0])
        ):
            meilleure = regle
    return meilleure


def proposer_depuis_comptes(
    cibles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — propositions de diligences depuis les comptes ciblés.

    ``cibles`` : comptes ciblés par la matérialité (clés ``compte``,
    ``libelle``). Une proposition par diligence type (dédupliquée par
    code — 7011 et 7071 ciblés → une seule « Revue du chiffre
    d'affaires »), portant la liste des comptes qui la justifient.
    Tri : ordre d'apparition des règles dans :data:`REGLES_MAPPING`.
    """
    par_code: dict[str, dict[str, Any]] = {}
    for cible in cibles:
        compte = str(cible.get("compte") or "").strip()
        regle = regle_pour_compte(compte)
        if regle is None:
            continue
        _, code, phase, libelle = regle
        proposition = par_code.setdefault(
            code,
            {
                "code": code,
                "phase": phase,
                "libelle": libelle,
                "origine": ORIGINE_MATERIALITE,
                "comptes": [],
                "justification": "",
            },
        )
        if compte not in proposition["comptes"]:
            proposition["comptes"].append(compte)

    ordre = {code: i for i, (_, code, _, _) in enumerate(REGLES_MAPPING)}
    propositions = sorted(
        par_code.values(), key=lambda p: ordre.get(p["code"], 999)
    )
    for p in propositions:
        nb = len(p["comptes"])
        p["justification"] = (
            f"Compte{'s' if nb > 1 else ''} ciblé"
            f"{'s' if nb > 1 else ''} par le seuil de matérialité : "
            + ", ".join(p["comptes"])
        )
    return propositions


def _code_impot(impot: str) -> str:
    """PUR — suffixe de code sûr depuis un impôt (« ITS » → ITS)."""
    nettoye = re.sub(r"[^A-Z0-9]+", "", str(impot or "").upper())
    return nettoye or "AUTRE"


def proposer_depuis_risques(
    risques: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — propositions de suivi depuis les risques non clos.

    ``risques`` : lignes ``{impot, libelle, statut}`` du registre des
    risques (statuts ouvert / en_traitement uniquement — filtrés en
    amont). Une proposition PAR IMPÔT concerné (phase « suivi »), la
    justification liste les libellés de risques (tronqués). Tri par
    impôt (stable).
    """
    par_impot: dict[str, list[str]] = {}
    for r in risques:
        impot = str(r.get("impot") or "").strip().upper()
        if not impot:
            continue
        libelle = str(r.get("libelle") or "").strip()
        par_impot.setdefault(impot, [])
        if libelle:
            par_impot[impot].append(libelle)

    propositions: list[dict[str, Any]] = []
    for impot in sorted(par_impot):
        libelles = par_impot[impot]
        nb = len(libelles)
        detail = " ; ".join(
            (li if len(li) <= 80 else li[:77] + "…") for li in libelles[:3]
        )
        propositions.append(
            {
                "code": f"PRO-RSQ-{_code_impot(impot)}",
                "phase": "suivi",
                "libelle": (
                    "Revue du traitement des risques ouverts — " + impot
                ),
                "origine": ORIGINE_RISQUES,
                "comptes": [],
                "justification": (
                    f"{nb} risque{'s' if nb > 1 else ''} non clos au "
                    f"registre ({impot})" + (f" : {detail}" if detail else "")
                ),
            }
        )
    return propositions


def _normaliser_libelle(libelle: str) -> str:
    """PUR — libellé normalisé pour la déduplication (casse, espaces)."""
    return " ".join(str(libelle or "").split()).casefold()


def marquer_deja_couvertes(
    propositions: list[dict[str, Any]],
    existantes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — signale les propositions déjà couvertes par le programme.

    ``existantes`` : diligences déjà présentes dans le programme de
    travail (clés ``code``, ``libelle``). Une proposition est
    ``deja_couverte`` si une diligence existante porte le MÊME CODE
    (marqueur d'origine « PRO-… » d'une acceptation antérieure) ou le
    MÊME LIBELLÉ (normalisé). Retourne de NOUVELLES listes (aucune
    mutation des entrées).
    """
    codes = {str(d.get("code") or "").strip() for d in existantes}
    libelles = {
        _normaliser_libelle(str(d.get("libelle") or ""))
        for d in existantes
    }
    marquees: list[dict[str, Any]] = []
    for p in propositions:
        couverte = (
            p["code"] in codes
            or _normaliser_libelle(p["libelle"]) in libelles
        )
        marquees.append({**p, "deja_couverte": couverte})
    return marquees


def construire_vue_programme_propose(
    cibles: list[dict[str, Any]],
    risques: list[dict[str, Any]],
    existantes: list[dict[str, Any]],
    seuil_retenu: str | None,
) -> dict[str, Any]:
    """PUR — vue complète du programme proposé, clés TOUJOURS présentes.

    ``seuil_retenu`` : montant retenu (str) ou ``None`` si le
    fiscaliste n'a pas encore arrêté de seuil — les propositions issues
    de la matérialité sont alors vides (statut ``seuil_a_retenir``),
    celles issues des risques restent visibles.
    """
    propositions = marquer_deja_couvertes(
        proposer_depuis_comptes(cibles) + proposer_depuis_risques(risques),
        existantes,
    )
    a_proposer = [p for p in propositions if not p["deja_couverte"]]
    if seuil_retenu is None:
        statut = STATUT_SEUIL_A_RETENIR
    elif not propositions:
        statut = STATUT_AUCUNE_PROPOSITION
    else:
        statut = STATUT_PROPOSITIONS
    return {
        "seuil_retenu": seuil_retenu,
        "propositions": propositions,
        "synthese": {
            "statut": statut,
            "nb_propositions": len(propositions),
            "nb_deja_couvertes": len(propositions) - len(a_proposer),
            "nb_a_accepter": len(a_proposer),
        },
        "note": NOTE_PROGRAMME_PROPOSE,
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text(
            "SELECT id, exercice, contribuable_id "
            "FROM mission WHERE id = :m"
        ),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurProgrammeProposeIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _risques_non_clos(
    session: Session, contribuable_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT impot, libelle, statut FROM risque "
            "WHERE contribuable_id = :c "
            "AND statut IN ('ouvert', 'en_traitement') "
            "ORDER BY impot, id"
        ),
        {"c": contribuable_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _diligences_existantes(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT code, libelle FROM diligence_mission "
            "WHERE mission_id = :m ORDER BY code"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _cibles_et_seuil(
    session: Session, mission_id: int
) -> tuple[list[dict[str, Any]], str | None]:
    """Comptes ciblés + seuil retenu — réutilise le module matérialité."""
    from backend.plateforme.materialite import (
        _seuil_retenu_mission,
        _soldes_mission,
        cibler_comptes,
    )

    seuil = _seuil_retenu_mission(session, mission_id)
    if seuil is None:
        return [], None
    montant = Decimal(str(seuil["seuil_retenu"]))
    soldes = _soldes_mission(session, mission_id)
    cibles = cibler_comptes(soldes, montant)
    return cibles, str(seuil["seuil_retenu"])


def programme_propose_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Programme de travail proposé de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurProgrammeProposeIntrouvable`
    (404 côté route). Se construit toujours : sans seuil retenu, les
    propositions matérialité sont vides (``statut=seuil_a_retenir``) —
    les clés restent présentes. AUCUNE écriture.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        cibles, seuil = _cibles_et_seuil(session, mission_id)
        risques = _risques_non_clos(
            session, int(mission["contribuable_id"])
        )
        existantes = _diligences_existantes(session, mission_id)

    vue = construire_vue_programme_propose(
        cibles, risques, existantes, seuil
    )
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    return vue


def accepter_proposition(
    session: Session,
    tenant_id: int,
    mission_id: int,
    code: object,
    acteur: str,
) -> dict[str, Any]:
    """Accepte UNE proposition — clic humain, seule écriture du module.

    Recalcule les propositions courantes puis crée la diligence dans le
    programme de travail existant via
    :func:`backend.plateforme.programme_travail.inserer_diligence`
    (aucune insertion dupliquée ici). Code hors des propositions
    courantes → :class:`ErreurProgrammeProposeInvalide` (422) ;
    proposition déjà couverte → ``statut="deja_couverte"`` sans
    écriture (idempotent). Mission hors tenant → 404. Journalise
    :data:`ACTION_ACCEPTATION` à la création.
    """
    from backend.moteur.journal import append_journal
    from backend.plateforme.programme_travail import inserer_diligence

    code_ok = str(code or "").strip()
    if not code_ok:
        raise ErreurProgrammeProposeInvalide(
            "code de proposition requis (ex. PRO-CA)"
        )

    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        cibles, seuil = _cibles_et_seuil(session, mission_id)
        risques = _risques_non_clos(
            session, int(mission["contribuable_id"])
        )
        existantes = _diligences_existantes(session, mission_id)
        vue = construire_vue_programme_propose(
            cibles, risques, existantes, seuil
        )
        par_code = {p["code"]: p for p in vue["propositions"]}
        proposition = par_code.get(code_ok)
        if proposition is None:
            raise ErreurProgrammeProposeInvalide(
                f"proposition inconnue « {code_ok} » — propositions "
                "courantes : "
                + (", ".join(sorted(par_code)) or "aucune")
            )

        if proposition["deja_couverte"]:
            statut = STATUT_ACCEPTATION_DEJA_COUVERTE
        else:
            creee = inserer_diligence(
                session,
                tenant_id,
                mission_id,
                proposition["phase"],
                proposition["code"],
                proposition["libelle"],
            )
            statut = (
                STATUT_ACCEPTATION_CREEE
                if creee
                else STATUT_ACCEPTATION_DEJA_COUVERTE
            )
            if creee:
                append_journal(
                    session,
                    tenant_id=tenant_id,
                    mission_id=mission_id,
                    acteur=acteur,
                    action=ACTION_ACCEPTATION,
                    charge_utile={
                        "code": proposition["code"],
                        "phase": proposition["phase"],
                        "libelle": proposition["libelle"],
                        "origine": proposition["origine"],
                    },
                )
    # Pas de commit ici : get_session committe en fin de requête.
    return {
        "mission_id": mission_id,
        "statut": statut,
        "diligence": {
            "code": proposition["code"],
            "phase": proposition["phase"],
            "libelle": proposition["libelle"],
            "origine": proposition["origine"],
        },
        "note": NOTE_PROGRAMME_PROPOSE,
    }
