"""Civisme fiscal — rapprochement échéancier théorique / pièces collectées.

En cabinet, le « civisme fiscal » d'un client se lit d'abord dans sa
capacité à produire les justificatifs de ses obligations déclaratives.
Ce module rapproche l'échéancier fiscal théorique de l'exercice revu
(:func:`backend.plateforme.echeancier_fiscal.construire_echeancier`)
des éléments réellement collectés sur la mission.

LIMITE ASSUMÉE (modèle de données réel) : l'application ne stocke PAS
les déclarations fiscales déposées par le client — seuls existent les
documents de la data room de mission (table ``piece_mission`` : balance,
états financiers, grand livre, FEC, autres pièces). Le rapprochement se
fait donc entre l'échéancier théorique et ces pièces, via une
correspondance DÉTERMINISTE et simple :

- une pièce ``etats_financiers`` couvre l'obligation « États
  financiers » de l'exercice ;
- une pièce ``autre`` est rattachée à un impôt par les mots (tokens) de
  son nom de fichier (« tva », « its », « patente », « bic »…), avec
  détection optionnelle du mois (période) — sans mois détecté, la pièce
  couvre toutes les périodes de l'impôt (simplification prudente à
  vérifier par l'humain) ;
- les pièces comptables (balance, grand livre, FEC) ne couvrent aucune
  obligation déclarative.

Analyse CONSULTATIVE : une échéance « manquante » signale seulement
qu'aucune pièce correspondante n'a été collectée — le fiscaliste vérifie
auprès du client avant toute conclusion. Aucun LLM, aucun calcul
d'impôt : fonctions pures + lecture seule sous RLS.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.echeancier_fiscal import (
    _MOIS_FR,
    ErreurEcheancierIntrouvable,
    echeancier_mission,
)

# ── Constantes de statut du rapprochement ────────────────────────────

STATUT_COUVERTE: Final[str] = "couverte"
STATUT_EN_ATTENTE: Final[str] = "en_attente"
STATUT_MANQUANTE: Final[str] = "manquante"

MENTION_NOTE: Final[str] = (
    "Rapprochement consultatif entre l'échéancier théorique de "
    "l'exercice et les pièces collectées en data room de mission — "
    "l'application ne stocke pas les déclarations déposées : une "
    "échéance « manquante » signifie seulement qu'aucune pièce "
    "correspondante n'a été collectée. À vérifier par le fiscaliste."
)

# Impôt de l'échéancier reconnu depuis un token du nom de fichier.
_IMPOT_PAR_TOKEN: Final[dict[str, str]] = {
    "tva": "TVA",
    "its": "ITS",
    "patente": "Patente",
    "patentes": "Patente",
    "irc": "IRC/IRCM",
    "ircm": "IRC/IRCM",
    "bic": "IS/BIC",
    "is": "IS/BIC",
    "resultat": "IS/BIC",
    "tee": "Taxe de l'entreprenant",
    "tce": "Taxe de l'entreprenant",
    "entreprenant": "Taxe de l'entreprenant",
    "ime": "Impôt des microentreprises",
    "microentreprise": "Impôt des microentreprises",
    "microentreprises": "Impôt des microentreprises",
}


class ErreurCivismeFiscal(Exception):
    """Échec de l'analyse de civisme fiscal."""


class ErreurCivismeIntrouvable(ErreurCivismeFiscal):
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


def elements_depuis_pieces(
    pieces: list[dict[str, Any]], exercice: int
) -> list[dict[str, Any]]:
    """PUR — éléments collectés déductibles des pièces de la data room.

    Chaque élément : ``{impot, periode, source}`` ; ``periode`` à None
    signifie « couvre toutes les périodes de l'impôt » (simplification
    documentée en tête de module). Correspondance déterministe :

    - ``etats_financiers`` → impôt « États financiers » ;
    - ``autre`` → impôts reconnus dans les tokens du nom de fichier
      (voir ``_IMPOT_PAR_TOKEN``), période mensuelle si un mois français
      figure dans le nom (ex. « declaration_tva_janvier.pdf ») ;
    - balance / grand_livre / fec → aucun élément (pièces comptables).
    """
    elements: list[dict[str, Any]] = []
    for piece in pieces:
        type_piece = str(piece.get("type_piece") or "")
        nom = str(piece.get("nom_fichier") or "")
        source = f"data room : {nom or type_piece}"
        if type_piece == "etats_financiers":
            elements.append(
                {"impot": "États financiers", "periode": None, "source": source}
            )
            continue
        if type_piece != "autre":
            continue  # Pièces comptables : pas des déclarations.
        tokens = _tokens(nom)
        impots: list[str] = []
        for t in tokens:
            impot = _IMPOT_PAR_TOKEN.get(t)
            if impot and impot not in impots:
                impots.append(impot)
        if "etats" in tokens and "financiers" in tokens:
            impots.append("États financiers")
        mois_detectes = [m for m in _MOIS_FR if _cle(m) in tokens]
        for impot in impots:
            if mois_detectes:
                for mois in mois_detectes:
                    elements.append(
                        {
                            "impot": impot,
                            "periode": f"{mois} {exercice}",
                            "source": source,
                        }
                    )
            else:
                elements.append(
                    {"impot": impot, "periode": None, "source": source}
                )
    return elements


def _element_correspondant(
    echeance: dict[str, Any], elements_collectes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Premier élément couvrant l'échéance (impôt égal, période égale
    ou élément sans période = couvre toutes les périodes)."""
    impot = _cle(echeance.get("impot"))
    periode = _cle(echeance.get("periode"))
    for element in elements_collectes:
        if _cle(element.get("impot")) != impot:
            continue
        periode_element = element.get("periode")
        if periode_element in (None, "") or _cle(periode_element) == periode:
            return element
    return None


def rapprocher(
    echeances: list[dict[str, Any]],
    elements_collectes: list[dict[str, Any]],
    aujourd_hui: date,
) -> list[dict[str, Any]]:
    """PUR — statut de chaque échéance théorique face au collecté.

    Pour chaque échéance (items de ``construire_echeancier`` : impot,
    obligation, periode, date_limite ISO) :

    - ``couverte`` : un élément collecté correspond (par impôt et
      période — voir :func:`_element_correspondant`) ;
    - ``en_attente`` : échéance non couverte dont la date limite n'est
      pas encore atteinte (``>= aujourd_hui``) ;
    - ``manquante`` : échéance passée non couverte.

    L'ordre des échéances est conservé. ``source`` trace la pièce qui
    couvre l'échéance (None sinon).
    """
    rapprochement: list[dict[str, Any]] = []
    for echeance in echeances:
        date_limite = date.fromisoformat(str(echeance["date_limite"]))
        element = _element_correspondant(echeance, elements_collectes)
        if element is not None:
            statut = STATUT_COUVERTE
        elif date_limite >= aujourd_hui:
            statut = STATUT_EN_ATTENTE
        else:
            statut = STATUT_MANQUANTE
        rapprochement.append(
            {
                "impot": str(echeance.get("impot") or ""),
                "obligation": str(echeance.get("obligation") or ""),
                "periode": str(echeance.get("periode") or ""),
                "date_limite": date_limite.isoformat(),
                "statut": statut,
                "source": element["source"] if element else None,
            }
        )
    return rapprochement


def synthese_rapprochement(
    rapprochement: list[dict[str, Any]],
) -> dict[str, Any]:
    """PUR — compteurs + taux de civisme (str Decimal en %).

    ``taux_civisme`` = couvertes / (couvertes + manquantes) × 100,
    arrondi à 0.01 (les échéances « en_attente » ne sont pas encore
    exigées : elles sont exclues du taux). Sans échéance exigible →
    « 100.00 » (rien à reprocher).
    """
    couvertes = sum(
        1 for r in rapprochement if r["statut"] == STATUT_COUVERTE
    )
    en_attente = sum(
        1 for r in rapprochement if r["statut"] == STATUT_EN_ATTENTE
    )
    manquantes = sum(
        1 for r in rapprochement if r["statut"] == STATUT_MANQUANTE
    )
    base = couvertes + manquantes
    if base == 0:
        taux = Decimal("100.00")
    else:
        taux = (Decimal(couvertes) * Decimal("100") / Decimal(base)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return {
        "couvertes": couvertes,
        "en_attente": en_attente,
        "manquantes": manquantes,
        "taux_civisme": str(taux),
    }


# ── Lecture par mission (RLS) ────────────────────────────────────────


def analyse_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
    *,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Analyse de civisme fiscal de la mission (lecture seule, RLS).

    Réutilise :func:`echeancier_mission` (échéancier théorique de
    l'exercice revu) puis rapproche les pièces de la data room
    (``piece_mission``). Mission hors tenant →
    :class:`ErreurCivismeIntrouvable` (404 côté route).
    """
    jour = aujourd_hui or date.today()
    # echeancier_mission ouvre son propre contexte_tenant : appel HORS
    # de tout autre with contexte_tenant.
    try:
        echeancier = echeancier_mission(session, tenant_id, mission_id)
    except ErreurEcheancierIntrouvable as e:
        raise ErreurCivismeIntrouvable(str(e)) from e

    with contexte_tenant(session, tenant_id):
        pieces = session.execute(
            text(
                "SELECT type_piece, nom_fichier FROM piece_mission "
                "WHERE mission_id = :m ORDER BY id"
            ),
            {"m": mission_id},
        ).mappings().all()

    elements = elements_depuis_pieces(
        [dict(p) for p in pieces], int(echeancier["exercice"])
    )
    rapprochement = rapprocher(echeancier["echeances"], elements, jour)
    return {
        "mission_id": mission_id,
        "exercice": echeancier["exercice"],
        "regime": echeancier["regime"],
        "aujourd_hui": jour.isoformat(),
        "elements_collectes": elements,
        "rapprochement": rapprochement,
        "synthese": synthese_rapprochement(rapprochement),
        "note": MENTION_NOTE,
    }
