"""Etancheite inter-cabinets — BLOQUANT en integration continue.

Ces tests protegent contre l incident qui tue un produit SaaS :
le cabinet A qui voit les dossiers du cabinet B.
"""
import pytest

pytestmark = pytest.mark.db

text = pytest.importorskip("sqlalchemy").text
DBAPIError = pytest.importorskip("sqlalchemy.exc").DBAPIError

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402


@pytest.fixture
def deux_cabinets(session):
    a = session.execute(
        text("INSERT INTO tenant (denomination, type, palier) "
             "VALUES ('Cabinet A', 'cabinet', 'standard') RETURNING id")
    ).scalar_one()
    b = session.execute(
        text("INSERT INTO tenant (denomination, type, palier) "
             "VALUES ('Cabinet B', 'cabinet', 'standard') RETURNING id")
    ).scalar_one()
    for t, nom in ((a, "Client A1"), (b, "Client B1")):
        # RLS FORCE + WITH CHECK : sans contexte, l'INSERT est refuse.
        with contexte_tenant(session, t):
            session.execute(
                text("INSERT INTO contribuable (tenant_id, denomination) VALUES (:t, :n)"),
                {"t": t, "n": nom},
            )
    # SET LOCAL survit jusqu'a la fin de transaction : sans reset,
    # test_sans_contexte_zero_ligne verrait encore le dernier tenant.
    effacer_contexte_tenant(session)
    session.flush()
    return a, b


def test_lecture_cloisonnee(session, deux_cabinets):
    a, b = deux_cabinets
    with contexte_tenant(session, a):
        lignes = session.execute(text("SELECT tenant_id FROM contribuable")).scalars().all()
    assert lignes and all(t == a for t in lignes), "fuite : le cabinet A voit d autres tenants"


def test_sans_contexte_zero_ligne(session, deux_cabinets):
    """Refus par defaut. Contexte absent ne doit JAMAIS signifier tout voir."""
    n = session.execute(text("SELECT count(*) FROM contribuable")).scalar_one()
    assert n == 0, "sans contexte de tenant, la lecture doit retourner zero ligne"


def test_ecriture_chez_un_autre_refusee(session, deux_cabinets):
    """WITH CHECK empeche d ecrire une ligne portant le tenant_id d un autre."""
    a, b = deux_cabinets
    with contexte_tenant(session, a), pytest.raises(DBAPIError):
        session.execute(
            text("INSERT INTO contribuable (tenant_id, denomination) VALUES (:t, 'Intrus')"),
            {"t": b},
        )
        session.flush()


def test_role_applicatif_sans_privileges(session):
    """Conditions 2 de l isolation : ni superuser, ni BYPASSRLS."""
    r = session.execute(
        text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).one()
    assert r.rolsuper is False, "le role applicatif ne doit pas etre superuser"
    assert r.rolbypassrls is False, "le role applicatif ne doit pas avoir BYPASSRLS"


def test_rls_activee_et_forcee(session):
    """Condition 1 : FORCE en plus de ENABLE, sinon le proprietaire contourne."""
    tables = [
        "contribuable",
        "mission",
        "solde_compte",
        "journal_audit",
        "utilisateur",
        "quota",
        "piece_mission",
        "point_ouvert",
        "mission_objectif",
        "objectif",
        "tache",
        "risque",
        "action_risque",
        "execution",
        "conclusion",
        "contestation",
        "rapport_fiabilisation",
        "metrage_ia",
        "facture",
        "demande_paiement",
        "demande_palier",
    ]
    lignes = session.execute(
        text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
             "WHERE relname = ANY(:t)"),
        {"t": tables},
    ).all()
    for nom, activee, forcee in lignes:
        assert activee, f"{nom} : RLS non activee"
        assert forcee, f"{nom} : RLS non forcee (FORCE ROW LEVEL SECURITY manquant)"


def test_journal_audit_en_ecriture_seule(session):
    """UPDATE et DELETE revoques : on ne reecrit pas l histoire d une mission."""
    for verbe in ("UPDATE", "DELETE"):
        autorise = session.execute(
            text("SELECT has_table_privilege(current_user, 'journal_audit', :v)"),
            {"v": verbe},
        ).scalar_one()
        assert autorise is False, f"{verbe} ne doit pas etre autorise sur journal_audit"
