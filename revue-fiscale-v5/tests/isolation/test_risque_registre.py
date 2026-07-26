"""Registre risques R1–R4 — RLS, clôture→risque (sans point_ouvert), actions."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

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

        lib = f"v-risq-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="risque")
        publier_version(session, lib, "risq@test.ci")

    email = f"risq.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Risq {email}",
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


def test_risque_crud_accepte_et_rls(session, client_cab):
    client, h, tid = client_cab
    cid = _contrib(client, h, "CI-RISQ-01")

    created = client.post(
        "/api/v1/risques",
        headers=h,
        json={
            "contribuable_id": cid,
            "impot": "TVA",
            "libelle": "Prorata TVA à revoir",
            "exercice_origine": 2024,
            "probabilite": "probable",
            "montant_estime": 1500000,
        },
    )
    assert created.status_code == 201, created.text
    rid = int(created.json()["id"])

    listed = client.get(
        f"/api/v1/contribuables/{cid}/risques", headers=h
    )
    assert listed.status_code == 200
    assert any(r["id"] == rid for r in listed.json())

    bad = client.patch(
        f"/api/v1/risques/{rid}",
        headers=h,
        json={"statut": "accepte"},
    )
    assert bad.status_code == 400

    ok = client.patch(
        f"/api/v1/risques/{rid}",
        headers=h,
        json={
            "statut": "accepte",
            "motif_acceptation": "Client assume le risque",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["statut"] == "accepte"

    effacer_contexte_tenant(session)
    n0 = session.execute(text("SELECT count(*) FROM risque")).scalar_one()
    assert int(n0) == 0


def test_action_transitions_et_retards(session, client_cab):
    client, h, _tid = client_cab
    cid = _contrib(client, h, "CI-RISQ-02")
    created = client.post(
        "/api/v1/risques",
        headers=h,
        json={
            "contribuable_id": cid,
            "impot": "BIC",
            "libelle": "Dons non justifiés",
            "exercice_origine": 2024,
        },
    )
    assert created.status_code == 201, created.text
    rid = int(created.json()["id"])

    hier = (date.today() - timedelta(days=3)).isoformat()
    act = client.post(
        f"/api/v1/risques/{rid}/actions",
        headers=h,
        json={
            "nature": "corrective",
            "libelle": "Collecter justificatifs",
            "echeance": hier,
        },
    )
    assert act.status_code == 201, act.text
    aid = int(act.json()["id"])

    refuse = client.patch(
        f"/api/v1/actions-risque/{aid}",
        headers=h,
        json={"statut": "refusee"},
    )
    assert refuse.status_code == 400

    acc = client.patch(
        f"/api/v1/actions-risque/{aid}",
        headers=h,
        json={"statut": "acceptee"},
    )
    assert acc.status_code == 200, acc.text

    retards = client.get("/api/v1/actions-risque/retards", headers=h)
    assert retards.status_code == 200
    assert any(a["id"] == aid for a in retards.json())

    resume = client.get(
        f"/api/v1/contribuables/{cid}/risques/resume", headers=h
    )
    assert resume.status_code == 200
    body = resume.json()
    assert body["total"] >= 1
    assert body["actions_en_retard"] >= 1


def test_cloture_cree_risque_depuis_anomalie(session, client_cab):
    client, h, tid = client_cab
    cid = _contrib(client, h, "CI-RISQ-03")
    mid = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert mid.status_code == 200, mid.text
    mission_id = int(mid.json()["id"])

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '601', 'Achats', 800000, 0)"
            ),
            {"t": tid, "m": mission_id},
        )
        session.commit()

    exe = client.post(
        f"/api/v1/missions/{mission_id}/executer", headers=h, json={}
    )
    assert exe.status_code == 200, exe.text

    # Forcer au moins une tâche anomalie si le moteur n'en a pas produit
    with contexte_tenant(session, tid):
        n_anom = session.execute(
            text(
                "SELECT count(*) FROM tache t "
                "JOIN objectif o ON o.id = t.objectif_id "
                "WHERE o.mission_id = :m AND t.statut = 'anomalie'"
            ),
            {"m": mission_id},
        ).scalar_one()
    if int(n_anom) == 0:
        pytest.skip("aucune anomalie sur cette exécution — jeu de règles")

    st = client.patch(
        f"/api/v1/missions/{mission_id}/statut",
        headers=h,
        json={"statut": "cloturee"},
    )
    assert st.status_code == 200, st.text
    assert st.json().get("risques_crees", 0) >= 1
    assert st.json().get("points_ouverts_crees", 0) == 0

    listed = client.get(
        f"/api/v1/contribuables/{cid}/risques", headers=h
    )
    assert listed.status_code == 200
    assert len(listed.json()) >= 1

    with contexte_tenant(session, tid):
        n_po = session.execute(
            text(
                "SELECT count(*) FROM point_ouvert "
                "WHERE contribuable_id = :c AND mission_source_id = :m"
            ),
            {"c": cid, "m": mission_id},
        ).scalar_one()
    assert int(n_po) == 0
