"""Temps passés par mission : saisie, récap, validations, cloisonnement."""
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


def _saisir(client, h, mid, **surcharges):
    corps = {
        "phase": "controles",
        "date_jour": "2026-07-20",
        "heures": 3.5,
    }
    corps.update(surcharges)
    return client.post(f"/api/v1/missions/{mid}/temps", headers=h, json=corps)


def test_saisie_et_recap(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    r1 = _saisir(
        client, h, mid,
        phase="cadrage", date_jour="2026-07-01", heures=2,
        collaborateur="a.kone@cab.ci", note="réunion de lancement",
    )
    assert r1.status_code == 200, r1.text
    e1 = r1.json()["entree"]
    assert e1["collaborateur"] == "a.kone@cab.ci"
    assert e1["phase"] == "cadrage"
    assert e1["heures"] == "2"
    assert e1["note"] == "réunion de lancement"
    assert e1["saisi_le"] is not None

    # Collaborateur par défaut = email connecté.
    r2 = _saisir(client, h, mid, phase="controles",
                 date_jour="2026-07-10", heures=5.25)
    assert r2.status_code == 200, r2.text
    assert r2.json()["entree"]["collaborateur"] == email

    r3 = _saisir(client, h, mid, phase="controles",
                 date_jour="2026-07-12", heures=1.5,
                 collaborateur="a.kone@cab.ci")
    assert r3.status_code == 200, r3.text

    out = client.get(f"/api/v1/missions/{mid}/temps", headers=h)
    assert out.status_code == 200, out.text
    recap = out.json()
    # Entrées triées date desc.
    assert [e["date_jour"] for e in recap["entrees"]] == [
        "2026-07-12", "2026-07-10", "2026-07-01",
    ]
    assert recap["total_heures"] == "8.75"
    assert recap["par_phase"] == {"cadrage": "2", "controles": "6.75"}
    assert recap["par_collaborateur"] == {
        "a.kone@cab.ci": "3.5",
        email: "5.25",
    }
    assert recap["valorisation"] is None

    # Valorisation au taux horaire : 8.75 h × 40 000 = 350 000.
    val = client.get(
        f"/api/v1/missions/{mid}/temps", headers=h,
        params={"taux_horaire": 40000},
    )
    assert val.status_code == 200, val.text
    assert val.json()["valorisation"] == "350000"


def test_phase_invalide_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)
    r = _saisir(client, h, mid, phase="redaction")
    assert r.status_code == 422
    assert "phase invalide" in r.json()["detail"]


def test_heures_invalides_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)
    assert _saisir(client, h, mid, heures=0).status_code == 422
    assert _saisir(client, h, mid, heures=-2).status_code == 422
    assert _saisir(client, h, mid, heures=24.5).status_code == 422
    # Le récap reste vide : aucune saisie invalide n'a été enregistrée.
    recap = client.get(f"/api/v1/missions/{mid}/temps", headers=h).json()
    assert recap["entrees"] == []
    assert recap["total_heures"] == "0"


def test_suppression_puis_recap_a_jour(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    e1 = _saisir(client, h, mid, phase="collecte",
                 date_jour="2026-07-05", heures=4).json()["entree"]
    _saisir(client, h, mid, phase="suivi", date_jour="2026-07-06", heures=1)

    supp = client.delete(
        f"/api/v1/missions/{mid}/temps/{e1['id']}", headers=h
    )
    assert supp.status_code == 200, supp.text
    assert supp.json()["entree"]["id"] == e1["id"]

    recap = client.get(f"/api/v1/missions/{mid}/temps", headers=h).json()
    assert recap["total_heures"] == "1"
    assert recap["par_phase"] == {"suivi": "1"}

    # Entrée déjà supprimée / inexistante → 404.
    assert client.delete(
        f"/api/v1/missions/{mid}/temps/{e1['id']}", headers=h
    ).status_code == 404


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)
    e = _saisir(client, h_a, mid).json()["entree"]

    h_b, _ = _connexion(client, email_b)
    assert _saisir(client, h_b, mid).status_code == 404
    assert client.get(
        f"/api/v1/missions/{mid}/temps", headers=h_b
    ).status_code == 404
    assert client.delete(
        f"/api/v1/missions/{mid}/temps/{e['id']}", headers=h_b
    ).status_code == 404
    # Le tenant légitime voit toujours son entrée.
    recap = client.get(f"/api/v1/missions/{mid}/temps", headers=h_a).json()
    assert [x["id"] for x in recap["entrees"]] == [e["id"]]


def test_auth_requise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(f"/api/v1/missions/{mid}/temps").status_code in (401, 403)
    assert client.post(
        f"/api/v1/missions/{mid}/temps",
        json={"phase": "cadrage", "date_jour": "2026-07-01", "heures": 1},
    ).status_code in (401, 403)
    assert client.delete(
        f"/api/v1/missions/{mid}/temps/1"
    ).status_code in (401, 403)


def test_recap_depuis_entrees_fonction_pure():
    from backend.plateforme.temps_mission import (
        ErreurTempsMission,
        recap_depuis_entrees,
    )

    entrees = [
        {"id": 1, "collaborateur": "a", "phase": "cadrage",
         "date_jour": "2026-07-01", "heures": "2.5"},
        {"id": 2, "collaborateur": "b", "phase": "controles",
         "date_jour": "2026-07-03", "heures": "4"},
        {"id": 3, "collaborateur": "a", "phase": "controles",
         "date_jour": "2026-07-03", "heures": "1.25"},
    ]
    recap = recap_depuis_entrees(entrees, taux_horaire="1000")
    assert [e["id"] for e in recap["entrees"]] == [3, 2, 1]
    assert recap["total_heures"] == "7.75"
    assert recap["par_phase"] == {"cadrage": "2.5", "controles": "5.25"}
    assert recap["par_collaborateur"] == {"a": "3.75", "b": "4"}
    assert recap["valorisation"] == "7750"

    vide = recap_depuis_entrees([])
    assert vide == {
        "entrees": [],
        "total_heures": "0",
        "par_phase": {},
        "par_collaborateur": {},
        "valorisation": None,
    }
    with pytest.raises(ErreurTempsMission):
        recap_depuis_entrees(entrees, taux_horaire="abc")
    with pytest.raises(ErreurTempsMission):
        recap_depuis_entrees(entrees, taux_horaire=-5)
