"""Comparaison inter-exercices d'un contribuable — N vs N-1.

POURQUOI : un cabinet revoit le même client exercice après exercice
(une mission par exercice). Pour apprécier si la situation fiscale
S'AMÉLIORE ou SE DÉGRADE d'une mission à l'autre, le fiscaliste a
besoin d'une lecture côte à côte des deux exercices les plus récents :
nombre de risques encore ouverts nés de chaque mission, exposition
totale par impôt (montant estimé + pénalités estimées), deltas et
tendance. Un delta positif (plus de risques ouverts, plus d'exposition)
signale une DÉGRADATION ; un delta négatif, une AMÉLIORATION.

Le périmètre est le registre des risques (table ``risque``) rattaché à
chaque mission via ``origine_mission_id`` : seuls les risques NON CLOS
(``ouvert`` / ``en_traitement``) comptent — un risque résolu, accepté ou
prescrit ne pèse plus sur l'exercice.

Analyse CONSULTATIVE : simple photographie chiffrée, sans appréciation
automatique de conformité — le fiscaliste interprète, le client décide.
AUCUN LLM — lecture seule, déterministe, sous RLS. Montants sérialisés
en str (Decimal).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.risques import STATUTS_NON_CLOS

# ── Constantes ───────────────────────────────────────────────────────

TENDANCE_AMELIORATION: Final[str] = "amelioration"
TENDANCE_DEGRADATION: Final[str] = "degradation"
TENDANCE_STABLE: Final[str] = "stable"

RAISON_AUCUNE_MISSION: Final[str] = (
    "Aucune mission — comparaison indisponible."
)
RAISON_UN_SEUL_EXERCICE: Final[str] = (
    "Un seul exercice revu — comparaison indisponible."
)

MENTION_NOTE: Final[str] = (
    "Comparaison consultative — risques encore ouverts nés de chaque "
    "mission, aux montants estimés par le cabinet. Simple photographie "
    "chiffrée entre deux exercices : le fiscaliste apprécie les "
    "évolutions et le client reste seul décideur des suites."
)


class ErreurComparaisonExercices(Exception):
    """Echec métier de la comparaison (ex. contribuable hors tenant)."""


# ── Fonctions pures ──────────────────────────────────────────────────


def agreger_par_impot(
    risques: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """PUR — nb de risques ouverts et exposition Decimal par impôt.

    ``risques`` : dicts avec ``impot``, ``montant_estime``,
    ``penalites_estimees`` (déjà filtrés sur les risques NON CLOS d'une
    mission). L'exposition d'un risque = montant + pénalités (0 si non
    chiffré — le risque compte quand même dans le nombre).
    """
    agregats: dict[str, dict[str, Any]] = {}
    for r in risques:
        impot = str(r.get("impot") or "").upper() or "AUTRE"
        exposition = Decimal("0")
        for cle in ("montant_estime", "penalites_estimees"):
            brut = r.get(cle)
            if brut is not None and brut != "":
                exposition += Decimal(str(brut))
        entree = agregats.setdefault(
            impot, {"nb_ouverts": 0, "exposition": Decimal("0")}
        )
        entree["nb_ouverts"] += 1
        entree["exposition"] += exposition
    return agregats


def qualifier_tendance(delta_nb: int, delta_exposition: Decimal) -> str:
    """PUR — tendance à partir des deltas (récent − précédent).

    Prudence fiscaliste : toute hausse (nombre OU exposition) qualifie
    une dégradation, même si l'autre indicateur baisse ; sinon toute
    baisse qualifie une amélioration ; sinon stable.
    """
    if delta_nb > 0 or delta_exposition > 0:
        return TENDANCE_DEGRADATION
    if delta_nb < 0 or delta_exposition < 0:
        return TENDANCE_AMELIORATION
    return TENDANCE_STABLE


def comparer_agregats(
    recent: dict[str, dict[str, Any]],
    precedent: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — deltas par impôt entre deux agrégats (N vs N-1).

    Union des impôts des deux exercices, tri alphabétique (stable et
    lisible). Montants sérialisés en str Decimal ; delta = récent −
    précédent (positif = dégradation).
    """
    lignes: list[dict[str, Any]] = []
    for impot in sorted(set(recent) | set(precedent)):
        r = recent.get(impot, {"nb_ouverts": 0, "exposition": Decimal("0")})
        p = precedent.get(
            impot, {"nb_ouverts": 0, "exposition": Decimal("0")}
        )
        delta_nb = int(r["nb_ouverts"]) - int(p["nb_ouverts"])
        delta_expo = Decimal(r["exposition"]) - Decimal(p["exposition"])
        lignes.append(
            {
                "impot": impot,
                "nb_ouverts_recent": int(r["nb_ouverts"]),
                "nb_ouverts_precedent": int(p["nb_ouverts"]),
                "delta_nb_ouverts": delta_nb,
                "exposition_recente": str(r["exposition"]),
                "exposition_precedente": str(p["exposition"]),
                "delta_exposition": str(delta_expo),
                "tendance": qualifier_tendance(delta_nb, delta_expo),
            }
        )
    return lignes


def synthese_comparaison(
    recent: dict[str, dict[str, Any]],
    precedent: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """PUR — totaux, deltas globaux et tendance d'ensemble."""
    def _totaux(agregats: dict[str, dict[str, Any]]) -> tuple[int, Decimal]:
        nb = sum(int(a["nb_ouverts"]) for a in agregats.values())
        expo = sum(
            (Decimal(a["exposition"]) for a in agregats.values()),
            Decimal("0"),
        )
        return nb, expo

    nb_r, expo_r = _totaux(recent)
    nb_p, expo_p = _totaux(precedent)
    delta_nb = nb_r - nb_p
    delta_expo = expo_r - expo_p
    return {
        "nb_ouverts_recent": nb_r,
        "nb_ouverts_precedent": nb_p,
        "delta_nb_ouverts": delta_nb,
        "exposition_recente": str(expo_r),
        "exposition_precedente": str(expo_p),
        "delta_exposition": str(delta_expo),
        "tendance": qualifier_tendance(delta_nb, delta_expo),
    }


# ── Lecture contribuable (RLS) ───────────────────────────────────────


def comparaison_contribuable(
    session: Session, tenant_id: int, contribuable_id: int
) -> dict[str, Any]:
    """Comparaison N vs N-1 d'un contribuable (lecture seule, RLS).

    Prend les deux missions les plus récentes du contribuable sur DEUX
    exercices distincts (par exercice décroissant puis id décroissant —
    à exercice égal, la mission la plus récente représente l'exercice).
    Sans deux exercices revus : ``disponible = False`` avec la raison,
    sans erreur. Lève :class:`ErreurComparaisonExercices`
    (« introuvable ») si le contribuable n'existe pas dans le tenant —
    pas de fuite cross-tenant. Ouvre son propre ``contexte_tenant`` :
    à appeler HORS de tout autre ``with contexte_tenant``.
    """
    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text(
                "SELECT id, denomination FROM contribuable WHERE id = :c"
            ),
            {"c": contribuable_id},
        ).mappings().one_or_none()
        if contrib is None:
            raise ErreurComparaisonExercices(
                f"contribuable {contribuable_id} introuvable"
            )

        missions = session.execute(
            text(
                "SELECT id, exercice, statut FROM mission "
                "WHERE contribuable_id = :c "
                "ORDER BY exercice DESC, id DESC"
            ),
            {"c": contribuable_id},
        ).mappings().all()

        base = {
            "contribuable": {
                "id": int(contrib["id"]),
                "denomination": str(contrib["denomination"]),
            },
            "note": MENTION_NOTE,
        }
        if not missions:
            return {
                **base,
                "disponible": False,
                "raison": RAISON_AUCUNE_MISSION,
            }
        mission_recente = missions[0]
        mission_precedente = next(
            (
                m
                for m in missions[1:]
                if int(m["exercice"]) != int(mission_recente["exercice"])
            ),
            None,
        )
        if mission_precedente is None:
            return {
                **base,
                "disponible": False,
                "raison": RAISON_UN_SEUL_EXERCICE,
            }

        rows = session.execute(
            text(
                "SELECT origine_mission_id, impot, montant_estime, "
                "penalites_estimees FROM risque "
                "WHERE contribuable_id = :c "
                "AND origine_mission_id IN (:mr, :mp) "
                "AND statut IN :statuts ORDER BY id"
            ).bindparams(bindparam("statuts", expanding=True)),
            {
                "c": contribuable_id,
                "mr": int(mission_recente["id"]),
                "mp": int(mission_precedente["id"]),
                "statuts": sorted(STATUTS_NON_CLOS),
            },
        ).mappings().all()

    risques_recent = [
        dict(r)
        for r in rows
        if int(r["origine_mission_id"]) == int(mission_recente["id"])
    ]
    risques_precedent = [
        dict(r)
        for r in rows
        if int(r["origine_mission_id"]) == int(mission_precedente["id"])
    ]
    agregats_recent = agreger_par_impot(risques_recent)
    agregats_precedent = agreger_par_impot(risques_precedent)
    return {
        **base,
        "disponible": True,
        "raison": None,
        "exercice_recent": {
            "exercice": int(mission_recente["exercice"]),
            "mission_id": int(mission_recente["id"]),
            "statut_mission": str(mission_recente["statut"]),
        },
        "exercice_precedent": {
            "exercice": int(mission_precedente["exercice"]),
            "mission_id": int(mission_precedente["id"]),
            "statut_mission": str(mission_precedente["statut"]),
        },
        "par_impot": comparer_agregats(agregats_recent, agregats_precedent),
        "synthese": synthese_comparaison(
            agregats_recent, agregats_precedent
        ),
    }
