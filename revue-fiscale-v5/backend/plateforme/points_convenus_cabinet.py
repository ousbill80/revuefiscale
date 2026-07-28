"""Points convenus en attente au niveau cabinet — vue transverse.

POURQUOI : le suivi des points convenus
(:mod:`backend.plateforme.points_convenus`) vit mission par mission ;
sur le tableau de bord cabinet, le fiscaliste veut voir d'un coup
d'œil TOUS les points encore « a_faire » de ses clients (missions
« en_cours » ou « cloturee » — le suivi se poursuit après clôture),
avec leur ancienneté, pour relancer sans ouvrir chaque mission.

LIMITE ASSUMÉE : vue strictement CONSULTATIVE — le tableau éclaire la
relance, l'humain décide et agit dans la mission concernée. Aucune
écriture, aucun LLM. Fonctions pures + lecture seule sous RLS via
``contexte_tenant`` (même pattern que
:mod:`backend.plateforme.echeances_cabinet`).
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

# Au-delà de 30 jours sans traitement, le point est « ancien »
# (badge rouge côté tableau de bord — relance prioritaire).
SEUIL_ANCIEN_JOURS: Final[int] = 30

# Plafond d'items restitués — vue de pilotage, pas un export exhaustif.
PLAFOND_ITEMS: Final[int] = 100

MENTION_NOTE: Final[str] = (
    "Vue consultative — points convenus encore « à faire » de tous les "
    "clients (missions en cours ou clôturées), du plus ancien au plus "
    "récent, pour prioriser les relances. Le traitement d'un point se "
    "décide et se saisit dans la mission concernée : l'humain décide."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def anciennete_jours(cree_le: object, aujourd_hui: date) -> int:
    """PUR — ancienneté d'un point en jours entiers depuis sa création.

    ``cree_le`` : ``datetime``, ``date`` ou chaîne ISO (les 10 premiers
    caractères suffisent — la granularité est le jour). Toujours ≥ 0
    (une création « future » — horloge décalée — vaut 0) ; valeur
    illisible → 0 (défensif, jamais bloquant).
    """
    if isinstance(cree_le, datetime):
        jour_creation = cree_le.date()
    elif isinstance(cree_le, date):
        jour_creation = cree_le
    else:
        try:
            jour_creation = date.fromisoformat(str(cree_le or "")[:10])
        except ValueError:
            return 0
    return max(0, (aujourd_hui - jour_creation).days)


def trier_points(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — plus ancien d'abord, puis client, puis id du point.

    Le point qui attend depuis le plus longtemps arrive en tête ; à
    ancienneté égale, ordre alphabétique des clients puis id croissant
    — stable et lisible.
    """
    def _cle(i: dict[str, Any]) -> tuple:
        return (
            -int(i.get("anciennete_jours") or 0),
            str(i.get("client") or ""),
            int(i.get("point_id") or 0),
        )

    return sorted(items, key=_cle)


def plafonner_points(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — tronque à :data:`PLAFOND_ITEMS` (liste déjà triée).

    Le plafond ne coupe donc que les points les plus récents — les
    plus anciens (à relancer en priorité) restent visibles.
    """
    return list(items)[:PLAFOND_ITEMS]


def synthese_points_cabinet(items: list[dict[str, Any]]) -> dict[str, int]:
    """PUR — compteurs : total, anciens (> 30 jours), clients, retards."""
    anciens = sum(
        1
        for i in items
        if int(i.get("anciennete_jours") or 0) > SEUIL_ANCIEN_JOURS
    )
    clients = {str(i.get("client") or "") for i in items}
    return {
        "total": len(items),
        "anciens_30j": anciens,
        "clients": len(clients),
        "en_retard": sum(1 for i in items if bool(i.get("en_retard"))),
    }


# ── Export CSV (Excel FR, séparateur « ; ») ──────────────────────────

# En-tête du CSV des points convenus en attente — délimiteur « ; ».
ENTETE_POINTS_CSV: Final[tuple[str, ...]] = (
    "anciennete_jours",
    "client",
    "exercice",
    "libelle",
    "date_cible",
    "statut_mission",
    "cree_le",
)


def generer_csv(vue: dict) -> str:
    """PUR — CSV « ; » des points convenus en attente (Excel FR).

    Une ligne par item de ``vue["items"]``, dans l'ordre trié (plus
    ancien d'abord). Échappement CSV par le module stdlib : valeurs
    entre guillemets (doublés) si elles contiennent « ; », un guillemet
    ou un retour à la ligne. Le BOM UTF-8 est ajouté côté route, pas
    ici. Liste vide → en-tête seul. La colonne « date_cible » (après
    « libelle » — l'échéance qualifie le point) est vide si le point
    n'en porte pas.
    """
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(ENTETE_POINTS_CSV)
    for i in list(vue.get("items") or []):
        anciennete = i.get("anciennete_jours")
        w.writerow(
            [
                str(anciennete) if anciennete is not None else "",
                str(i.get("client") or ""),
                str(i.get("exercice") or ""),
                str(i.get("libelle") or ""),
                str(i.get("date_cible") or ""),
                str(i.get("statut_mission") or ""),
                str(i.get("cree_le") or ""),
            ]
        )
    return buf.getvalue()


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def points_convenus_cabinet(
    session: Session, tenant_id: int, aujourd_hui: date | None = None
) -> dict[str, Any]:
    """Points « a_faire » de tous les clients — lecture seule, RLS.

    Jointure ``point_convenu`` → ``mission`` → ``contribuable`` du
    tenant : points au statut « a_faire » des missions « en_cours » ou
    « cloturee », les plus anciens d'abord, plafonnés à
    :data:`PLAFOND_ITEMS` (SQL puis re-tri pur sur l'ancienneté
    calculée). Se construit toujours (tenant sans point → liste vide).
    """
    from backend.plateforme.missions import STATUT_CLOTUREE, STATUT_EN_COURS
    from backend.plateforme.points_convenus import (
        STATUT_A_FAIRE,
        point_en_retard,
    )

    jour = aujourd_hui or date.today()
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT p.id AS point_id, p.libelle, p.date_cible, "
                "p.cree_le, "
                "m.id AS mission_id, m.exercice, "
                "m.statut AS statut_mission, "
                "c.denomination AS client "
                "FROM point_convenu p "
                "JOIN mission m ON m.id = p.mission_id "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE p.statut = :sp AND m.statut IN (:s1, :s2) "
                "ORDER BY p.cree_le, c.denomination, p.id "
                "LIMIT :lim"
            ),
            {
                "sp": STATUT_A_FAIRE,
                "s1": STATUT_EN_COURS,
                "s2": STATUT_CLOTUREE,
                "lim": PLAFOND_ITEMS,
            },
        ).mappings().all()

    items: list[dict[str, Any]] = []
    for r in rows:
        cree = r["cree_le"]
        cible = r["date_cible"]
        items.append(
            {
                "client": str(r["client"] or ""),
                "mission_id": int(r["mission_id"]),
                "exercice": int(r["exercice"]),
                "statut_mission": str(r["statut_mission"] or ""),
                "point_id": int(r["point_id"]),
                "libelle": str(r["libelle"] or ""),
                "date_cible": (
                    cible.isoformat() if isinstance(cible, date) else None
                ),
                "en_retard": point_en_retard(STATUT_A_FAIRE, cible, jour),
                "anciennete_jours": anciennete_jours(cree, jour),
                "cree_le": (
                    cree.isoformat() if isinstance(cree, datetime) else None
                ),
            }
        )
    items = plafonner_points(trier_points(items))
    return {
        "aujourd_hui": jour.isoformat(),
        "items": items,
        "synthese": synthese_points_cabinet(items),
        "note": MENTION_NOTE,
    }
