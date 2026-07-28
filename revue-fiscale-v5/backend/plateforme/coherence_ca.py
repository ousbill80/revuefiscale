"""Cohérence CA comptable / CA reconstitué depuis les déclarations TVA.

POURQUOI : le croisement classique de la DGI lors d'un contrôle est la
reconstitution du chiffre d'affaires depuis la TVA collectée déclarée
(TVA ÷ taux normal) et sa comparaison au chiffre d'affaires comptable.
Le présent module offre ce croisement AU RÉVISEUR, en consultatif,
AVANT que l'administration ne le fasse — un écart au-delà du seuil
appelle une EXPLICATION (exonérations, taux réduits, décalages de
facturation, opérations hors champ…), JAMAIS une accusation.

DIFFÉRENT de :mod:`backend.plateforme.rapprochement_tva` : celui-ci
compare les déclarations aux COMPTES DE TVA (443x/445x) ; ici on
compare au CHIFFRE D'AFFAIRES (comptes 70x).

APPROXIMATION ASSUMÉE (documentée, ``approximation: true``) : le CA
est reconstitué en divisant la TVA collectée totale déclarée par le
seul taux normal :data:`TAUX_TVA_NORMAL` (18 %) — les exonérations,
les taux réduits et les opérations hors champ de TVA sont IGNORÉS.
L'écart relatif est apprécié contre le seuil indicatif
:data:`SEUIL_ECART_RELATIF_PCT` (5 %).

DONNÉES : lecture seule de ``solde_compte`` (comptes 70x, logique CA
de :mod:`backend.plateforme.patente` réutilisée) et de
``declaration_tva`` (TVA collectée saisie) — AUCUNE table nouvelle,
AUCUNE migration.

DOCTRINE : déterministe, AUCUN LLM, strictement CONSULTATIF — l'écart
éclaire, l'humain apprécie et décide. Fonctions pures testables sans
base + accès RLS via ``contexte_tenant`` (pattern
:mod:`backend.plateforme.patente`). Montants sérialisés en ``str``
(Decimal). Contrat stable : clés toujours présentes, note consultative
toujours présente.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.patente import (
    PREFIXE_CHIFFRE_AFFAIRES,
    extraire_chiffre_affaires,
)

# ── Constantes métier ────────────────────────────────────────────────

# Taux normal de TVA ivoirien (CGI, art. 359) : 18 %. Seul taux
# retenu pour la reconstitution — approximation assumée (taux réduits,
# exonérations et hors champ ignorés).
TAUX_TVA_NORMAL: Final = Decimal("0.18")

# Seuil indicatif d'écart relatif (en %) au-delà duquel l'écart entre
# CA comptable et CA reconstitué appelle une explication du réviseur.
SEUIL_ECART_RELATIF_PCT: Final = Decimal("5.0")

STATUT_INDISPONIBLE: Final = "indisponible"
STATUT_COHERENT: Final = "coherent"
STATUT_ECART: Final = "ecart_a_expliquer"

LIBELLES_STATUT: Final[dict[str, str]] = {
    STATUT_INDISPONIBLE: (
        "Croisement indisponible — importez la balance (comptes 70x) "
        "et saisissez au moins une déclaration de TVA"
    ),
    STATUT_COHERENT: (
        "CA comptable et CA reconstitué cohérents (écart relatif "
        "dans le seuil indicatif)"
    ),
    STATUT_ECART: (
        "Écart à expliquer entre CA comptable et CA reconstitué — "
        "exonérations, taux réduits, décalages de facturation, "
        "opérations hors champ… l'humain apprécie"
    ),
}

# Note consultative — TOUJOURS présente dans les réponses. Jamais
# accusatoire : un écart s'EXPLIQUE, il ne se conclut pas.
NOTE_COHERENCE_CA: Final = (
    "Croisement consultatif du chiffre d'affaires comptable (comptes "
    "70x de la balance) et du chiffre d'affaires reconstitué depuis "
    "la TVA collectée déclarée divisée par le seul taux normal de "
    "18 % — c'est le contrôle de cohérence classique de la DGI, "
    "offert ici au réviseur avant l'administration. APPROXIMATION "
    "ASSUMÉE : les exonérations, les taux réduits et les opérations "
    "hors champ de TVA sont ignorés par la reconstitution. Un écart "
    "au-delà du seuil indicatif est un « écart à expliquer » "
    "(exonérations, décalages de facturation, taux réduits, avances "
    "clients…), jamais une conclusion — l'humain apprécie et décide."
)

# Références restituées — TOUJOURS présentes.
REFERENCES_COHERENCE_CA: Final[tuple[dict[str, str], ...]] = (
    {
        "reference": "CGI, art. 339 et s.",
        "portee": (
            "Champ d'application de la TVA — opérations imposables, "
            "exonérations et opérations hors champ ignorées par la "
            "reconstitution"
        ),
    },
    {
        "reference": "CGI, art. 359",
        "portee": (
            "Taux normal de TVA de 18 % — seul taux retenu pour "
            "reconstituer le chiffre d'affaires (approximation)"
        ),
    },
    {
        "reference": "LPF, art. 2 et s.",
        "portee": (
            "Droit de contrôle de l'administration — la "
            "reconstitution du chiffre d'affaires depuis les "
            "déclarations de TVA est un croisement classique de la DGI"
        ),
    },
)

# Code journalisé dans le journal d'audit.
ACTION_CONSULTATION: Final = "consultation_coherence_ca"


class ErreurCoherenceCa(Exception):
    """Échec du croisement de cohérence du chiffre d'affaires."""


class ErreurCoherenceCaIntrouvable(ErreurCoherenceCa):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def totaliser_tva_collectee(
    declarations: list[dict[str, Any]],
) -> Decimal:
    """PUR — total de la TVA collectée déclarée (Decimal)."""
    total = Decimal("0")
    for d in declarations:
        total += Decimal(str(d.get("tva_collectee") or 0))
    return total


def reconstituer_ca(
    tva_collectee_totale: Decimal,
    taux: Decimal = TAUX_TVA_NORMAL,
) -> Decimal:
    """PUR — CA reconstitué = TVA collectée ÷ taux normal (2 déc.).

    APPROXIMATION documentée : seul le taux normal est appliqué —
    exonérations, taux réduits et opérations hors champ ignorés.
    """
    return (tva_collectee_totale / taux).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def calculer_ecart_relatif_pct(
    ecart: Decimal, ca_comptable: Decimal
) -> Decimal | None:
    """PUR — écart relatif en % sur base CA comptable (1 décimale).

    CA comptable nul → ``None`` (base de comparaison absente, aucun
    pourcentage inventé).
    """
    if ca_comptable == 0:
        return None
    return (ecart / ca_comptable * Decimal("100")).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )


def evaluer_coherence_ca(
    soldes: list[dict[str, Any]],
    declarations: list[dict[str, Any]],
    seuil_pct: Decimal = SEUIL_ECART_RELATIF_PCT,
) -> dict[str, Any]:
    """PUR — croisement CA comptable / CA reconstitué depuis la TVA.

    ``soldes`` : lignes de balance ``{compte, libelle, debit,
    credit}`` (seuls les 70x comptent, 709x en moins) ;
    ``declarations`` : lignes ``{periode, tva_collectee}``. Montants
    restitués en ``str`` (Decimal). Clés TOUJOURS présentes ;
    ``disponible`` est vrai seulement si la balance porte au moins un
    compte 70x ET qu'au moins une déclaration de TVA est saisie — le
    croisement ne se chiffre que sur données complètes.

    Statuts : ``indisponible``, ``coherent`` (|écart relatif| ≤
    ``seuil_pct``) ou ``ecart_a_expliquer`` — JAMAIS de conclusion
    accusatoire, l'écart appelle une explication humaine.
    """
    ca = extraire_chiffre_affaires(soldes)
    ca_comptable = ca["chiffre_affaires"]
    tva_totale = totaliser_tva_collectee(declarations)
    disponible = bool(ca["disponible"]) and bool(declarations)

    if disponible:
        ca_reconstitue = reconstituer_ca(tva_totale)
        ecart = ca_comptable - ca_reconstitue
        ecart_relatif = calculer_ecart_relatif_pct(ecart, ca_comptable)
        if ecart_relatif is not None:
            statut = (
                STATUT_COHERENT
                if abs(ecart_relatif) <= seuil_pct
                else STATUT_ECART
            )
        else:
            # CA comptable nul : pas de base relative — cohérent
            # seulement si l'écart absolu est nul lui aussi.
            statut = STATUT_COHERENT if ecart == 0 else STATUT_ECART
    else:
        ca_reconstitue = Decimal("0")
        ecart = Decimal("0")
        ecart_relatif = None
        statut = STATUT_INDISPONIBLE

    return {
        "disponible": disponible,
        "ca_comptable": str(ca_comptable),
        "nb_declarations": len(declarations),
        "tva_collectee_totale": str(tva_totale),
        "taux_normal": str(TAUX_TVA_NORMAL),
        "ca_reconstitue": str(ca_reconstitue),
        # La reconstitution est TOUJOURS une approximation (taux
        # normal seul) — le contrat l'assume explicitement.
        "approximation": True,
        "ecart": str(ecart),
        "ecart_relatif_pct": (
            str(ecart_relatif) if ecart_relatif is not None else None
        ),
        "seuil_pct": str(seuil_pct),
        "statut": statut,
        "synthese": {
            "statut": statut,
            "libelle_statut": LIBELLES_STATUT[statut],
            "nb_comptes_ca": int(ca["nb_comptes_ca"]),
            "nb_declarations": len(declarations),
        },
        "note": NOTE_COHERENCE_CA,
        "references": [dict(r) for r in REFERENCES_COHERENCE_CA],
    }


# ── Accès DB (contexte tenant obligatoire) ───────────────────────────


def _mission_ou_404(session: Session, mission_id: int) -> dict[str, Any]:
    """Mission du tenant courant — contexte déjà posé par l'appelant."""
    mission = session.execute(
        text("SELECT id, exercice FROM mission WHERE id = :m"),
        {"m": mission_id},
    ).mappings().one_or_none()
    if mission is None:
        raise ErreurCoherenceCaIntrouvable(
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


def _declarations_tva_mission(
    session: Session, mission_id: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT periode, tva_collectee "
            "FROM declaration_tva WHERE mission_id = :m "
            "ORDER BY periode"
        ),
        {"m": mission_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def coherence_ca_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Croisement de cohérence du CA de la mission — lecture seule, RLS.

    Mission hors tenant → :class:`ErreurCoherenceCaIntrouvable` (404
    côté route). Se construit toujours : sans balance (aucun compte
    70x) ou sans déclaration de TVA saisie, ``disponible=false`` et
    ``statut="indisponible"`` — les clés restent présentes, aucun
    montant inventé. Tolérance par bloc : un échec de lecture dégrade
    en indisponible au lieu de faire échouer la vue.
    """
    with contexte_tenant(session, tenant_id):
        mission = _mission_ou_404(session, mission_id)
        try:
            soldes = _soldes_ca_mission(session, mission_id)
        except Exception:
            soldes = []
        try:
            declarations = _declarations_tva_mission(session, mission_id)
        except Exception:
            declarations = []

    vue = evaluer_coherence_ca(soldes, declarations)
    vue["mission_id"] = mission_id
    vue["exercice"] = int(mission["exercice"])
    vue["aujourd_hui"] = date.today().isoformat()
    return vue
