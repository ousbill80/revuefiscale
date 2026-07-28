"""Délais moyens de traitement du cabinet — vue transverse.

POURQUOI : les délais par mission (:mod:`delais_mission`) montrent où
UNE mission a traîné ; le cabinet veut aussi savoir sur quelles étapes
SES missions traînent EN MOYENNE — amélioration continue du processus
(ex. « le premier visa arrive systématiquement 6 jours après les
constatations »). Ce module agrège les jalons de chaque mission en
moyennes par transition canonique et identifie la transition la plus
lente.

CHOIX D'AGRÉGATION : contrairement à la vue par mission (qui PONTE les
jalons absents pour ne pas perdre l'écoulement du temps), l'agrégat ne
retient la durée d'une transition « de → a » QUE si les deux jalons
canoniquement CONSÉCUTIFS sont datés. Une durée pontée (ex. création →
constatations faute de dépôt journalisé) mesure autre chose que la
transition élémentaire : la mélanger aux durées strictes fausserait la
moyenne.

LIMITE ASSUMÉE : vue strictement CONSULTATIVE et déterministe — aucune
écriture, aucun LLM, aucun jugement : des moyennes indicatives issues
du journal d'audit, l'humain interprète. Moyennes en ``str`` de
``Decimal`` arrondis au dixième de jour (``None`` sans observation) ;
une moyenne négative reste possible (ordre observé ≠ ordre canonique).
Fonctions pures + lecture seule sous RLS via ``contexte_tenant``.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.delais_mission import (
    JALONS,
    _parser_horodatage,
    calculer_durees,
)

# Code journalisé par la route de consultation — jamais un jalon.
ACTION_CONSULTATION: Final[str] = "consultation_delais_cabinet"

# Plafond de missions agrégées — vue de pilotage, coût borné.
PLAFOND_MISSIONS: Final[int] = 50

MENTION_NOTE: Final[str] = (
    "Vue consultative — moyennes indicatives déduites du journal "
    "d'audit des missions du cabinet. Une transition n'est comptée "
    "pour une mission que si les deux étapes consécutives y sont "
    "datées ; une moyenne absente signifie qu'aucune mission n'a les "
    "deux étapes journalisées. L'humain interprète."
)

# Transitions canoniques : paires de jalons consécutifs de JALONS.
TRANSITIONS: Final[list[tuple[str, str, str, str]]] = [
    (c1, c2, l1, l2)
    for (c1, _a1, l1), (c2, _a2, l2) in zip(JALONS, JALONS[1:])
]

# Rang canonique de chaque jalon — pour détecter les durées pontées.
_RANG: Final[dict[str, int]] = {
    code: i for i, (code, _actions, _lib) in enumerate(JALONS)
}


# ── Fonctions pures ──────────────────────────────────────────────────


def durees_canoniques(jalons: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    """PUR — durées STRICTEMENT canoniques d'une mission.

    Depuis les jalons (format :func:`delais_mission.calculer_jalons`),
    ne garde que les durées entre jalons canoniquement CONSÉCUTIFS tous
    deux datés — les durées pontées (jalon absent entre les deux) sont
    écartées : elles mesurent autre chose que la transition élémentaire.
    Retourne ``{(de, a): jours}`` (str Decimal, négatif possible).
    """
    return {
        (d["de"], d["a"]): d["jours"]
        for d in calculer_durees(jalons)
        if _RANG[d["a"]] - _RANG[d["de"]] == 1
    }


def duree_creation_dernier(jalons: list[dict[str, Any]]) -> str | None:
    """PUR — durée de la création au DERNIER jalon daté de la mission.

    ``None`` si la création n'est pas datée ou si aucun autre jalon
    n'est daté (rien à mesurer).
    """
    dates = [
        d
        for j in jalons
        if (d := _parser_horodatage(j.get("date"))) is not None
    ]
    if not jalons or len(dates) < 2:
        return None
    creation = _parser_horodatage(jalons[0].get("date"))
    if creation is None:
        return None
    secondes = Decimal(str((max(dates) - creation).total_seconds()))
    jours = secondes / Decimal("86400")
    return str(jours.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def moyenne_jours(valeurs: list[str]) -> str | None:
    """PUR — moyenne de durées str Decimal, arrondie au dixième.

    ``None`` si la liste est vide (aucune observation ≠ moyenne nulle).
    """
    if not valeurs:
        return None
    total = sum(Decimal(v) for v in valeurs)
    moyenne = total / Decimal(len(valeurs))
    return str(moyenne.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def agreger_delais(missions: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — agrège les jalons par mission en moyennes par transition.

    Entrée : ``[{mission_id, client, jalons}]`` (jalons au format de
    :func:`calculer_jalons`). Sortie : transitions canoniques avec
    ``moyenne_jours`` (str Decimal 0.1, None sans observation) et
    ``nb_missions`` observées, durée totale moyenne (création → dernier
    jalon daté de chaque mission) et transition la plus lente (moyenne
    maximale ; à égalité, la première dans l'ordre canonique).
    """
    observations: dict[tuple[str, str], list[str]] = {
        (de, a): [] for (de, a, _l1, _l2) in TRANSITIONS
    }
    totales: list[str] = []
    for m in missions:
        jalons = list(m.get("jalons") or [])
        for paire, jours in durees_canoniques(jalons).items():
            observations[paire].append(jours)
        totale = duree_creation_dernier(jalons)
        if totale is not None:
            totales.append(totale)

    transitions: list[dict[str, Any]] = []
    for de, a, libelle_de, libelle_a in TRANSITIONS:
        obs = observations[(de, a)]
        transitions.append(
            {
                "de": de,
                "a": a,
                "libelle_de": libelle_de,
                "libelle_a": libelle_a,
                "moyenne_jours": moyenne_jours(obs),
                "nb_missions": len(obs),
            }
        )

    plus_lente: dict[str, Any] | None = None
    for t in transitions:
        if t["moyenne_jours"] is None:
            continue
        if plus_lente is None or Decimal(t["moyenne_jours"]) > Decimal(
            plus_lente["moyenne_jours"]
        ):
            plus_lente = t

    return {
        "transitions": transitions,
        "duree_totale_moyenne_jours": moyenne_jours(totales),
        "nb_missions": len(missions),
        "transition_la_plus_lente": plus_lente,
    }


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def delais_cabinet(session: Session, tenant_id: int) -> dict[str, Any]:
    """Délais moyens de traitement du cabinet — lecture seule, RLS.

    Missions non archivées du tenant (tous statuts : cadrage, en_cours,
    cloturee — aucun statut « archivée » n'existe à ce jour), plafonnées
    à :data:`PLAFOND_MISSIONS` (les plus récentes d'abord). Une seule
    requête groupée lit les événements du journal, en excluant les
    consultations (actions ``consultation_%`` — jamais des jalons),
    puis les fonctions pures calculent jalons et moyennes.
    """
    from backend.plateforme.delais_mission import calculer_jalons

    with contexte_tenant(session, tenant_id):
        missions_rows = session.execute(
            text(
                "SELECT m.id AS mission_id, c.denomination AS client "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "ORDER BY m.id DESC "
                "LIMIT :lim"
            ),
            {"lim": PLAFOND_MISSIONS},
        ).mappings().all()

        evenements: dict[int, list[dict[str, Any]]] = {
            int(r["mission_id"]): [] for r in missions_rows
        }
        if evenements:
            rows = session.execute(
                text(
                    "SELECT mission_id, action, horodatage "
                    "FROM journal_audit "
                    "WHERE mission_id IN :mids "
                    "AND action NOT LIKE 'consultation\\_%' ESCAPE '\\' "
                    "ORDER BY id"
                ).bindparams(bindparam("mids", expanding=True)),
                {"mids": list(evenements)},
            ).mappings().all()
            for r in rows:
                evenements[int(r["mission_id"])].append(
                    {"action": r["action"], "horodatage": r["horodatage"]}
                )

    missions = [
        {
            "mission_id": int(r["mission_id"]),
            "client": str(r["client"] or ""),
            "jalons": calculer_jalons(evenements[int(r["mission_id"])]),
        }
        for r in missions_rows
    ]
    return {**agreger_delais(missions), "note": MENTION_NOTE}
