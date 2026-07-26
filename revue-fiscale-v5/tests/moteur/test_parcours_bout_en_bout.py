"""Parcours bout-en-bout : mission epinglee → balance → moteur → restitution.

Utilise BIC-CHG-18G-DONS (valeurs a_confirmer dans le YAML).
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.editorial.publication import (
    charger_regle_yaml,
    creer_version_brouillon,
    publier_version,
)
from backend.moteur.service import executer_mission
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.missions import creer_mission
from backend.restitution.service import produire_restitution
from backend.socle.modeles import LigneBalance
from backend.socle.service import fiabiliser_balance

pytestmark = pytest.mark.db

YAML_DONS = (
    Path(__file__).resolve().parents[2] / "referentiel" / "BIC-CHG-18G-DONS.yaml"
)


@pytest.fixture
def version_dons(session):
    libelle = f"v2026-e2e-dons-{uuid.uuid4().hex[:8]}"
    vid = creer_version_brouillon(session, libelle, note="e2e dons uniquement")
    charger_regle_yaml(session, vid, YAML_DONS)
    publier_version(session, libelle, par="test-e2e")
    session.flush()
    return vid


@pytest.fixture
def mission_dons(session, version_dons):
    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab E2E', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    with contexte_tenant(session, tid):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client E2E SA') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()
        # Quota du mois courant : requis depuis l'enforcement a la creation
        session.execute(
            text(
                "INSERT INTO quota (tenant_id, periode, missions_incluses) "
                "VALUES (:t, date_trunc('month', current_date)::date, 100)"
            ),
            {"t": tid},
        )
    effacer_contexte_tenant(session)

    mid = creer_mission(
        session,
        tid,
        contribuable_id=int(cid),
        exercice=2026,
        profil={"regime": "reel", "forme_juridique": "SA"},
    )
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET version_referentiel_id = :v WHERE id = :m"),
            {"v": version_dons, "m": mid},
        )
    effacer_contexte_tenant(session)
    session.flush()

    # 6582 = 5_000_000 ; CA via 701 = 100_000_000
    # resultat = 5M - min(0.025*100M, 200M) = 5M - 2.5M = 2.5M
    lignes = [
        LigneBalance(
            compte="6582", libelle="Dons", debit=Decimal("5000000"), credit=Decimal("0")
        ),
        LigneBalance(
            compte="701",
            libelle="Ventes",
            debit=Decimal("0"),
            credit=Decimal("100000000"),
        ),
        LigneBalance(
            compte="512",
            libelle="Banque",
            debit=Decimal("95000000"),
            credit=Decimal("0"),
        ),
    ]
    rapport = fiabiliser_balance(session, tid, mid, lignes)
    assert rapport.statut == "ok", rapport.anomalies
    return tid, mid, version_dons


def test_parcours_bout_en_bout_dons(session, mission_dons):
    tid, mid, version_id = mission_dons
    conclusions = executer_mission(session, tid, mid, acteur="testeur-e2e", reponses={})
    declenchees = {c.regle_id: c for c in conclusions if c.declenchee}
    assert "BIC-CHG-18G-DONS" in declenchees
    assert declenchees["BIC-CHG-18G-DONS"].montant == Decimal("2500000")
    assert declenchees["BIC-CHG-18G-DONS"].sens == "reintegration"

    rest = produire_restitution(session, tid, mid)
    assert rest.passage.total_reintegration == Decimal("2500000")
    assert rest.score_risque.score > 0
    assert "Score heuristique" in rest.score_risque.avertissement
    assert rest.rapport_markdown.startswith("# Rapport")


def test_parcours_rejouable_identique(session, mission_dons):
    tid, mid, _ = mission_dons
    r1 = {
        c.regle_id: c.montant
        for c in executer_mission(session, tid, mid, "t1", reponses={})
        if c.declenchee
    }
    r2 = {
        c.regle_id: c.montant
        for c in executer_mission(session, tid, mid, "t2", reponses={})
        if c.declenchee
    }
    assert r1 == r2
