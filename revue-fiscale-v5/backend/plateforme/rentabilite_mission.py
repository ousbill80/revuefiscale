"""Paramètres et calcul de rentabilité d'une mission.

POURQUOI : le cabinet convient d'HONORAIRES forfaitaires par mission et
applique un TAUX HORAIRE standard interne pour valoriser le temps passé.
La rentabilité se pilote ainsi : coût estimé = heures saisies × taux
horaire ; marge estimée = honoraires − coût ; taux de marge =
marge / honoraires × 100. Les deux paramètres sont portés par la table
``mission`` (colonnes nullables — migration 040) : tant qu'ils ne sont
pas renseignés, les indicateurs correspondants restent ``null`` sans
bloquer la saisie des temps.

Module déterministe, aucun appel LLM, RLS stricte via
:func:`contexte_tenant`. Le calcul est une fonction pure
(:func:`calculer_rentabilite`) en :class:`~decimal.Decimal` — jamais de
float — testable sans base.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# Note consultative — TOUJOURS présente dans la charge utile : la
# rentabilité est un indicateur interne de pilotage, pas un document
# opposable ni une base de facturation.
NOTE_RENTABILITE: Final = (
    "Indicateur interne de pilotage du cabinet, fourni à titre "
    "consultatif : il ne préjuge ni de la facturation ni des honoraires "
    "convenus avec le client."
)

# Seuils consultatifs sur le pourcentage d'honoraires consommé par le
# temps valorisé : < 80 % ok, 80-100 % vigilance, > 100 % dépassement.
SEUIL_VIGILANCE_PCT: Final = Decimal("80")
SEUIL_DEPASSEMENT_PCT: Final = Decimal("100")


def seuil_consommation(pourcentage: Decimal | None) -> str | None:
    """PUR — seuil consultatif du budget d'honoraires consommé.

    ``None`` (pourcentage incalculable) → ``None`` ; sinon « ok »
    (< 80 %), « vigilance » (80-100 % inclus) ou « depassement »
    (> 100 %).
    """
    if pourcentage is None:
        return None
    if pourcentage < SEUIL_VIGILANCE_PCT:
        return "ok"
    if pourcentage <= SEUIL_DEPASSEMENT_PCT:
        return "vigilance"
    return "depassement"


def totaux_heures_par_intervenant(
    entrees: list[dict[str, Any]],
) -> dict[str, str]:
    """PUR — cumul d'heures par intervenant, ordre d'heures décroissant.

    ``entrees`` : dictionnaires portant ``collaborateur`` et ``heures``
    (str Decimal). Retourne {intervenant: heures str} — à volume égal,
    ordre alphabétique (stable, déterministe).
    """
    totaux: dict[str, Decimal] = {}
    for e in entrees:
        nom = str(e["collaborateur"])
        totaux[nom] = totaux.get(nom, Decimal("0")) + Decimal(
            str(e["heures"])
        )
    tri = sorted(totaux.items(), key=lambda kv: (-kv[1], kv[0]))
    return {nom: _fmt(h) for nom, h in tri}


def _fmt(d: Decimal) -> str:
    """Décimal → texte stable, sans notation scientifique ni zéros finaux."""
    return format(d.normalize(), "f")


class ErreurRentabilite(Exception):
    """Paramètre de rentabilité invalide (négatif, non numérique) — 422."""


class ErreurRentabiliteIntrouvable(ErreurRentabilite):
    """Mission hors périmètre du tenant — 404."""


def _valider_montant(valeur: Any, libelle: str) -> Decimal | None:
    """Montant >= 0, deux décimales max — ``None`` conservé (effacement)."""
    if valeur is None:
        return None
    try:
        m = Decimal(str(valeur))
    except (InvalidOperation, ValueError) as e:
        raise ErreurRentabilite(f"{libelle} invalide « {valeur} »") from e
    if not m.is_finite() or m < 0:
        raise ErreurRentabilite(
            f"{libelle} invalide « {valeur} » — attendu : montant >= 0"
        )
    if -m.as_tuple().exponent > 2:
        raise ErreurRentabilite(
            f"{libelle} invalide « {valeur} » — deux décimales maximum"
        )
    return m


def calculer_rentabilite(
    honoraires: Any,
    taux_horaire: Any,
    total_heures: Any,
) -> dict[str, Any]:
    """PUR — indicateurs de rentabilité d'une mission (Decimal, pas float).

    - ``cout_estime`` : heures × taux horaire — ``null`` sans taux ;
    - ``marge_estimee`` : honoraires − coût — ``null`` si l'un des deux
      paramètres manque (on ne fait pas croire à une marge sans base) ;
    - ``taux_marge_pct`` : marge / honoraires × 100, arrondi commercial à
      une décimale — ``null`` si honoraires absents ou nuls (division) ;
    - ``pourcentage_consomme`` : coût / honoraires × 100 (une décimale) —
      part du budget d'honoraires consommée par le temps valorisé ;
    - ``seuil`` : lecture consultative du pourcentage consommé
      (:func:`seuil_consommation`) ;
    - ``note`` : mention consultative, toujours présente.
    """
    h = _valider_montant(honoraires, "honoraires")
    t = _valider_montant(taux_horaire, "taux horaire")
    heures = Decimal(str(total_heures))

    cout: Decimal | None = None if t is None else heures * t
    marge: Decimal | None = (
        None if (h is None or cout is None) else h - cout
    )
    taux_pct: Decimal | None = None
    consomme: Decimal | None = None
    if cout is not None and h is not None and h > 0:
        taux_pct = ((h - cout) / h * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        consomme = (cout / h * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
    return {
        "honoraires": None if h is None else _fmt(h),
        "taux_horaire": None if t is None else _fmt(t),
        "total_heures": _fmt(heures),
        "cout_estime": None if cout is None else _fmt(cout),
        "marge_estimee": None if marge is None else _fmt(marge),
        "taux_marge_pct": None if taux_pct is None else format(taux_pct, "f"),
        "pourcentage_consomme": (
            None if consomme is None else format(consomme, "f")
        ),
        "seuil": seuil_consommation(consomme),
        "note": NOTE_RENTABILITE,
    }


def definir_parametres(
    session: Session,
    tenant_id: int,
    mission_id: int,
    honoraires: Any = None,
    taux_horaire: Any = None,
) -> dict[str, Any]:
    """Enregistre les paramètres de rentabilité de la mission.

    ``None`` efface le paramètre (retour à « non convenu »). Valeur
    négative ou non numérique → :class:`ErreurRentabilite` (422).
    Mission hors périmètre du tenant (RLS) →
    :class:`ErreurRentabiliteIntrouvable` (404). Retourne les paramètres
    enregistrés, sérialisés.
    """
    h = _valider_montant(honoraires, "honoraires")
    t = _valider_montant(taux_horaire, "taux horaire")
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE mission SET honoraires = :h, taux_horaire = :t "
                "WHERE id = :m RETURNING honoraires, taux_horaire"
            ),
            {"h": h, "t": t, "m": mission_id},
        ).mappings().one_or_none()
    if row is None:
        raise ErreurRentabiliteIntrouvable(
            f"mission {mission_id} introuvable"
        )
    return {
        "honoraires": (
            None if row["honoraires"] is None
            else _fmt(Decimal(str(row["honoraires"])))
        ),
        "taux_horaire": (
            None if row["taux_horaire"] is None
            else _fmt(Decimal(str(row["taux_horaire"])))
        ),
    }


def rentabilite_mission(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, Any]:
    """Rentabilité de la mission : paramètres, coût, marge, taux de marge.

    Lit sous RLS les paramètres de la mission et les temps saisis
    (``temps_mission``), puis délègue le calcul aux fonctions pures
    :func:`calculer_rentabilite` et :func:`totaux_heures_par_intervenant`
    (clé ``heures_par_intervenant``). Mission hors périmètre du tenant
    → :class:`ErreurRentabiliteIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT m.honoraires, m.taux_horaire, "
                "COALESCE(SUM(t.heures), 0) AS total_heures "
                "FROM mission m "
                "LEFT JOIN temps_mission t ON t.mission_id = m.id "
                "WHERE m.id = :m GROUP BY m.honoraires, m.taux_horaire"
            ),
            {"m": mission_id},
        ).mappings().one_or_none()
        entrees = session.execute(
            text(
                "SELECT collaborateur, heures FROM temps_mission "
                "WHERE mission_id = :m ORDER BY id"
            ),
            {"m": mission_id},
        ).mappings().all()
    if row is None:
        raise ErreurRentabiliteIntrouvable(
            f"mission {mission_id} introuvable"
        )
    resultat = calculer_rentabilite(
        honoraires=row["honoraires"],
        taux_horaire=row["taux_horaire"],
        total_heures=row["total_heures"],
    )
    resultat["heures_par_intervenant"] = totaux_heures_par_intervenant(
        [dict(e) for e in entrees]
    )
    return resultat


# ── Suivi budgétaire des missions (tableau de bord cabinet) ──────────

# Plafond d'items retournés — liste opérationnelle, pas un export.
PLAFOND_ITEMS_CABINET: Final = 50

# Note consultative du bloc cabinet — TOUJOURS présente.
NOTE_RENTABILITE_CABINET: Final = (
    "Suivi consultatif du budget temps des missions en cours : le "
    "pourcentage d'honoraires consommé est un indicateur interne de "
    "pilotage du cabinet, il ne préjuge ni de la facturation ni des "
    "honoraires convenus avec chaque client."
)

# Ordre d'affichage des seuils sous tension : dépassement avant vigilance.
_RANG_SEUIL: Final = {"depassement": 0, "vigilance": 1}


def item_rentabilite_cabinet(agregat: dict[str, Any]) -> dict[str, Any]:
    """PUR — item de suivi budgétaire d'une mission depuis ses agrégats.

    ``agregat`` : ``mission_id``, ``client``, ``exercice``,
    ``honoraires``, ``taux_horaire``, ``total_heures``. Délègue le
    calcul à :func:`calculer_rentabilite` et ne conserve que les champs
    du bloc cabinet (dont ``pourcentage_consomme`` et ``seuil``).
    """
    r = calculer_rentabilite(
        honoraires=agregat["honoraires"],
        taux_horaire=agregat["taux_horaire"],
        total_heures=agregat["total_heures"],
    )
    return {
        "mission_id": int(agregat["mission_id"]),
        "client": str(agregat.get("client") or ""),
        "exercice": int(agregat["exercice"]),
        "total_heures": r["total_heures"],
        "honoraires": r["honoraires"],
        "cout_estime": r["cout_estime"],
        "pourcentage_consomme": r["pourcentage_consomme"],
        "seuil": r["seuil"],
    }


def trier_rentabilite_cabinet(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — dépassements d'abord, puis pourcentage consommé décroissant.

    À pourcentage égal, ordre alphabétique des clients puis mission —
    tri stable et déterministe. Les items sans pourcentage (théoriques
    ici) vont en queue.
    """
    def _cle(i: dict[str, Any]) -> tuple:
        brut = i.get("pourcentage_consomme")
        pct = Decimal(str(brut)) if brut not in (None, "") else None
        return (
            _RANG_SEUIL.get(str(i.get("seuil")), 9),
            (1, Decimal("0")) if pct is None else (0, -pct),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
        )

    return sorted(items, key=_cle)


def synthese_rentabilite_cabinet(
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """PUR — compteurs : missions suivies, en vigilance, en dépassement.

    ``missions_suivies`` compte TOUTES les missions paramétrées (y
    compris « ok ») ; seules vigilance et dépassement ressortent en
    liste.
    """
    seuils = [str(i.get("seuil")) for i in items]
    return {
        "missions_suivies": len(items),
        "en_vigilance": seuils.count("vigilance"),
        "en_depassement": seuils.count("depassement"),
    }


def rentabilite_cabinet(session: Session, tenant_id: int) -> dict[str, Any]:
    """Suivi budgétaire des missions du cabinet (lecture, RLS).

    Missions NON clôturées dont honoraires ET taux horaire sont
    renseignés, avec le total d'heures saisies (une seule requête SQL,
    agrégat ``SUM``). Les items ne retiennent que les missions sous
    tension (« vigilance » 80-100 %, « dépassement » > 100 %), triées
    dépassement d'abord puis pourcentage décroissant, plafonnées à
    :data:`PLAFOND_ITEMS_CABINET` ; la synthèse compte toutes les
    missions suivies. Se construit toujours (tenant vide → liste vide).
    """
    from backend.plateforme.missions import STATUT_CLOTUREE

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, m.honoraires, "
                "m.taux_horaire, c.denomination AS client, "
                "COALESCE(SUM(t.heures), 0) AS total_heures "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "LEFT JOIN temps_mission t ON t.mission_id = m.id "
                "WHERE m.statut <> :clot "
                "AND m.honoraires IS NOT NULL "
                "AND m.taux_horaire IS NOT NULL "
                "GROUP BY m.id, m.exercice, m.honoraires, m.taux_horaire, "
                "c.denomination "
                "ORDER BY c.denomination, m.id"
            ),
            {"clot": STATUT_CLOTUREE},
        ).mappings().all()

    suivies = [item_rentabilite_cabinet(dict(r)) for r in rows]
    sous_tension = trier_rentabilite_cabinet(
        [i for i in suivies if i["seuil"] in ("vigilance", "depassement")]
    )
    return {
        "items": sous_tension[:PLAFOND_ITEMS_CABINET],
        "synthese": synthese_rentabilite_cabinet(suivies),
        "note": NOTE_RENTABILITE_CABINET,
    }


# En-tête du CSV de rentabilité — délimiteur « ; » (usage cabinet / Excel FR).
ENTETE_RENTABILITE_CSV: Final = ("rubrique", "cle", "heures", "montant_fcfa")


def exporter_rentabilite_csv(
    session: Session, tenant_id: int, mission_id: int
) -> tuple[str, bytes]:
    """CSV Excel FR (« ; ») : paramètres, temps valorisés, synthèse marge.

    Retourne (nom_fichier, contenu). Paramètres non renseignés (ni
    honoraires ni taux horaire) → :class:`ErreurRentabilite` (422) —
    l'export n'aurait aucune valorisation à montrer. Mission hors
    périmètre du tenant → :class:`ErreurRentabiliteIntrouvable` (404).
    """
    import csv
    import io

    from backend.plateforme.temps_mission import (
        ErreurTempsIntrouvable,
        recap_temps,
    )

    r = rentabilite_mission(session, tenant_id, mission_id)
    if r["honoraires"] is None and r["taux_horaire"] is None:
        raise ErreurRentabilite(
            "paramètres de rentabilité non renseignés "
            "(honoraires ou taux horaire)"
        )
    try:
        recap = recap_temps(session, tenant_id, mission_id)
    except ErreurTempsIntrouvable as e:  # pragma: no cover — même RLS
        raise ErreurRentabiliteIntrouvable(str(e)) from e
    taux = None if r["taux_horaire"] is None else Decimal(r["taux_horaire"])

    def _valorise(heures: str) -> str:
        """Heures × taux horaire (Decimal) — vide sans taux renseigné."""
        return "" if taux is None else _fmt(Decimal(heures) * taux)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(ENTETE_RENTABILITE_CSV)
    w.writerow(["parametre", "honoraires", "", r["honoraires"] or ""])
    w.writerow(["parametre", "taux_horaire", "", r["taux_horaire"] or ""])
    for phase, heures in recap["par_phase"].items():
        w.writerow(["par_phase", phase, heures, _valorise(heures)])
    for collab, heures in recap["par_collaborateur"].items():
        w.writerow(["par_collaborateur", collab, heures, _valorise(heures)])
    w.writerow([])
    w.writerow(["synthese", "total_heures", r["total_heures"], ""])
    w.writerow(["synthese", "cout_estime", "", r["cout_estime"] or ""])
    w.writerow(["synthese", "marge_estimee", "", r["marge_estimee"] or ""])
    w.writerow(["synthese", "taux_marge_pct", "", r["taux_marge_pct"] or ""])
    return (
        f"rentabilite_mission_{mission_id}.csv",
        buf.getvalue().encode("utf-8"),
    )
