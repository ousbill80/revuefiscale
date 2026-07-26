"""Contexte de tenant — le point de passage obligé de toute route abonné.

SET LOCAL, jamais SET.

Avec un pool de connexions, un SET de session survit a la transaction. La
connexion retourne au pool en conservant le tenant precedent, et sert la requete
suivante avec le mauvais contexte. En developpement, avec un seul utilisateur,
ce bug ne se manifeste jamais.

Voir docs/09-multitenant.md, condition n 4.
"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session


class ErreurTenant(Exception):
    """Contexte de tenant absent ou invalide."""


@contextmanager
def contexte_tenant(session: Session, tenant_id: int) -> Iterator[None]:
    """Positionne le contexte pour la duree de la transaction en cours."""
    if tenant_id is None or tenant_id <= 0:
        raise ErreurTenant(f"tenant_id invalide : {tenant_id!r}")

    # SET LOCAL : portee limitee a la transaction. Ne jamais remplacer par SET.
    session.execute(text("SET LOCAL app.tenant_id = :t"), {"t": str(tenant_id)})
    yield
    # le contexte disparait avec la transaction, aucun nettoyage necessaire


def tenant_courant(session: Session) -> int | None:
    """Retourne le tenant positionne, ou None. Utile en test."""
    valeur = session.execute(
        text("SELECT current_setting('app.tenant_id', true)")
    ).scalar()
    return int(valeur) if valeur else None
