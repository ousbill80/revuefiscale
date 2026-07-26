"""Metrique d usage IA — domaine abonne (tenant_id NOT NULL + RLS)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant


def enregistre_appel(
    session: Session,
    tenant_id: int,
    modele: str,
    tokens_in: int,
    tokens_out: int,
    usage: str,
    cout_estime: Decimal | float | int = 0,
) -> int:
    """Enregistre un appel IA sous contexte tenant (set_config LOCAL)."""
    with contexte_tenant(session, tenant_id):
        mid = session.execute(
            text(
                "INSERT INTO metrage_ia "
                "(tenant_id, modele, tokens_entree, tokens_sortie, cout_estime, usage) "
                "VALUES (:t, :m, :ti, :to, :c, :u) RETURNING id"
            ),
            {
                "t": tenant_id,
                "m": modele,
                "ti": int(tokens_in),
                "to": int(tokens_out),
                "c": Decimal(str(cout_estime)),
                "u": usage,
            },
        ).scalar_one()
        session.flush()
        return int(mid)
