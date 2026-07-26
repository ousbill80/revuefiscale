"""Smoke E2E API — auth démo → contribuable → mission → balance FICTIF → restitution.

Données synthétiques uniquement. Aucun taux fiscal inventé.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.main import app  # noqa: E402
from backend.plateforme.auth import hasher_mot_de_passe  # noqa: E402
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BALANCE_JSON = FIXTURES / "balance_fictif_commerce.json"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = "v-smoke-e2e"
    creer_version_brouillon(session, lib, note="smoke")
    publier_version(session, lib, "smoke@test.ci")
    # Charger au moins une règle via seed si vide — le seed global est attendu en CI.


@pytest.fixture
def client_smoke(session):
    """Provisionne un cabinet éphémère + TestClient."""
    import uuid

    _assurer_version(session)
    email = f"smoke.{uuid.uuid4().hex[:8]}@demo.local"
    mdp = "smoke-smoke1"
    r = provisionner_cabinet(
        session,
        denomination=f"Cabinet Smoke {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin=mdp,
        creer_demo=False,
    )
    session.commit()
    client = TestClient(app)
    return client, email, mdp, r


def test_smoke_mission_parcours_complet(client_smoke, session):
    client, email, mdp, _prov = client_smoke

    # 1. Auth
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": mdp},
    )
    assert login.status_code == 200, login.text
    jeton = login.json()["jeton"]
    h = {"Authorization": f"Bearer {jeton}"}

    # 2. Empty states
    cl = client.get("/api/v1/contribuables", headers=h)
    assert cl.status_code == 200
    assert cl.json() == []
    mi = client.get("/api/v1/missions", headers=h)
    assert mi.status_code == 200
    assert mi.json() == []

    # 3. Quota lisible
    q = client.get("/api/v1/quota", headers=h)
    assert q.status_code == 200
    assert "missions_incluses" in q.json()

    # 4. Contribuable PM
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "Société Smoke FICTIF",
            "ncc": "CI-SMOKE-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-FICTIF",
            "dfe": "DFE-SMOKE-0001",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    cid = c.json()["id"]

    # 5. Fiche détail + historique vide
    det = client.get(f"/api/v1/contribuables/{cid}", headers=h)
    assert det.status_code == 200
    assert det.json()["nb_missions"] == 0
    assert det.json()["forme"] == "pm"

    # 6. Mission
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    mid = m.json()["id"]
    assert m.json()["version_referentiel_id"]

    # 7. Balance FICTIF
    corps = json.loads(BALANCE_JSON.read_text(encoding="utf-8"))
    bal = client.post(
        f"/api/v1/missions/{mid}/balance",
        headers=h,
        json=corps,
    )
    assert bal.status_code == 200, bal.text

    # 8. Exécuter
    ex = client.post(
        f"/api/v1/missions/{mid}/executer",
        headers=h,
        json={"reponses": {}},
    )
    assert ex.status_code == 200, ex.text

    # 9. Restitution markdown + épinglage + a_confirmer + statut en_cours
    rest = client.get(f"/api/v1/missions/{mid}/restitution", headers=h)
    assert rest.status_code == 200, rest.text
    body = rest.json()
    assert body["version_referentiel_id"]
    assert body.get("rapport_markdown")
    assert "a_confirmer_total" in body
    assert isinstance(body.get("a_confirmer_regles"), list)
    assert body.get("identification", {}).get("statut") == "en_cours"

    # 9b. Clôture dossier
    clot = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "cloturee"},
    )
    assert clot.status_code == 200, clot.text
    assert clot.json()["statut"] == "cloturee"

    # 10. Exports docx / pdf (liens / bytes)
    docx = client.get(f"/api/v1/missions/{mid}/restitution/rapport.docx", headers=h)
    assert docx.status_code == 200, docx.text
    assert len(docx.content) > 100
    pdf = client.get(f"/api/v1/missions/{mid}/restitution/rapport.pdf", headers=h)
    assert pdf.status_code == 200, pdf.text
    assert pdf.content[:4] == b"%PDF"

    # 11. Historique missions sur fiche
    det2 = client.get(f"/api/v1/contribuables/{cid}", headers=h)
    assert det2.json()["nb_missions"] == 1


def test_smoke_lecteur_lecture_seule(session):
    """Lecteur : GET OK, POST mission / balance / exécuter → 403."""
    import uuid

    _assurer_version(session)
    email_admin = f"adm.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Lecteur {email_admin}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_admin,
        mot_de_passe_admin="admin-admin1",
        creer_demo=True,
    )
    with contexte_tenant(session, r.tenant_id):
        lid = session.execute(
            text(
                "INSERT INTO utilisateur (tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'lecteur', :h, TRUE) RETURNING id"
            ),
            {
                "t": r.tenant_id,
                "e": f"lec.{uuid.uuid4().hex[:8]}@demo.local",
                "h": hasher_mot_de_passe("lecteur-lecteur1"),
            },
        ).scalar_one()
        cid = session.execute(
            text("SELECT id FROM contribuable ORDER BY id LIMIT 1")
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.commit()

    from backend.plateforme.auth import emettre_jeton

    jeton = emettre_jeton(
        utilisateur_id=int(lid),
        tenant_id=r.tenant_id,
        role="lecteur",
        email="lecteur@test.ci",
    )
    client = TestClient(app)
    h = {"Authorization": f"Bearer {jeton}"}

    assert client.get("/api/v1/contribuables", headers=h).status_code == 200
    assert client.get("/api/v1/missions", headers=h).status_code == 200
    assert (
        client.post(
            "/api/v1/missions",
            headers=h,
            json={
                "contribuable_id": int(cid),
                "type_engagement": "autre",
                "exercice": 2025,
                "profil": {"regime": "reel", "forme_juridique": "SA"},
            },
        ).status_code
        == 403
    )
    assert client.post("/api/v1/invitations", headers=h, json={
        "email": "x@y.ci",
        "role": "lecteur",
    }).status_code == 403
