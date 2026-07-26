"""Cycle de vie mission : cadrage → en_cours → cloturee (+ réouverture).

Aucun taux fiscal inventé — statut dossier uniquement.
"""
from __future__ import annotations

import json
import uuid
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
from backend.plateforme.rbac import CAPACITES, ROLE_LECTEUR  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BALANCE_JSON = FIXTURES / "balance_fictif_commerce.json"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-statut-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="statut")
    publier_version(session, lib, "statut@test.ci")


def _cabinet(session):
    email = f"statut.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Statut {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    return r, email


def test_matrice_cloturer_mission():
    assert ROLE_LECTEUR not in CAPACITES["cloturer_mission"]


def test_statut_auto_en_cours_puis_cloture_reouverture(session):
    _assurer_version(session)
    prov, email = _cabinet(session)
    client = TestClient(app)

    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM Statut FICTIF",
            "ncc": "CI-STATUT-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-STATUT",
            "dfe": "DFE-STATUT-1",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    cid = c.json()["id"]

    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    mid = m.json()["id"]
    assert m.json()["statut"] == "cadrage"

    liste = client.get("/api/v1/missions", headers=h)
    assert liste.status_code == 200
    row = next(x for x in liste.json() if x["id"] == mid)
    assert row["statut"] == "cadrage"

    # Transition manuelle cadrage → en_cours
    p1 = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "en_cours"},
    )
    assert p1.status_code == 200, p1.text
    assert p1.json()["statut"] == "en_cours"

    # Retour cadrage interdit
    bad = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "cadrage"},
    )
    assert bad.status_code == 400

    corps = json.loads(BALANCE_JSON.read_text(encoding="utf-8"))
    bal = client.post(f"/api/v1/missions/{mid}/balance", headers=h, json=corps)
    assert bal.status_code == 200, bal.text

    ex = client.post(
        f"/api/v1/missions/{mid}/executer",
        headers=h,
        json={"reponses": {}},
    )
    assert ex.status_code == 200, ex.text

    rest = client.get(f"/api/v1/missions/{mid}/restitution", headers=h)
    assert rest.status_code == 200
    assert rest.json()["identification"]["statut"] == "en_cours"

    clot = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "cloturee"},
    )
    assert clot.status_code == 200, clot.text
    assert clot.json()["statut"] == "cloturee"

    # Exécution refusée si clôturée
    ex2 = client.post(
        f"/api/v1/missions/{mid}/executer",
        headers=h,
        json={"reponses": {}},
    )
    assert ex2.status_code == 400
    assert "clôtur" in ex2.json()["detail"].lower() or "clotur" in ex2.json()[
        "detail"
    ].lower()

    # Réouverture
    reouv = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "en_cours"},
    )
    assert reouv.status_code == 200
    assert reouv.json()["statut"] == "en_cours"

    # Filtre API
    filt = client.get("/api/v1/missions?statut=en_cours", headers=h)
    assert filt.status_code == 200
    assert any(x["id"] == mid for x in filt.json())


def test_lecteur_ne_peut_pas_cloturer(session):
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email_admin = f"adm.st.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Lec Statut {email_admin}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_admin,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    email_lec = f"lec.st.{uuid.uuid4().hex[:8]}@demo.local"
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Lec', 'pm') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        # Passe en_cours pour que la transition clôture soit valide côté métier
        # (le lecteur doit être bloqué par RBAC avant).
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
        session.execute(
            text(
                "INSERT INTO utilisateur (tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'lecteur', :h, TRUE)"
            ),
            {
                "t": r.tenant_id,
                "e": email_lec,
                "h": hasher_mot_de_passe("lecteur-lecteur1"),
            },
        )
    effacer_contexte_tenant(session)
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email_lec, "mot_de_passe": "lecteur-lecteur1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    resp = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "cloturee"},
    )
    assert resp.status_code == 403


def test_accepter_invitation_http(session):
    from backend.abonne.service import creer_invitation

    _assurer_version(session)
    prov, _email = _cabinet(session)
    with contexte_tenant(session, prov.tenant_id):
        inv = creer_invitation(
            session,
            prov.tenant_id,
            email=f"collegue.{uuid.uuid4().hex[:6]}@demo.local",
            role="lecteur",
            invitee_par=prov.utilisateur_id,
        )
    effacer_contexte_tenant(session)
    session.commit()

    client = TestClient(app)
    acc = client.post(
        "/api/v1/invitations/accepter",
        json={"token": inv["token"], "mot_de_passe": "invite-invite1"},
    )
    assert acc.status_code == 200, acc.text
    assert acc.json()["role"] == "lecteur"
    assert acc.json()["email"] == inv["email"]

    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": inv["email"], "mot_de_passe": "invite-invite1"},
    )
    assert login.status_code == 200, login.text
