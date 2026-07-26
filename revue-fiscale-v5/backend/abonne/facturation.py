"""Facturation abonné — lecture factures + signalement paiement (rapprochement).

L'abonné ne marque JAMAIS une facture payée (marquer_payee = staff only).
Les montants sont commerciaux (abonnement), jamais fiscaux CGI.

Prérequis routes : `session_abonne` pose SET LOCAL (`contexte_tenant`) —
RLS FORCE sur `facture` / `demande_*` filtre par la base. Le filtre
`tenant_id` reste une défense en profondeur applicative.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.abonne.service import ErreurAbonne
from backend.billing.config_editeur import lire_mentions_facture
from backend.billing.factures import ErreurFacture, lire_facture, rendre_facture_pdf


def lister_factures_tenant(session: Session, tenant_id: int) -> list[dict[str, Any]]:
    """Factures du cabinet — RLS FORCE + filtre tenant_id (défense en profondeur).

    Appeler sous `contexte_tenant` (routes via `session_abonne`).
    """
    rows = session.execute(
        text(
            "SELECT f.id, f.tenant_id, f.numero, f.periode, f.montant, f.devise, "
            "f.statut, f.palier, f.note, f.emise_at, f.cree_le, "
            "t.denomination, "
            "(SELECT d.statut FROM demande_paiement d "
            " WHERE d.facture_id = f.id AND d.tenant_id = f.tenant_id "
            "   AND d.statut = 'ouvert' "
            " ORDER BY d.id DESC LIMIT 1) AS demande_paiement_ouverte "
            "FROM facture f "
            "JOIN tenant t ON t.id = f.tenant_id "
            "WHERE f.tenant_id = :t "
            "ORDER BY f.id DESC"
        ),
        {"t": tenant_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def lire_facture_tenant(
    session: Session, tenant_id: int, facture_id: int
) -> dict[str, Any]:
    """Détail facture : billing_lire_facture puis garde tenant (IDOR)."""
    try:
        facture = lire_facture(session, facture_id)
    except ErreurFacture as e:
        raise ErreurAbonne(str(e)) from e
    if int(facture["tenant_id"]) != tenant_id:
        raise ErreurAbonne(f"facture {facture_id} introuvable")
    return facture


def pdf_facture_tenant(
    session: Session, tenant_id: int, facture_id: int
) -> tuple[bytes, str]:
    facture = lire_facture_tenant(session, tenant_id, facture_id)
    mentions = lire_mentions_facture(session)["effectif"]
    pdf = rendre_facture_pdf(facture, mentions=mentions)
    numero = str(facture.get("numero") or facture_id).replace("/", "-")
    return pdf, numero


def instructions_virement(session: Session) -> dict[str, Any]:
    """Coordonnées virement depuis config éditeur / env — À CONFIRMER OK."""
    mentions = lire_mentions_facture(session)
    effectif = mentions["effectif"]
    return {
        "raison_sociale": effectif.get("raison_sociale") or "À CONFIRMER",
        "compte_bancaire": effectif.get("compte_bancaire") or "À CONFIRMER",
        "siege": effectif.get("siege") or "À CONFIRMER",
        "a_confirmer": bool(mentions.get("a_confirmer", True)),
        "note": (
            "Effectuez un virement puis signalez le paiement depuis la facture. "
            "Le statut « payée » n'est posé qu'après rapprochement par le staff 2AàZ."
        ),
    }


def signaler_paiement(
    session: Session,
    *,
    tenant_id: int,
    facture_id: int,
    cree_par: int,
    note: str | None = None,
) -> dict[str, Any]:
    """Ouvre une demande de rapprochement — ne change PAS le statut facture."""
    facture = lire_facture_tenant(session, tenant_id, facture_id)
    if facture["statut"] not in {"emise", "brouillon"}:
        raise ErreurAbonne(
            f"facture non signalable (statut={facture['statut']})"
        )

    ouverte = session.execute(
        text(
            "SELECT id FROM demande_paiement "
            "WHERE tenant_id = :t AND facture_id = :f AND statut = 'ouvert' "
            "LIMIT 1"
        ),
        {"t": tenant_id, "f": facture_id},
    ).scalar_one_or_none()
    if ouverte is not None:
        raise ErreurAbonne(
            f"demande de rapprochement déjà ouverte (id={int(ouverte)})"
        )

    try:
        rid = session.execute(
            text(
                "INSERT INTO demande_paiement "
                "(tenant_id, facture_id, statut, note, cree_par) "
                "VALUES (:t, :f, 'ouvert', :n, :u) RETURNING id"
            ),
            {
                "t": tenant_id,
                "f": facture_id,
                "n": (note or "").strip() or None,
                "u": cree_par,
            },
        ).scalar_one()
    except IntegrityError as e:
        raise ErreurAbonne(
            "demande de rapprochement déjà ouverte (concurrence)"
        ) from e

    # Garde-fou : le statut facture ne doit pas avoir bougé.
    statut_apres = session.execute(
        text("SELECT statut FROM facture WHERE id = :id AND tenant_id = :t"),
        {"id": facture_id, "t": tenant_id},
    ).scalar_one()
    if statut_apres != facture["statut"]:
        raise ErreurAbonne("refus : signalement ne doit pas modifier la facture")

    return {
        "id": int(rid),
        "facture_id": facture_id,
        "facture_statut": str(statut_apres),
        "statut": "ouvert",
        "note": (note or "").strip() or None,
        "message": (
            "Demande de rapprochement enregistrée. "
            "La facture n'est pas marquée payée."
        ),
    }
