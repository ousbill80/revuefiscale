"""Tests S3/S5/S6 — abonne, factures, editorial auth, portail client."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.abonne.service import (  # noqa: E402
    accepter_invitation,
    creer_invitation,
    creer_lien_acces,
)
from backend.billing.auth import emettre_jeton_staff  # noqa: E402
from backend.billing.factures import (  # noqa: E402
    creer_facture_brouillon,
    emettre_facture,
    lister_factures,
)
from backend.billing.service import creer_tenant  # noqa: E402
from backend.editorial.publication import (  # noqa: E402
    creer_version_brouillon,
    publier_version,
)
from backend.main import app  # noqa: E402
from backend.plateforme.auth import (  # noqa: E402
    emettre_jeton,
    hasher_mot_de_passe,
)
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402
from backend.plateforme.missions import creer_mission  # noqa: E402


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _assurer_version_publiee(session) -> None:
    row = session.execute(
        text(
            "SELECT id FROM version_referentiel "
            "WHERE publiee_le IS NOT NULL ORDER BY id DESC LIMIT 1"
        )
    ).scalar_one_or_none()
    if row is not None:
        return
    lib = f"v-s3-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="test")
    publier_version(session, lib, "test@2aaz.ci")


def _cabinet(session, palier: str = "standard"):
    email = _email("cab")
    r = creer_tenant(
        session,
        denomination=f"Cabinet {email}",
        type_tenant="cabinet",
        palier=palier,
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    return r, email


def test_liste_missions_et_contribuables(session):
    _assurer_version_publiee(session)
    r, email = _cabinet(session)
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Demo', 'pm') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=int(cid),
        exercice=2025,
        profil={"regime": "reel", "forme_juridique": "SA"},
    )
    session.commit()

    jeton = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=email,
    )
    client = TestClient(app)
    h = {"Authorization": f"Bearer {jeton}"}

    cl = client.get("/api/v1/contribuables", headers=h)
    assert cl.status_code == 200
    assert any(c["id"] == int(cid) for c in cl.json())

    ml = client.get("/api/v1/missions", headers=h)
    assert ml.status_code == 200
    assert any(m["id"] == mid for m in ml.json())

    q = client.get("/api/v1/quota", headers=h)
    assert q.status_code == 200
    body = q.json()
    assert "alerte_80" in body
    assert body["missions_utilisees"] >= 1


def test_lecteur_ne_cree_pas_mission(session):
    r, email = _cabinet(session)
    with contexte_tenant(session, r.tenant_id):
        uid = session.execute(
            text(
                "INSERT INTO utilisateur (tenant_id, email, role, password_hash) "
                "VALUES (:t, :e, 'lecteur', :h) RETURNING id"
            ),
            {
                "t": r.tenant_id,
                "e": _email("lect"),
                "h": hasher_mot_de_passe("secret12345"),
            },
        ).scalar_one()
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'X') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.commit()

    jeton = emettre_jeton(
        utilisateur_id=int(uid),
        tenant_id=r.tenant_id,
        role="lecteur",
        email="lecteur@test.ci",
    )
    client = TestClient(app)
    resp = client.post(
        "/api/v1/missions",
        headers={"Authorization": f"Bearer {jeton}"},
        json={
            "contribuable_id": int(cid),
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert resp.status_code == 403


def test_invitation_creer_et_accepter(session):
    r, email = _cabinet(session)
    with contexte_tenant(session, r.tenant_id):
        inv = creer_invitation(
            session,
            r.tenant_id,
            email=_email("invite"),
            role="reviseur",
            invitee_par=r.utilisateur_id,
        )
    effacer_contexte_tenant(session)
    token = inv["token"]
    acc = accepter_invitation(session, token=token, mot_de_passe="accepte12345")
    assert acc["role"] == "reviseur"
    assert acc["tenant_id"] == r.tenant_id


def test_facture_crud(session):
    r, _email_admin = _cabinet(session, palier="standard")
    f = creer_facture_brouillon(session, r.tenant_id)
    assert f.statut == "brouillon"
    assert f.montant > 0
    emise = emettre_facture(session, f.id)
    assert emise["statut"] == "emise"
    liste = lister_factures(session, r.tenant_id)
    assert any(x["id"] == f.id for x in liste)

    # API
    staff_email = _email("billf")
    session.execute(
        text(
            "INSERT INTO staff_2aaz (email, password_hash, role) "
            "VALUES (:e, :h, 'billing')"
        ),
        {"e": staff_email, "h": hasher_mot_de_passe("StaffTest2026!")},
    )
    session.commit()
    jeton = emettre_jeton_staff(staff_id=1, role="billing", email=staff_email)
    # staff_id in token not verified against DB for authz — role matters
    client = TestClient(app)
    # login propre
    auth = client.post(
        "/api/v1/billing/auth/connexion",
        json={"email": staff_email, "mot_de_passe": "StaffTest2026!"},
    )
    assert auth.status_code == 200
    jeton = auth.json()["jeton"]
    h = {"Authorization": f"Bearer {jeton}"}
    liste_api = client.get("/api/v1/billing/factures", headers=h)
    assert liste_api.status_code == 200
    usage = client.get("/api/v1/billing/usage", headers=h)
    assert usage.status_code == 200


def test_editorial_refuse_sans_token_et_billing_seul(session):
    client = TestClient(app)
    assert client.get("/api/v1/editorial/versions").status_code == 401

    staff_email = _email("billonly")
    session.execute(
        text(
            "INSERT INTO staff_2aaz (email, password_hash, role) "
            "VALUES (:e, :h, 'billing')"
        ),
        {"e": staff_email, "h": hasher_mot_de_passe("StaffTest2026!")},
    )
    session.commit()
    auth = client.post(
        "/api/v1/billing/auth/connexion",
        json={"email": staff_email, "mot_de_passe": "StaffTest2026!"},
    )
    jeton = auth.json()["jeton"]
    refus = client.get(
        "/api/v1/editorial/versions",
        headers={"Authorization": f"Bearer {jeton}"},
    )
    assert refus.status_code == 403

    # editorial OK
    ed_email = _email("edok")
    session.execute(
        text(
            "INSERT INTO staff_2aaz (email, password_hash, role) "
            "VALUES (:e, :h, 'editorial')"
        ),
        {"e": ed_email, "h": hasher_mot_de_passe("StaffTest2026!")},
    )
    session.commit()
    auth2 = client.post(
        "/api/v1/billing/auth/connexion",
        json={"email": ed_email, "mot_de_passe": "StaffTest2026!"},
    )
    ok = client.get(
        "/api/v1/editorial/versions",
        headers={"Authorization": f"Bearer {auth2.json()['jeton']}"},
    )
    assert ok.status_code == 200


def test_portail_client_lien(session):
    _assurer_version_publiee(session)
    r, email = _cabinet(session)
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Portail') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=int(cid),
        exercice=2025,
        profil={"regime": "reel", "forme_juridique": "SA"},
    )
    with contexte_tenant(session, r.tenant_id):
        lien = creer_lien_acces(
            session,
            r.tenant_id,
            mission_id=mid,
            email_contact="client@exemple.ci",
            cree_par=r.utilisateur_id,
        )
    effacer_contexte_tenant(session)
    session.commit()

    client = TestClient(app)
    resp = client.get(f"/api/v1/client/{lien['token']}/restitution")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("sans_restitution") is True
    assert body.get("restitution") is None
    assert body["mission_id"] == mid
