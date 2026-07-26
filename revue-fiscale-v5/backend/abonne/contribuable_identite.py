"""Validation identité légale contribuable (PM / PP).

Aucune règle de calcul fiscal — contrôles de complétude documentaire uniquement.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


class ErreurIdentiteLegale(Exception):
    """Fiche contribuable incomplète pour la forme déclarée."""


COLONNES_IDENTITE = (
    "denomination",
    "ncc",
    "rccm",
    "forme",
    "dfe",
    "regime_fiscal",
    "forme_juridique",
    "siege_social",
    "commune",
    "centre_impots",
    "capital_social",
    "mois_cloture",
    "activite_principale",
    "date_immatriculation",
)

FORMES_VALIDES = frozenset({"pm", "pp"})


def _strip(val: object | None) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _capital_social(val: object | None) -> Decimal | None:
    if val is None or val == "":
        return None
    try:
        d = Decimal(str(val).replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError) as e:
        raise ErreurIdentiteLegale("capital_social invalide") from e
    if d < 0:
        raise ErreurIdentiteLegale("capital_social négatif interdit")
    return d.quantize(Decimal("0.01"))


def _mois_cloture(val: object | None) -> int | None:
    if val is None or val == "":
        return None
    try:
        m = int(val)
    except (TypeError, ValueError) as e:
        raise ErreurIdentiteLegale("mois_cloture invalide (1–12)") from e
    if m < 1 or m > 12:
        raise ErreurIdentiteLegale("mois_cloture invalide (1–12)")
    return m


def _date_immatriculation(val: object | None) -> date | None:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError as e:
        raise ErreurIdentiteLegale(
            "date_immatriculation invalide (YYYY-MM-DD)"
        ) from e


def serialiser_identite(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise types DB → JSON (Decimal, date, timestamptz)."""
    out = dict(row)
    cap = out.get("capital_social")
    if isinstance(cap, Decimal):
        out["capital_social"] = float(cap)
    elif cap is not None:
        out["capital_social"] = float(cap)
    di = out.get("date_immatriculation")
    if isinstance(di, (date, datetime)):
        out["date_immatriculation"] = di.isoformat()[:10]
    cree = out.get("cree_le")
    if isinstance(cree, datetime):
        out["cree_le"] = cree.isoformat()
    return out


def normaliser_payload(
    *,
    denomination: str,
    ncc: str | None = None,
    rccm: str | None = None,
    forme: str | None = None,
    dfe: str | None = None,
    regime_fiscal: str | None = None,
    forme_juridique: str | None = None,
    siege_social: str | None = None,
    commune: str | None = None,
    centre_impots: str | None = None,
    capital_social: object | None = None,
    mois_cloture: object | None = None,
    activite_principale: str | None = None,
    date_immatriculation: object | None = None,
) -> dict[str, Any]:
    f = _strip(forme)
    if f is not None and f not in FORMES_VALIDES:
        raise ErreurIdentiteLegale("forme invalide (pm|pp)")
    fj = _strip(forme_juridique)
    # PP : forme juridique métier = EI si absente
    if f == "pp" and not fj:
        fj = "EI"
    mois = _mois_cloture(mois_cloture)
    # Défaut pratique CI : année civile (décembre) si non saisi
    if mois is None:
        mois = 12
    return {
        "denomination": denomination.strip(),
        "ncc": _strip(ncc),
        "rccm": _strip(rccm),
        "forme": f,
        "dfe": _strip(dfe),
        "regime_fiscal": _strip(regime_fiscal),
        "forme_juridique": fj,
        "siege_social": _strip(siege_social),
        "commune": _strip(commune),
        "centre_impots": _strip(centre_impots),
        "capital_social": _capital_social(capital_social),
        "mois_cloture": mois,
        "activite_principale": _strip(activite_principale),
        "date_immatriculation": _date_immatriculation(date_immatriculation),
    }


def valider_identite_legale(payload: dict[str, Any], *, strict: bool = True) -> None:
    """Exige les pièces d'identité selon PM / PP.

    ``strict=True`` (création / enregistrement fiche) :
    - commun : denomination, ncc, forme, regime_fiscal, mois_cloture
    - PM : rccm, forme_juridique
    - PP : forme_juridique (EI par défaut)

    DFE : optionnel — le n° figurant sur la DFE est en pratique le NCC.
    Commune, adresse, centre des impôts, capital, activité : jauge UI, non
    bloquants API (sauf si présents et invalides à la normalisation).
    """
    if not payload.get("denomination"):
        raise ErreurIdentiteLegale("dénomination obligatoire")
    manquants: list[str] = []
    if not payload.get("ncc"):
        manquants.append("ncc")
    if not payload.get("forme"):
        manquants.append("forme (pm|pp)")
    if not payload.get("regime_fiscal"):
        manquants.append("regime_fiscal")
    if not payload.get("mois_cloture"):
        manquants.append("mois_cloture")

    forme = payload.get("forme")
    if forme == "pm":
        if not payload.get("rccm"):
            manquants.append("rccm")
        if not payload.get("forme_juridique"):
            manquants.append("forme_juridique")
    elif forme == "pp":
        if not payload.get("forme_juridique"):
            manquants.append("forme_juridique")

    if manquants and strict:
        raise ErreurIdentiteLegale(
            "identité légale incomplète : " + ", ".join(manquants)
        )


def completude_identite(payload: dict[str, Any]) -> dict[str, Any]:
    """Score documentaire pour l'UI (0–100) + cases manquantes."""
    forme = payload.get("forme") or "pm"
    if forme == "pm":
        cases = [
            ("denomination", "Dénomination"),
            ("ncc", "NCC"),
            ("rccm", "RCCM"),
            ("forme_juridique", "Forme juridique"),
            ("regime_fiscal", "Régime fiscal"),
            ("capital_social", "Capital social"),
            ("mois_cloture", "Clôture d'exercice"),
            ("activite_principale", "Secteur / activité"),
            ("commune", "Commune / ville"),
            ("siege_social", "Adresse du siège"),
            ("centre_impots", "Centre des impôts"),
        ]
    else:
        cases = [
            ("denomination", "Nom / dénomination"),
            ("ncc", "NCC"),
            ("regime_fiscal", "Régime fiscal"),
            ("mois_cloture", "Clôture d'exercice"),
            ("activite_principale", "Secteur / activité"),
            ("commune", "Commune / ville"),
            ("centre_impots", "Centre des impôts"),
        ]
    faits = [c for c, _ in cases if payload.get(c) not in (None, "")]
    total = len(cases)
    ok = len(faits)
    manquants = [lib for cle, lib in cases if payload.get(cle) in (None, "")]
    cles_manquantes = [cle for cle, _ in cases if payload.get(cle) in (None, "")]
    return {
        "forme": forme,
        "ok": ok,
        "total": total,
        "pct": int(round(100 * ok / total)) if total else 0,
        "manquants": manquants,
        "cles_manquantes": cles_manquantes,
        "complet": ok == total,
    }
