"""PATCH rôle utilisateur + révocation invitation."""
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


def test_modifier_role_et_revoquer_invitation(session):
    email = f"admin.lot2.{uuid.uuid4().hex[:8]}@example.ci"
    r = provisionner_cabinet(
        session,
        denomination=f"Cabinet Lot2 {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="demo-demo1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "demo-demo1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    inv = client.post(
        "/api/v1/invitations",
        headers=h,
        json={
            "email": f"invite.{uuid.uuid4().hex[:6]}@example.ci",
            "role": "lecteur",
        },
    )
    assert inv.status_code == 201, inv.text
    inv_id = inv.json()["id"]

    users = client.get("/api/v1/utilisateurs", headers=h)
    assert users.status_code == 200
    admin = next(u for u in users.json() if u["id"] == r.utilisateur_id)

    patch = client.patch(
        f"/api/v1/utilisateurs/{admin['id']}",
        headers=h,
        json={"role": "admin"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["role"] == "admin"

    rev = client.post(f"/api/v1/invitations/{inv_id}/revoquer", headers=h)
    assert rev.status_code == 200, rev.text
    assert rev.json()["statut"] == "annulee"

    rev2 = client.post(f"/api/v1/invitations/{inv_id}/revoquer", headers=h)
    assert rev2.status_code == 400


def _cabinet_avec_lecteur_reviseur(session):
    email = f"eq.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Equipe {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
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
    return r, int(lec), int(rev), email


def test_lecteur_reviseur_403_patch_role_et_revoquer(session):
    """Seul l'admin peut PATCH /utilisateurs/{id} et révoquer une invitation."""
    r, lec_id, rev_id, email = _cabinet_avec_lecteur_reviseur(session)
    client = TestClient(app)

    j_adm = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=email,
    )
    j_lec = emettre_jeton(
        utilisateur_id=lec_id, tenant_id=r.tenant_id, role="lecteur", email="l@t.ci"
    )
    j_rev = emettre_jeton(
        utilisateur_id=rev_id, tenant_id=r.tenant_id, role="reviseur", email="r@t.ci"
    )
    h_adm = {"Authorization": f"Bearer {j_adm}"}
    h_lec = {"Authorization": f"Bearer {j_lec}"}
    h_rev = {"Authorization": f"Bearer {j_rev}"}

    inv = client.post(
        "/api/v1/invitations",
        headers=h_adm,
        json={
            "email": f"inv.eq.{uuid.uuid4().hex[:6]}@demo.local",
            "role": "lecteur",
        },
    )
    assert inv.status_code == 201, inv.text
    inv_id = inv.json()["id"]

    for h in (h_lec, h_rev):
        assert (
            client.patch(
                f"/api/v1/utilisateurs/{lec_id}",
                headers=h,
                json={"role": "reviseur"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"/api/v1/invitations/{inv_id}/revoquer",
                headers=h,
            ).status_code
            == 403
        )

    # Admin peut toujours patcher / révoquer (happy path inchangé)
    assert (
        client.patch(
            f"/api/v1/utilisateurs/{lec_id}",
            headers=h_adm,
            json={"role": "lecteur"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/invitations/{inv_id}/revoquer",
            headers=h_adm,
        ).status_code
        == 200
    )


def test_garde_dernier_admin(session):
    """Le dernier admin ne peut pas se retirer le rôle admin."""
    email = f"last.adm.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab LastAdmin {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    j = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=email,
    )
    h = {"Authorization": f"Bearer {j}"}

    refuse = client.patch(
        f"/api/v1/utilisateurs/{r.utilisateur_id}",
        headers=h,
        json={"role": "lecteur"},
    )
    assert refuse.status_code == 400, refuse.text
    detail = str(refuse.json().get("detail", "")).lower()
    assert "dernier" in detail and "admin" in detail


def test_patch_role_isolation_cross_tenant(session):
    """Admin A ne peut pas modifier un utilisateur du cabinet B (RLS)."""
    email_a = f"a.{uuid.uuid4().hex[:8]}@demo.local"
    email_b = f"b.{uuid.uuid4().hex[:8]}@demo.local"
    a = provisionner_cabinet(
        session,
        denomination=f"Cab A {email_a}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_a,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    b = provisionner_cabinet(
        session,
        denomination=f"Cab B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    j_a = emettre_jeton(
        utilisateur_id=a.utilisateur_id,
        tenant_id=a.tenant_id,
        role="admin",
        email=email_a,
    )
    h_a = {"Authorization": f"Bearer {j_a}"}

    # Tentative de patch sur l'utilisateur du tenant B → introuvable (RLS)
    patch = client.patch(
        f"/api/v1/utilisateurs/{b.utilisateur_id}",
        headers=h_a,
        json={"role": "lecteur"},
    )
    assert patch.status_code == 400, patch.text
    assert "introuvable" in str(patch.json().get("detail", "")).lower()

    # Invitation B non révocable depuis A
    j_b = emettre_jeton(
        utilisateur_id=b.utilisateur_id,
        tenant_id=b.tenant_id,
        role="admin",
        email=email_b,
    )
    inv = client.post(
        "/api/v1/invitations",
        headers={"Authorization": f"Bearer {j_b}"},
        json={
            "email": f"cross.{uuid.uuid4().hex[:6]}@demo.local",
            "role": "lecteur",
        },
    )
    assert inv.status_code == 201, inv.text
    rev = client.post(
        f"/api/v1/invitations/{inv.json()['id']}/revoquer",
        headers=h_a,
    )
    assert rev.status_code == 400, rev.text
