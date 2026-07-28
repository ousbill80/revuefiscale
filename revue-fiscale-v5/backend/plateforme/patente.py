"""Estimation consultative de la contribution des patentes — CGI ivoirien.

POURQUOI : lors de la revue, le fiscaliste ivoirien vérifie la
cohérence de la patente déclarée par la mission (CGI, art. 264 et
suivants). La contribution des patentes se compose de DEUX droits :
le droit sur le chiffre d'affaires et le droit sur la valeur
locative des locaux professionnels. Le présent module estime le
PREMIER depuis la balance et SIGNALE — sans jamais l'inventer — que
le second n'est pas calculable depuis la seule balance.

APPROXIMATION ASSUMÉE (documentée) : le droit sur le chiffre
d'affaires est estimé à :data:`TAUX_DROIT_CA` (0,5 %) du chiffre
d'affaires lu dans les comptes 70x de la balance (ventes et produits
d'activité), borné par le plancher :data:`PLANCHER_DROIT_CA_FCFA`
(300 000 FCFA) et le plafond indicatif
:data:`PLAFOND_DROIT_CA_INDICATIF_FCFA`. Le CGI prévoit des taux,
minima et maxima PARTICULIERS selon les professions, communes et
régimes (stations-service, transporteurs, marchands forains…) que
seule l'appréciation humaine sait appliquer — l'estimation reste un
ordre de grandeur au régime général.

DROIT SUR LA VALEUR LOCATIVE : assis sur la valeur locative des
locaux professionnels (CGI, art. 275 et s.), donnée ABSENTE de la
balance comptable — il est restitué ``calculable: false`` avec un
motif explicite, JAMAIS estimé ni inventé. L'estimation totale est
donc PARTIELLE et le nom de la clé l'assume
(``estimation_totale_partielle``).

DONNÉES : lecture seule de ``solde_compte`` (comptes 70x) — AUCUNE
table nouvelle, AUCUNE migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF —
l'estimation éclaire la vérification de la patente, l'humain décide.
Fonctions pures testables sans base + accès RLS via
``contexte_tenant`` (pattern :mod:`backend.plateforme.resultat_fiscal`).
Montants sérialisés en ``str`` (Decimal). Contrat stable : clés
toujours présentes, note consultative toujours présente.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

# Préfixe SYSCOHADA du chiffre d'affaires lu dans la balance —
# comptes 70x (ventes de marchandises, produits fabriqués, travaux,
# services…). Les autres produits (71x subventions, 77x financiers…)
# sont exclus de l'assiette estimée (choix documenté, approximation).
PREFIXE_CHIFFRE_AFFAIRES: Final = "70"

# Droit sur le chiffre d'affaires (CGI, art. 274) — taux général de
# 0,5 % du chiffre d'affaires ou des recettes de l'exercice.
TAUX_DROIT_CA: Final = Decimal("0.005")

# Plancher du droit sur le chiffre d'affaires (CGI, art. 274) :
# le droit ne peut être inférieur à 300 000 FCFA.
PLANCHER_DROIT_CA_FCFA: Final = Decimal("300000")

# Plafond INDICATIF du droit sur le chiffre d'affaires (ordre de
# grandeur CGI, art. 274 — le maximum de perception varie selon les
# professions et situations) : sert à borner l'estimation, jamais à
# liquider.
PLAFOND_DROIT_CA_INDICATIF_FCFA: Final = Decimal("3000000")

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_ESTIMEE: Final = "estimation_partielle"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Estimation indisponible — importez la balance (comptes 70x)"
    ),
    STATUT_ESTIMEE: (
        "Estimation partielle (droit sur le chiffre d'affaires seul)"
    ),
}

# Motif restitué pour le droit sur la valeur locative — JAMAIS
# calculé depuis la balance, jamais inventé.
MOTIF_VALEUR_LOCATIVE_NON_CALCULABLE: Final = (
    "Le droit sur la valeur locative (CGI, art. 275 et s.) est assis "
    "sur la valeur locative des locaux professionnels, donnée absente "
    "de la balance comptable — il n'est pas estimé ici : le "
    "fiscaliste l'apprécie depuis les baux, la déclaration foncière "
    "ou l'évaluation administrative."
)

# Références CGI restituées — TOUJOURS présentes (approximations
# documentées, à vérifier par le fiscaliste sur le CGI en vigueur).
REFERENCES_PATENTE: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, art. 264 et s.",
        "portee": (
            "Contribution des patentes — droit sur le chiffre "
            "d'affaires et droit sur la valeur locative"
        ),
    },
    {
        "reference": "CGI, art. 274",
        "portee": (
            "Droit sur le chiffre d'affaires : 0,5 % du chiffre "
            "d'affaires, minimum 300 000 FCFA, maximum de perception "
            "selon les professions (plafond indicatif retenu ici)"
        ),
    },
    {
        "reference": "CGI, art. 275 et s.",
        "portee": (
            "Droit sur la valeur locative des locaux professionnels — "
            "non calculable depuis la balance"
        ),
    },
)

# Note consultative — TOUJOURS présente dans les réponses.
NOTE_PATENTE: Final = (
    "Estimation consultative de la contribution des patentes (CGI, "
    "art. 264 et s.) : droit sur le chiffre d'affaires approché à "
    "0,5 % du chiffre d'affaires des comptes 70x de la balance, "
    "borné par le plancher de 300 000 FCFA et un plafond indicatif — "
    "les taux, minima et maxima particuliers (professions, communes, "
    "régimes) ne sont pas appliqués. Le droit sur la valeur locative "
    "n'est pas calculable depuis la balance et n'est jamais estimé : "
    "l'estimation totale est partielle. L'humain liquide, apprécie "
    "et décide."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_patente"


class ErreurPatente(Exception):
    """Échec de l'estimation de la patente."""


class ErreurPatenteIntrouvable(ErreurPatente):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def arrondir_franc(montant: Decimal) -> Decimal:
    """PUR — arrondi au franc CFA (entier, ROUND_HALF_UP)."""
    return montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def extraire_chiffre_affaires(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — chiffre d'affaires depuis les comptes 70x de la balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :

    - ``chiffre_affaires`` : soldes créditeurs nets des comptes 70x ;
    - ``comptes`` : détail par compte (solde créditeur net signé) ;
    - ``nb_comptes_ca`` : nombre de comptes 70x lus ;
    - ``disponible`` : vrai si au moins un compte 70x existe.
    """
    total = Decimal("0")
    comptes: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte.startswith(PREFIXE_CHIFFRE_AFFAIRES):
            continue
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        solde = credit - debit
        total += solde
        comptes.append(
            {
                "compte": compte,
                "libelle": str(ligne.get("libelle") or ""),
                "solde": solde,
            }
        )
    return {
        "chiffre_affaires": total,
        "comptes": comptes,
        "nb_comptes_ca": len(comptes),
        "disponible": bool(comptes),
    }


def calculer_droit_chiffre_affaires(
    chiffre_affaires: Decimal,
    taux: Decimal = TAUX_DROIT_CA,
    plancher: Decimal = PLANCHER_DROIT_CA_FCFA,
    plafond: Decimal = PLAFOND_DROIT_CA_INDICATIF_FCFA,
) -> dict[str, Any]:
    """PUR — droit sur le chiffre d'affaires borné plancher/plafond.

    Déterministe : droit théorique = ``taux`` × chiffre d'affaires
    (négatif ramené à 0), arrondi au franc, puis borné par le
    ``plancher`` (300 000 FCFA — appliqué aussi quand le CA est nul
    ou négatif) et le ``plafond`` indicatif. Retourne les Decimal
    ``droit_theorique``, ``droit_retenu`` et les booléens
    ``plancher_applique`` / ``plafond_applique``.
    """
    assiette = max(chiffre_affaires, Decimal("0"))
    droit_theorique = arrondir_franc(assiette * taux)
    plancher_applique = droit_theorique < plancher
    droit_retenu = max(droit_theorique, plancher)
    plafond_applique = droit_retenu > plafond
    if plafond_applique:
        droit_retenu = plafond
    return {
        "droit_theorique": droit_theorique,
        "droit_retenu": droit_retenu,
        "plancher_applique": plancher_applique,
        "plafond_applique": plafond_applique,
    }


def calculer_estimation_patente(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — estimation consultative de la patente depuis la balance.

    ``soldes`` : lignes de balance ``{compte, libelle, debit,
    credit}``. Montants restitués en ``str`` (Decimal). Clés TOUJOURS
    présentes ; ``disponible`` est vrai seulement si la balance porte
    au moins un compte 70x — sans lui, rien n'est chiffré (aucun
    montant inventé).

    Le droit sur la valeur locative est TOUJOURS restitué
    ``calculable: false`` avec son motif : l'estimation totale est
    partielle (droit sur le chiffre d'affaires seul).
    """
    ca = extraire_chiffre_affaires(soldes)
    disponible = bool(ca["disponible"])

    if disponible:
        droit = calculer_droit_chiffre_affaires(ca["chiffre_affaires"])
        droit_ca = droit["droit_retenu"]
        plancher_applique = bool(droit["plancher_applique"])
        plafond_applique = bool(droit["plafond_applique"])
        statut = STATUT_ESTIMEE
    else:
        droit_ca = Decimal("0")
        plancher_applique = False
        plafond_applique = False
        statut = STATUT_INDISPONIBLE

    return {
        "disponible": disponible,
        "chiffre_affaires": str(ca["chiffre_affaires"]),
        "comptes_ca": [
            {
                "compte": c["compte"],
                "libelle": c["libelle"],
                "solde": str(c["solde"]),
            }
            for c in ca["comptes"]
        ],
        "taux": str(TAUX_DROIT_CA),
        "droit_chiffre_affaires": str(droit_ca),
        "plancher_applique": plancher_applique,
        "plafond_applique": plafond_applique,
        "plancher_fcfa": str(PLANCHER_DROIT_CA_FCFA),
        "plafond_indicatif_fcfa": str(PLAFOND_DROIT_CA_INDICATIF_FCFA),
        "droit_valeur_locative": {
            "calculable": False,
            "motif": MOTIF_VALEUR_LOCATIVE_NON_CALCULABLE,
        },
        "estimation_totale_partielle": str(droit_ca),
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_comptes_ca": int(ca["nb_comptes_ca"]),
            "plancher_applique": plancher_applique,
            "plafond_applique": plafond_applique,
        },
        "note": NOTE_PATENTE,
        "references": [dict(r) for r in REFERENCES_PATENTE],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurPatenteIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _soldes_ca_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND compte LIKE :p ORDER BY compte"
        ),
        {"m": mission_id, "p": PREFIXE_CHIFFRE_AFFAIRES + "%"},
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_patente_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Estimation de la patente de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurPatenteIntrouvable` (404 côté
    route). Se construit toujours : sans balance (aucun compte 70x),
    ``disponible=false`` et ``synthese.statut="indisponible"`` — les
    clés restent présentes, aucun montant inventé. Tolérance par
    bloc : un échec de lecture de la balance dégrade en
    ``disponible=false`` au lieu de faire échouer la vue.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        try:
            soldes = _soldes_ca_mission(session, mission_id)
        except Exception:
            # Tolérance par bloc : balance illisible → estimation
            # indisponible, la vue reste servie (clés stables).
            soldes = []

    vue = calculer_estimation_patente(soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
