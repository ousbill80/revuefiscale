"""Connexion base. Le moteur applicatif utilise TOUJOURS le role app_revue."""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import config

moteur = create_engine(config.database_url, pool_pre_ping=True, future=True)
Fabrique = sessionmaker(bind=moteur, expire_on_commit=False, future=True)


def session_scope() -> Iterator[Session]:
    """Dependance FastAPI. Ouvre une transaction, la ferme proprement."""
    session = Fabrique()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
