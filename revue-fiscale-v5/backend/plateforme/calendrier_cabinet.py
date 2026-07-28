"""Calendrier fiscal du cabinet — consolidation mensuelle des échéances.

POURQUOI : les échéances vivent dans des vues séparées du tableau de
bord (échéances fiscales des missions, points convenus datés) et sont
présentées en listes plates orientées « urgence ». Pour PLANIFIER la
charge du cabinet sur les prochains mois, l'associé veut une vue
CALENDRIER : mois par mois, tout ce qui attend le cabinet — sans
ouvrir chaque mission ni recouper plusieurs blocs.

Assemblage DÉTERMINISTE et CONSULTATIF (aucun LLM, AUCUN email) :
chaque source réutilise le MODULE EXISTANT qui alimente déjà le centre
d'alertes — :mod:`backend.plateforme.echeances_cabinet` (échéancier du
régime de chaque mission « en_cours » appliqué au calendrier courant,
mêmes requête et fonctions pures, fenêtre étendue à l'horizon) et
:mod:`backend.plateforme.points_convenus_cabinet` (points « à faire »
datés — les points des missions clôturées sont écartés ici : le
calendrier planifie la charge des missions OUVERTES). Aucun calcul
métier n'est dupliqué : seules des fonctions PURES de normalisation,
tri, groupement mensuel, plafond et synthèse s'ajoutent ici.

TOLÉRANCE : une source qui échoue est simplement ignorée (listée dans
``sources_en_echec``) — jamais bloquant, même pattern que
:mod:`backend.plateforme.centre_alertes`. Lecture seule sous RLS via
``contexte_tenant`` — AUCUNE écriture, AUCUNE migration. Dates ISO
côté API (l'affichage JJ/MM/AAAA est l'affaire du frontend) ; seuls
les libellés de mois sont rendus en français ici (« Août 2026 »).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

#: Types d'éléments consolidés dans le calendrier.
TYPES_ELEMENT: Final[tuple[str, ...]] = (
    "echeance_fiscale",
    "point_convenu",
)

#: Horizon par défaut : les 3 prochains mois (mois courant inclus).
HORIZON_DEFAUT: Final[int] = 3

#: Horizon maximal : 12 mois — au-delà, l'échéancier théorique perd
#: son sens (les calendriers officiels DGI ne sont pas publiés).
HORIZON_MAX: Final[int] = 12

#: Plafond d'éléments restitués — vue de planification, pas un export.
PLAFOND_ELEMENTS: Final[int] = 500

#: Noms français des mois (index 1 à 12) — libellés « Août 2026 ».
MOIS_FRANCAIS: Final[tuple[str, ...]] = (
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
)

MENTION_NOTE: Final[str] = (
    "Calendrier consultatif du cabinet — consolidation mensuelle "
    "déterministe des échéances déjà calculées par les vues "
    "existantes : échéances fiscales indicatives des missions en "
    "cours (échéancier théorique du régime de chaque mission, "
    "vérifier le calendrier officiel DGI) et points convenus datés "
    "encore à faire. Planification indicative de la charge du "
    "cabinet : rien n'est automatique, l'humain arbitre les "
    "priorités et décide. Aucune alerte n'est envoyée par email — "
    "tout reste dans l'application."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def borner_horizon(horizon_mois: int) -> int:
    """PUR — horizon borné à [1, 12] mois (défensif — la route valide déjà)."""
    try:
        h = int(horizon_mois)
    except (TypeError, ValueError):
        return HORIZON_DEFAUT
    return max(1, min(h, HORIZON_MAX))


def fin_horizon(aujourd_hui: date, horizon_mois: int) -> date:
    """PUR — dernier jour du dernier mois couvert par l'horizon.

    Horizon de N mois = mois COURANT inclus + (N − 1) mois suivants :
    « 3 mois » depuis le 28/07 couvre juillet, août et septembre
    (fin le 30/09) — lecture naturelle d'un calendrier mensuel.
    """
    h = borner_horizon(horizon_mois)
    total = aujourd_hui.month - 1 + h  # index 0 du mois SUIVANT la fin
    annee = aujourd_hui.year + total // 12
    mois = total % 12 + 1
    return date(annee, mois, 1) - timedelta(days=1)


def libelle_mois(mois: str) -> str:
    """PUR — « 2026-08 » → « Août 2026 » ; valeur illisible → inchangée."""
    try:
        annee, numero = str(mois).split("-")
        return f"{MOIS_FRANCAIS[int(numero) - 1]} {int(annee)}"
    except (ValueError, IndexError):
        return str(mois)


def normaliser_element(
    brute: dict[str, Any], aujourd_hui: date
) -> dict[str, Any] | None:
    """PUR — élément au contrat stable, clés TOUJOURS présentes.

    ``type`` hors référentiel → « echeance_fiscale » écarté ? Non :
    valeur conservée telle quelle si connue, sinon l'élément est
    écarté (défensif). Date illisible → élément écarté — jamais
    bloquant. ``depassee`` : date strictement antérieure à
    ``aujourd_hui`` (constat factuel de calendrier, pas un reproche).
    """
    try:
        d = date.fromisoformat(str(brute.get("date") or ""))
    except ValueError:
        return None
    type_element = str(brute.get("type") or "")
    if type_element not in TYPES_ELEMENT:
        return None
    mission = brute.get("mission_id")
    return {
        "date": d.isoformat(),
        "type": type_element,
        "client": str(brute.get("client") or ""),
        "mission_id": int(mission) if mission is not None else None,
        "libelle": str(brute.get("libelle") or ""),
        "depassee": d < aujourd_hui,
    }


def trier_elements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — chronologique ; à date égale, client, mission, type, libellé."""
    def _cle(i: dict[str, Any]) -> tuple:
        return (
            str(i.get("date") or ""),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
            str(i.get("type") or ""),
            str(i.get("libelle") or ""),
        )

    return sorted(items, key=_cle)


def plafonner_elements(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — tronque à :data:`PLAFOND_ELEMENTS` (liste déjà triée).

    Le plafond ne coupe donc que les échéances les plus lointaines —
    les plus proches (à planifier d'abord) restent visibles.
    """
    return list(items)[:PLAFOND_ELEMENTS]


def grouper_par_mois(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — groupes mensuels ordonnés (liste déjà triée en entrée).

    Chaque groupe : ``{mois "2026-08", libelle_mois "Août 2026",
    elements}`` — l'ordre chronologique des éléments induit celui des
    mois (tri stable en amont).
    """
    groupes: list[dict[str, Any]] = []
    for i in items:
        mois = str(i.get("date") or "")[:7]
        if not groupes or groupes[-1]["mois"] != mois:
            groupes.append(
                {
                    "mois": mois,
                    "libelle_mois": libelle_mois(mois),
                    "elements": [],
                }
            )
        groupes[-1]["elements"].append(i)
    return groupes


def compteurs_calendrier(
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """PUR — compteurs : total, dépassées, à venir."""
    depassees = sum(1 for i in items if bool(i.get("depassee")))
    return {
        "nb_total": len(items),
        "nb_depassees": depassees,
        "nb_a_venir": len(items) - depassees,
    }


def assembler_calendrier(
    elements: list[dict[str, Any]], aujourd_hui: date
) -> dict[str, Any]:
    """PUR — vue finale : normalisation, tri, plafond, groupes, note.

    Se construit toujours (aucun élément → ``mois`` vide, compteurs à
    zéro, note présente) — clés stables.
    """
    normalises = [
        n
        for e in elements
        if (n := normaliser_element(e, aujourd_hui)) is not None
    ]
    retenus = plafonner_elements(trier_elements(normalises))
    return {
        "aujourd_hui": aujourd_hui.isoformat(),
        "mois": grouper_par_mois(retenus),
        "compteurs": compteurs_calendrier(retenus),
        "note": MENTION_NOTE,
    }


# ── Sources (chacune réutilise un module existant, RLS) ──────────────


def _source_echeances_fiscales(
    session: Session, tenant_id: int, jour: date, fin: date
) -> list[dict[str, Any]]:
    """Échéances fiscales des missions en cours — pattern echeances_cabinet.

    MÊME requête et MÊMES fonctions pures que
    :func:`backend.plateforme.echeances_cabinet.echeances_cabinet`
    (source du centre d'alertes) — seule la FENÊTRE change : de
    ``jour`` à ``fin`` (fin d'horizon) au lieu de 30 jours. Aucun
    recalcul d'échéancier ici : tout vient de
    :func:`backend.plateforme.echeancier_fiscal.construire_echeancier`.
    Une mission en erreur est simplement omise (jamais bloquant).
    """
    from backend.plateforme.echeances_cabinet import (
        PLAFOND_MISSIONS,
        filtrer_fenetre,
    )
    from backend.plateforme.echeancier_fiscal import (
        _profil_mission,
        _releve_de_la_dge,
        construire_echeancier,
        normaliser_regime,
    )
    from backend.plateforme.missions import STATUT_EN_COURS

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, m.profil, "
                "c.denomination AS client, c.centre_impots "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut = :s "
                "ORDER BY c.denomination, m.id "
                "LIMIT :lim"
            ),
            {"s": STATUT_EN_COURS, "lim": PLAFOND_MISSIONS},
        ).mappings().all()

    fenetre_jours = max(0, (fin - jour).days)
    elements: list[dict[str, Any]] = []
    for r in rows:
        # Tolérance par mission : un échéancier qui échoue n'empêche
        # pas le calendrier des autres missions.
        try:
            profil = _profil_mission(r["profil"])
            regime = (
                normaliser_regime(str(profil.get("regime") or "")) or "reel"
            )
            dge = _releve_de_la_dge(r["centre_impots"])
            echeancier = [
                e
                for annee in range(jour.year - 1, fin.year + 1)
                for e in construire_echeancier(annee, regime, dge=dge)
            ]
            retenues = filtrer_fenetre(echeancier, jour, fenetre_jours)
        except Exception:  # noqa: BLE001 — mission annexe tolérée
            continue
        for e in retenues:
            impot = str(e.get("impot") or "")
            obligation = str(e.get("obligation") or "")
            periode = str(e.get("periode") or "")
            libelle = impot
            if obligation:
                libelle += f" — {obligation}"
            if periode:
                libelle += f" ({periode})"
            elements.append(
                {
                    "date": str(e.get("date_limite") or ""),
                    "type": "echeance_fiscale",
                    "client": str(r["client"] or ""),
                    "mission_id": int(r["mission_id"]),
                    "libelle": libelle,
                }
            )
    return elements


def _source_points_convenus(
    session: Session, tenant_id: int, jour: date, fin: date
) -> list[dict[str, Any]]:
    """Points convenus DATÉS encore à faire — module points_convenus_cabinet.

    La vue est celle DÉJÀ construite par
    :func:`backend.plateforme.points_convenus_cabinet.points_convenus_cabinet`
    (source du centre d'alertes — aucun recalcul ici) : ne sont gardés
    que les points portant une ``date_cible`` (un point non daté ne se
    planifie pas dans un calendrier), des missions NON clôturées, dont
    la date cible tombe au plus tard en fin d'horizon — les dates déjà
    passées restent visibles (``depassee``) : elles pèsent encore sur
    la charge du cabinet.
    """
    from backend.plateforme.missions import STATUT_CLOTUREE
    from backend.plateforme.points_convenus_cabinet import (
        points_convenus_cabinet,
    )

    vue = points_convenus_cabinet(session, tenant_id, jour)
    elements: list[dict[str, Any]] = []
    for i in vue.get("items") or []:
        date_cible = i.get("date_cible")
        if not date_cible:
            continue
        if str(i.get("statut_mission") or "") == STATUT_CLOTUREE:
            continue
        if str(date_cible) > fin.isoformat():
            continue
        libelle = str(i.get("libelle") or "")
        elements.append(
            {
                "date": str(date_cible),
                "type": "point_convenu",
                "client": i.get("client"),
                "mission_id": i.get("mission_id"),
                "libelle": (
                    f"point convenu — {libelle}"
                    if libelle
                    else "point convenu"
                ),
            }
        )
    return elements


#: Sources consolidées : (nom, constructeur) — chacune est TOLÉRANTE.
_SOURCES: Final[
    tuple[
        tuple[
            str,
            Callable[[Session, int, date, date], list[dict[str, Any]]],
        ],
        ...,
    ]
] = (
    ("echeances_fiscales", _source_echeances_fiscales),
    ("points_convenus", _source_points_convenus),
)


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def calendrier_cabinet(
    session: Session,
    tenant_id: int,
    horizon_mois: int = HORIZON_DEFAUT,
    aujourd_hui: date | None = None,
) -> dict[str, Any]:
    """Calendrier fiscal du cabinet — LECTURE SEULE, RLS, jamais bloquant.

    Chaque source est tentée indépendamment (try/except) : une source
    en échec est ignorée et listée dans ``sources_en_echec`` — pattern
    :mod:`backend.plateforme.centre_alertes`. Se construit toujours
    (tenant sans échéance → mois vides, clés stables, note présente).
    Aucun email, aucune écriture.
    """
    jour = aujourd_hui or date.today()
    horizon = borner_horizon(horizon_mois)
    fin = fin_horizon(jour, horizon)
    elements: list[dict[str, Any]] = []
    en_echec: list[str] = []
    for nom, construire in _SOURCES:
        # Tolérance par source : un module en échec n'empêche jamais
        # la restitution du calendrier.
        try:
            elements.extend(construire(session, tenant_id, jour, fin))
        except Exception:  # noqa: BLE001 — source annexe tolérée
            en_echec.append(nom)
    vue = assembler_calendrier(elements, jour)
    vue["horizon_mois"] = horizon
    vue["fin_horizon"] = fin.isoformat()
    vue["sources_en_echec"] = sorted(en_echec)
    return vue
