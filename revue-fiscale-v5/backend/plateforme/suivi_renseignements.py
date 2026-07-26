"""Suivi de circularisation de la demande de renseignements.

En cabinet, après l'envoi de la « Demande de renseignements et de
documents », il faut suivre les réponses du client : quels items sont
reçus, lesquels restent en attente, lesquels sont à relancer. La liste
des items est RECONSTRUITE à chaque lecture depuis les mêmes sources que
le livrable .docx (``demande_renseignements.collecter_items``) puis
fusionnée (LEFT JOIN logique) avec les statuts saisis dans la table
``suivi_demande_renseignements``. Aucun taux ni seuil fiscal ici.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.demande_renseignements import collecter_items

STATUTS_SUIVI: Final = ("en_attente", "recu", "sans_objet")
STATUT_DEFAUT: Final = "en_attente"


class ErreurSuiviRenseignements(Exception):
    """Echec du suivi (mission introuvable, statut ou item invalide…)."""


class ErreurSuiviIntrouvable(ErreurSuiviRenseignements):
    """Mission ou item hors périmètre du tenant — 404 côté route."""


def _mission_existe(session: Session, mission_id: int) -> bool:
    return (
        session.execute(
            text("SELECT 1 FROM mission WHERE id = :m"), {"m": mission_id}
        ).scalar_one_or_none()
        is not None
    )


def _statuts_enregistres(
    session: Session, mission_id: int
) -> dict[str, dict[str, Any]]:
    rows = session.execute(
        text(
            "SELECT cle_item, statut, date_relance, note, maj_le "
            "FROM suivi_demande_renseignements WHERE mission_id = :m"
        ),
        {"m": mission_id},
    ).mappings().all()
    return {str(r["cle_item"]): dict(r) for r in rows}


def _fusionner(
    items: list[dict[str, str]], suivis: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Items courants + statuts saisis — défaut ``en_attente`` sans saisie."""
    fusion: list[dict[str, Any]] = []
    for item in items:
        cle = item["cle_item"]
        s = suivis.get(cle)
        fusion.append(
            {
                "cle_item": cle,
                "libelle": item["libelle"],
                "statut": str(s["statut"]) if s else STATUT_DEFAUT,
                "date_relance": (
                    s["date_relance"].isoformat()
                    if s and s.get("date_relance")
                    else None
                ),
                "note": (s.get("note") if s else None) or None,
                "maj_le": (
                    s["maj_le"].isoformat() if s and s.get("maj_le") else None
                ),
            }
        )
    return fusion


def lister_items(
    session: Session, tenant_id: int, mission_id: int
) -> list[dict[str, Any]]:
    """Liste courante des items demandables fusionnée avec leurs statuts.

    [{cle_item, libelle, statut, date_relance, note, maj_le}] — mêmes
    sources et même ordre que le .docx. RLS via ``contexte_tenant`` :
    mission d'un autre tenant → :class:`ErreurSuiviIntrouvable`.
    """
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
        items = collecter_items(session, mission_id)
        suivis = _statuts_enregistres(session, mission_id)
    return _fusionner(items, suivis)


def maj_item(
    session: Session,
    tenant_id: int,
    mission_id: int,
    cle_item: str,
    statut: str,
    date_relance: date | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """UPSERT du statut d'un item — retourne l'item fusionné à jour.

    Le statut est validé contre :data:`STATUTS_SUIVI` ; la clé doit
    appartenir à la liste courante des items demandables (sinon 404).
    """
    statut = str(statut or "").strip()
    if statut not in STATUTS_SUIVI:
        raise ErreurSuiviRenseignements(
            f"statut invalide « {statut} » — attendus : "
            + ", ".join(STATUTS_SUIVI)
        )
    cle_item = str(cle_item or "").strip()
    with contexte_tenant(session, tenant_id):
        if not _mission_existe(session, mission_id):
            raise ErreurSuiviIntrouvable(f"mission {mission_id} introuvable")
        items = collecter_items(session, mission_id)
        par_cle = {i["cle_item"]: i for i in items}
        if cle_item not in par_cle:
            raise ErreurSuiviIntrouvable(
                f"item « {cle_item} » inconnu pour la mission {mission_id}"
            )
        row = session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "date_relance, note) "
                "VALUES (:t, :m, :c, :l, :s, :d, :n) "
                "ON CONFLICT (tenant_id, mission_id, cle_item) DO UPDATE SET "
                "statut = EXCLUDED.statut, "
                "date_relance = EXCLUDED.date_relance, "
                "note = EXCLUDED.note, "
                "libelle = EXCLUDED.libelle, "
                "maj_le = now() "
                "RETURNING cle_item, statut, date_relance, note, maj_le"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": cle_item,
                "l": par_cle[cle_item]["libelle"],
                "s": statut,
                "d": date_relance,
                "n": (note or "").strip() or None,
            },
        ).mappings().one()
    # Pas de commit ici : la transaction (et son SET LOCAL tenant) reste
    # ouverte — get_session committe en fin de requête.
    return _fusionner(
        [par_cle[cle_item]], {cle_item: dict(row)}
    )[0]


def synthese_depuis_items(items: list[dict[str, Any]]) -> dict[str, int]:
    """Compteurs {total, en_attente, recu, sans_objet, a_relancer}."""
    aujourd_hui = date.today().isoformat()
    compte = {"total": len(items), "en_attente": 0, "recu": 0, "sans_objet": 0}
    a_relancer = 0
    for it in items:
        statut = str(it.get("statut") or STATUT_DEFAUT)
        if statut in compte:
            compte[statut] += 1
        relance = it.get("date_relance")
        if statut == STATUT_DEFAUT and relance and str(relance) <= aujourd_hui:
            a_relancer += 1
    compte["a_relancer"] = a_relancer
    return compte


def synthese(
    session: Session, tenant_id: int, mission_id: int
) -> dict[str, int]:
    """Synthèse du suivi — recalculée depuis la liste fusionnée."""
    return synthese_depuis_items(lister_items(session, tenant_id, mission_id))
