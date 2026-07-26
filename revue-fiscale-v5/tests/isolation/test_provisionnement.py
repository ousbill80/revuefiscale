"""Tests provisionnement et auth — etape 1 complete."""
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text_sa = sa.text

from backend.plateforme.auth import (  # noqa: E402
    decoder_jeton,
    emettre_jeton,
    hasher_mot_de_passe,
    verifier_mot_de_passe,
)
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    ErreurProvisionnement,
    provisionner_cabinet,
)


def test_hash_mot_de_passe_rond():
    h = hasher_mot_de_passe("motdepasse-secret")
    assert verifier_mot_de_passe("motdepasse-secret", h)
    assert not verifier_mot_de_passe("autre", h)


def test_jeton_session():
    j = emettre_jeton(utilisateur_id=1, tenant_id=2, role="admin", email="a@b.ci")
    s = decoder_jeton(j)
    assert s.tenant_id == 2 and s.role == "admin"


def test_provisionner_isole(session):
    a = provisionner_cabinet(
        session,
        denomination="Cabinet Alpha",
        type_tenant="cabinet",
        palier="standard",
        email_admin="admin.alpha@example.ci",
        mot_de_passe_admin="secret12345",
        creer_demo=True,
    )
    b = provisionner_cabinet(
        session,
        denomination="Cabinet Beta",
        type_tenant="cabinet",
        palier="essentiel",
        email_admin="admin.beta@example.ci",
        mot_de_passe_admin="secret12345",
        creer_demo=True,
    )
    assert a.tenant_id != b.tenant_id
    assert a.demo_contribuable_id is not None

    with contexte_tenant(session, a.tenant_id):
        noms = session.execute(text_sa("SELECT denomination FROM contribuable")).scalars().all()
    assert len(noms) == 1
    assert "Alpha" in noms[0]

    with contexte_tenant(session, b.tenant_id):
        noms_b = session.execute(text_sa("SELECT denomination FROM contribuable")).scalars().all()
    assert len(noms_b) == 1
    assert "Beta" in noms_b[0]

    effacer_contexte_tenant(session)
    assert session.execute(text_sa("SELECT count(*) FROM contribuable")).scalar_one() == 0


def test_provisionner_email_duplique(session):
    provisionner_cabinet(
        session,
        denomination="Cab",
        type_tenant="cabinet",
        palier="standard",
        email_admin="dup@example.ci",
        mot_de_passe_admin="secret12345",
    )
    with pytest.raises(ErreurProvisionnement, match="email"):
        provisionner_cabinet(
            session,
            denomination="Cab2",
            type_tenant="cabinet",
            palier="standard",
            email_admin="dup@example.ci",
            mot_de_passe_admin="secret12345",
        )


def test_quota_cree(session):
    r = provisionner_cabinet(
        session,
        denomination="Cab Q",
        type_tenant="cabinet",
        palier="premium",
        email_admin="q@example.ci",
        mot_de_passe_admin="secret12345",
    )
    with contexte_tenant(session, r.tenant_id):
        n = session.execute(text("SELECT missions_incluses FROM quota")).scalar_one()
    assert n == 100
