"""Services facturation commerciale — montants abonnement, pas fiscaux."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.billing.config_editeur import prix_effectif_xof
from backend.plateforme.contexte import contexte_tenant
from backend.plateforme.paliers import PALIERS_VALIDES


class ErreurFacture(Exception):
    """Echec metier facture."""


@dataclass(frozen=True)
class FactureCreee:
    id: int
    numero: str
    montant: Decimal
    statut: str


def _premier_jour_mois(aujourd_hui: date | None = None) -> date:
    j = aujourd_hui or date.today()
    return j.replace(day=1)


def _lire_facture_definer(session: Session, facture_id: int) -> dict[str, Any]:
    """Résout une facture via SECURITY DEFINER (hors / avec RLS)."""
    row = session.execute(
        text("SELECT * FROM billing_lire_facture(:id)"),
        {"id": facture_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurFacture(f"facture introuvable : {facture_id}")
    return dict(row)


def creer_facture_brouillon(
    session: Session,
    tenant_id: int,
    *,
    periode: date | None = None,
    note: str | None = None,
) -> FactureCreee:
    row = session.execute(
        text("SELECT id, palier, statut FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurFacture(f"tenant introuvable : {tenant_id}")
    palier = str(row["palier"])
    if palier not in PALIERS_VALIDES:
        raise ErreurFacture(f"palier invalide : {palier}")

    p = periode or _premier_jour_mois()
    montant = prix_effectif_xof(session, palier)
    with contexte_tenant(session, tenant_id):
        # nextval avance la sequence — on utilise RETURNING id pour le numero
        fid = session.execute(
            text(
                "INSERT INTO facture "
                "(tenant_id, numero, periode, montant, statut, palier, note) "
                "VALUES (:t, :n, :p, :m, 'brouillon', :pal, :note) RETURNING id"
            ),
            {
                "t": tenant_id,
                "n": f"TMP-{tenant_id}-{p.isoformat()}",
                "p": p,
                "m": montant,
                "pal": palier,
                "note": note or "À CONFIRMER — tarif provisoire (saisie éditeur 2AàZ)",
            },
        ).scalar_one()
        numero = f"FA-{p.year}{p.month:02d}-{tenant_id}-{int(fid)}"
        session.execute(
            text("UPDATE facture SET numero = :n WHERE id = :id"),
            {"n": numero, "id": int(fid)},
        )
    return FactureCreee(id=int(fid), numero=numero, montant=montant, statut="brouillon")


def emettre_facture(session: Session, facture_id: int) -> dict[str, Any]:
    row = _lire_facture_definer(session, facture_id)
    if row["statut"] != "brouillon":
        raise ErreurFacture(f"facture non emettable (statut={row['statut']})")
    tenant_id = int(row["tenant_id"])
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "UPDATE facture SET statut = 'emise', emise_at = now() WHERE id = :id"
            ),
            {"id": facture_id},
        )
    return _lire_facture_definer(session, facture_id)


def marquer_payee(session: Session, facture_id: int) -> dict[str, Any]:
    row = _lire_facture_definer(session, facture_id)
    if row["statut"] not in {"emise", "brouillon"}:
        raise ErreurFacture(f"facture non payable (statut={row['statut']})")
    tenant_id = int(row["tenant_id"])
    with contexte_tenant(session, tenant_id):
        session.execute(
            text("UPDATE facture SET statut = 'payee' WHERE id = :id"),
            {"id": facture_id},
        )
    return _lire_facture_definer(session, facture_id)


def annuler_facture(session: Session, facture_id: int) -> dict[str, Any]:
    row = _lire_facture_definer(session, facture_id)
    if row["statut"] == "payee":
        raise ErreurFacture("facture deja payee — annulation refusee")
    tenant_id = int(row["tenant_id"])
    with contexte_tenant(session, tenant_id):
        session.execute(
            text("UPDATE facture SET statut = 'annulee' WHERE id = :id"),
            {"id": facture_id},
        )
    return _lire_facture_definer(session, facture_id)


def lister_factures(
    session: Session, tenant_id: int | None = None
) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT * FROM billing_lister_factures(:t)"),
        {"t": tenant_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def export_factures_csv(lignes: list[dict[str, Any]]) -> str:
    entetes = [
        "id",
        "tenant_id",
        "denomination",
        "numero",
        "periode",
        "montant",
        "devise",
        "statut",
        "palier",
    ]
    out = [";".join(entetes)]
    for r in lignes:
        out.append(
            ";".join(
                str(r.get(c) if r.get(c) is not None else "") for c in entetes
            )
        )
    return "\n".join(out) + "\n"


def lire_facture(session: Session, facture_id: int) -> dict[str, Any]:
    """Charge une facture + denomination via billing_lire_facture (SECURITY DEFINER)."""
    return _lire_facture_definer(session, facture_id)


def rendre_facture_pdf(
    facture: dict[str, Any],
    *,
    mentions: dict[str, str] | None = None,
) -> bytes:
    """PDF commercial minimal (reportlab) — montants d'abonnement, pas fiscaux.

    Mentions légales / TVA : saisie éditeur / env / placeholders **À CONFIRMER**.
    Aucun RCCM / taux inventé présenté comme vrai.
    """
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    from backend.config import config

    mentions = mentions or config.mentions_legales_facture()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _largeur, hauteur = A4
    y = hauteur - 2 * cm

    def ligne(texte: str, *, gras: bool = False, delta: float = 14) -> None:
        nonlocal y
        if y < 2 * cm:
            c.showPage()
            y = hauteur - 2 * cm
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 12 if gras else 10)
        c.drawString(2 * cm, y, texte[:110])
        y -= delta

    ligne("Revue Fiscale — Facture d'abonnement", gras=True, delta=20)
    ligne(f"Édité par {mentions['raison_sociale']}", delta=16)
    y -= 4
    ligne(f"N° {facture.get('numero') or '—'}", gras=True)
    ligne(f"Abonné : {facture.get('denomination') or '—'}")
    ligne(f"Tenant id : {facture.get('tenant_id')}")
    ligne(f"Période : {facture.get('periode')}")
    ligne(f"Palier : {facture.get('palier')}")
    ligne(f"Statut : {facture.get('statut')}")
    y -= 6
    montant = facture.get("montant")
    devise = facture.get("devise") or "XOF"
    ligne(f"Montant TTC affiché : {montant} {devise}", gras=True, delta=18)
    note = facture.get("note")
    if note:
        ligne(f"Note : {note}", delta=12)
    y -= 10
    ligne("Mentions légales éditeur", gras=True, delta=16)
    ligne(f"Raison sociale : {mentions['raison_sociale']}", delta=12)
    ligne(f"RCCM : {mentions['rccm']}", delta=12)
    ligne(f"IDU : {mentions['idu']}", delta=12)
    ligne(f"Siège social : {mentions['siege']}", delta=12)
    ligne(f"Compte bancaire : {mentions['compte_bancaire']}", delta=12)
    y -= 6
    ligne("TVA sur abonnement SaaS", gras=True, delta=16)
    ligne(f"Régime TVA : {mentions['regime_tva']}", delta=12)
    ligne(f"Taux TVA : {mentions['taux_tva']} — aucun taux inventé ici", delta=12)
    ligne(
        "Montant HT / TVA / TTC : À CONFIRMER (voir montant affiché)",
        delta=12,
    )
    y -= 8
    ligne(
        "Montant commercial d'abonnement — À CONFIRMER. Pas un montant fiscal CGI.",
        delta=12,
    )
    ligne(
        "Tarifs : saisie éditeur 2AàZ ou provisoire technique — À CONFIRMER si non saisis.",
        delta=12,
    )
    c.save()
    return buf.getvalue()
