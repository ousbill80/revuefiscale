"""Matrice RBAC abonné — routes clés."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.main import app  # noqa: E402
from backend.plateforme.auth import emettre_jeton, hasher_mot_de_passe  # noqa: E402
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import provisionner_cabinet  # noqa: E402
from backend.plateforme.rbac import CAPACITES, ROLE_ADMIN, ROLE_LECTEUR, ROLE_REVISEUR  # noqa: E402


def test_matrice_capacites_coherence():
    assert ROLE_LECTEUR in CAPACITES["lire"]
    assert ROLE_LECTEUR not in CAPACITES["creer_mission"]
    assert ROLE_LECTEUR not in CAPACITES["cloturer_mission"]
    assert ROLE_LECTEUR not in CAPACITES["executer_mission"]
    assert ROLE_LECTEUR not in CAPACITES["importer_balance"]
    assert ROLE_LECTEUR not in CAPACITES["inviter"]
    assert ROLE_LECTEUR not in CAPACITES["gerer_equipe"]
    assert ROLE_REVISEUR in CAPACITES["executer_mission"]
    assert ROLE_REVISEUR in CAPACITES["cloturer_mission"]
    assert ROLE_REVISEUR not in CAPACITES["inviter"]
    assert ROLE_REVISEUR not in CAPACITES["gerer_equipe"]
    assert ROLE_ADMIN in CAPACITES["inviter"]
    assert ROLE_ADMIN in CAPACITES["gerer_equipe"]
    assert ROLE_ADMIN in CAPACITES["cloturer_mission"]


def _cabinet_avec_roles(session):
    email = f"rbac.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RBAC {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=True,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text("SELECT id FROM contribuable ORDER BY id LIMIT 1")
        ).scalar_one()
        lec = session.execute(
            text(
                "INSERT INTO utilisateur (tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'lecteur', :h, TRUE) RETURNING id"
            ),
            {
                "t": r.tenant_id,
                "e": f"lec.{uuid.uuid4().hex[:8]}@demo.local",
                "h": hasher_mot_de_passe("x"),
            },
        ).scalar_one()
        rev = session.execute(
            text(
                "INSERT INTO utilisateur (tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'reviseur', :h, TRUE) RETURNING id"
            ),
            {
                "t": r.tenant_id,
                "e": f"rev.{uuid.uuid4().hex[:8]}@demo.local",
                "h": hasher_mot_de_passe("x"),
            },
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.commit()
    return r, int(cid), int(lec), int(rev), email


def test_rbac_lecteur_reviseur_admin(session):
    r, cid, lec_id, rev_id, email = _cabinet_avec_roles(session)
    client = TestClient(app)

    j_lec = emettre_jeton(
        utilisateur_id=lec_id, tenant_id=r.tenant_id, role="lecteur", email="l@t.ci"
    )
    j_rev = emettre_jeton(
        utilisateur_id=rev_id, tenant_id=r.tenant_id, role="reviseur", email="r@t.ci"
    )
    j_adm = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=email,
    )

    h_lec = {"Authorization": f"Bearer {j_lec}"}
    h_rev = {"Authorization": f"Bearer {j_rev}"}
    h_adm = {"Authorization": f"Bearer {j_adm}"}

    # Lecteur lecture OK
    assert client.get("/api/v1/contribuables", headers=h_lec).status_code == 200
    assert client.get(f"/api/v1/contribuables/{cid}", headers=h_lec).status_code == 200

    # Lecteur écriture / exécution / invitations refusées
    assert (
        client.patch(
            f"/api/v1/contribuables/{cid}",
            headers=h_lec,
            json={"denomination": "X"},
        ).status_code
        == 403
    )
    assert client.get("/api/v1/utilisateurs", headers=h_lec).status_code == 403
    assert client.get("/api/v1/invitations", headers=h_lec).status_code == 403
    assert (
        client.patch(
            f"/api/v1/utilisateurs/{lec_id}",
            headers=h_lec,
            json={"role": "reviseur"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/utilisateurs/{lec_id}",
            headers=h_rev,
            json={"role": "admin"},
        ).status_code
        == 403
    )

    # Réviseur : peut créer mission, pas inviter
    m = client.post(
        "/api/v1/missions",
        headers=h_rev,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    assert client.post(
        "/api/v1/invitations",
        headers=h_rev,
        json={"email": f"inv.{uuid.uuid4().hex[:6]}@demo.local", "role": "lecteur"},
    ).status_code == 403

    # Admin : invitations OK (+ outbox en dev)
    inv = client.post(
        "/api/v1/invitations",
        headers=h_adm,
        json={"email": f"inv.{uuid.uuid4().hex[:6]}@demo.local", "role": "lecteur"},
    )
    assert inv.status_code == 201, inv.text
    body = inv.json()
    assert body.get("token")
    assert "email_envoi" in body
