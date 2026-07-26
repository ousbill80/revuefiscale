"""Traitement staff des demandes abonné (paiement / palier)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.billing.factures import ErreurFacture, marquer_payee
from backend.billing.service import ErreurBilling, PatchTenant, patcher_tenant


class ErreurDemande(Exception):
    """Echec metier file demandes."""


def lister_demandes_paiement(
    session: Session, statut: str | None = None
) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT * FROM billing_lister_demandes_paiement(:s)"),
        {"s": statut},
    ).mappings().all()
    return [dict(r) for r in rows]


def lister_demandes_palier(
    session: Session, statut: str | None = None
) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT * FROM billing_lister_demandes_palier(:s)"),
        {"s": statut},
    ).mappings().all()
    return [dict(r) for r in rows]


def _demande_paiement_ouverte(session: Session, demande_id: int) -> dict[str, Any]:
    for d in lister_demandes_paiement(session, "ouvert"):
        if int(d["id"]) == demande_id:
            return d
    toutes = {int(d["id"]): d for d in lister_demandes_paiement(session)}
    if demande_id not in toutes:
        raise ErreurDemande(f"demande_paiement {demande_id} introuvable")
    raise ErreurDemande(
        f"demande non traitable (statut={toutes[demande_id]['statut']})"
    )


def _demande_palier_ouverte(session: Session, demande_id: int) -> dict[str, Any]:
    for d in lister_demandes_palier(session, "ouvert"):
        if int(d["id"]) == demande_id:
            return d
    raise ErreurDemande(f"demande_palier {demande_id} introuvable ou non ouverte")


def _clore_demande_paiement(
    session: Session,
    demande_id: int,
    *,
    statut: str,
    note_staff: str | None,
) -> None:
    ok = session.execute(
        text(
            "SELECT billing_clore_demande_paiement(:id, :s, :n)"
        ),
        {
            "id": demande_id,
            "s": statut,
            "n": (note_staff or "").strip() or None,
        },
    ).scalar_one()
    if not ok:
        raise ErreurDemande(
            "demande déjà traitée ou refusée (course concurrente)"
        )


def _clore_demande_palier(
    session: Session,
    demande_id: int,
    *,
    statut: str,
    note_staff: str | None,
) -> None:
    ok = session.execute(
        text("SELECT billing_clore_demande_palier(:id, :s, :n)"),
        {
            "id": demande_id,
            "s": statut,
            "n": (note_staff or "").strip() or None,
        },
    ).scalar_one()
    if not ok:
        raise ErreurDemande(
            "demande déjà traitée ou refusée (course concurrente)"
        )


def accepter_demande_paiement(
    session: Session,
    demande_id: int,
    *,
    note_staff: str | None = None,
    marquer_facture_payee: bool = True,
) -> dict[str, Any]:
    """Rapprochement : verrouille la demande puis marque éventuellement payée (staff)."""
    demande = _demande_paiement_ouverte(session, demande_id)
    facture_id = int(demande["facture_id"])

    # Verrou d'abord — évite payée + refuse en concurrence (SECURITY DEFINER)
    _clore_demande_paiement(
        session, demande_id, statut="traite", note_staff=note_staff
    )

    if marquer_facture_payee:
        try:
            marquer_payee(session, facture_id)
        except ErreurFacture as e:
            raise ErreurDemande(str(e)) from e

    maj = next(
        (d for d in lister_demandes_paiement(session) if int(d["id"]) == demande_id),
        None,
    )
    return maj or {"id": demande_id, "statut": "traite"}


def refuser_demande_paiement(
    session: Session,
    demande_id: int,
    *,
    note_staff: str | None = None,
) -> dict[str, Any]:
    _demande_paiement_ouverte(session, demande_id)
    _clore_demande_paiement(
        session, demande_id, statut="refuse", note_staff=note_staff
    )

    maj = next(
        (d for d in lister_demandes_paiement(session) if int(d["id"]) == demande_id),
        None,
    )
    return maj or {"id": demande_id, "statut": "refuse"}


def accepter_demande_palier(
    session: Session,
    demande_id: int,
    *,
    note_staff: str | None = None,
) -> dict[str, Any]:
    """Verrouille la demande puis patcher_tenant — seul le staff mute le palier."""
    demande = _demande_palier_ouverte(session, demande_id)
    tenant_id = int(demande["tenant_id"])
    palier_cible = str(demande["palier_cible"])

    _clore_demande_palier(
        session, demande_id, statut="traite", note_staff=note_staff
    )

    try:
        patcher_tenant(
            session,
            tenant_id,
            PatchTenant(
                palier=palier_cible,
                note=note_staff or f"Acceptation demande_palier #{demande_id}",
            ),
        )
    except ErreurBilling as e:
        raise ErreurDemande(str(e)) from e

    maj = next(
        (d for d in lister_demandes_palier(session) if int(d["id"]) == demande_id),
        None,
    )
    return maj or {"id": demande_id, "statut": "traite"}


def refuser_demande_palier(
    session: Session,
    demande_id: int,
    *,
    note_staff: str | None = None,
) -> dict[str, Any]:
    _demande_palier_ouverte(session, demande_id)
    _clore_demande_palier(
        session, demande_id, statut="refuse", note_staff=note_staff
    )

    maj = next(
        (d for d in lister_demandes_palier(session) if int(d["id"]) == demande_id),
        None,
    )
    return maj or {"id": demande_id, "statut": "refuse"}
