"""Retenue à la source sur honoraires — vue consultative depuis la balance.

POURQUOI : lors de la revue, le fiscaliste vérifie que les honoraires,
commissions et courtages versés par la mission à des prestataires
(conseils, intermédiaires…) ont bien supporté, le cas échéant, la
retenue à la source sur les rémunérations versées à des tiers que le
débiteur doit précompter pour le compte du prestataire. Le présent
module lit les rémunérations d'intermédiaires et de conseils (comptes
632x SYSCOHADA) de la balance et restitue un ORDRE DE GRANDEUR de la
retenue théorique MAXIMALE, jamais une liquidation.

LIMITE STRUCTURELLE ASSUMÉE (documentée) : la retenue dépend du RÉGIME
DU PRESTATAIRE (résident ou non-résident, immatriculé ou non, régime
d'imposition, conventions fiscales…), donnée ABSENTE de la balance
comptable. Le taux courant :data:`TAUX_RETENUE_HONORAIRES` (7,5 %,
prestataires résidents non immatriculés) n'est dû que sur les sommes
versées à certains prestataires : le montant restitué est donc un
MAXIMUM théorique indicatif calculé comme si TOUTES les sommes y
étaient soumises. Le taux varie selon le régime du prestataire et le
CGI applicable (taux majorés pour les non-résidents, dispenses pour
les prestataires immatriculés…). La répartition par prestataire est
restituée ``calculable: false`` avec un motif explicite — JAMAIS
estimée ni inventée : seul l'humain qualifie les prestataires depuis
les contrats, les factures et les justificatifs de retenue.

DONNÉES : lecture seule de ``solde_compte`` (comptes 632x, soldes
débiteurs nets) — AUCUNE table nouvelle, AUCUNE migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — la vue
éclaire la vérification des retenues sur honoraires, l'humain qualifie
et décide. Fonctions pures testables sans base + accès RLS via
``contexte_tenant`` (pattern :mod:`backend.plateforme.retenue_loyers`).
Montants sérialisés en ``str`` (Decimal). Contrat stable : clés
toujours présentes, note consultative toujours présente. Formulations
jamais accusatoires : une retenue absente s'EXPLIQUE (prestataire
immatriculé, dispense, convention fiscale, régime particulier…), elle
ne se conclut pas.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

# Préfixe SYSCOHADA des rémunérations d'intermédiaires et de conseils
# lues dans la balance — comptes 632x (honoraires, commissions,
# courtages, frais d'actes et de contentieux…). Approximation
# assumée : tout le 632x est retenu comme « honoraires bruts », y
# compris d'éventuels frais hors champ de la retenue — l'humain trie.
PREFIXE_HONORAIRES: Final = "632"

# Taux courant de la retenue à la source sur les honoraires,
# commissions et courtages versés à des prestataires résidents non
# immatriculés (CGI, retenue sur les rémunérations versées à des
# tiers) — 7,5 % des sommes brutes. Taux INDICATIF : il varie selon le
# régime du prestataire (résident/non-résident, immatriculé ou non,
# conventions fiscales) et le CGI applicable — l'humain qualifie
# chaque prestataire.
TAUX_RETENUE_HONORAIRES: Final = Decimal("0.075")

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_A_QUALIFIER: Final = "a_qualifier"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Vue indisponible — importez la balance (comptes 632x "
        "« rémunérations d'intermédiaires et de conseils »)"
    ),
    STATUT_A_QUALIFIER: (
        "Retenue théorique maximale indicative calculée — le régime "
        "de chaque prestataire (résident ou non, immatriculé ou non) "
        "reste à qualifier : l'humain apprécie et décide"
    ),
}

# Motif restitué pour la répartition par régime de prestataire —
# JAMAIS calculée depuis la balance, jamais inventée.
MOTIF_REGIME_PRESTATAIRE_NON_CALCULABLE: Final = (
    "Le régime du prestataire (résident ou non-résident, immatriculé "
    "ou non, régime d'imposition, conventions fiscales éventuelles) "
    "conditionne la retenue à la source sur les honoraires et est "
    "absent de la balance comptable — la répartition des sommes "
    "soumises / non soumises n'est pas calculée ici : le fiscaliste "
    "la qualifie depuis les contrats, les factures et les "
    "justificatifs de retenue."
)

# Références restituées — TOUJOURS présentes (portées génériques, à
# vérifier par le fiscaliste sur le CGI en vigueur).
REFERENCES_RETENUE_HONORAIRES: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, retenue à la source sur les rémunérations "
        "versées à des tiers",
        "portee": (
            "Le débiteur établi précompte, le cas échéant, une "
            "retenue à la source sur les honoraires, commissions et "
            "courtages versés à des prestataires — le taux varie "
            "selon le régime du prestataire et le CGI applicable"
        ),
    },
    {
        "reference": "CGI, taux de la retenue sur honoraires",
        "portee": (
            "Taux courant de 7,5 % des sommes brutes versées à des "
            "prestataires résidents non immatriculés — taux "
            "indicatif retenu ici comme maximum théorique, taux "
            "majorés (non-résidents) et dispenses (prestataires "
            "immatriculés) non appliqués"
        ),
    },
    {
        "reference": "LPF, obligations des tiers payeurs",
        "portee": (
            "Obligations de précompte, de reversement et de "
            "déclaration du débiteur — les justificatifs de retenue "
            "et quittances font foi, pas la balance"
        ),
    },
)

# Note consultative — TOUJOURS présente dans les réponses. Jamais
# accusatoire : une retenue absente s'explique, elle ne se conclut pas.
NOTE_RETENUE_HONORAIRES: Final = (
    "Vue consultative de la retenue à la source sur honoraires et "
    "rémunérations d'intermédiaires : les sommes sont lues dans les "
    "comptes 632x de la balance et la retenue théorique MAXIMALE est "
    "approchée au taux courant de 7,5 % comme si toutes les sommes "
    "étaient versées à des prestataires résidents non immatriculés "
    "soumis à la retenue. LIMITE ASSUMÉE : le régime du prestataire "
    "(résident ou non-résident, immatriculé ou non, conventions) "
    "conditionne la retenue et son taux et est absent de la balance — "
    "la répartition n'est jamais calculée ni inventée. Un écart entre "
    "retenue théorique et retenue pratiquée est un « écart à "
    "expliquer » (prestataires immatriculés, dispenses, conventions "
    "fiscales…), jamais une conclusion — les justificatifs de retenue "
    "et quittances font foi, seul l'humain qualifie chaque "
    "prestataire et décide."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_retenue_honoraires"


class ErreurRetenueHonoraires(Exception):
    """Échec de la vue retenue à la source sur honoraires."""


class ErreurRetenueHonorairesIntrouvable(ErreurRetenueHonoraires):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def arrondir_franc(montant: Decimal) -> Decimal:
    """PUR — arrondi au franc CFA (entier, ROUND_HALF_UP)."""
    return montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def extraire_honoraires(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — honoraires depuis les comptes 632x de la balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :

    - ``honoraires_bruts`` : soldes débiteurs nets des comptes 632x ;
    - ``comptes`` : détail par compte (solde débiteur net signé) ;
    - ``nb_comptes_honoraires`` : nombre de comptes 632x lus ;
    - ``disponible`` : vrai si au moins un compte 632x existe.
    """
    total = Decimal("0")
    comptes: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte.startswith(PREFIXE_HONORAIRES):
            continue
        debit = Decimal(str(ligne.get("debit") or 0))
        credit = Decimal(str(ligne.get("credit") or 0))
        solde = debit - credit
        total += solde
        comptes.append(
            {
                "compte": compte,
                "libelle": str(ligne.get("libelle") or ""),
                "solde": solde,
            }
        )
    return {
        "honoraires_bruts": total,
        "comptes": comptes,
        "nb_comptes_honoraires": len(comptes),
        "disponible": bool(comptes),
    }


def calculer_retenue_theorique_max(
    honoraires_bruts: Decimal,
    taux: Decimal = TAUX_RETENUE_HONORAIRES,
) -> Decimal:
    """PUR — retenue théorique MAXIMALE = taux × honoraires bruts (franc).

    Maximum indicatif : calcul « comme si » toutes les sommes étaient
    soumises à la retenue au taux courant — le régime réel des
    prestataires peut la réduire jusqu'à zéro (ou la majorer pour des
    non-résidents), seul l'humain qualifie. Assiette négative ramenée
    à 0 (aucune retenue négative inventée).
    """
    assiette = max(honoraires_bruts, Decimal("0"))
    return arrondir_franc(assiette * taux)


def evaluer_retenue_honoraires(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — vue consultative de la retenue sur honoraires (balance).

    ``soldes`` : lignes de balance ``{compte, libelle, debit,
    credit}``. Montants restitués en ``str`` (Decimal). Clés TOUJOURS
    présentes ; ``disponible`` est vrai seulement si la balance porte
    au moins un compte 632x — sans lui, rien n'est chiffré (aucun
    montant inventé).

    La répartition par régime de prestataire est TOUJOURS restituée
    ``calculable: false`` avec son motif : la retenue restituée est un
    MAXIMUM théorique indicatif, jamais une liquidation.
    """
    honoraires = extraire_honoraires(soldes)
    disponible = bool(honoraires["disponible"])

    if disponible:
        retenue_max = calculer_retenue_theorique_max(
            honoraires["honoraires_bruts"]
        )
        statut = STATUT_A_QUALIFIER
    else:
        retenue_max = Decimal("0")
        statut = STATUT_INDISPONIBLE

    return {
        "disponible": disponible,
        "honoraires_bruts": str(honoraires["honoraires_bruts"]),
        "comptes_honoraires": [
            {
                "compte": c["compte"],
                "libelle": c["libelle"],
                "solde": str(c["solde"]),
            }
            for c in honoraires["comptes"]
        ],
        "taux_indicatif": str(TAUX_RETENUE_HONORAIRES),
        "retenue_theorique_max": str(retenue_max),
        # La répartition soumis / non soumis dépend du régime du
        # prestataire, inconnu de la balance — JAMAIS calculée.
        "repartition_par_prestataire": {
            "calculable": False,
            "motif": MOTIF_REGIME_PRESTATAIRE_NON_CALCULABLE,
        },
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_comptes_honoraires": int(
                honoraires["nb_comptes_honoraires"]
            ),
        },
        "note": NOTE_RETENUE_HONORAIRES,
        "references": [dict(r) for r in REFERENCES_RETENUE_HONORAIRES],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurRetenueHonorairesIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _soldes_honoraires_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND compte LIKE :p ORDER BY compte"
        ),
        {"m": mission_id, "p": PREFIXE_HONORAIRES + "%"},
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_retenue_honoraires_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Retenue sur honoraires de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurRetenueHonorairesIntrouvable`
    (404 côté route). Se construit toujours : sans balance (aucun
    compte 632x), ``disponible=false`` et ``statut="indisponible"`` —
    les clés restent présentes, aucun montant inventé. Tolérance par
    bloc : un échec de lecture de la balance dégrade en indisponible
    au lieu de faire échouer la vue.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        try:
            soldes = _soldes_honoraires_mission(session, mission_id)
        except Exception:
            # Tolérance par bloc : balance illisible → vue
            # indisponible, servie quand même (clés stables).
            soldes = []

    vue = evaluer_retenue_honoraires(soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
