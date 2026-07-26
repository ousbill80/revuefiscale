"""Services billing — tenants, paliers, suspension (sans donnees mission)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.billing.config_editeur import missions_effectives
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.paliers import PALIERS_VALIDES
from backend.plateforme.provisionnement import (
    ErreurProvisionnement,
    ResultatProvisionnement,
    provisionner_cabinet,
)


class ErreurBilling(Exception):
    """Echec metier billing."""


@dataclass(frozen=True)
class PatchTenant:
    statut: str | None = None
    palier: str | None = None
    note: str | None = None


def _premier_jour_mois(aujourd_hui: date | None = None) -> date:
    j = aujourd_hui or date.today()
    return j.replace(day=1)


def lister_tenants(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(text("SELECT * FROM billing_lister_tenants()")).mappings().all()
    return [dict(r) for r in rows]


def quotas_tenant(session: Session, tenant_id: int) -> list[dict[str, Any]]:
    rows = session.execute(
        text("SELECT * FROM billing_quotas_tenant(:t)"),
        {"t": tenant_id},
    ).mappings().all()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        inclus = int(d.get("missions_incluses") or 0)
        utilisees = int(d.get("missions_utilisees") or 0)
        ratio = (utilisees / inclus) if inclus > 0 else 0.0
        d["ratio"] = round(ratio, 4)
        d["alerte_80"] = ratio >= 0.8
        d["bloque"] = utilisees >= inclus if inclus > 0 else False
        out.append(d)
    return out


def resume_usage_tenants(session: Session) -> list[dict[str, Any]]:
    """Dashboard usage : quotas + metrage IA agrege (sans balances/conclusions)."""
    tenants = lister_tenants(session)
    out: list[dict[str, Any]] = []
    for t in tenants:
        tid = int(t["tenant_id"])
        inclus = t.get("missions_incluses")
        utilisees = t.get("missions_utilisees")
        ratio = 0.0
        alerte_80 = False
        if inclus is not None and int(inclus) > 0:
            ratio = int(utilisees or 0) / int(inclus)
            alerte_80 = ratio >= 0.8
        metrage = session.execute(
            text("SELECT * FROM billing_metrage_tenant(:t)"),
            {"t": tid},
        ).mappings().all()
        out.append(
            {
                "tenant_id": tid,
                "denomination": t["denomination"],
                "palier": t["palier"],
                "statut": t["statut"],
                "missions_incluses": inclus,
                "missions_utilisees": utilisees,
                "ratio": round(ratio, 4),
                "alerte_80": alerte_80,
                "metrage_ia": [dict(m) for m in metrage],
            }
        )
    return out


def creer_tenant(
    session: Session,
    *,
    denomination: str,
    type_tenant: str,
    palier: str,
    email_admin: str,
    mot_de_passe_admin: str,
    creer_demo: bool = False,
    note: str | None = None,
) -> ResultatProvisionnement:
    try:
        r = provisionner_cabinet(
            session,
            denomination=denomination,
            type_tenant=type_tenant,
            palier=palier,
            email_admin=email_admin,
            mot_de_passe_admin=mot_de_passe_admin,
            creer_demo=creer_demo,
        )
    except ErreurProvisionnement as e:
        raise ErreurBilling(str(e)) from e

    if note:
        session.execute(
            text(
                "UPDATE abonnement SET note = :n "
                "WHERE id = ("
                "  SELECT id FROM abonnement WHERE tenant_id = :t "
                "  ORDER BY cree_le DESC, id DESC LIMIT 1"
                ")"
            ),
            {"n": note, "t": r.tenant_id},
        )
    return r


def patcher_tenant(session: Session, tenant_id: int, patch: PatchTenant) -> dict[str, Any]:
    row = session.execute(
        text("SELECT id, denomination, type, palier, statut FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurBilling(f"tenant introuvable : {tenant_id}")

    nouveau_statut = patch.statut if patch.statut is not None else str(row["statut"])
    nouveau_palier = patch.palier if patch.palier is not None else str(row["palier"])

    if nouveau_statut not in {"actif", "suspendu", "resilie"}:
        raise ErreurBilling(f"statut invalide : {nouveau_statut}")
    if nouveau_palier not in PALIERS_VALIDES:
        raise ErreurBilling(f"palier invalide : {nouveau_palier}")

    change_statut = nouveau_statut != str(row["statut"])
    change_palier = nouveau_palier != str(row["palier"])
    if not change_statut and not change_palier and not patch.note:
        return dict(row)

    session.execute(
        text("UPDATE tenant SET statut = :s, palier = :p WHERE id = :t"),
        {"s": nouveau_statut, "p": nouveau_palier, "t": tenant_id},
    )

    if change_palier or change_statut:
        # Cloture l enregistrement contractuel precedent (si ouvert).
        session.execute(
            text(
                "UPDATE abonnement SET periode_fin = CURRENT_DATE "
                "WHERE tenant_id = :t AND periode_fin IS NULL"
            ),
            {"t": tenant_id},
        )
        session.execute(
            text(
                "INSERT INTO abonnement "
                "(tenant_id, palier, periode_debut, statut, note) "
                "VALUES (:t, :p, :d, :s, :n)"
            ),
            {
                "t": tenant_id,
                "p": nouveau_palier,
                "d": _premier_jour_mois(),
                "s": nouveau_statut if nouveau_statut != "resilie" else "resilie",
                "n": patch.note
                or (
                    "changement palier"
                    if change_palier
                    else f"statut → {nouveau_statut}"
                ),
            },
        )

    if change_palier:
        n = missions_effectives(session, nouveau_palier)
        debut = _premier_jour_mois()
        with contexte_tenant(session, tenant_id):
            existe = session.execute(
                text("SELECT 1 FROM quota WHERE tenant_id = :t AND periode = :p"),
                {"t": tenant_id, "p": debut},
            ).scalar_one_or_none()
            if existe:
                session.execute(
                    text(
                        "UPDATE quota SET missions_incluses = :n "
                        "WHERE tenant_id = :t AND periode = :p"
                    ),
                    {"n": n, "t": tenant_id, "p": debut},
                )
            else:
                session.execute(
                    text(
                        "INSERT INTO quota (tenant_id, periode, missions_incluses) "
                        "VALUES (:t, :p, :n)"
                    ),
                    {"t": tenant_id, "p": debut, "n": n},
                )
        effacer_contexte_tenant(session)

    maj = session.execute(
        text("SELECT id, denomination, type, palier, statut FROM tenant WHERE id = :t"),
        {"t": tenant_id},
    ).mappings().one()
    return dict(maj)
