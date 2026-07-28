"""Délais de traitement par étape — pilotage du processus de mission.

POURQUOI : le journal d'audit (table ``journal_audit`` : horodatage,
acteur, action — écriture seule, hash chaîné) trace déjà les moments
clés d'une mission : création, premier dépôt de pièce en data room,
génération de la demande de renseignements, premières constatations
(exécution de la revue), premier visa de supervision, restitution.
Ce module en déduit les JALONS datés et les DURÉES en jours entre
jalons consécutifs, pour identifier où le temps se perd.

LIMITE ASSUMÉE : restitution strictement CONSULTATIVE et déterministe —
aucune écriture, aucun LLM, aucun jugement : ce sont des délais
indicatifs issus du journal, l'humain interprète. Un jalon absent
(action jamais journalisée) a une date ``None`` et est ponté : les
durées relient les jalons datés entre eux. Les durées sont des
``str`` de ``Decimal`` arrondis au dixième de jour. La consultation
elle-même est journalisée (:data:`ACTION_CONSULTATION`) mais EXCLUE du
calcul pour ne pas polluer les jalons. Fonctions pures + lecture seule
sous RLS via ``contexte_tenant``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# Code journalisé par la route de consultation — jamais un jalon.
ACTION_CONSULTATION: Final[str] = "consultation_delais_mission"

MENTION_NOTE: Final[str] = (
    "Vue consultative — délais indicatifs déduits du journal d'audit "
    "de la mission (première occurrence de chaque étape). Un jalon "
    "absent signifie que l'étape n'a pas encore été journalisée ; les "
    "durées relient les étapes datées entre elles. Une durée négative "
    "signale une étape survenue avant la précédente dans l'ordre "
    "canonique. L'humain interprète."
)

# Jalons canoniques, dans l'ordre du processus de mission.
# (code jalon, codes d'action RÉELS du journal, libellé français)
JALONS: Final[list[tuple[str, tuple[str, ...], str]]] = [
    ("creation", ("creation_mission",), "Création de la mission"),
    (
        "premier_depot_piece",
        ("depot_piece_contribuable",),
        "Premier dépôt de pièce en data room",
    ),
    (
        "demande_renseignements",
        ("telechargement_demande_renseignements",),
        "Génération de la demande de renseignements",
    ),
    (
        "premieres_constatations",
        ("execution_moteur",),
        "Premières constatations (exécution de la revue)",
    ),
    (
        "premier_visa",
        ("pose_visa_mission",),
        "Premier visa de supervision",
    ),
    (
        "restitution",
        ("enregistrement_compte_rendu",),
        "Restitution (compte-rendu de réunion)",
    ),
]


class ErreurDelaisMission(Exception):
    """Échec du calcul des délais de mission."""


class ErreurDelaisIntrouvable(ErreurDelaisMission):
    """Mission hors périmètre du tenant — 404 côté route."""


# ── Fonctions pures ──────────────────────────────────────────────────


def _parser_horodatage(valeur: Any) -> datetime | None:
    """PUR — horodatage (datetime ou ISO 8601) → datetime UTC naïf.

    Normalise en UTC naïf pour permettre la soustraction entre valeurs
    avec et sans fuseau. Valeur illisible → ``None`` (jalon inexploitable
    plutôt qu'une durée fausse).
    """
    if isinstance(valeur, datetime):
        d = valeur
    else:
        brut = str(valeur or "").strip()
        if not brut:
            return None
        try:
            d = datetime.fromisoformat(brut)
        except ValueError:
            return None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def calculer_jalons(
    evenements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — événements ``{action, horodatage}`` → jalons datés.

    Pour chaque jalon canonique (:data:`JALONS`), retient la PREMIÈRE
    occurrence (horodatage minimal) parmi ses codes d'action. Jalon
    jamais journalisé → ``date`` à ``None``. Les consultations des
    délais eux-mêmes (:data:`ACTION_CONSULTATION`) sont ignorées.

    Chaque item : ``{code, libelle, date}`` (date ISO 8601 ou None).
    """
    premieres: dict[str, datetime] = {}
    for e in evenements:
        action = str(e.get("action") or "").strip()
        if not action or action == ACTION_CONSULTATION:
            continue
        quand = _parser_horodatage(e.get("horodatage"))
        if quand is None:
            continue
        deja = premieres.get(action)
        if deja is None or quand < deja:
            premieres[action] = quand

    jalons: list[dict[str, Any]] = []
    for code, actions, libelle in JALONS:
        dates = [premieres[a] for a in actions if a in premieres]
        premiere = min(dates) if dates else None
        jalons.append(
            {
                "code": code,
                "libelle": libelle,
                "date": premiere.isoformat() if premiere else None,
            }
        )
    return jalons


def _jours_entre(debut: datetime, fin: datetime) -> str:
    """PUR — durée en jours (Decimal str, arrondi au dixième)."""
    secondes = Decimal(str((fin - debut).total_seconds()))
    jours = secondes / Decimal("86400")
    return str(jours.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def calculer_durees(
    jalons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """PUR — jalons datés → durées entre jalons DATÉS consécutifs.

    Les jalons absents (date ``None``) sont pontés : chaque durée relie
    un jalon daté au jalon daté suivant dans l'ordre canonique, pour ne
    pas perdre l'écoulement du temps quand une étape n'a pas été
    journalisée. Une durée peut être négative si l'étape suivante est
    survenue avant la précédente (ordre observé ≠ ordre canonique) —
    valeur factuelle, l'humain interprète.

    Chaque item : ``{de, a, jours}`` avec ``jours`` en str Decimal
    (arrondi 0.1).
    """
    dates = [
        (j["code"], d)
        for j in jalons
        if (d := _parser_horodatage(j.get("date"))) is not None
    ]
    return [
        {"de": code1, "a": code2, "jours": _jours_entre(d1, d2)}
        for (code1, d1), (code2, d2) in zip(dates, dates[1:])
    ]


def duree_totale(jalons: list[dict[str, Any]]) -> str | None:
    """PUR — durée entre le premier et le dernier jalon datés.

    ``None`` si moins de deux jalons sont datés (rien à mesurer).
    """
    dates = [
        d
        for d in (_parser_horodatage(j.get("date")) for j in jalons)
        if d is not None
    ]
    if len(dates) < 2:
        return None
    return _jours_entre(min(dates), max(dates))


# ── Lecture par mission (RLS) ────────────────────────────────────────


def delais_mission(
    session: Session,
    tenant_id: int,
    mission_id: int,
) -> dict[str, Any]:
    """Délais de traitement de la mission — lecture seule, RLS.

    Lit les événements ``{action, horodatage}`` du journal d'audit
    rattachés à la mission puis délègue le calcul aux fonctions pures.
    Mission hors tenant → :class:`ErreurDelaisIntrouvable` (404).
    """
    with contexte_tenant(session, tenant_id):
        mission = session.execute(
            text("SELECT id FROM mission WHERE id = :m"),
            {"m": mission_id},
        ).scalar_one_or_none()
        if mission is None:
            raise ErreurDelaisIntrouvable(
                f"mission {mission_id} introuvable"
            )
        rows = session.execute(
            text(
                "SELECT action, horodatage FROM journal_audit "
                "WHERE mission_id = :m AND action <> :excl "
                "ORDER BY id"
            ),
            {"m": mission_id, "excl": ACTION_CONSULTATION},
        ).mappings().all()

    jalons = calculer_jalons([dict(r) for r in rows])
    return {
        "mission_id": mission_id,
        "jalons": jalons,
        "durees": calculer_durees(jalons),
        "duree_totale_jours": duree_totale(jalons),
        "note": MENTION_NOTE,
    }
