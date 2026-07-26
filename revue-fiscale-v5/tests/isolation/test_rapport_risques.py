"""Rapport PDF « Synthèse des risques fiscaux » — contenu, RLS cross-tenant."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

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


def _provisionner(session) -> tuple[str, str]:
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-rapport-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="rapport risques")
        publier_version(session, lib, "rapport@test.ci")

    email = f"rapport.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Rapport {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return email, "admin-admin1"


def _connexion(client: TestClient, email: str, mdp: str) -> dict:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": mdp},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['jeton']}"}


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

    _skip_si_absente(session)
    email, mdp = _provisionner(session)
    session.commit()
    client = TestClient(app)
    return client, _connexion(client, email, mdp)


def test_rapport_pdf_contenu_et_entetes(session, client_cab):
    client, h = client_cab
    cid = _contrib(client, h, "CI-RAP-01")

    created = client.post(
        "/api/v1/risques",
        headers=h,
        json={
            "contribuable_id": cid,
            "impot": "TVA",
            "libelle": "TVA déductible non justifiée",
            "exercice_origine": 2024,
            "probabilite": "probable",
            "montant_estime": 2500000,
            "penalites_estimees": 500000,
        },
    )
    assert created.status_code == 201, created.text

    r = client.get(
        f"/api/v1/contribuables/{cid}/risques/rapport.pdf", headers=h
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    dispo = r.headers.get("content-disposition", "")
    assert "attachment" in dispo
    assert "rapport_risques_" in dispo
    assert dispo.strip().endswith('.pdf"')


def test_rapport_pdf_donnees_consolidees(session, client_cab):
    from backend.plateforme.rapport_risques import construire_donnees_rapport

    client, h = client_cab
    cid = _contrib(client, h, "CI-RAP-02")

    for impot, montant, statut in (
        ("TVA", 1000000, "ouvert"),
        ("BIC", 3000000, "ouvert"),
        ("TVA", 700000, "accepte"),
    ):
        corps = {
            "contribuable_id": cid,
            "impot": impot,
            "libelle": f"Risque {impot} {montant}",
            "exercice_origine": 2023,
            "montant_estime": montant,
        }
        created = client.post("/api/v1/risques", headers=h, json=corps)
        assert created.status_code == 201, created.text
        if statut == "accepte":
            p = client.patch(
                f"/api/v1/risques/{created.json()['id']}",
                headers=h,
                json={
                    "statut": "accepte",
                    "motif_acceptation": "Client assume",
                },
            )
            assert p.status_code == 200, p.text

    me = client.get("/api/v1/moi", headers=h)
    assert me.status_code == 200, me.text
    tid = int(me.json()["tenant_id"])

    donnees = construire_donnees_rapport(session, tid, cid)
    assert donnees["nombre_risques"] == 3
    from decimal import Decimal

    assert donnees["exposition_ouverte"] == Decimal("4000000")
    assert donnees["exposition_traitee"] == Decimal("700000")
    assert donnees["exposition_totale"] == Decimal("4700000")
    impots = {i["impot"]: i for i in donnees["par_impot"]}
    assert impots["TVA"]["nombre"] == 2
    assert impots["TVA"]["ouverts"] == 1
    assert impots["BIC"]["nombre"] == 1
    statuts = {s["statut"]: s for s in donnees["par_statut"]}
    assert statuts["ouvert"]["nombre"] == 2
    assert statuts["accepte"]["nombre"] == 1
    # Top risques : le plus gros d'abord, risques clos exclus.
    assert donnees["top_risques"][0]["impot"] == "BIC"
    assert all(
        r["statut"] in {"ouvert", "en_traitement"}
        for r in donnees["top_risques"]
    )
    # Format jj/mm/aaaa de la date d'édition.
    assert len(donnees["edite_le"].split("/")) == 3


def test_rapport_pdf_cross_tenant_404(session, client_cab):
    client, h = client_cab
    cid = _contrib(client, h, "CI-RAP-03")

    email2, mdp2 = _provisionner(session)
    session.commit()
    h2 = _connexion(client, email2, mdp2)

    r = client.get(
        f"/api/v1/contribuables/{cid}/risques/rapport.pdf", headers=h2
    )
    assert r.status_code == 404, r.text


def test_rapport_pdf_contribuable_inconnu_404(session, client_cab):
    client, h = client_cab
    r = client.get(
        "/api/v1/contribuables/999999999/risques/rapport.pdf", headers=h
    )
    assert r.status_code == 404, r.text
