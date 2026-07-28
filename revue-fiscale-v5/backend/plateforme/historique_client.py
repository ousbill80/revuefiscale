"""Historique pluriannuel du client — exposition fiscale et civisme.

POURQUOI : en réunion, le fiscaliste montre au client sa TRAJECTOIRE
sur plusieurs exercices — pas seulement N vs N-1 (déjà couvert par
:mod:`backend.plateforme.comparaison_exercices`), mais la tendance de
fond sur TOUTES les missions du client : exposition fiscale (risques
encore ouverts nés de chaque mission, montants + pénalités estimés)
et taux de civisme fiscal (rapprochement échéancier / pièces de
:mod:`backend.plateforme.civisme_fiscal`).

Une entrée par EXERCICE : si plusieurs missions portent sur le même
exercice, la plus récente (id max) représente l'exercice. La tendance
globale compare le PREMIER et le DERNIER exercice de la trajectoire :

- exposition « hausse » / « baisse » / « stable » — seuil de ±1 % de
  variation relative pour qualifier le stable (éviter de dramatiser un
  écart d'arrondi) ;
- civisme « amelioration » / « degradation » / « stable » — seuil de
  ±1 point de pourcentage, même prudence.

Analyse CONSULTATIVE : simple photographie chiffrée pluriannuelle,
le fiscaliste interprète, le client décide. AUCUN LLM — lecture seule,
déterministe, sous RLS. Montants sérialisés en str (Decimal).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.plateforme.civisme_fiscal import analyse_mission
from backend.plateforme.comparaison_exercices import agreger_par_impot
from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.risques import STATUTS_NON_CLOS

# ── Constantes ───────────────────────────────────────────────────────

PLAFOND_EXERCICES: Final[int] = 10

EXPOSITION_HAUSSE: Final[str] = "hausse"
EXPOSITION_BAISSE: Final[str] = "baisse"
CIVISME_AMELIORATION: Final[str] = "amelioration"
CIVISME_DEGRADATION: Final[str] = "degradation"
TENDANCE_STABLE: Final[str] = "stable"

# Seuils de stabilité : ±1 % de variation relative d'exposition,
# ±1 point de taux de civisme — en deçà, la trajectoire est « stable ».
SEUIL_EXPOSITION_PCT: Final[Decimal] = Decimal("1")
SEUIL_CIVISME_POINTS: Final[Decimal] = Decimal("1")

MENTION_NOTE: Final[str] = (
    "Trajectoire consultative sur les exercices revus — exposition des "
    "risques encore ouverts nés de chaque mission (montants estimés par "
    "le cabinet) et taux de civisme déduit des pièces collectées. "
    "Simple photographie pluriannuelle : le fiscaliste apprécie la "
    "tendance et le client reste seul décideur des suites."
)


class ErreurHistoriqueClient(Exception):
    """Echec métier de l'historique (ex. contribuable hors tenant)."""


# ── Fonctions pures ──────────────────────────────────────────────────


def consolider_exercices(
    entrees: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """PUR — une entrée par exercice, triée par exercice CROISSANT.

    ``entrees`` : dicts par mission avec au moins ``mission_id`` et
    ``exercice``. À exercice égal, la mission la plus récente
    (``mission_id`` max) représente l'exercice. Plafond
    :data:`PLAFOND_EXERCICES` : seuls les exercices les plus récents
    sont conservés.
    """
    par_exercice: dict[int, dict[str, Any]] = {}
    for entree in entrees:
        exercice = int(entree["exercice"])
        actuel = par_exercice.get(exercice)
        if actuel is None or int(entree["mission_id"]) > int(
            actuel["mission_id"]
        ):
            par_exercice[exercice] = entree
    tries = [par_exercice[ex] for ex in sorted(par_exercice)]
    return tries[-PLAFOND_EXERCICES:]


def qualifier_exposition(premiere: Decimal, derniere: Decimal) -> str:
    """PUR — tendance d'exposition premier → dernier exercice.

    Stable si la variation relative est dans ±1 % de la première
    exposition ; première exposition nulle : toute exposition finale
    strictement positive qualifie une hausse.
    """
    delta = derniere - premiere
    if premiere == 0:
        if derniere > 0:
            return EXPOSITION_HAUSSE
        return TENDANCE_STABLE
    variation_pct = abs(delta) * Decimal("100") / premiere
    if variation_pct <= SEUIL_EXPOSITION_PCT:
        return TENDANCE_STABLE
    return EXPOSITION_HAUSSE if delta > 0 else EXPOSITION_BAISSE


def qualifier_civisme(
    premier: Decimal | None, dernier: Decimal | None
) -> str | None:
    """PUR — tendance de civisme premier → dernier exercice.

    ``None`` si l'un des deux taux est indisponible (mission non
    exploitable). Stable dans ±1 point de pourcentage ; un taux qui
    monte est une AMÉLIORATION (plus d'obligations couvertes).
    """
    if premier is None or dernier is None:
        return None
    delta = dernier - premier
    if abs(delta) <= SEUIL_CIVISME_POINTS:
        return TENDANCE_STABLE
    return CIVISME_AMELIORATION if delta > 0 else CIVISME_DEGRADATION


def tendance_globale(exercices: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — tendance de fond entre premier et dernier exercice.

    ``exercices`` : sortie de :func:`consolider_exercices` (dicts avec
    ``exercice``, ``exposition_totale`` str et ``taux_civisme``
    str | None). Moins de deux exercices → tendances ``None`` (pas de
    trajectoire à lire).
    """
    if len(exercices) < 2:
        return {
            "exercice_premier": None,
            "exercice_dernier": None,
            "exposition": None,
            "civisme": None,
        }
    premier, dernier = exercices[0], exercices[-1]

    def _taux(entree: dict[str, Any]) -> Decimal | None:
        brut = entree.get("taux_civisme")
        return None if brut in (None, "") else Decimal(str(brut))

    return {
        "exercice_premier": int(premier["exercice"]),
        "exercice_dernier": int(dernier["exercice"]),
        "exposition": qualifier_exposition(
            Decimal(str(premier["exposition_totale"])),
            Decimal(str(dernier["exposition_totale"])),
        ),
        "civisme": qualifier_civisme(_taux(premier), _taux(dernier)),
    }


# ── Lecture contribuable (RLS) ───────────────────────────────────────


def historique_client(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Trajectoire pluriannuelle d'un contribuable (lecture seule, RLS).

    Toutes les missions du contribuable (une entrée par exercice —
    mission la plus récente à exercice égal, plafond de
    :data:`PLAFOND_EXERCICES` exercices). Par mission : exposition
    totale des risques NON CLOS nés de la mission
    (``origine_mission_id``) et taux de civisme fiscal si la mission
    est exploitable (``None`` sinon — tolérance d'erreur par mission).
    Lève :class:`ErreurHistoriqueClient` (« introuvable ») si le
    contribuable n'existe pas dans le tenant — pas de fuite
    cross-tenant. Ouvre son propre ``contexte_tenant`` : à appeler
    HORS de tout autre ``with contexte_tenant``.
    """
    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text(
                "SELECT id, denomination FROM contribuable WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if contrib is None:
            raise ErreurHistoriqueClient(
                f"contribuable {contribuable_id} introuvable"
            )

        missions = session.execute(
            text(
                "SELECT id, exercice, statut FROM mission "
                "WHERE contribuable_id = :c "
                "ORDER BY exercice ASC, id ASC"
            ),
            {"c": contribuable_id},
        ).mappings().all()

        expositions: dict[int, dict[str, Any]] = {}
        if missions:
            rows = session.execute(
                text(
                    "SELECT origine_mission_id, impot, montant_estime, "
                    "penalites_estimees FROM risque "
                    "WHERE contribuable_id = :c "
                    "AND origine_mission_id IN :missions "
                    "AND statut IN :statuts ORDER BY id"
                ).bindparams(
                    bindparam("missions", expanding=True),
                    bindparam("statuts", expanding=True),
                ),
                {
                    "c": contribuable_id,
                    "missions": [int(m["id"]) for m in missions],
                    "statuts": sorted(STATUTS_NON_CLOS),
                },
            ).mappings().all()
            for mission in missions:
                agregats = agreger_par_impot(
                    [
                        dict(r)
                        for r in rows
                        if int(r["origine_mission_id"]) == int(mission["id"])
                    ]
                )
                expositions[int(mission["id"])] = {
                    "nb": sum(
                        int(a["nb_ouverts"]) for a in agregats.values()
                    ),
                    "exposition": sum(
                        (Decimal(a["exposition"]) for a in agregats.values()),
                        Decimal("0"),
                    ),
                }

    entrees: list[dict[str, Any]] = []
    for mission in missions:
        mission_id = int(mission["id"])
        expo = expositions.get(
            mission_id, {"nb": 0, "exposition": Decimal("0")}
        )
        entrees.append(
            {
                "mission_id": mission_id,
                "exercice": int(mission["exercice"]),
                "statut": str(mission["statut"]),
                "exposition_totale": str(expo["exposition"]),
                "nb_risques_ouverts": int(expo["nb"]),
                "taux_civisme": None,  # posé ci-dessous
            }
        )

    # Une entrée par exercice AVANT le civisme : pas d'analyse inutile
    # sur les missions écartées (doublon d'exercice, hors plafond).
    exercices = consolider_exercices(entrees)
    for entree in exercices:
        # Civisme par mission — tolérance d'erreur : une mission non
        # exploitable (profil incomplet…) n'empêche pas la trajectoire.
        # analyse_mission ouvre son propre contexte_tenant : appel HORS
        # de tout autre with contexte_tenant.
        try:
            civisme = analyse_mission(
                session, tenant_id, int(entree["mission_id"])
            )
            entree["taux_civisme"] = str(
                civisme["synthese"]["taux_civisme"]
            )
        except Exception:  # noqa: BLE001 — mission non exploitable tolérée
            entree["taux_civisme"] = None
    return {
        "contribuable_id": int(contrib["id"]),
        "denomination": str(contrib["denomination"]),
        "exercices": exercices,
        "tendance": tendance_globale(exercices),
        "note": MENTION_NOTE,
    }
