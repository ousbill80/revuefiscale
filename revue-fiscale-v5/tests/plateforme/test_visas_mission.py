"""Visas de supervision : ordre hiérarchique, révocation, cloisonnement."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _mission,
)


def _viser(client, h, mid, phase="restitution", role="preparateur", **extra):
    corps = {"phase": phase, "role": role}
    corps.update(extra)
    return client.post(f"/api/v1/missions/{mid}/visas", headers=h, json=corps)


def test_pose_dans_l_ordre_et_etat_complet(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    r1 = _viser(client, h, mid, role="preparateur",
                commentaire="travaux préparés")
    assert r1.status_code == 200, r1.text
    v1 = r1.json()["visa"]
    assert v1["phase"] == "restitution"
    assert v1["role"] == "preparateur"
    assert v1["vise_par"] == email
    assert v1["commentaire"] == "travaux préparés"
    assert v1["vise_le"] is not None

    assert _viser(client, h, mid, role="reviseur").status_code == 200
    assert _viser(client, h, mid, role="associe").status_code == 200

    out = client.get(f"/api/v1/missions/{mid}/visas", headers=h)
    assert out.status_code == 200, out.text
    etat = out.json()
    assert [p["phase"] for p in etat["phases"]] == [
        "cadrage", "collecte", "controles", "restitution",
    ]
    par_phase = {p["phase"]: p for p in etat["phases"]}
    assert par_phase["restitution"]["complet"] is True
    assert [v["role"] for v in par_phase["restitution"]["visas"]] == [
        "preparateur", "reviseur", "associe",
    ]
    assert par_phase["cadrage"]["complet"] is False
    assert par_phase["cadrage"]["visas"] == []
    assert etat["synthese"] == {"phases_completes": 1, "total_visas": 3}


def test_reviseur_sans_preparateur_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    r = _viser(client, h, mid, phase="controles", role="reviseur")
    assert r.status_code == 422
    assert "preparateur" in r.json()["detail"]

    r2 = _viser(client, h, mid, phase="controles", role="associe")
    assert r2.status_code == 422
    assert "reviseur" in r2.json()["detail"]


def test_doublon_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert _viser(client, h, mid, phase="cadrage").status_code == 200
    r = _viser(client, h, mid, phase="cadrage")
    assert r.status_code == 422
    assert "déjà visé" in r.json()["detail"]


def test_phase_ou_role_invalide_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    r = _viser(client, h, mid, phase="suivi")
    assert r.status_code == 422
    assert "phase invalide" in r.json()["detail"]
    r2 = _viser(client, h, mid, role="stagiaire")
    assert r2.status_code == 422
    assert "rôle invalide" in r2.json()["detail"]


def test_revocation_bloquee_puis_possible(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert _viser(client, h, mid, role="preparateur").status_code == 200
    assert _viser(client, h, mid, role="reviseur").status_code == 200

    # Rang supérieur (réviseur) présent → révocation du préparateur refusée.
    r = client.delete(
        f"/api/v1/missions/{mid}/visas/restitution/preparateur", headers=h
    )
    assert r.status_code == 422
    assert "rang supérieur" in r.json()["detail"]

    # On révoque d'abord le réviseur, puis le préparateur passe.
    assert client.delete(
        f"/api/v1/missions/{mid}/visas/restitution/reviseur", headers=h
    ).status_code == 200
    ok = client.delete(
        f"/api/v1/missions/{mid}/visas/restitution/preparateur", headers=h
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["visa"]["role"] == "preparateur"

    # Visa déjà révoqué → 404.
    assert client.delete(
        f"/api/v1/missions/{mid}/visas/restitution/preparateur", headers=h
    ).status_code == 404

    etat = client.get(f"/api/v1/missions/{mid}/visas", headers=h).json()
    assert etat["synthese"] == {"phases_completes": 0, "total_visas": 0}


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)
    assert _viser(client, h_a, mid).status_code == 200

    h_b, _ = _connexion(client, email_b)
    assert _viser(client, h_b, mid).status_code == 404
    assert client.get(
        f"/api/v1/missions/{mid}/visas", headers=h_b
    ).status_code == 404
    assert client.delete(
        f"/api/v1/missions/{mid}/visas/restitution/preparateur", headers=h_b
    ).status_code == 404
    # Le tenant légitime voit toujours son visa.
    etat = client.get(f"/api/v1/missions/{mid}/visas", headers=h_a).json()
    assert etat["synthese"]["total_visas"] == 1


def test_auth_requise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(f"/api/v1/missions/{mid}/visas").status_code in (401, 403)
    assert client.post(
        f"/api/v1/missions/{mid}/visas",
        json={"phase": "cadrage", "role": "preparateur"},
    ).status_code in (401, 403)
    assert client.delete(
        f"/api/v1/missions/{mid}/visas/cadrage/preparateur"
    ).status_code in (401, 403)


def test_fonctions_pures_ordre():
    from backend.plateforme.visas_mission import (
        ORDRE_ROLES,
        role_manquant_pour_poser,
        roles_superieurs_presents,
    )

    assert ORDRE_ROLES == ("preparateur", "reviseur", "associe")
    # Pose : le premier rang n'exige rien ; chaque rang exige l'inférieur.
    assert role_manquant_pour_poser("preparateur", set()) is None
    assert role_manquant_pour_poser("reviseur", set()) == "preparateur"
    assert role_manquant_pour_poser("reviseur", {"preparateur"}) is None
    assert role_manquant_pour_poser("associe", {"preparateur"}) == "reviseur"
    assert (
        role_manquant_pour_poser("associe", {"preparateur", "reviseur"})
        is None
    )
    # Révocation : liste des rangs supérieurs déjà visés.
    assert roles_superieurs_presents("preparateur", {"preparateur"}) == []
    assert roles_superieurs_presents(
        "preparateur", {"preparateur", "reviseur"}
    ) == ["reviseur"]
    assert roles_superieurs_presents(
        "preparateur", {"preparateur", "reviseur", "associe"}
    ) == ["reviseur", "associe"]
    assert roles_superieurs_presents(
        "associe", {"preparateur", "reviseur", "associe"}
    ) == []


def test_point_controle_cloture_visas(session):
    """Le point « Visas de supervision » apparaît : attention puis ok."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    ctrl = client.get(f"/api/v1/missions/{mid}/controle-cloture", headers=h)
    assert ctrl.status_code == 200, ctrl.text
    points = {p["code"]: p for p in ctrl.json()["points"]}
    visas = points["visas_supervision"]
    assert visas["libelle"] == "Visas de supervision"
    assert visas["statut"] == "attention"
    for role in ("preparateur", "reviseur", "associe"):
        assert role in visas["detail"]

    for role in ("preparateur", "reviseur", "associe"):
        assert _viser(client, h, mid, role=role).status_code == 200

    ctrl2 = client.get(f"/api/v1/missions/{mid}/controle-cloture", headers=h)
    points2 = {p["code"]: p for p in ctrl2.json()["points"]}
    assert points2["visas_supervision"]["statut"] == "ok"
