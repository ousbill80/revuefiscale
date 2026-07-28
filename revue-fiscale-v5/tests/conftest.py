import os

import pytest

# Les tests ne doivent JAMAIS envoyer de vrais emails : une clé Resend
# présente dans .env transformerait chaque test d'invitation en envoi
# réel vers des adresses fictives (bounces, réputation du domaine).
os.environ["RESEND_API_KEY"] = ""


@pytest.fixture(autouse=True)
def _resend_neutralise():
    try:
        from backend import config as _cfg
    except ImportError:  # pragma: no cover
        yield
        return
    ancienne = _cfg.config.resend_api_key
    _cfg.config.resend_api_key = ""
    yield
    _cfg.config.resend_api_key = ancienne


URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://app_revue:changeme@localhost:5433/revue_fiscale",
)


@pytest.fixture(scope="session")
def moteur():
    """Moteur de base. Saute proprement si la base ou le pilote sont absents."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError:  # pragma: no cover
        pytest.skip("sqlalchemy absent — lancez make install")

    try:
        m = create_engine(URL, future=True)
        with m.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"base indisponible ({type(e).__name__}) — lancez make db-up")
    return m


@pytest.fixture
def session(moteur):
    from sqlalchemy.orm import Session

    with Session(moteur) as s:
        yield s
        s.rollback()
