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

Le module porte AUSSI l'« échéancier fiscal de la mission » : pour
l'exercice revu, le calendrier complet des obligations déclaratives et
de paiement du contribuable (:func:`construire_echeancier`, fonction
pure) et sa lecture par mission sous RLS (:func:`echeancier_mission`).
POURQUOI : dans la pratique d'un cabinet fiscaliste ivoirien, la revue
du respect du calendrier déclaratif est un contrôle de base — le
collaborateur confronte les dates de dépôt effectives du client aux
dates limites de l'exercice pour repérer les déclarations tardives
(pénalités et intérêts de retard du CGI CI). Hypothèses documentées
sur :func:`construire_echeancier`. Déterministe, aucun appel LLM.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

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


# ── Échéancier fiscal de la mission (exercice revu) ──────────────────
#
# HYPOTHÈSES RETENUES (pratique déclarative usuelle CI, simplifiée et
# assumée — vérifier le calendrier officiel DGI pour chaque dossier) :
# - TVA et ITS mensuels : au plus tard le 10 du mois suivant pour les
#   entreprises relevant de la DGE, le 15 pour le réel normal (RNI),
#   le 20 pour le réel simplifié (RSI) ;
# - déclaration de résultat BIC/IS et dépôt des états financiers :
#   30 avril N+1 (30 mai N+1 pour la DGE) ;
# - paiement fractionné BIC/IS : trois fractions en N+1 (avril, juin,
#   septembre), même règle de jour que la TVA (10 DGE / 15 / 20) ;
# - contribution des patentes : 15 mars de l'exercice ;
# - IRC/IRCM : reversement des retenues, le cas échéant, au plus tard
#   le 15 du mois suivant chaque trimestre civil.

_BASE_PRATIQUE: Final[str] = "CGI CI — pratique déclarative"

_MOIS_FR: Final[tuple[str, ...]] = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


class ErreurEcheancierIntrouvable(Exception):
    """Mission hors périmètre du tenant — 404 côté route."""


def _jour_mensuel(regime: str, dge: bool) -> int:
    """Jour limite des obligations mensuelles : 10 DGE, 15 RNI, 20 RSI."""
    if dge:
        return 10
    return 20 if regime == "reel_simplifie" else 15


def _item(
    impot: str,
    obligation: str,
    periode: str,
    date_limite: date,
    base_legale: str = _BASE_PRATIQUE,
) -> dict[str, Any]:
    return {
        "impot": impot,
        "obligation": obligation,
        "periode": periode,
        "date_limite": date_limite.isoformat(),
        "base_legale": base_legale,
    }


def _echeances_mensuelles(
    exercice: int, jour: int, impot: str, obligation: str
) -> list[dict[str, Any]]:
    """12 échéances : le mois M de l'exercice est dû le mois M+1."""
    items: list[dict[str, Any]] = []
    for mois in range(1, 13):
        annee_lim, mois_lim = (
            (exercice + 1, 1) if mois == 12 else (exercice, mois + 1)
        )
        items.append(
            _item(
                impot,
                obligation,
                f"{_MOIS_FR[mois - 1]} {exercice}",
                _date_clampee(annee_lim, mois_lim, jour),
            )
        )
    return items


def construire_echeancier(
    exercice: int, regime: str, dge: bool = False
) -> list[dict[str, Any]]:
    """PUR — échéancier des obligations fiscales de l'exercice revu.

    Chaque item : ``{impot, obligation, periode, date_limite (ISO),
    base_legale}``. Dates calculées via :class:`datetime.date`, jamais
    de LLM — testable sans base. Hypothèses de dates documentées en
    tête de section (référentiel indicatif, prudent : ``base_legale``
    renvoie à la pratique déclarative, pas à un article précis).

    Régime inconnu → traité comme réel normal (échéancier le plus
    complet : prudent pour une revue). TEE/IME → déclarations
    simplifiées uniquement. Trié par date limite croissante.
    """
    cle = normaliser_regime(regime) or "reel"
    items: list[dict[str, Any]] = []

    if cle == "tee":
        items += _echeances_mensuelles(
            exercice,
            10,
            "Taxe de l'entreprenant",
            "Déclaration et paiement mensuels simplifiés",
        )
    elif cle == "ime":
        for trimestre in range(1, 5):
            annee_lim, mois_lim = (
                (exercice + 1, 1)
                if trimestre == 4
                else (exercice, trimestre * 3 + 1)
            )
            items.append(
                _item(
                    "Impôt des microentreprises",
                    "Déclaration et paiement trimestriels simplifiés",
                    f"T{trimestre} {exercice}",
                    _date_clampee(annee_lim, mois_lim, 15),
                )
            )
    else:  # reel / reel_simplifie — jeu complet d'obligations.
        jour = _jour_mensuel(cle, dge)
        items += _echeances_mensuelles(
            exercice,
            jour,
            "TVA",
            "Déclaration et paiement de la TVA du mois",
        )
        items += _echeances_mensuelles(
            exercice,
            jour,
            "ITS",
            "Déclaration et reversement des ITS du mois",
        )
        # IRC/IRCM : reversement trimestriel des retenues, le cas échéant.
        for trimestre in range(1, 5):
            annee_lim, mois_lim = (
                (exercice + 1, 1)
                if trimestre == 4
                else (exercice, trimestre * 3 + 1)
            )
            items.append(
                _item(
                    "IRC/IRCM",
                    "Reversement des retenues IRC/IRCM (le cas échéant)",
                    f"T{trimestre} {exercice}",
                    _date_clampee(annee_lim, mois_lim, 15),
                )
            )
        # Patente de l'exercice — date civile, pratique usuelle.
        items.append(
            _item(
                "Patente",
                "Déclaration et paiement de la contribution des patentes",
                f"exercice {exercice}",
                date(exercice, 3, 15),
            )
        )
        # Résultat + états financiers : 30/04 N+1 (30/05 N+1 pour la DGE).
        mois_annuel = 5 if dge else 4
        date_annuelle = _date_clampee(exercice + 1, mois_annuel, 30)
        items.append(
            _item(
                "IS/BIC",
                "Déclaration annuelle de résultat (BIC/IS)",
                f"exercice {exercice}",
                date_annuelle,
            )
        )
        items.append(
            _item(
                "États financiers",
                "Dépôt des états financiers (SYSCOHADA / DGI)",
                f"exercice {exercice}",
                date_annuelle,
            )
        )
        # Paiement fractionné BIC/IS en N+1 : avril, juin, septembre.
        for rang, mois_fraction in enumerate((4, 6, 9), start=1):
            items.append(
                _item(
                    "IS/BIC",
                    f"Paiement fractionné de l'impôt BIC/IS ({rang}/3)",
                    f"exercice {exercice}",
                    _date_clampee(exercice + 1, mois_fraction, jour),
                )
            )

    items.sort(key=lambda e: (e["date_limite"], e["impot"], e["obligation"]))
    return items


def _profil_mission(profil: Any) -> dict[str, Any]:
    """Profil JSON de la mission — dict tolérant (str JSON ou None)."""
    if isinstance(profil, str):
        try:
            profil = json.loads(profil)
        except ValueError:
            profil = {}
    return profil if isinstance(profil, dict) else {}


def _releve_de_la_dge(centre_impots: Any) -> bool:
    """Vrai si le centre des impôts renvoie à la DGE (heuristique texte)."""
    libelle = str(centre_impots or "").lower()
    return "dge" in libelle or "grandes entreprises" in libelle


def echeancier_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Échéancier fiscal de l'exercice revu par la mission (RLS stricte).

    Lit l'exercice et le régime (profil JSON) de la mission, détecte la
    DGE depuis ``contribuable.centre_impots`` (heuristique texte), puis
    délègue à :func:`construire_echeancier` (pur). Mission hors tenant →
    :class:`ErreurEcheancierIntrouvable` (404 côté route). Retourne
    ``{mission_id, exercice, regime, dge, echeances, synthese: {total,
    par_impot}}`` — se construit toujours (aucun cas d'échec métier).
    """
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.exercice, m.profil, c.centre_impots "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.id = :m"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurEcheancierIntrouvable(f"mission {mission_id} introuvable")

    exercice = int(row["exercice"])
    profil = _profil_mission(row["profil"])
    regime = normaliser_regime(str(profil.get("regime") or "")) or "reel"
    dge = _releve_de_la_dge(row["centre_impots"])
    echeances = construire_echeancier(exercice, regime, dge=dge)

    par_impot: dict[str, int] = {}
    for e in echeances:
        par_impot[e["impot"]] = par_impot.get(e["impot"], 0) + 1
    return {
        "mission_id": mission_id,
        "exercice": exercice,
        "regime": regime,
        "dge": dge,
        "echeances": echeances,
        "synthese": {"total": len(echeances), "par_impot": par_impot},
    }
