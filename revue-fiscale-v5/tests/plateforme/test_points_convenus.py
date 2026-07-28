"""Suivi des points convenus du compte-rendu de restitution."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.points_convenus import (
    ErreurPointConvenuConflit,
    ErreurPointConvenuInvalide,
    STATUTS_POINT,
    synthese_points,
    valider_libelle,
    valider_transition,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_statuts_connus():
    assert STATUTS_POINT == ("a_faire", "fait", "abandonne")


def test_valider_libelle_normalise():
    assert valider_libelle("  Régulariser la TVA  ") == "Régulariser la TVA"


def test_valider_libelle_vide_refuse():
    with pytest.raises(ErreurPointConvenuInvalide):
        valider_libelle("   ")
    with pytest.raises(ErreurPointConvenuInvalide):
        valider_libelle(None)


def test_valider_libelle_trop_long_refuse():
    assert len(valider_libelle("x" * 500)) == 500
    with pytest.raises(ErreurPointConvenuInvalide):
        valider_libelle("x" * 501)


def test_transitions_autorisees():
    assert valider_transition("a_faire", "fait") == "fait"
    assert valider_transition("a_faire", "abandonne") == "abandonne"
    # Réouverture humaine possible.
    assert valider_transition("fait", "a_faire") == "a_faire"
    assert valider_transition("abandonne", "a_faire") == "a_faire"


def test_transitions_refusees():
    with pytest.raises(ErreurPointConvenuConflit):
        valider_transition("fait", "abandonne")
    with pytest.raises(ErreurPointConvenuConflit):
        valider_transition("abandonne", "fait")
    with pytest.raises(ErreurPointConvenuConflit):
        valider_transition("a_faire", "a_faire")


def test_transition_statut_inconnu_422():
    with pytest.raises(ErreurPointConvenuInvalide):
        valider_transition("a_faire", "termine")


def test_synthese_compteurs():
    points = [
        {"statut": "a_faire"},
        {"statut": "fait"},
        {"statut": "fait"},
        {"statut": "abandonne"},
        {"statut": "inconnu"},  # ignoré
    ]
    assert synthese_points(points) == {
        "a_faire": 1,
        "fait": 2,
        "abandonne": 1,
    }
    assert synthese_points([]) == {"a_faire": 0, "fait": 0, "abandonne": 0}


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-pconv-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="points-convenus")
    publier_version(session, lib, "pconv@test.ci")


def _mission(session, statut: str = "en_cours") -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"pconv.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab PConv {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM PConv FICTIF', 'pm') RETURNING id"
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
        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": statut, "m": mid},
        )
    return r.tenant_id, int(mid), email


def _client_connecte(email: str):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['jeton']}"}


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/points-convenus"


def test_api_creation_et_liste(session):
    _tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid), headers=h, json={"libelle": " Régulariser la TVA Q4 "}
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["point"]["libelle"] == "Régulariser la TVA Q4"
    assert corps["point"]["statut"] == "a_faire"
    assert corps["point"]["cree_le"] is not None
    assert "consultatif" in corps["note"].lower()

    client.post(_url(mid), headers=h, json={"libelle": "Fournir le FEC"})
    g = client.get(_url(mid), headers=h)
    assert g.status_code == 200, g.text
    liste = g.json()
    assert [p["libelle"] for p in liste["points"]] == [
        "Régulariser la TVA Q4",
        "Fournir le FEC",
    ]
    assert liste["synthese"] == {"a_faire": 2, "fait": 0, "abandonne": 0}
    assert liste["mission_id"] == mid


def test_api_changement_statut_et_synthese(session):
    _tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    pid = client.post(
        _url(mid), headers=h, json={"libelle": "Provision à passer"}
    ).json()["point"]["id"]

    r = client.post(
        f"/api/v1/points-convenus/{pid}/statut",
        headers=h,
        json={"statut": "fait"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["point"]["statut"] == "fait"
    assert r.json()["mission_id"] == mid

    g = client.get(_url(mid), headers=h)
    assert g.json()["synthese"] == {"a_faire": 0, "fait": 1, "abandonne": 0}

    # Transition refusée : fait → abandonne.
    r2 = client.post(
        f"/api/v1/points-convenus/{pid}/statut",
        headers=h,
        json={"statut": "abandonne"},
    )
    assert r2.status_code == 409, r2.text

    # Statut inconnu → 422.
    r3 = client.post(
        f"/api/v1/points-convenus/{pid}/statut",
        headers=h,
        json={"statut": "termine"},
    )
    assert r3.status_code == 422, r3.text


def test_api_journalise_creation_et_maj(session):
    tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    pid = client.post(
        _url(mid), headers=h, json={"libelle": "Point journalisé"}
    ).json()["point"]["id"]
    client.post(
        f"/api/v1/points-convenus/{pid}/statut",
        headers=h,
        json={"statut": "abandonne"},
    )
    with contexte_tenant(session, tid):
        actions = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT action FROM journal_audit "
                    "WHERE mission_id = :m AND action IN "
                    "('creation_point_convenu', 'maj_point_convenu') "
                    "ORDER BY id"
                ),
                {"m": mid},
            )
        ]
    assert actions == ["creation_point_convenu", "maj_point_convenu"]


def test_api_422_libelle_invalide(session):
    _tid, mid, email = _mission(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(_url(mid), headers=h, json={"libelle": "   "})
    assert r.status_code == 422, r.text
    r2 = client.post(_url(mid), headers=h, json={"libelle": "x" * 501})
    assert r2.status_code == 422, r2.text


def test_api_409_mission_cadrage(session):
    _tid, mid, email = _mission(session, statut="cadrage")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(_url(mid), headers=h, json={"libelle": "Trop tôt"})
    assert r.status_code == 409, r.text


def test_api_creation_mission_cloturee_ok(session):
    """Le suivi se poursuit après clôture (post-restitution)."""
    _tid, mid, email = _mission(session, statut="cloturee")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid), headers=h, json={"libelle": "Suivi post-clôture"}
    )
    assert r.status_code == 200, r.text


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, email_a = _mission(session)
    session.commit()
    client_a, h_a = _client_connecte(email_a)
    pid_a = client_a.post(
        _url(mid_a), headers=h_a, json={"libelle": "Point tenant A"}
    ).json()["point"]["id"]

    _tid_b, _mid_b, email_b = _mission(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert (
        client_b.post(
            _url(mid_a), headers=h_b, json={"libelle": "intrusion"}
        ).status_code
        == 404
    )
    assert (
        client_b.post(
            f"/api/v1/points-convenus/{pid_a}/statut",
            headers=h_b,
            json={"statut": "fait"},
        ).status_code
        == 404
    )


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert (
        client.post(_url(1), json={"libelle": "x"}).status_code == 401
    )
    assert (
        client.post(
            "/api/v1/points-convenus/1/statut", json={"statut": "fait"}
        ).status_code
        == 401
    )
