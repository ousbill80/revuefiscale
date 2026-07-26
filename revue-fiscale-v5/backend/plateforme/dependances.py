"""Dependances FastAPI : session + contexte tenant obligatoires sur routes abonne."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from backend.db import Fabrique
from backend.plateforme.auth import ErreurAuth, SessionUtilisateur, decoder_jeton
from backend.plateforme.contexte import contexte_tenant


def get_session() -> Iterator[Session]:
    session = Fabrique()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def utilisateur_courant(
    authorization: Annotated[str | None, Header()] = None,
) -> SessionUtilisateur:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer requis",
        )
    jeton = authorization.split(" ", 1)[1].strip()
    try:
        return decoder_jeton(jeton)
    except ErreurAuth as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


UtilisateurDep = Annotated[SessionUtilisateur, Depends(utilisateur_courant)]


def session_abonne(
    session: SessionDep,
    utilisateur: UtilisateurDep,
) -> Iterator[Session]:
    """Pose le contexte tenant pour toute la transaction de la requete."""
    with contexte_tenant(session, utilisateur.tenant_id):
        yield session
