"""Retenue à la source sur loyers — vue consultative depuis la balance.

POURQUOI : lors de la revue, le fiscaliste vérifie que les loyers de
locaux professionnels versés par la mission ont bien supporté, le cas
échéant, la retenue à la source sur les revenus locatifs que le
locataire doit précompter pour le compte du bailleur. Le présent
module lit les charges locatives (comptes 622x « Locations et charges
locatives » de la balance) et restitue un ORDRE DE GRANDEUR de la
retenue théorique MAXIMALE, jamais une liquidation.

LIMITE STRUCTURELLE ASSUMÉE (documentée) : la retenue dépend de la
QUALITÉ DU BAILLEUR (personne physique ou morale, régime d'imposition,
bailleur déjà imposé à l'impôt foncier…), donnée ABSENTE de la
balance comptable. Le taux courant :data:`TAUX_RETENUE_LOYERS` (15 %)
n'est dû que sur les loyers versés à certains bailleurs (typiquement
les personnes physiques) : le montant restitué est donc un MAXIMUM
théorique indicatif calculé comme si TOUS les loyers y étaient
soumis. La répartition par bailleur est restituée
``calculable: false`` avec un motif explicite — JAMAIS estimée ni
inventée : seul l'humain qualifie les bailleurs depuis les baux et
les quittances.

DONNÉES : lecture seule de ``solde_compte`` (comptes 622x, soldes
débiteurs nets) — AUCUNE table nouvelle, AUCUNE migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — la vue
éclaire la vérification des retenues sur loyers, l'humain qualifie et
décide. Fonctions pures testables sans base + accès RLS via
``contexte_tenant`` (pattern :mod:`backend.plateforme.patente`).
Montants sérialisés en ``str`` (Decimal). Contrat stable : clés
toujours présentes, note consultative toujours présente. Formulations
jamais accusatoires : une retenue absente s'EXPLIQUE (bailleur
personne morale, exonération, régime particulier…), elle ne se
conclut pas.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes métier ────────────────────────────────────────────────

# Préfixe SYSCOHADA des charges locatives lues dans la balance —
# comptes 622x (locations de bâtiments, de terrains, de matériel,
# charges locatives…). Approximation assumée : tout le 622x est
# retenu comme « loyers bruts », y compris d'éventuelles locations
# mobilières hors champ de la retenue — l'humain trie.
PREFIXE_CHARGES_LOCATIVES: Final = "622"

# Taux courant de la retenue à la source sur les loyers versés à des
# bailleurs personnes physiques (CGI, régime des revenus locatifs) —
# 15 % des loyers bruts. Taux INDICATIF : régimes, exonérations et
# taux particuliers non appliqués.
TAUX_RETENUE_LOYERS: Final = Decimal("0.15")

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_A_QUALIFIER: Final = "a_qualifier"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Vue indisponible — importez la balance (comptes 622x "
        "« locations et charges locatives »)"
    ),
    STATUT_A_QUALIFIER: (
        "Retenue théorique maximale indicative calculée — la qualité "
        "de chaque bailleur (personne physique ou morale, régime) "
        "reste à qualifier : l'humain apprécie et décide"
    ),
}

# Motif restitué pour la répartition par qualité de bailleur — JAMAIS
# calculée depuis la balance, jamais inventée.
MOTIF_QUALITE_BAILLEUR_NON_CALCULABLE: Final = (
    "La qualité du bailleur (personne physique ou personne morale, "
    "régime d'imposition, exonérations éventuelles) conditionne la "
    "retenue à la source sur les loyers et est absente de la balance "
    "comptable — la répartition des loyers soumis / non soumis n'est "
    "pas calculée ici : le fiscaliste la qualifie depuis les baux, "
    "les quittances et les justificatifs de retenue."
)

# Références restituées — TOUJOURS présentes (portées génériques, à
# vérifier par le fiscaliste sur le CGI en vigueur).
REFERENCES_RETENUE_LOYERS: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, dispositions sur l'impôt sur les revenus "
        "locatifs",
        "portee": (
            "Imposition des revenus locatifs — le locataire "
            "professionnel précompte, le cas échéant, une retenue à "
            "la source sur les loyers versés au bailleur"
        ),
    },
    {
        "reference": "CGI, retenue à la source sur les loyers",
        "portee": (
            "Taux courant de 15 % des loyers bruts versés à des "
            "bailleurs personnes physiques — taux indicatif retenu "
            "ici comme maximum théorique, régimes particuliers non "
            "appliqués"
        ),
    },
    {
        "reference": "LPF, obligations des tiers payeurs",
        "portee": (
            "Obligations de précompte, de reversement et de "
            "déclaration du locataire — les quittances et "
            "justificatifs de retenue font foi, pas la balance"
        ),
    },
)

# Note consultative — TOUJOURS présente dans les réponses. Jamais
# accusatoire : une retenue absente s'explique, elle ne se conclut pas.
NOTE_RETENUE_LOYERS: Final = (
    "Vue consultative de la retenue à la source sur loyers : les "
    "charges locatives sont lues dans les comptes 622x de la balance "
    "et la retenue théorique MAXIMALE est approchée au taux courant "
    "de 15 % comme si tous les loyers étaient versés à des bailleurs "
    "personnes physiques soumis à la retenue. LIMITE ASSUMÉE : la "
    "qualité du bailleur (personne physique ou morale, régime, "
    "exonérations) conditionne la retenue et est absente de la "
    "balance — la répartition n'est jamais calculée ni inventée. Un "
    "écart entre retenue théorique et retenue pratiquée est un "
    "« écart à expliquer » (bailleurs personnes morales, locations "
    "mobilières, exonérations…), jamais une conclusion — seul "
    "l'humain qualifie les bailleurs et décide."
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_retenue_loyers"


class ErreurRetenueLoyers(Exception):
    """Échec de la vue retenue à la source sur loyers."""


class ErreurRetenueLoyersIntrouvable(ErreurRetenueLoyers):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def arrondir_franc(montant: Decimal) -> Decimal:
    """PUR — arrondi au franc CFA (entier, ROUND_HALF_UP)."""
    return montant.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def extraire_charges_locatives(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — charges locatives depuis les comptes 622x de la balance.

    ``soldes`` : lignes ``{compte, libelle, debit, credit}`` (mêmes
    clés que ``solde_compte``). Retourne, en :class:`Decimal` :

    - ``loyers_bruts`` : soldes débiteurs nets des comptes 622x ;
    - ``comptes`` : détail par compte (solde débiteur net signé) ;
    - ``nb_comptes_loyers`` : nombre de comptes 622x lus ;
    - ``disponible`` : vrai si au moins un compte 622x existe.
    """
    total = Decimal("0")
    comptes: list[dict[str, Any]] = []
    for ligne in soldes:
        compte = str(ligne.get("compte") or "").strip()
        if not compte.startswith(PREFIXE_CHARGES_LOCATIVES):
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
        "loyers_bruts": total,
        "comptes": comptes,
        "nb_comptes_loyers": len(comptes),
        "disponible": bool(comptes),
    }


def calculer_retenue_theorique_max(
    loyers_bruts: Decimal,
    taux: Decimal = TAUX_RETENUE_LOYERS,
) -> Decimal:
    """PUR — retenue théorique MAXIMALE = taux × loyers bruts (franc).

    Maximum indicatif : calcul « comme si » tous les loyers étaient
    soumis à la retenue au taux courant — la qualité réelle des
    bailleurs peut la réduire jusqu'à zéro, seul l'humain qualifie.
    Assiette négative ramenée à 0 (aucune retenue négative inventée).
    """
    assiette = max(loyers_bruts, Decimal("0"))
    return arrondir_franc(assiette * taux)


def evaluer_retenue_loyers(
    soldes: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — vue consultative de la retenue sur loyers depuis la balance.

    ``soldes`` : lignes de balance ``{compte, libelle, debit,
    credit}``. Montants restitués en ``str`` (Decimal). Clés TOUJOURS
    présentes ; ``disponible`` est vrai seulement si la balance porte
    au moins un compte 622x — sans lui, rien n'est chiffré (aucun
    montant inventé).

    La répartition par qualité de bailleur est TOUJOURS restituée
    ``calculable: false`` avec son motif : la retenue restituée est un
    MAXIMUM théorique indicatif, jamais une liquidation.
    """
    charges = extraire_charges_locatives(soldes)
    disponible = bool(charges["disponible"])

    if disponible:
        retenue_max = calculer_retenue_theorique_max(
            charges["loyers_bruts"]
        )
        statut = STATUT_A_QUALIFIER
    else:
        retenue_max = Decimal("0")
        statut = STATUT_INDISPONIBLE

    return {
        "disponible": disponible,
        "loyers_bruts": str(charges["loyers_bruts"]),
        "comptes_loyers": [
            {
                "compte": c["compte"],
                "libelle": c["libelle"],
                "solde": str(c["solde"]),
            }
            for c in charges["comptes"]
        ],
        "taux_indicatif": str(TAUX_RETENUE_LOYERS),
        "retenue_theorique_max": str(retenue_max),
        # La répartition soumis / non soumis dépend de la qualité du
        # bailleur, inconnue de la balance — JAMAIS calculée.
        "repartition_par_bailleur": {
            "calculable": False,
            "motif": MOTIF_QUALITE_BAILLEUR_NON_CALCULABLE,
        },
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_comptes_loyers": int(charges["nb_comptes_loyers"]),
        },
        "note": NOTE_RETENUE_LOYERS,
        "references": [dict(r) for r in REFERENCES_RETENUE_LOYERS],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurRetenueLoyersIntrouvable(
            f"mission {mission_id} introuvable pour ce tenant"
        )
    return dict(mission)


def _soldes_loyers_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT compte, libelle, debit, credit "
            "FROM solde_compte WHERE mission_id = :m "
            "AND compte LIKE :p ORDER BY compte"
        ),
        {"m": mission_id, "p": PREFIXE_CHARGES_LOCATIVES + "%"},
    ).mappings().all()
    return [dict(r) for r in rows]


def vue_retenue_loyers_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Retenue sur loyers de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurRetenueLoyersIntrouvable` (404
    côté route). Se construit toujours : sans balance (aucun compte
    622x), ``disponible=false`` et ``statut="indisponible"`` — les
    clés restent présentes, aucun montant inventé. Tolérance par
    bloc : un échec de lecture de la balance dégrade en indisponible
    au lieu de faire échouer la vue.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        try:
            soldes = _soldes_loyers_mission(session, mission_id)
        except Exception:
            # Tolérance par bloc : balance illisible → vue
            # indisponible, servie quand même (clés stables).
            soldes = []

    vue = evaluer_retenue_loyers(soldes)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
