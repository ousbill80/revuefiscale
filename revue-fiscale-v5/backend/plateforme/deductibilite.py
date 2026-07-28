"""Revue de déductibilité des charges — points de vigilance IS.

POURQUOI : lors d'une revue fiscale ivoirienne, l'auditeur balaye les
comptes de charges (classe 6 SYSCOHADA) pour repérer les postes qui
appellent une analyse de DÉDUCTIBILITÉ au regard de l'impôt BIC/IS
(CGI ivoirien, art. 18 principalement). Ce module LECTURE SEULE
rapproche chaque compte de charge de la balance importée
(``solde_compte``) d'un RÉFÉRENTIEL DÉTERMINISTE de règles fiscales
(préfixe de compte → point de vigilance) et restitue, par règle, les
comptes concernés, leur solde et la règle résumée en français.

AUCUN calcul de réintégration automatique : les montants signalés sont
les SOLDES COMPTABLES concernés — la fraction à réintégrer relève de
l'appréciation du fiscaliste (bénéficiaire réel, plafonds, caractère
professionnel…). Trois gravités documentent la nature du point :

- ``non_deductible`` : exclusion de principe (ex. amendes, art. 18 F) ;
- ``plafond`` : déductibilité plafonnée (ex. frais de siège 18 A 3°) ;
- ``appreciation`` : déductibilité conditionnelle à apprécier (ex.
  provisions 18 E 1°, rémunérations 18 A 1°).

RATTACHEMENT DÉTERMINISTE : un compte est rattaché à la règle portant
le PRÉFIXE LE PLUS LONG qui le matche (ex. 6257 → cadeaux, pas 625
assurances) — un compte alimente au plus un point de vigilance.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — le
repérage éclaire la revue, l'humain apprécie et décide. Fonctions
pures testables sans base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.materialite`). Montants sérialisés en ``str``
(Decimal). Contrat stable : clés toujours présentes, note consultative
toujours présente, ``disponible=false`` sans balance. AUCUNE écriture,
AUCUNE migration — la consultation est journalisée par la route.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

GRAVITE_NON_DEDUCTIBLE: Final = "non_deductible"
GRAVITE_PLAFOND: Final = "plafond"
GRAVITE_APPRECIATION: Final = "appreciation"

# Ordre de restitution des gravités (du plus tranché au plus ouvert).
ORDRE_GRAVITES: Final[tuple[str, ...]] = (
    GRAVITE_NON_DEDUCTIBLE,
    GRAVITE_PLAFOND,
    GRAVITE_APPRECIATION,
)

LIBELLES_GRAVITES: Final[dict[str, str]] = {
    GRAVITE_NON_DEDUCTIBLE: "Non déductible par principe",
    GRAVITE_PLAFOND: "Déductibilité plafonnée",
    GRAVITE_APPRECIATION: "Déductibilité à apprécier",
}

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_AUCUN_POINT: Final = "aucun_point"
STATUT_POINTS_A_APPRECIER: Final = "points_a_apprecier"

# Référentiel déterministe des points de vigilance de réintégration
# fiscale IS (CGI ivoirien, art. 18 principalement). Chaque règle :
# code stable, préfixes de comptes SYSCOHADA déclencheurs (cohérents
# avec le référentiel de règles du moteur), libellé du point, règle
# fiscale résumée en français, gravité. AUCUN taux appliqué ici : le
# module repère, l'humain apprécie.
REGLES_DEDUCTIBILITE: Final[tuple[dict[str, Any], ...]] = (
    {
        "code": "amendes_penalites",
        "prefixes": ("6461", "647", "648", "6580"),
        "libelle": "Amendes, pénalités et sanctions",
        "regle": (
            "Les amendes, pénalités et sanctions de toute nature "
            "(fiscales, sociales, douanières, contraventions) sont "
            "exclues des charges déductibles — réintégration "
            "intégrale (CGI, art. 18 F)."
        ),
        "gravite": GRAVITE_NON_DEDUCTIBLE,
    },
    {
        "code": "cadeaux_clientele",
        "prefixes": ("6234", "6238", "6257", "6583"),
        "libelle": "Cadeaux, objets publicitaires et pourboires",
        "regle": (
            "Les cadeaux et objets spécialement conçus pour la "
            "publicité ne sont déductibles que s'ils présentent un "
            "caractère professionnel et une valeur unitaire modique — "
            "au-delà, réintégration de la fraction non justifiée "
            "(CGI, art. 18 E)."
        ),
        "gravite": GRAVITE_PLAFOND,
    },
    {
        "code": "dons_liberalites",
        "prefixes": ("6581", "6582"),
        "libelle": "Dons, libéralités et mécénat",
        "regle": (
            "Les libéralités ne sont pas déductibles par principe ; "
            "les dons et le mécénat ne sont admis qu'au profit "
            "d'organismes limitativement visés et dans un plafond "
            "assis sur le chiffre d'affaires (CGI, art. 18 G) — "
            "vérifier l'agrément du bénéficiaire et le plafond."
        ),
        "gravite": GRAVITE_PLAFOND,
    },
    {
        "code": "assurances",
        "prefixes": ("625",),
        "libelle": "Primes d'assurance",
        "regle": (
            "Les primes sont déductibles si le risque couvert est "
            "celui de l'entreprise ; les assurances-vie souscrites au "
            "profit de dirigeants, d'associés ou de tiers ne le sont "
            "pas — analyse du bénéficiaire effectif du contrat (CGI, "
            "art. 18)."
        ),
        "gravite": GRAVITE_APPRECIATION,
    },
    {
        "code": "loyers",
        "prefixes": ("622", "623"),
        "libelle": "Loyers, locations et redevances",
        "regle": (
            "Les loyers sont déductibles dans la limite de la valeur "
            "locative normale des biens loués ; la fraction excessive "
            "— notamment envers des parties liées — est réintégrée "
            "(CGI, art. 18 A 2°). Les redevances versées à des "
            "entreprises liées s'apprécient au regard du service rendu."
        ),
        "gravite": GRAVITE_APPRECIATION,
    },
    {
        "code": "frais_siege",
        "prefixes": ("631", "632", "634"),
        "libelle": "Frais de siège et d'assistance technique",
        "regle": (
            "Les frais de siège, d'études et d'assistance technique "
            "versés hors de Côte d'Ivoire sont déductibles dans la "
            "double limite de 5 % du chiffre d'affaires et de 20 % "
            "des frais généraux — l'excédent est réintégré (CGI, "
            "art. 18 A 3°)."
        ),
        "gravite": GRAVITE_PLAFOND,
    },
    {
        "code": "impots_taxes",
        "prefixes": ("641",),
        "libelle": "Impôts et taxes",
        "regle": (
            "L'impôt BIC lui-même et certains impôts (dont l'IRVM et "
            "les impôts supportés pour le compte de tiers) ne sont "
            "pas déductibles — ventiler le compte pour isoler les "
            "impôts exclus (CGI, art. 18 D)."
        ),
        "gravite": GRAVITE_APPRECIATION,
    },
    {
        "code": "remunerations",
        "prefixes": ("661", "663", "664", "667"),
        "libelle": "Rémunérations et charges de personnel",
        "regle": (
            "Les rémunérations ne sont déductibles que si elles "
            "correspondent à un travail effectif et ne sont pas "
            "excessives eu égard au service rendu — la fraction "
            "fictive ou excessive est réintégrée ; vigilance "
            "particulière sur les dirigeants, associés et personnels "
            "expatriés (CGI, art. 18 A 1°)."
        ),
        "gravite": GRAVITE_APPRECIATION,
    },
    {
        "code": "interets_comptes_courants",
        "prefixes": ("671", "672", "674"),
        "libelle": (
            "Charges financières et intérêts de comptes courants "
            "d'associés"
        ),
        "regle": (
            "Les intérêts servis aux associés à raison des sommes "
            "laissées en compte courant ne sont déductibles que si le "
            "capital est entièrement libéré et dans la limite du taux "
            "BCEAO majoré de deux points — l'excédent est réintégré "
            "(CGI, art. 18 A 6°)."
        ),
        "gravite": GRAVITE_PLAFOND,
    },
    {
        "code": "amortissements",
        "prefixes": ("681",),
        "libelle": "Dotations aux amortissements",
        "regle": (
            "Les amortissements sont admis dans la limite des durées "
            "d'usage ; les véhicules de tourisme sont plafonnés — la "
            "fraction excédentaire est réintégrée (réintégration "
            "temporaire ou définitive selon le cas, CGI, art. 18 B)."
        ),
        "gravite": GRAVITE_APPRECIATION,
    },
    {
        "code": "provisions",
        "prefixes": ("691", "6594"),
        "libelle": "Dotations aux provisions et créances douteuses",
        "regle": (
            "Les provisions ne sont déductibles que si elles sont "
            "nettement précisées, individualisées, probables et "
            "portées au relevé spécial des provisions — les "
            "provisions forfaitaires sont réintégrées (CGI, art. 18 "
            "E 1°)."
        ),
        "gravite": GRAVITE_APPRECIATION,
    },
)

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_DEDUCTIBILITE: Final = (
    "Revue de déductibilité consultative : les points de vigilance "
    "sont repérés de façon déterministe depuis la balance (préfixes "
    "de comptes de charges, classe 6 SYSCOHADA) au regard du CGI "
    "ivoirien (art. 18 notamment). Les soldes signalés sont les "
    "soldes comptables concernés — AUCUNE réintégration n'est "
    "calculée automatiquement : la fraction non déductible relève de "
    "l'appréciation du fiscaliste, l'humain décide."
)

# Code journalisé dans le journal d'audit (consultation).
ACTION_CONSULTATION: Final = "consultation_deductibilite"


class ErreurDeductibilite(Exception):
    """Échec de la revue de déductibilité."""


class ErreurDeductibiliteIntrouvable(ErreurDeductibilite):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def _solde_signe(ligne: dict[str, Any]) -> Decimal:
    """PUR — solde signé débit - crédit d'une ligne de balance."""
    debit = Decimal(str(ligne.get("debit") or 0))
    credit = Decimal(str(ligne.get("credit") or 0))
    return debit - credit


def regle_pour_compte(compte: str) -> dict[str, Any] | None:
    """PUR — règle du référentiel rattachée à un compte de charge.

    Rattachement déterministe au PRÉFIXE LE PLUS LONG qui matche
    (ex. ``6257`` → cadeaux et non assurances ``625``). ``None`` si
    aucun préfixe du référentiel ne matche ou si le compte n'est pas
    en classe 6.
    """
    compte = str(compte or "").strip()
    if not compte.startswith("6"):
        return None
    meilleur: dict[str, Any] | None = None
    longueur = -1
    for regle in REGLES_DEDUCTIBILITE:
        for prefixe in regle["prefixes"]:
            if compte.startswith(prefixe) and len(prefixe) > longueur:
                meilleur = regle
                longueur = len(prefixe)
    return meilleur


def balayer_charges(
    soldes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """PUR — points de vigilance depuis les lignes de balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Seuls les comptes de classe 6 à solde
    signé NON NUL alimentent un point. Retourne UN point par règle
    déclenchée : comptes concernés (triés), total des soldes
    (:class:`Decimal`) — tri stable : gravité (non_deductible,
    plafond, appreciation) puis code de règle.
    """
    par_code: dict[str, dict[str, Any]] = {}
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte:
            continue
        solde = _solde_signe(ligne)
        if solde == 0:
            continue
        regle = regle_pour_compte(compte)
        if regle is None:
            continue
        point = par_code.setdefault(
            regle["code"],
            {
                "code": regle["code"],
                "libelle": regle["libelle"],
                "regle": regle["regle"],
                "gravite": regle["gravite"],
                "prefixes": list(regle["prefixes"]),
                "comptes": [],
                "total_solde": Decimal("0"),
            },
        )
        point["comptes"].append(
            {
                "compte": compte,
                "libelle": str(ligne.get("libelle") or ""),
                "solde": solde,
            }
        )
        point["total_solde"] += solde

    for point in par_code.values():
        point["comptes"].sort(key=lambda c: c["compte"])
        point["nb_comptes"] = len(point["comptes"])

    rang_gravite = {g: i for i, g in enumerate(ORDRE_GRAVITES)}
    return sorted(
        par_code.values(),
        key=lambda p: (rang_gravite[p["gravite"]], p["code"]),
    )


def synthese_points(
    soldes: list[dict[str, Any]], points: list[dict[str, Any]]
) -> dict[str, Any]:
    """PUR — synthèse de la revue (comptages et masses, Decimal).

    ``nb_par_gravite`` porte TOUJOURS les trois gravités (0 si
    absente). ``total_soldes_concernes`` = somme des totaux des
    points ; ``total_charges`` = somme des soldes signés de la
    classe 6 (assiette de comparaison).
    """
    nb_par_gravite = {g: 0 for g in ORDRE_GRAVITES}
    total_concerne = Decimal("0")
    for point in points:
        nb_par_gravite[point["gravite"]] += 1
        total_concerne += point["total_solde"]

    total_charges = Decimal("0")
    nb_comptes_charges = 0
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte.startswith("6"):
            continue
        nb_comptes_charges += 1
        total_charges += _solde_signe(ligne)

    return {
        "nb_points": len(points),
        "nb_par_gravite": nb_par_gravite,
        "total_soldes_concernes": total_concerne,
        "nb_comptes_charges": nb_comptes_charges,
        "total_charges": total_charges,
    }


def construire_vue_deductibilite(
    soldes: list[dict[str, Any]]
) -> dict[str, Any]:
    """PUR — vue complète de la revue de déductibilité (montants str).

    Clés TOUJOURS présentes ; ``disponible`` vrai seulement si la
    balance porte au moins un compte. Le référentiel complet est
    restitué (transparence de la doctrine appliquée), les points ne
    portent que les règles déclenchées.
    """
    disponible = bool(soldes)
    points = balayer_charges(soldes) if disponible else []
    synthese = synthese_points(soldes, points)

    if not disponible:
        statut = STATUT_INDISPONIBLE
    elif not points:
        statut = STATUT_AUCUN_POINT
    else:
        statut = STATUT_POINTS_A_APPRECIER

    return {
        "disponible": disponible,
        "points": [
            {
                "code": p["code"],
                "libelle": p["libelle"],
                "regle": p["regle"],
                "gravite": p["gravite"],
                "gravite_libelle": LIBELLES_GRAVITES[p["gravite"]],
                "prefixes": p["prefixes"],
                "nb_comptes": p["nb_comptes"],
                "total_solde": str(p["total_solde"]),
                "comptes": [
                    {
                        "compte": c["compte"],
                        "libelle": c["libelle"],
                        "solde": str(c["solde"]),
                    }
                    for c in p["comptes"]
                ],
            }
            for p in points
        ],
        "referentiel": [
            {
                "code": r["code"],
                "libelle": r["libelle"],
                "regle": r["regle"],
                "gravite": r["gravite"],
                "gravite_libelle": LIBELLES_GRAVITES[r["gravite"]],
                "prefixes": list(r["prefixes"]),
            }
            for r in REGLES_DEDUCTIBILITE
        ],
        "synthese": {
            "statut": statut,
            "nb_points": synthese["nb_points"],
            "nb_par_gravite": dict(synthese["nb_par_gravite"]),
            "total_soldes_concernes": str(
                synthese["total_soldes_concernes"]
            ),
            "nb_comptes_charges": synthese["nb_comptes_charges"],
            "total_charges": str(synthese["total_charges"]),
        },
        "note": NOTE_DEDUCTIBILITE,
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurDeductibiliteIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _soldes_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m ORDER BY compte"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def deductibilite_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Revue de déductibilité de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurDeductibiliteIntrouvable`
    (404 côté route). Se construit toujours : sans balance importée,
    ``disponible=false`` et ``synthese.statut="indisponible"`` — les
    clés restent présentes. AUCUNE écriture.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        soldes = _soldes_mission(session, mission_id)

    vue = construire_vue_deductibilite(soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
