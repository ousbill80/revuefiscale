"""Fiabilisation de balance — tests unitaires et integration DB."""
from decimal import Decimal

import pytest

from backend.socle.agregats import calculer_agregats, soldes_depuis_lignes
from backend.socle.controles import controler_balance
from backend.socle.lecteurs.balance import parser_balance
from backend.socle.mapping import appliquer_mapping
from backend.socle.modeles import LigneBalance
from backend.socle.service import fiabiliser_balance

text = pytest.importorskip("sqlalchemy").text
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402


def test_equilibre_ok():
    lignes = [
        LigneBalance(compte="701", libelle="CA", debit=Decimal("0"), credit=Decimal("100")),
        LigneBalance(compte="411", libelle="Clients", debit=Decimal("100"), credit=Decimal("0")),
    ]
    assert controler_balance(lignes) == []


def test_desequilibre():
    lignes = [
        LigneBalance(compte="701", debit=Decimal("0"), credit=Decimal("100")),
        LigneBalance(compte="411", debit=Decimal("50"), credit=Decimal("0")),
    ]
    anomalies = controler_balance(lignes)
    assert any("desequilibree" in a for a in anomalies)


def test_compte_vide():
    lignes = [
        LigneBalance(compte="  ", debit=Decimal("10"), credit=Decimal("10")),
    ]
    anomalies = controler_balance(lignes)
    assert any("vide" in a for a in anomalies)


def test_compte_double():
    lignes = [
        LigneBalance(compte="701", debit=Decimal("0"), credit=Decimal("50")),
        LigneBalance(compte="701", debit=Decimal("50"), credit=Decimal("0")),
    ]
    anomalies = controler_balance(lignes)
    assert any("double" in a for a in anomalies)


def test_parser_csv():
    csv = "compte,libelle,debit,credit\n701,Ventes,0,1000\n411,Clients,1000,0\n"
    lignes = parser_balance(csv)
    assert len(lignes) == 2
    assert lignes[0].compte == "701"
    assert lignes[0].credit == Decimal("1000")


def test_parser_tsv():
    tsv = "601\tAchats\t200\t0\n401\tFournisseurs\t0\t200\n"
    lignes = parser_balance(tsv)
    assert lignes[0].debit == Decimal("200")


def test_mapping_remap():
    lignes = [
        LigneBalance(compte="VTE", debit=Decimal("0"), credit=Decimal("100")),
        LigneBalance(compte="CLI", debit=Decimal("100"), credit=Decimal("0")),
    ]
    mappees = appliquer_mapping(lignes, {"VTE": "701", "CLI": "411"})
    assert [ligne.compte for ligne in mappees] == ["701", "411"]


def test_agregat_ca():
    soldes = soldes_depuis_lignes(
        [
            ("701", Decimal("0"), Decimal("1000000")),
            ("707", Decimal("0"), Decimal("500000")),
            ("601", Decimal("200000"), Decimal("0")),
        ]
    )
    agregats = calculer_agregats(soldes)
    assert agregats["CA"] == Decimal("1500000")


# ── Integration DB ────────────────────────────────────────────────────

pytestmark_db = pytest.mark.db


@pytest.fixture
def mission_demo(session):
    """Tenant + contribuable + mission (sans epinglage obligatoire pour le socle)."""
    tenant_id = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab Socle', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    with contexte_tenant(session, tenant_id):
        contrib = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Socle') RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        mission_id = session.execute(
            text(
                "INSERT INTO mission (tenant_id, contribuable_id, exercice, profil) "
                "VALUES (:t, :c, 2025, '{}') RETURNING id"
            ),
            {"t": tenant_id, "c": contrib},
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.flush()
    return tenant_id, int(mission_id)


@pytest.mark.db
def test_fiabiliser_balance_ok_persiste(session, mission_demo):
    tenant_id, mission_id = mission_demo
    lignes = [
        LigneBalance(compte="701", libelle="CA", debit=Decimal("0"), credit=Decimal("1000")),
        LigneBalance(compte="411", libelle="Clients", debit=Decimal("1000"), credit=Decimal("0")),
    ]
    rapport = fiabiliser_balance(session, tenant_id, mission_id, lignes)
    assert rapport.statut == "ok"
    assert rapport.nb_comptes == 2
    assert rapport.anomalies == []

    with contexte_tenant(session, tenant_id):
        n = session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mission_id},
        ).scalar_one()
        statut_rap = session.execute(
            text(
                "SELECT statut FROM rapport_fiabilisation "
                "WHERE id = :id"
            ),
            {"id": rapport.rapport_id},
        ).scalar_one()
    assert n == 2
    assert statut_rap == "ok"


@pytest.mark.db
def test_fiabiliser_refuse_conserve_soldes(session, mission_demo):
    tenant_id, mission_id = mission_demo
    ok = [
        LigneBalance(compte="701", debit=Decimal("0"), credit=Decimal("500")),
        LigneBalance(compte="411", debit=Decimal("500"), credit=Decimal("0")),
    ]
    fiabiliser_balance(session, tenant_id, mission_id, ok)

    mauvaise = [
        LigneBalance(compte="701", debit=Decimal("0"), credit=Decimal("500")),
        LigneBalance(compte="411", debit=Decimal("100"), credit=Decimal("0")),
    ]
    rapport = fiabiliser_balance(session, tenant_id, mission_id, mauvaise)
    assert rapport.statut == "refuse"
    assert rapport.nb_comptes == 0
    assert any("desequilibree" in a for a in rapport.anomalies)

    with contexte_tenant(session, tenant_id):
        n = session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mission_id},
        ).scalar_one()
    assert n == 2, "un import refuse ne doit pas effacer les soldes precedents"
