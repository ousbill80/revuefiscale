"""Préparation à la clôture des missions du cabinet — vue transverse.

POURQUOI : sur le tableau de bord cabinet, le fiscaliste veut voir d'un
coup d'œil quelles missions EN COURS sont prêtes à être clôturées et ce
qui bloque encore sur les autres — sans ouvrir chaque mission. Ce bloc
agrège le bilan de pré-clôture existant
(:func:`backend.plateforme.bilan_cloture.bilan_mission`) sur les
missions au statut « en_cours » : nombre de points au vert, points
d'attention restants (libellés), statut « prête » quand aucun point
n'est en attention.

LIMITE ASSUMÉE : vue strictement CONSULTATIVE — aucun statut bloquant,
aucune écriture, aucun LLM. La clôture reste un clic explicite du
fiscaliste sur la mission ; ce bloc l'aide seulement à prioriser.
Fonctions pures + lecture seule sous RLS via ``contexte_tenant``.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.bilan_cloture import STATUT_ATTENTION
from backend.plateforme.contexte import contexte_tenant

# ── Constantes ───────────────────────────────────────────────────────

# Plafond de missions examinées — vue de pilotage, pas un export
# (chaque mission déclenche un bilan complet : coût borné et prévisible).
PLAFOND_MISSIONS: Final[int] = 20

# Plafond de libellés d'attention restitués par mission — lisibilité du
# tableau de bord (le bilan complet reste consultable sur la mission).
PLAFOND_POINTS_ATTENTION: Final[int] = 5

MENTION_NOTE: Final[str] = (
    "Vue consultative — état de préparation à la clôture des missions "
    "en cours, d'après le bilan de pré-clôture de chacune. La clôture "
    "reste une décision explicite du fiscaliste sur la mission."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def synthese_bilan(bilan: dict[str, Any]) -> dict[str, Any]:
    """PUR — synthèse d'un bilan de pré-clôture pour le tableau de bord.

    Depuis le retour de :func:`bilan_cloture.bilan_mission`
    (``{points, synthese, note}``) : compteurs ok/attention, libellés
    des points d'attention (plafonnés à
    :data:`PLAFOND_POINTS_ATTENTION`) et statut ``prete`` quand AUCUN
    point n'est en attention — simple lecture, jamais bloquante.
    """
    points = list(bilan.get("points") or [])
    attention = [
        str(p.get("libelle") or "")
        for p in points
        if p.get("statut") == STATUT_ATTENTION
    ]
    return {
        "nb_ok": len(points) - len(attention),
        "nb_attention": len(attention),
        "prete": len(attention) == 0,
        "points_attention": attention[:PLAFOND_POINTS_ATTENTION],
    }


def trier_preparation(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — prêtes d'abord, puis nb_attention croissant, puis client.

    Les missions prêtes à clôturer en tête (le fiscaliste peut agir
    tout de suite), puis les plus proches de l'être ; à égalité, ordre
    alphabétique des clients puis mission — stable et lisible.
    """
    def _cle(i: dict[str, Any]) -> tuple:
        return (
            0 if bool(i.get("prete")) else 1,
            int(i.get("nb_attention") or 0),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
        )

    return sorted(items, key=_cle)


def synthese_preparation(items: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs : missions en cours, prêtes, à compléter."""
    pretes = sum(1 for i in items if bool(i.get("prete")))
    return {
        "en_cours": len(items),
        "pretes": pretes,
        "a_completer": len(items) - pretes,
    }


# ── Export CSV (Excel FR, séparateur « ; ») ──────────────────────────

# En-tête du CSV de préparation à la clôture — délimiteur « ; ».
ENTETE_CLOTURE_CSV: Final[tuple[str, ...]] = (
    "client",
    "exercice",
    "statut_preparation",
    "nb_ok",
    "nb_attention",
    "points_attention",
)

# Statuts en clair pour le tableur — vocabulaire du tableau de bord.
STATUT_CSV_PRETE: Final[str] = "Prête"
STATUT_CSV_A_COMPLETER: Final[str] = "À compléter"


def generer_csv(preparation: dict) -> str:
    """PUR — CSV « ; » de la préparation à la clôture (Excel FR).

    Une ligne par item de ``preparation["items"]``, dans l'ordre trié
    (prêtes d'abord, puis nb_attention croissant). ``statut_preparation``
    en clair (« Prête » / « À compléter ») ; les points d'attention sont
    joints par « | » dans une seule cellule. Échappement CSV par le
    module stdlib : valeurs entre guillemets (doublés) si elles
    contiennent « ; », un guillemet ou un retour à la ligne. Le BOM
    UTF-8 est ajouté côté route, pas ici. Liste vide → en-tête seul.
    """
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(ENTETE_CLOTURE_CSV)
    for i in list(preparation.get("items") or []):
        nb_ok = i.get("nb_ok")
        nb_attention = i.get("nb_attention")
        w.writerow(
            [
                str(i.get("client") or ""),
                str(i.get("exercice") or ""),
                STATUT_CSV_PRETE
                if bool(i.get("prete"))
                else STATUT_CSV_A_COMPLETER,
                str(nb_ok) if nb_ok is not None else "",
                str(nb_attention) if nb_attention is not None else "",
                " | ".join(
                    str(p or "") for p in (i.get("points_attention") or [])
                ),
            ]
        )
    return buf.getvalue()


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def preparation_cloture_cabinet(
    session: Session, tenant_id: int
) -> dict[str, Any]:
    """Préparation à la clôture des missions en cours (lecture, RLS).

    Missions au statut « en_cours » du tenant (plafonnées à
    :data:`PLAFOND_MISSIONS`), chacune passée au bilan de pré-clôture
    (:func:`bilan_cloture.bilan_mission` — appelée HORS de tout
    ``with`` : elle ouvre ses propres contextes). Une mission dont le
    bilan échoue est simplement omise (échec silencieux, jamais
    bloquant). Tri : prêtes d'abord, puis nb_attention croissant. Se
    construit toujours (tenant sans mission en cours → liste vide).
    """
    from backend.plateforme.bilan_cloture import bilan_mission
    from backend.plateforme.missions import STATUT_EN_COURS

    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT m.id AS mission_id, m.exercice, "
                "c.denomination AS client "
                "FROM mission m "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "WHERE m.statut = :s "
                "ORDER BY c.denomination, m.id "
                "LIMIT :lim"
            ),
            {"s": STATUT_EN_COURS, "lim": PLAFOND_MISSIONS},
        ).mappings().all()

    items: list[dict[str, Any]] = []
    for r in rows:
        # bilan_mission ouvre ses PROPRES contexte_tenant : appel HORS
        # de tout with. Tolérance d'erreur par mission : un bilan qui
        # échoue n'empêche pas le reste du tableau de bord.
        try:
            bilan = bilan_mission(session, tenant_id, int(r["mission_id"]))
        except Exception:
            continue
        items.append(
            {
                "mission_id": int(r["mission_id"]),
                "client": str(r["client"] or ""),
                "exercice": int(r["exercice"]),
                **synthese_bilan(bilan),
            }
        )
    items = trier_preparation(items)
    return {
        "items": items,
        "synthese": synthese_preparation(items),
        "note": MENTION_NOTE,
    }
