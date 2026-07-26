"""Fiabilisation de balance — avec base."""
from decimal import Decimal

import pytest
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.socle.modeles import LigneBalance
from backend.socle.service import fiabiliser_balance

pytestmark = pytest.mark.db


@pytest.fixture
def mission_prete(session):
    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab Fiab', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    with contexte_tenant(session, tid):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Fiab') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()
        mid = session.execute(
            text(
                "INSERT INTO mission (tenant_id, contribuable_id, exercice, profil) "
                "VALUES (:t, :c, 2025, '{}') RETURNING id"
            ),
            {"t": tid, "c": cid},
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.flush()
    return tid, mid


def test_fiabiliser_ok(session, mission_prete):
    tid, mid = mission_prete
    lignes = [
        LigneBalance(compte="701", libelle="CA", debit=Decimal("0"), credit=Decimal("500")),
        LigneBalance(compte="411", libelle="Clients", debit=Decimal("500"), credit=Decimal("0")),
    ]
    rapport = fiabiliser_balance(session, tid, mid, lignes)
    assert rapport.statut == "ok"
    assert rapport.nb_comptes == 2
    assert rapport.rapport_id is not None

    with contexte_tenant(session, tid):
        n = session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mid},
        ).scalar_one()
        statut = session.execute(
            text("SELECT statut FROM rapport_fiabilisation WHERE id = :id"),
            {"id": rapport.rapport_id},
        ).scalar_one()
    assert n == 2
    assert statut == "ok"


def test_fiabiliser_refuse_desequilibre(session, mission_prete):
    tid, mid = mission_prete
    lignes = [
        LigneBalance(compte="701", debit=Decimal("0"), credit=Decimal("100")),
        LigneBalance(compte="411", debit=Decimal("10"), credit=Decimal("0")),
    ]
    rapport = fiabiliser_balance(session, tid, mid, lignes)
    assert rapport.statut == "refuse"
    assert rapport.anomalies
    assert rapport.nb_comptes == 0

    with contexte_tenant(session, tid):
        n = session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mid},
        ).scalar_one()
    assert n == 0
