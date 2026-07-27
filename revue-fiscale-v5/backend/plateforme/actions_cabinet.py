"""Actions à mettre en œuvre du cabinet — décisions « retenue » du plan.

Vue TRANSVERSE pour le fiscaliste : sur toutes les missions du tenant
(clôturées incluses — la décision reste à mettre en œuvre), les actions
du plan d'actions marquées « retenue » dans ``suivi_plan_actions`` et
non encore « faites » ni « écartées » (une décision ultérieure remplace
la ligne par UPSERT — seul l'état courant ``retenue`` ressort). Même
définition que le bloc « Actions retenues en cours » de la fiche client
(:func:`backend.plateforme.plan_actions.actions_retenues_contribuable`),
mais tous clients confondus : la liste de travail du cabinet, avec
l'exposition totale en jeu.

Analyse CONSULTATIVE : une action « retenue » est une décision HUMAINE
déjà prise — ce bloc rappelle seulement ce qui reste à mettre en œuvre ;
le fiscaliste et le client décident de la suite. Aucun LLM : lecture
seule sous RLS.
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.plan_actions import (
    DECISION_RETENUE,
    PREFIXE_CLE_RISQUE,
    _exposition,
)
from backend.plateforme.risques import STATUTS_NON_CLOS

# ── Constantes ───────────────────────────────────────────────────────

# Plafond d'items retournés — liste opérationnelle, pas un export.
PLAFOND_ITEMS: Final[int] = 50

MENTION_NOTE: Final[str] = (
    "Liste consultative — actions du plan d'actions marquées « retenue » "
    "par le fiscaliste et non encore faites, tous clients confondus. "
    "Chaque action reste une suggestion : le fiscaliste apprécie sa "
    "pertinence et le client décide de sa mise en œuvre."
)


# ── Fonctions pures ──────────────────────────────────────────────────


def trier_actions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PUR — tri par exposition décroissante puis client, mission.

    La plus grosse exposition en tête (l'enjeu le plus fort d'abord) ;
    les actions sans exposition chiffrée en queue ; à exposition égale,
    ordre alphabétique des clients puis mission et clé — stable et
    lisible.
    """
    def _cle(i: dict[str, Any]) -> tuple:
        brut = i.get("exposition")
        exposition = (
            Decimal(str(brut)) if brut is not None and brut != "" else None
        )
        return (
            # None (non chiffrée) après les montants, puis desc.
            (1, Decimal("0")) if exposition is None else (0, -exposition),
            str(i.get("client") or ""),
            int(i.get("mission_id") or 0),
            str(i.get("cle_action") or ""),
        )

    return sorted(items, key=_cle)


def synthese_actions(items: list[dict[str, Any]]) -> dict[str, Any]:
    """PUR — compteurs : total, clients distincts, exposition totale.

    ``exposition_totale`` : somme Decimal des expositions chiffrées,
    sérialisée en str (les actions non chiffrées comptent pour 0).
    """
    clients = {str(i.get("client") or "") for i in items}
    exposition = Decimal("0")
    for i in items:
        brut = i.get("exposition")
        if brut is not None and brut != "":
            exposition += Decimal(str(brut))
    return {
        "total": len(items),
        "clients": len(clients),
        "exposition_totale": str(exposition),
    }


# ── Export CSV (Excel FR, séparateur « ; ») ──────────────────────────

# En-tête du CSV des actions retenues — délimiteur « ; » (Excel FR).
ENTETE_ACTIONS_CSV: Final[tuple[str, ...]] = (
    "client",
    "mission",
    "exercice",
    "impot",
    "libelle",
    "exposition",
    "note",
)


def generer_csv(actions: dict) -> str:
    """PUR — CSV « ; » des actions retenues à mettre en œuvre (Excel FR).

    Une ligne par item de ``actions["items"]``, dans l'ordre trié des
    actions (exposition décroissante puis client, mission). Échappement
    CSV par le module stdlib : valeurs entre guillemets (doublés) si
    elles contiennent « ; », un guillemet ou un retour à la ligne. Le
    BOM UTF-8 est ajouté côté route, pas ici. Liste vide → en-tête seul.
    """
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(ENTETE_ACTIONS_CSV)
    for i in list(actions.get("items") or []):
        w.writerow(
            [
                str(i.get("client") or ""),
                str(i.get("mission_id") or ""),
                str(i.get("exercice") or ""),
                str(i.get("impot") or ""),
                str(i.get("libelle_risque") or ""),
                str(i.get("exposition") or ""),
                str(i.get("decision_note") or ""),
            ]
        )
    return buf.getvalue()


# ── Lecture cabinet (RLS) ────────────────────────────────────────────


def actions_retenues_cabinet(
    session: Session, tenant_id: int
) -> dict[str, Any]:
    """Actions retenues à mettre en œuvre du cabinet (lecture, RLS).

    Décisions ``retenue`` de ``suivi_plan_actions`` sur toutes les
    missions du tenant, avec mission, client (JOIN) et risque d'origine
    (LEFT JOIN via ``cle_action`` = ``risque:{id}`` — s'il a été clos ou
    purgé depuis, l'action reste listée avec ``risque_clos = true``).
    Tri par exposition décroissante puis client ; liste plafonnée à
    :data:`PLAFOND_ITEMS` (la synthèse reste calculée sur l'ensemble).
    Se construit toujours (tenant sans action → liste vide, sans
    erreur).
    """
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT s.mission_id, s.cle_action, s.note, s.maj_le, "
                "m.exercice, c.denomination, r.libelle, r.impot, "
                "r.statut AS statut_risque, r.montant_estime, "
                "r.penalites_estimees "
                "FROM suivi_plan_actions s "
                "JOIN mission m ON m.id = s.mission_id "
                "JOIN contribuable c ON c.id = m.contribuable_id "
                "LEFT JOIN risque r "
                "ON s.cle_action = :prefixe || r.id::text "
                "AND r.contribuable_id = m.contribuable_id "
                "WHERE s.decision = :d "
                "ORDER BY c.denomination, s.mission_id, s.id"
            ),
            {"prefixe": PREFIXE_CLE_RISQUE, "d": DECISION_RETENUE},
        ).mappings().all()

    items: list[dict[str, Any]] = []
    for r in rows:
        statut = (
            str(r["statut_risque"]).lower()
            if r["statut_risque"] is not None
            else None
        )
        exposition = _exposition(dict(r))
        maj = r["maj_le"]
        items.append(
            {
                "mission_id": int(r["mission_id"]),
                "client": str(r["denomination"] or ""),
                "exercice": int(r["exercice"]),
                "cle_action": str(r["cle_action"]),
                "libelle_risque": str(r["libelle"] or ""),
                "impot": str(r["impot"] or "").upper(),
                "exposition": (
                    str(exposition) if exposition is not None else None
                ),
                # Risque clos (ou purgé) depuis la décision — l'action
                # retenue reste affichée avec mention.
                "risque_clos": statut is None
                or statut not in STATUTS_NON_CLOS,
                "decision_note": (r["note"] or None) or None,
                "maj_le": maj.isoformat() if maj is not None else None,
            }
        )
    items = trier_actions(items)
    return {
        "total": len(items),
        "synthese": synthese_actions(items),
        "items": items[:PLAFOND_ITEMS],
        "note": MENTION_NOTE,
    }
