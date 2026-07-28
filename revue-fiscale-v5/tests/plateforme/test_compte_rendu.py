"""Compte-rendu de la réunion de restitution — saisie humaine traçable."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.compte_rendu import (
    ErreurCompteRenduInvalide,
    valider_compte_rendu,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────

_JOUR = date(2026, 7, 27)


def test_valider_compte_rendu_normalise():
    out = valider_compte_rendu(
        "2026-07-20", "  M. X, Mme Y  ", "  Régularisation TVA.  ", _JOUR
    )
    assert out == {
        "date_reunion": date(2026, 7, 20),
        "participants": "M. X, Mme Y",
        "points_convenus": "Régularisation TVA.",
    }


def test_valider_compte_rendu_aujourd_hui_accepte():
    out = valider_compte_rendu(_JOUR.isoformat(), "M. X", "RAS", _JOUR)
    assert out["date_reunion"] == _JOUR


def test_valider_compte_rendu_date_objet_accepte():
    out = valider_compte_rendu(date(2026, 7, 1), "M. X", "RAS", _JOUR)
    assert out["date_reunion"] == date(2026, 7, 1)


def test_valider_compte_rendu_date_future_refusee():
    with pytest.raises(ErreurCompteRenduInvalide, match="future"):
        valider_compte_rendu("2026-07-28", "M. X", "RAS", _JOUR)


def test_valider_compte_rendu_date_invalide_ou_absente():
    with pytest.raises(ErreurCompteRenduInvalide, match="requise"):
        valider_compte_rendu("", "M. X", "RAS", _JOUR)
    with pytest.raises(ErreurCompteRenduInvalide, match="invalide"):
        valider_compte_rendu("20/07/2026", "M. X", "RAS", _JOUR)


def test_valider_compte_rendu_participants_et_points_requis():
    with pytest.raises(ErreurCompteRenduInvalide, match="participants"):
        valider_compte_rendu("2026-07-20", "   ", "RAS", _JOUR)
    with pytest.raises(ErreurCompteRenduInvalide, match="points"):
        valider_compte_rendu("2026-07-20", "M. X", "", _JOUR)


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
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-cr-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="compte-rendu")
    publier_version(session, lib, "cr@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"cr.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab CR {email}",
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
                "VALUES (:t, 'PM CR FICTIF', 'pm') RETURNING id"
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
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
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
    return f"/api/v1/missions/{mid}/compte-rendu"


_SAISIE = {
    "date_reunion": "2026-01-15",
    "participants": "M. X (gérant), cabinet — associé",
    "points_convenus": "Régularisation TVA avant le 15 février.",
}


def test_api_get_null_puis_post_puis_get(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    g0 = client.get(_url(mid), headers=h)
    assert g0.status_code == 200, g0.text
    assert g0.json() == {"mission_id": mid, "compte_rendu": None}

    p = client.post(_url(mid), headers=h, json=_SAISIE)
    assert p.status_code == 200, p.text
    cr = p.json()["compte_rendu"]
    assert cr["date_reunion"] == "2026-01-15"
    assert cr["participants"] == _SAISIE["participants"]
    assert cr["points_convenus"] == _SAISIE["points_convenus"]
    assert cr["maj_le"] is not None

    g1 = client.get(_url(mid), headers=h)
    assert g1.status_code == 200, g1.text
    assert g1.json()["compte_rendu"]["date_reunion"] == "2026-01-15"

    # Enregistrement journalisé — visible dans la chronologie.
    chrono = client.get(f"/api/v1/missions/{mid}/chronologie", headers=h)
    assert chrono.status_code == 200, chrono.text
    actions = [e["action"] for e in chrono.json()["evenements"]]
    assert "enregistrement_compte_rendu" in actions


def test_api_upsert_un_seul_compte_rendu_par_mission(session):
    tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    p1 = client.post(_url(mid), headers=h, json=_SAISIE)
    assert p1.status_code == 200, p1.text
    p2 = client.post(
        _url(mid),
        headers=h,
        json=_SAISIE
        | {"date_reunion": "2026-02-01", "points_convenus": "Point unique."},
    )
    assert p2.status_code == 200, p2.text
    assert p2.json()["compte_rendu"]["date_reunion"] == "2026-02-01"
    assert p2.json()["compte_rendu"]["points_convenus"] == "Point unique."

    with contexte_tenant(session, tid):
        nb = session.execute(
            text(
                "SELECT count(*) FROM compte_rendu_reunion "
                "WHERE mission_id = :m"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(nb) == 1


def test_api_422_date_future_et_champs_vides(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid),
        headers=h,
        json=_SAISIE | {"date_reunion": "2099-01-01"},
    )
    assert r.status_code == 422, r.text
    assert "future" in r.json()["detail"]

    r2 = client.post(_url(mid), headers=h, json=_SAISIE | {"participants": " "})
    assert r2.status_code == 422, r2.text
    assert "participants" in r2.json()["detail"]


def test_api_409_mission_cloturee(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(_url(mid), headers=h, json=_SAISIE)
    assert r.status_code == 409, r.text
    assert "clôturée" in r.json()["detail"]


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _email_a = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"cr.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab CR B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    r = client_b.post(_url(mid_a), headers=h_b, json=_SAISIE)
    assert r.status_code == 404, r.text


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(_url(1), json=_SAISIE).status_code == 401


# ── Bilan de clôture — point compte-rendu ──────────────────────────


def test_construire_bilan_point_compte_rendu():
    from backend.plateforme.bilan_cloture import construire_bilan

    # Signal indisponible → point absent (échec silencieux).
    bilan = construire_bilan({})
    assert "compte_rendu_reunion" not in {p["code"] for p in bilan["points"]}

    # Disponible sans compte-rendu → attention.
    bilan = construire_bilan(
        {"compte_rendu_disponible": True, "compte_rendu_date": None}
    )
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["compte_rendu_reunion"]["statut"] == "attention"
    assert par_code["compte_rendu_reunion"]["libelle"] == (
        "Aucun compte-rendu de réunion consigné"
    )

    # Disponible avec compte-rendu → ok, date au format français.
    bilan = construire_bilan(
        {"compte_rendu_disponible": True, "compte_rendu_date": "2026-01-15"}
    )
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["compte_rendu_reunion"]["statut"] == "ok"
    assert par_code["compte_rendu_reunion"]["libelle"] == (
        "Compte-rendu de réunion de restitution consigné (15/01/2026)"
    )


def test_bilan_mission_compte_rendu_absent_puis_consigne(session):
    from backend.plateforme.bilan_cloture import bilan_mission
    from backend.plateforme.compte_rendu import enregistrer_compte_rendu

    tid, mid, _email = _mission_en_cours(session)

    bilan = bilan_mission(session, tid, mid)
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["compte_rendu_reunion"]["statut"] == "attention"

    enregistrer_compte_rendu(
        session,
        tid,
        mid,
        "2026-01-15",
        "M. X",
        "Points convenus.",
        aujourd_hui=date(2026, 7, 27),
    )
    bilan = bilan_mission(session, tid, mid)
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["compte_rendu_reunion"]["statut"] == "ok"
    assert "15/01/2026" in par_code["compte_rendu_reunion"]["libelle"]
