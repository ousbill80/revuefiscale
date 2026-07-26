"""R5 — socle auto-prescrit non armé + prescrit manuel."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.prescription import (
    MOTIF_ATTENTE_VISA,
    TABLE_PARAMETRE_PRESCRIPTION,
    evaluer_prescription,
    evaluer_prescription_tenant,
    lire_parametres_prescription,
    table_parametre_prescription_existe,
)

pytestmark = pytest.mark.db


def _skip_si_absente(session) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'risque'"
        )
    ).scalar_one()
    if n == 0:
        pytest.skip("migration 020 non appliquée — make migrate")


def _contrib(client: TestClient, h: dict, ncc: str) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM {ncc}",
            "ncc": ncc,
            "forme": "pm",
            "rccm": f"RCCM-{ncc}",
            "dfe": f"DFE-{ncc}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    return int(c.json()["id"])


@pytest.fixture
def client_cab(session):
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    _skip_si_absente(session)
    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-r5-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="r5")
        publier_version(session, lib, "r5@test.ci")

    email = f"r5.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab R5 {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    return client, {"Authorization": f"Bearer {body['jeton']}"}, int(
        body["tenant_id"]
    )


def test_table_parametre_absente_et_lecture_none(session):
    _skip_si_absente(session)
    assert table_parametre_prescription_existe(session) is False
    assert (
        lire_parametres_prescription(
            session, impot="TVA", millesime=2024
        )
        is None
    )


def test_auto_prescrit_noop_sans_delai_referentiel(session, client_cab):
    client, h, tid = client_cab
    cid = _contrib(client, h, "CI-R5-01")
    created = client.post(
        "/api/v1/risques",
        headers=h,
        json={
            "contribuable_id": cid,
            "impot": "TVA",
            "libelle": "Risque ouvert ancien",
            "exercice_origine": 2010,
            "probabilite": "possible",
        },
    )
    assert created.status_code == 201, created.text
    rid = int(created.json()["id"])
    assert created.json()["statut"] == "ouvert"

    res = evaluer_prescription(session, tenant_id=tid, dry_run=False)
    assert res["arme"] is False
    assert res["motif"] == MOTIF_ATTENTE_VISA
    assert res["passes_prescrit"] == 0

    res_t = evaluer_prescription_tenant(session, tid)
    assert res_t.arme is False
    assert res_t.passes_prescrit == 0
    assert any(TABLE_PARAMETRE_PRESCRIPTION in d for d in res_t.details)

    lu = client.get(f"/api/v1/risques/{rid}", headers=h)
    assert lu.status_code == 200
    assert lu.json()["statut"] == "ouvert"
    assert lu.json()["prescrit_le"] is None


def test_prescrit_manuel_ok(session, client_cab):
    client, h, tid = client_cab
    cid = _contrib(client, h, "CI-R5-02")
    created = client.post(
        "/api/v1/risques",
        headers=h,
        json={
            "contribuable_id": cid,
            "impot": "BIC",
            "libelle": "À clôturer manuellement prescrit",
            "exercice_origine": 2018,
        },
    )
    assert created.status_code == 201, created.text
    rid = int(created.json()["id"])

    ok = client.patch(
        f"/api/v1/risques/{rid}",
        headers=h,
        json={"statut": "prescrit"},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["statut"] == "prescrit"
    assert body["prescrit_le"] is not None

    # Auto ne doit pas toucher un déjà prescrit, ni inventer d'autres passages.
    res = evaluer_prescription(session, tenant_id=tid)
    assert res["arme"] is False
    assert res["passes_prescrit"] == 0

    with contexte_tenant(session, tid):
        st = session.execute(
            text("SELECT statut FROM risque WHERE id = :id"),
            {"id": rid},
        ).scalar_one()
    effacer_contexte_tenant(session)
    assert st == "prescrit"
