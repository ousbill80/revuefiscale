"""Complétude de la data room — socle documentaire de la revue fiscale.

AVANT d'analyser, le fiscaliste vérifie que les PIÈCES COMPTABLES DE
BASE de la revue sont réunies dans la data room de mission (table
``piece_mission`` : balance, etats_financiers, grand_livre, fec,
autre). Ce module évalue cette complétude de façon DÉTERMINISTE, par
simple rapprochement des ``type_piece`` (et, pour les déclarations
déposées en « autre », de mots-clés du nom de fichier).

PÉRIMÈTRE ASSUMÉ : la complétude porte sur le SOCLE documentaire — elle
NE DUPLIQUE PAS le civisme fiscal (rapprochement échéance par échéance,
:mod:`backend.plateforme.civisme_fiscal`) ni la demande de
renseignements (items demandés au client).

Référentiel par régime (pratique de cabinet ivoirien) :

- ``reel`` / ``reel_simplifie`` (RNI/RSI, SYSCOHADA système normal) :
  états financiers, balance générale, grand livre ou FEC (détail des
  écritures), déclarations fiscales de l'exercice (pièces « autre » au
  nom évocateur — utiles mais non essentielles au démarrage : le détail
  relève du civisme fiscal) ;
- ``ime`` (microentreprise, SMT) : états financiers SMT, déclarations
  simplifiées, journal recettes-dépenses (facultatif) ;
- ``tee`` (taxe de l'entreprenant) : déclarations simplifiées,
  journal recettes-dépenses (facultatif — simple livre de recettes).

Analyse CONSULTATIVE : « manquante » signifie seulement qu'aucune pièce
du type attendu n'a été déposée — le fiscaliste apprécie (pièce reçue
hors application, dispense, etc.). Aucun LLM ; fonctions pures +
lecture seule sous RLS ; taux en str Decimal (0.01).
"""
from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.echeancier_fiscal import (
    _profil_mission,
    normaliser_regime,
)

MENTION_NOTE: Final[str] = (
    "Complétude consultative du socle documentaire de la revue : une "
    "pièce « manquante » signifie seulement qu'aucun document du type "
    "attendu n'a été déposé en data room de mission — le fiscaliste "
    "vérifie auprès du client (pièce reçue hors application, dispense) "
    "avant toute conclusion. Le détail déclaration par déclaration "
    "relève du civisme fiscal."
)

# Nombre maximal d'exemples de fichiers restitués par pièce attendue.
MAX_EXEMPLES: Final[int] = 3

# Tokens de nom de fichier reconnaissant une déclaration fiscale
# déposée en pièce « autre » (déterministe, volontairement large).
_TOKENS_DECLARATION: Final[frozenset[str]] = frozenset(
    {
        "declaration", "declarations", "dfe",
        "tva", "its", "patente", "patentes", "bic", "is", "irc", "ircm",
        "impot", "impots",
        "tee", "tce", "entreprenant", "ime",
        "microentreprise", "microentreprises",
    }
)

# ── Référentiel PUR des pièces attendues par régime ──────────────────
# Chaque attendu : code, libelle, types_acceptes (type_piece du schéma
# piece_mission), tokens (facultatif : restreint les pièces « autre »
# aux noms de fichier contenant l'un de ces tokens), essentielle.

_EF_SYSCOHADA: Final[dict[str, Any]] = {
    "code": "etats_financiers",
    "libelle": "États financiers de l'exercice (SYSCOHADA)",
    "types_acceptes": ("etats_financiers",),
    "essentielle": True,
}

_BALANCE_GENERALE: Final[dict[str, Any]] = {
    "code": "balance_generale",
    "libelle": "Balance générale des comptes",
    "types_acceptes": ("balance",),
    "essentielle": True,
}

_GRAND_LIVRE_OU_FEC: Final[dict[str, Any]] = {
    "code": "grand_livre_ou_fec",
    "libelle": "Grand livre ou FEC (détail des écritures)",
    "types_acceptes": ("grand_livre", "fec"),
    "essentielle": True,
}

_DECLARATIONS_EXERCICE: Final[dict[str, Any]] = {
    "code": "declarations_fiscales",
    "libelle": "Déclarations fiscales de l'exercice (TVA, ITS, résultat…)",
    "types_acceptes": ("autre",),
    "tokens": _TOKENS_DECLARATION,
    "essentielle": False,
}

_EF_SMT: Final[dict[str, Any]] = {
    "code": "etats_financiers",
    "libelle": "États financiers SMT (système minimal de trésorerie)",
    "types_acceptes": ("etats_financiers",),
    "essentielle": True,
}

_DECLARATIONS_SIMPLIFIEES: Final[dict[str, Any]] = {
    "code": "declarations_simplifiees",
    "libelle": "Déclarations simplifiées de l'exercice",
    "types_acceptes": ("autre",),
    "tokens": _TOKENS_DECLARATION,
    "essentielle": True,
}

_JOURNAL_RECETTES: Final[dict[str, Any]] = {
    "code": "journal_recettes_depenses",
    "libelle": "Journal des recettes et dépenses (livre de recettes)",
    "types_acceptes": ("balance", "grand_livre", "fec"),
    "essentielle": False,
}

_ATTENDUS_PAR_REGIME: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    # Réel (RNI/RSI) : comptabilité SYSCOHADA complète.
    "reel": (
        _EF_SYSCOHADA,
        _BALANCE_GENERALE,
        _GRAND_LIVRE_OU_FEC,
        _DECLARATIONS_EXERCICE,
    ),
    "reel_simplifie": (
        _EF_SYSCOHADA,
        _BALANCE_GENERALE,
        _GRAND_LIVRE_OU_FEC,
        _DECLARATIONS_EXERCICE,
    ),
    # Microentreprise (IME) : SMT — états financiers simplifiés.
    "ime": (_EF_SMT, _DECLARATIONS_SIMPLIFIEES, _JOURNAL_RECETTES),
    # Taxe de l'entreprenant (TEE/TCE) : simple livre de recettes.
    "tee": (_DECLARATIONS_SIMPLIFIEES, _JOURNAL_RECETTES),
}


class ErreurCompletudeDataRoom(Exception):
    """Échec de l'évaluation de complétude de la data room."""


class ErreurCompletudeIntrouvable(ErreurCompletudeDataRoom):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def _cle(texte: Any) -> str:
    """Clé de comparaison : sans accents, minuscules, sans bords."""
    brut = str(texte or "")
    sans_accents = (
        unicodedata.normalize("NFKD", brut)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return sans_accents.strip().casefold()


def _tokens(nom_fichier: Any) -> list[str]:
    """Tokens alphanumériques du nom de fichier (clé normalisée)."""
    return [t for t in re.split(r"[^a-z0-9]+", _cle(nom_fichier)) if t]


def referentiel_attendus(regime: str | None) -> list[dict[str, Any]]:
    """PUR — pièces attendues du socle documentaire selon le régime.

    Régime normalisé via :func:`normaliser_regime` ; inconnu ou vide →
    traité comme réel (référentiel le plus complet : prudent pour une
    revue). Chaque attendu est copié (le référentiel reste immuable) :
    ``{code, libelle, types_acceptes: [...], essentielle}``.
    """
    cle = normaliser_regime(regime) or "reel"
    attendus = _ATTENDUS_PAR_REGIME.get(cle, _ATTENDUS_PAR_REGIME["reel"])
    return [
        {
            "code": str(a["code"]),
            "libelle": str(a["libelle"]),
            "types_acceptes": list(a["types_acceptes"]),
            "essentielle": bool(a["essentielle"]),
        }
        for a in attendus
    ]


def _piece_correspond(attendu: dict[str, Any], piece: dict[str, Any]) -> bool:
    """Vrai si la pièce satisfait l'attendu (type + tokens éventuels)."""
    if str(piece.get("type_piece") or "") not in attendu["types_acceptes"]:
        return False
    tokens_requis = attendu.get("tokens")
    if not tokens_requis:
        return True
    return any(t in tokens_requis for t in _tokens(piece.get("nom_fichier")))


def evaluer_completude(
    regime: str | None, pieces: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """PUR — état de chaque pièce attendue face aux pièces déposées.

    ``pieces`` : liste de ``{type_piece, nom_fichier}`` (data room de la
    mission). Chaque attendu du référentiel du régime est restitué avec
    ``{code, libelle, essentielle, presente, nb_pieces, exemples}`` —
    ``exemples`` : noms de fichiers correspondants, plafonnés à
    :data:`MAX_EXEMPLES`, dans l'ordre de la liste fournie.
    """
    cle = normaliser_regime(regime) or "reel"
    attendus = _ATTENDUS_PAR_REGIME.get(cle, _ATTENDUS_PAR_REGIME["reel"])
    evaluation: list[dict[str, Any]] = []
    for attendu in attendus:
        correspondantes = [p for p in pieces if _piece_correspond(attendu, p)]
        exemples = [
            str(p.get("nom_fichier") or "")
            for p in correspondantes[:MAX_EXEMPLES]
        ]
        evaluation.append(
            {
                "code": str(attendu["code"]),
                "libelle": str(attendu["libelle"]),
                "essentielle": bool(attendu["essentielle"]),
                "presente": bool(correspondantes),
                "nb_pieces": len(correspondantes),
                "exemples": exemples,
            }
        )
    return evaluation


def synthese_completude(evaluation: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — synthèse chiffrée de la complétude du socle.

    ``taux_completude`` (str Decimal, 0.01) = essentielles présentes /
    essentielles attendues × 100 — les pièces non essentielles éclairent
    sans peser sur le taux. Sans essentielle attendue → « 100.00 »
    (rien d'indispensable à réunir).
    """
    essentielles = [e for e in evaluation if e["essentielle"]]
    presentes_essentielles = sum(1 for e in essentielles if e["presente"])
    if not essentielles:
        taux = Decimal("100.00")
    else:
        taux = (
            Decimal(presentes_essentielles)
            * Decimal("100")
            / Decimal(len(essentielles))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "attendues": len(evaluation),
        "presentes": sum(1 for e in evaluation if e["presente"]),
        "essentielles_manquantes": len(essentielles)
        - presentes_essentielles,
        "taux_completude": str(taux),
    }


# ── Lecture par mission (RLS) ────────────────────────────────────────


def completude_data_room(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Complétude du socle documentaire de la mission (lecture seule, RLS).

    Lit le régime (profil JSON de la mission) et les pièces de la data
    room (``piece_mission``), puis délègue aux fonctions pures. Mission
    hors tenant → :class:`ErreurCompletudeIntrouvable` (404 côté route).
    """
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text("SELECT profil FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurCompletudeIntrouvable(
                f"mission {mission_id} introuvable"
            )
        pieces = session.execute(
            text(
                "SELECT type_piece, nom_fichier FROM piece_mission "
                "WHERE mission_id = :m ORDER BY id"
            ),
            {"m": mission_id},
        ).mappings().all()

    profil = _profil_mission(row["profil"])
    regime = normaliser_regime(str(profil.get("regime") or "")) or "reel"
    evaluation = evaluer_completude(regime, [dict(p) for p in pieces])
    return {
        "mission_id": mission_id,
        "regime": regime,
        "attendus": evaluation,
        "synthese": synthese_completude(evaluation),
        "note": MENTION_NOTE,
    }
