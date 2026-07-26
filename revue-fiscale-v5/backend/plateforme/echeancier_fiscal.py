"""Échéancier déclaratif indicatif par régime fiscal (Côte d'Ivoire).

RÉFÉRENTIEL INDICATIF — pratique usuelle CI encodée en constantes.
Ce module NE REMPLACE PAS le calendrier officiel de la DGI : les dates
limites réelles peuvent varier (taille de l'entreprise, centre des
impôts, actualité fiscale). Objectif : rappel proactif pour le cabinet,
afin d'anticiper les échéances de ses clients et d'éviter pénalités et
intérêts de retard. Aucun calcul d'impôt ici — uniquement des dates.

Régimes couverts (valeurs canoniques de ``contribuable.regime_fiscal``) :
- ``reel`` (RNI — réel normal d'imposition) ;
- ``reel_simplifie`` (RSI — réel simplifié d'imposition) ;
- ``tee`` / ``tce`` (taxe de l'entreprenant) et ``ime`` (microentreprise).

Régime inconnu ou vide → liste vide, sans erreur (défensif).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any, Final

# ── Constantes de statut ─────────────────────────────────────────────

STATUT_A_VENIR: Final[str] = "a_venir"
STATUT_IMMINENTE: Final[str] = "imminente"
STATUT_DEPASSEE: Final[str] = "depassee"

# Une échéance à moins de 15 jours est « imminente ».
SEUIL_IMMINENCE_JOURS: Final[int] = 15
# Les échéances dépassées restent visibles 30 jours (rappel de retard).
RETARD_VISIBLE_JOURS: Final[int] = 30
# Horizon de projection par défaut.
HORIZON_JOURS_DEFAUT: Final[int] = 90

# ── Alias régimes (tolérance de saisie) ──────────────────────────────

_ALIAS_REGIME: Final[dict[str, str]] = {
    "reel": "reel",
    "rni": "reel",
    "reel_normal": "reel",
    "reel_simplifie": "reel_simplifie",
    "rsi": "reel_simplifie",
    "tee": "tee",
    "tce": "tee",
    "ime": "ime",
    "micro": "ime",
    "microentreprise": "ime",
}

# ── Référentiel indicatif des obligations déclaratives ───────────────
# Chaque obligation : code, libelle, periodicite (mensuelle |
# trimestrielle | annuelle), jour_limite, mois_limite (annuelles :
# mois pour une clôture en décembre — décalé si clôture ≠ décembre),
# decalable_cloture (True si l'échéance suit l'exercice comptable),
# impots (impôts concernés, libellés indicatifs).

_TVA_MENSUELLE: Final[dict[str, Any]] = {
    "code": "tva_mensuelle",
    "libelle": "Déclaration et paiement TVA du mois précédent",
    "periodicite": "mensuelle",
    "jour_limite": 15,
    "decalable_cloture": False,
    "impots": ["TVA"],
}

_ITS_RETENUES_MENSUELLES: Final[dict[str, Any]] = {
    "code": "its_retenues_mensuelles",
    "libelle": "ITS et retenues à la source du mois précédent",
    "periodicite": "mensuelle",
    "jour_limite": 15,
    "decalable_cloture": False,
    "impots": ["ITS", "Retenues à la source"],
}

_RESULTAT_ANNUEL: Final[dict[str, Any]] = {
    "code": "resultat_annuel",
    "libelle": "Déclaration annuelle de résultat (BIC/IS)",
    "periodicite": "annuelle",
    "jour_limite": 30,
    "mois_limite": 4,  # 30/04 pour clôture décembre (pratique PM).
    "decalable_cloture": True,
    "impots": ["BIC", "IS"],
}

_ETATS_FINANCIERS: Final[dict[str, Any]] = {
    "code": "etats_financiers",
    "libelle": "Dépôt des états financiers (SYSCOHADA / DGI)",
    "periodicite": "annuelle",
    "jour_limite": 30,
    "mois_limite": 6,  # 30/06 pour clôture décembre (selon calendrier).
    "decalable_cloture": True,
    "impots": ["États financiers"],
}

_PATENTE_ANNUELLE: Final[dict[str, Any]] = {
    "code": "patente_annuelle",
    "libelle": "Contribution des patentes (déclaration annuelle)",
    "periodicite": "annuelle",
    "jour_limite": 15,
    "mois_limite": 3,  # Pratique usuelle — date civile, non décalée.
    "decalable_cloture": False,
    "impots": ["Patente"],
}

_TEE_MENSUELLE: Final[dict[str, Any]] = {
    "code": "tee_mensuelle",
    "libelle": "Déclaration simplifiée mensuelle (taxe de l'entreprenant)",
    "periodicite": "mensuelle",
    "jour_limite": 10,
    "decalable_cloture": False,
    "impots": ["Taxe de l'entreprenant"],
}

_IME_TRIMESTRIELLE: Final[dict[str, Any]] = {
    "code": "ime_trimestrielle",
    "libelle": "Déclaration simplifiée trimestrielle (microentreprise)",
    "periodicite": "trimestrielle",
    "jour_limite": 15,
    "decalable_cloture": False,
    "impots": ["Impôt des microentreprises"],
}

OBLIGATIONS_PAR_REGIME: Final[dict[str, tuple[dict[str, Any], ...]]] = {
    # Réel normal (RNI) : TVA + ITS mensuelles, résultat + états
    # financiers + patente annuels.
    "reel": (
        _TVA_MENSUELLE,
        _ITS_RETENUES_MENSUELLES,
        _RESULTAT_ANNUEL,
        _ETATS_FINANCIERS,
        _PATENTE_ANNUELLE,
    ),
    # Réel simplifié (RSI) : TVA mensuelle + résultat annuel.
    "reel_simplifie": (
        _TVA_MENSUELLE,
        _RESULTAT_ANNUEL,
        _PATENTE_ANNUELLE,
    ),
    # Taxe de l'entreprenant (TEE/TCE) : déclaration mensuelle simplifiée.
    "tee": (_TEE_MENSUELLE,),
    # Microentreprise (IME) : déclaration trimestrielle simplifiée.
    "ime": (_IME_TRIMESTRIELLE,),
}


# ── Fonctions pures ──────────────────────────────────────────────────


def normaliser_regime(regime: str | None) -> str | None:
    """Régime canonique (clé de ``OBLIGATIONS_PAR_REGIME``) ou None."""
    if regime is None:
        return None
    cle = str(regime).strip().lower()
    return _ALIAS_REGIME.get(cle)


def _date_clampee(annee: int, mois: int, jour: int) -> date:
    """Date au jour demandé, bornée à la fin du mois (ex. 30/02 → 28/02)."""
    dernier = calendar.monthrange(annee, mois)[1]
    return date(annee, mois, min(jour, dernier))


def _mois_annuel_effectif(obligation: dict[str, Any], mois_cloture: int) -> int:
    """Mois de l'échéance annuelle, décalé selon le mois de clôture.

    ``mois_limite`` est exprimé pour une clôture en décembre (année
    civile). Une clôture en mois M décale l'échéance de (M − 12) mois :
    ex. résultat à +4 mois après clôture → clôture juin (6) ⇒ octobre.
    """
    mois_limite = int(obligation["mois_limite"])
    if not obligation.get("decalable_cloture") or mois_cloture == 12:
        return mois_limite
    return ((mois_limite + mois_cloture - 12 - 1) % 12) + 1


def _statut(date_limite: date, date_reference: date) -> str:
    if date_limite < date_reference:
        return STATUT_DEPASSEE
    if (date_limite - date_reference).days < SEUIL_IMMINENCE_JOURS:
        return STATUT_IMMINENTE
    return STATUT_A_VENIR


def _occurrences(
    obligation: dict[str, Any],
    debut: date,
    fin: date,
    mois_cloture: int,
) -> list[date]:
    """Dates limites de l'obligation dans [debut, fin] (bornes incluses)."""
    jour = int(obligation["jour_limite"])
    periodicite = str(obligation["periodicite"])
    dates: list[date] = []
    if periodicite == "annuelle":
        mois = _mois_annuel_effectif(obligation, mois_cloture)
        for annee in range(debut.year, fin.year + 1):
            d = _date_clampee(annee, mois, jour)
            if debut <= d <= fin:
                dates.append(d)
        return dates
    # Mensuelle / trimestrielle : on parcourt les mois de la fenêtre.
    mois_trimestriels = {1, 4, 7, 10}  # Mois suivant chaque trimestre civil.
    annee, mois = debut.year, debut.month
    while (annee, mois) <= (fin.year, fin.month):
        if periodicite == "mensuelle" or (
            periodicite == "trimestrielle" and mois in mois_trimestriels
        ):
            d = _date_clampee(annee, mois, jour)
            if debut <= d <= fin:
                dates.append(d)
        mois += 1
        if mois > 12:
            mois, annee = 1, annee + 1
    return dates


def prochaines_echeances(
    regime: str | None,
    date_reference: date,
    horizon_jours: int = HORIZON_JOURS_DEFAUT,
    mois_cloture: int | None = None,
) -> list[dict[str, Any]]:
    """Échéances déclaratives indicatives autour de ``date_reference``.

    Fenêtre : dépassées récentes (≤ 30 jours) + à venir sur
    ``horizon_jours``. Régime inconnu/None → liste vide (sans erreur).
    ``mois_cloture`` (1–12, défaut décembre) décale les annuelles liées
    à l'exercice. Résultat trié par date limite croissante.

    RÉFÉRENTIEL INDICATIF — vérifier le calendrier officiel DGI.
    """
    cle = normaliser_regime(regime)
    if cle is None:
        return []
    obligations = OBLIGATIONS_PAR_REGIME.get(cle, ())
    mc = mois_cloture if mois_cloture in range(1, 13) else 12
    debut = date_reference - timedelta(days=RETARD_VISIBLE_JOURS)
    fin = date_reference + timedelta(days=max(0, int(horizon_jours)))
    resultat: list[dict[str, Any]] = []
    for obligation in obligations:
        for d in _occurrences(obligation, debut, fin, mc):
            resultat.append(
                {
                    "code": str(obligation["code"]),
                    "libelle": str(obligation["libelle"]),
                    "periodicite": str(obligation["periodicite"]),
                    "impots": list(obligation["impots"]),
                    "date_limite": d.isoformat(),
                    "jours_restants": (d - date_reference).days,
                    "statut": _statut(d, date_reference),
                }
            )
    resultat.sort(key=lambda e: (e["date_limite"], e["code"]))
    return resultat
