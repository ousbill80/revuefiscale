"""Programme de travail : initialisation paresseuse, coches, avancement."""
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


def _cocher(client, h, mid, code, fait=True):
    return client.put(
        f"/api/v1/missions/{mid}/programme/{code}",
        headers=h,
        json={"fait": fait},
    )


def test_initialisation_paresseuse_programme_complet(session):
    """Le premier GET initialise le programme standard, rien de coché."""
    from backend.plateforme.programme_travail import PROGRAMME_STANDARD

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    out = client.get(f"/api/v1/missions/{mid}/programme", headers=h)
    assert out.status_code == 200, out.text
    etat = out.json()
    assert [p["phase"] for p in etat["phases"]] == [
        "cadrage", "collecte", "controles", "restitution", "suivi",
    ]
    codes = [
        d["code"] for p in etat["phases"] for d in p["diligences"]
    ]
    assert sorted(codes) == sorted(c for _, c, _ in PROGRAMME_STANDARD)
    assert etat["synthese"]["total"] == len(PROGRAMME_STANDARD)
    assert etat["synthese"]["faites"] == 0
    assert etat["synthese"]["avancement_pct"] == "0.0"
    for p in etat["phases"]:
        assert p["faites"] == 0
        assert p["avancement_pct"] == "0.0"
        for d in p["diligences"]:
            assert d["fait"] is False
            assert d["fait_par"] is None
            assert d["fait_le"] is None
    # Libellé métier fidèle au programme standard.
    par_code = {
        d["code"]: d for p in etat["phases"] for d in p["diligences"]
    }
    assert par_code["CAD-01"]["libelle"] == (
        "Lettre de mission signée et archivée"
    )
    # Deuxième GET : idempotent, pas de doublon.
    etat2 = client.get(
        f"/api/v1/missions/{mid}/programme", headers=h
    ).json()
    assert etat2["synthese"]["total"] == len(PROGRAMME_STANDARD)


def test_cocher_puis_decocher_diligence(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    r = _cocher(client, h, mid, "CAD-01")
    assert r.status_code == 200, r.text
    d = r.json()["diligence"]
    assert d["code"] == "CAD-01"
    assert d["phase"] == "cadrage"
    assert d["fait"] is True
    assert d["fait_par"] == email
    assert d["fait_le"] is not None

    r2 = _cocher(client, h, mid, "CAD-01", fait=False)
    assert r2.status_code == 200, r2.text
    d2 = r2.json()["diligence"]
    assert d2["fait"] is False
    assert d2["fait_par"] is None
    assert d2["fait_le"] is None


def test_code_inconnu_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    r = _cocher(client, h, mid, "XXX-99")
    assert r.status_code == 422
    assert "diligence inconnue" in r.json()["detail"]


def test_avancement_par_phase_et_global(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    # 2 diligences de cadrage sur 3, 1 de contrôles sur 4.
    for code in ("CAD-01", "CAD-02", "CTL-03"):
        assert _cocher(client, h, mid, code).status_code == 200

    etat = client.get(f"/api/v1/missions/{mid}/programme", headers=h).json()
    par_phase = {p["phase"]: p for p in etat["phases"]}
    assert par_phase["cadrage"]["faites"] == 2
    assert par_phase["cadrage"]["total"] == 3
    assert par_phase["cadrage"]["avancement_pct"] == "66.7"
    assert par_phase["controles"]["faites"] == 1
    assert par_phase["controles"]["total"] == 4
    assert par_phase["controles"]["avancement_pct"] == "25.0"
    assert par_phase["collecte"]["avancement_pct"] == "0.0"
    assert etat["synthese"]["faites"] == 3
    assert etat["synthese"]["total"] == 15
    assert etat["synthese"]["avancement_pct"] == "20.0"


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)
    assert _cocher(client, h_a, mid, "COL-01").status_code == 200

    h_b, _ = _connexion(client, email_b)
    assert client.get(
        f"/api/v1/missions/{mid}/programme", headers=h_b
    ).status_code == 404
    assert _cocher(client, h_b, mid, "COL-01").status_code == 404
    # Le tenant légitime voit toujours sa coche.
    etat = client.get(
        f"/api/v1/missions/{mid}/programme", headers=h_a
    ).json()
    assert etat["synthese"]["faites"] == 1


def test_auth_requise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(
        f"/api/v1/missions/{mid}/programme"
    ).status_code in (401, 403)
    assert client.put(
        f"/api/v1/missions/{mid}/programme/CAD-01", json={"fait": True}
    ).status_code in (401, 403)


def test_fonction_pure_avancement_pct():
    from backend.plateforme.programme_travail import (
        PROGRAMME_STANDARD,
        avancement_pct,
    )

    assert avancement_pct(0, 0) == "0.0"
    assert avancement_pct(0, 3) == "0.0"
    assert avancement_pct(1, 3) == "33.3"
    assert avancement_pct(2, 3) == "66.7"
    assert avancement_pct(3, 3) == "100.0"
    assert avancement_pct(1, 4) == "25.0"
    assert avancement_pct(3, 15) == "20.0"
    assert avancement_pct(1, 8) == "12.5"
    # Le programme standard couvre les 5 phases sans doublon de code.
    codes = [c for _, c, _ in PROGRAMME_STANDARD]
    assert len(codes) == len(set(codes)) == 15
    assert {p for p, _, _ in PROGRAMME_STANDARD} == {
        "cadrage", "collecte", "controles", "restitution", "suivi",
    }
