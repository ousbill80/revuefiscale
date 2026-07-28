"""Fiche client consolidée — tout ce que le cabinet sait déjà.

POURQUOI : avant un rendez-vous, le fiscaliste veut UNE page pour un
contribuable donné : ses missions par exercice avec leurs statuts, les
points convenus encore ouverts (avec date cible dépassée ou non),
l'évolution pluriannuelle de sa charge fiscale déjà calculée par
:mod:`backend.plateforme.evolution_charge_fiscale`, et les signaux du
centre d'alertes (:mod:`backend.plateforme.centre_alertes`) qui le
concernent — sans ouvrir quatre écrans.

AUCUN recalcul : pure CONSOLIDATION de vues existantes. Chaque volet
est TOLÉRANT (try/except) : un volet en échec est listé dans
``volets_en_echec`` et ne bloque jamais la fiche — pattern
:mod:`backend.plateforme.centre_alertes`. Vue CONSULTATIVE et
déterministe : la fiche éclaire l'entretien, le fiscaliste apprécie et
le client décide. AUCUN LLM — lecture seule, sous RLS.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

# Plafond d'alertes restituées sur la fiche — synthèse d'entretien,
# pas un centre d'alertes complet (qui reste l'écran dédié).
PLAFOND_ALERTES_FICHE: Final[int] = 20

MENTION_NOTE: Final[str] = (
    "Fiche client consultative — consolidation de l'existant, sans "
    "aucun recalcul : missions par exercice, points convenus encore "
    "ouverts, évolution de la charge fiscale estimée déjà restituée "
    "par sa vue dédiée et signaux du centre d'alertes concernant ce "
    "client. Chaque volet s'apprécie dans son écran d'origine : le "
    "fiscaliste analyse et le client reste seul décideur des suites."
)


class ErreurFicheClient(Exception):
    """Echec métier de la fiche (ex. contribuable hors tenant)."""


# ── Fonctions pures ──────────────────────────────────────────────────


def trier_missions(missions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — missions par exercice DÉCROISSANT (le plus récent d'abord).

    À exercice égal, la mission la plus récente (``mission_id`` max)
    d'abord — la lecture d'entretien part du présent.
    """
    def _cle(m: dict[str, Any]) -> tuple:
        return (
            -int(m.get("exercice") or 0),
            -int(m.get("mission_id") or 0),
        )

    return sorted(missions, key=_cle)


def normaliser_point(
    brut: dict[str, Any], aujourd_hui: date
) -> dict[str, Any]:
    """PUR — point convenu ouvert au contrat stable, clés présentes.

    ``depassee`` : vrai si la date cible est STRICTEMENT antérieure au
    jour (le jour même reste actionnable — constat, pas un reproche) ;
    sans date cible ou date illisible → ``False`` (défensif, jamais
    bloquant).
    """
    cible = brut.get("date_cible")
    if isinstance(cible, datetime):
        cible = cible.date()
    if isinstance(cible, date):
        cible_iso: str | None = cible.isoformat()
    else:
        cible_iso = str(cible)[:10] if cible else None
    depassee = False
    if cible_iso:
        try:
            depassee = date.fromisoformat(cible_iso) < aujourd_hui
        except ValueError:
            cible_iso = None
    mission = brut.get("mission_id")
    return {
        "point_id": int(brut.get("point_id") or 0),
        "mission_id": int(mission) if mission is not None else None,
        "exercice": (
            int(brut["exercice"]) if brut.get("exercice") is not None else None
        ),
        "libelle": str(brut.get("libelle") or ""),
        "date_cible": cible_iso,
        "depassee": depassee,
    }


def filtrer_alertes_client(
    alertes: list[dict[str, Any]],
    denomination: str,
    mission_ids: set[int],
) -> list[dict[str, Any]]:
    """PUR — alertes du centre concernant CE client, tolérant.

    Une alerte est retenue si sa ``mission_id`` appartient aux missions
    du client OU si son champ ``client`` égale la dénomination (les
    sources du centre portent l'un, l'autre ou les deux). L'ordre du
    centre (gravité puis échéance) est conservé ; plafond
    :data:`PLAFOND_ALERTES_FICHE`.
    """
    retenues: list[dict[str, Any]] = []
    for a in alertes:
        mission = a.get("mission_id")
        par_mission = mission is not None and int(mission) in mission_ids
        par_nom = bool(denomination) and (
            str(a.get("client") or "") == denomination
        )
        if par_mission or par_nom:
            retenues.append(a)
    return retenues[:PLAFOND_ALERTES_FICHE]


def assembler_fiche(
    identite: dict[str, Any],
    missions: list[dict[str, Any]],
    points_ouverts: list[dict[str, Any]],
    evolution: dict[str, Any] | None,
    alertes: list[dict[str, Any]],
    volets_en_echec: list[str],
    aujourd_hui: date,
) -> dict[str, Any]:
    """PUR — fiche finale : tri, synthèse, note, clés stables."""
    tries = trier_missions(missions)
    return {
        "aujourd_hui": aujourd_hui.isoformat(),
        "contribuable_id": int(identite["contribuable_id"]),
        "denomination": str(identite.get("denomination") or ""),
        "forme": (
            str(identite["forme"]) if identite.get("forme") else None
        ),
        "missions": tries,
        "points_ouverts": points_ouverts,
        "evolution_charge_fiscale": evolution,
        "alertes": alertes,
        "synthese": {
            "nb_missions": len(tries),
            "nb_points_ouverts": len(points_ouverts),
            "nb_points_depasses": sum(
                1 for p in points_ouverts if bool(p.get("depassee"))
            ),
            "nb_alertes": len(alertes),
        },
        "volets_en_echec": sorted(volets_en_echec),
        "note": MENTION_NOTE,
    }


# ── Lecture contribuable (RLS) ───────────────────────────────────────


def fiche_client(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Fiche client consolidée — LECTURE SEULE, RLS, jamais bloquante.

    Identité obligatoire : contribuable hors tenant →
    :class:`ErreurFicheClient` (« introuvable », 404 côté route — pas
    de fuite cross-tenant). Chaque VOLET est ensuite tenté
    indépendamment (missions, points convenus ouverts, évolution de la
    charge fiscale du dernier exercice, alertes du centre filtrées sur
    le client) : un volet en échec est listé dans ``volets_en_echec``
    sans empêcher la fiche. AUCUN recalcul : projection de vues
    existantes. Ouvre son propre ``contexte_tenant`` : à appeler HORS
    de tout autre ``with contexte_tenant``.
    """
    from backend.plateforme.points_convenus import STATUT_A_FAIRE

    jour = date.today()
    volets_en_echec: list[str] = []

    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text(
                "SELECT id, denomination, forme "
                "FROM contribuable WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if contrib is None:
            raise ErreurFicheClient(
                f"contribuable {contribuable_id} introuvable"
            )

        # Volet missions — tolérant : un échec n'empêche pas la fiche.
        missions: list[dict[str, Any]] = []
        try:
            rows = session.execute(
                text(
                    "SELECT id, exercice, statut FROM mission "
                    "WHERE contribuable_id = :c "
                    "ORDER BY exercice DESC, id DESC"
                ),
                {"c": contribuable_id},
            ).mappings().all()
            missions = [
                {
                    "mission_id": int(r["id"]),
                    "exercice": int(r["exercice"]),
                    "statut": str(r["statut"] or ""),
                }
                for r in rows
            ]
        except Exception:  # noqa: BLE001 — volet annexe toléré
            volets_en_echec.append("missions")

        # Volet points convenus encore « à faire » — tolérant.
        points_ouverts: list[dict[str, Any]] = []
        try:
            rows_points = session.execute(
                text(
                    "SELECT p.id AS point_id, p.libelle, p.date_cible, "
                    "m.id AS mission_id, m.exercice "
                    "FROM point_convenu p "
                    "JOIN mission m ON m.id = p.mission_id "
                    "WHERE m.contribuable_id = :c AND p.statut = :s "
                    "ORDER BY p.date_cible NULLS LAST, p.id"
                ),
                {"c": contribuable_id, "s": STATUT_A_FAIRE},
            ).mappings().all()
            points_ouverts = [
                normaliser_point(dict(r), jour) for r in rows_points
            ]
        except Exception:  # noqa: BLE001 — volet annexe toléré
            volets_en_echec.append("points_convenus")

    # Volet évolution de la charge fiscale — projection de la vue
    # existante sur la mission du DERNIER exercice disponible. La vue
    # ouvre son propre contexte_tenant : appel HORS du with ci-dessus.
    evolution: dict[str, Any] | None = None
    if missions:
        try:
            from backend.plateforme.evolution_charge_fiscale import (
                vue_evolution_charge_fiscale_mission,
            )

            derniere = trier_missions(missions)[0]
            evolution = vue_evolution_charge_fiscale_mission(
                session, tenant_id, int(derniere["mission_id"])
            )
        except Exception:  # noqa: BLE001 — volet annexe toléré
            volets_en_echec.append("evolution_charge_fiscale")

    # Volet alertes — filtre client sur l'assemblée EXISTANTE du
    # centre (aucun recalcul propre) ; le centre ouvre ses contextes.
    alertes: list[dict[str, Any]] = []
    try:
        from backend.plateforme.centre_alertes import centre_alertes_cabinet

        centre = centre_alertes_cabinet(session, tenant_id, jour)
        alertes = filtrer_alertes_client(
            list(centre.get("alertes") or []),
            str(contrib["denomination"] or ""),
            {int(m["mission_id"]) for m in missions},
        )
    except Exception:  # noqa: BLE001 — volet annexe toléré
        volets_en_echec.append("alertes")

    return assembler_fiche(
        {
            "contribuable_id": int(contrib["id"]),
            "denomination": contrib["denomination"],
            "forme": contrib["forme"],
        },
        missions,
        points_ouverts,
        evolution,
        alertes,
        volets_en_echec,
        jour,
    )
