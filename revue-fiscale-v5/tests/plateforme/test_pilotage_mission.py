"""Pilotage de mission : synthèse transverse, blocs agrégés, cloisonnement."""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _mission,
)
from tests.plateforme.test_temps_mission import _saisir  # noqa: E402


def _regle_version_id(session) -> int:
    rv = session.execute(
        text("SELECT id FROM regle_version ORDER BY id LIMIT 1")
    ).scalar_one_or_none()
    if rv is not None:
        return int(rv)
    vr = session.execute(
        text("SELECT id FROM version_referentiel ORDER BY id DESC LIMIT 1")
    ).scalar_one()
    ident = f"TEST_PILOT_{uuid.uuid4().hex[:8].upper()}"
    session.execute(
        text(
            "INSERT INTO regle (identifiant, impot, libelle) "
            "VALUES (:i, 'BIC', 'Règle test pilotage mission')"
        ),
        {"i": ident},
    )
    return int(
        session.execute(
            text(
                "INSERT INTO regle_version (regle_id, version_referentiel_id, "
                "reference_article, reference_source, millesime, date_effet, "
                "nature, condition_declenchement, expression_resultat, "
                "niveau_risque) "
                "VALUES (:r, :v, 'art. test', 'test', 2025, '2025-01-01', "
                "'reintegration', 'true', '0', 'moyen') RETURNING id"
            ),
            {"r": ident, "v": vr},
        ).scalar_one()
    )


def _creer_execution_conclusions(
    session, tenant_id: int, mission_id: int, statuts: list[str]
) -> int:
    """Exécution + une conclusion par statut demandé — retourne exec_id."""
    rv = _regle_version_id(session)
    with contexte_tenant(session, tenant_id):
        eid = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test@pilotage') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        for statut in statuts:
            session.execute(
                text(
                    "INSERT INTO conclusion (tenant_id, execution_id, "
                    "regle_version_id, niveau_risque, statut) "
                    "VALUES (:t, :e, :rv, 'moyen', :st)"
                ),
                {"t": tenant_id, "e": eid, "rv": rv, "st": statut},
            )
    session.commit()
    return int(eid)


def test_pilotage_mission_blocs_attendus(session):
    """200 — tous les blocs présents, programme 0/15, rentabilité null."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    r = client.get(f"/api/v1/missions/{mid}/pilotage", headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert set(out) == {
        "mission",
        "programme",
        "controle_cloture",
        "temps",
        "rentabilite",
        "visas",
        "derniere_execution",
    }

    # Identité de la mission.
    assert out["mission"]["id"] == mid
    assert out["mission"]["exercice"] == 2025
    assert out["mission"]["contribuable"] == "PM Demande FICTIF"
    assert isinstance(out["mission"]["statut"], str)

    # Programme initialisé paresseusement : 0/15 au départ.
    assert out["programme"]["synthese"] == {
        "faites": 0,
        "total": 15,
        "avancement_pct": "0.0",
    }
    phases = {p["phase"]: p for p in out["programme"]["phases"]}
    assert set(phases) == {
        "cadrage", "collecte", "controles", "restitution", "suivi"
    }
    # Synthèse par phase seulement — pas le détail des diligences.
    assert "diligences" not in out["programme"]["phases"][0]

    # Contrôle de pré-clôture : synthèse + recommandation, sans les points.
    assert set(out["controle_cloture"]) == {"synthese", "cloture_recommandee"}
    assert set(out["controle_cloture"]["synthese"]) == {
        "ok", "attention", "bloquant"
    }
    assert isinstance(out["controle_cloture"]["cloture_recommandee"], bool)

    # Temps, rentabilité, visas, dernière exécution : états initiaux.
    assert out["temps"] == {"total_heures": "0", "par_phase": {}}
    assert out["rentabilite"] is None
    assert out["visas"] == {"phases_completes": 0, "total_visas": 0}
    assert out["derniere_execution"] is None


def test_pilotage_rentabilite_et_temps_renseignes(session):
    """Après saisie de temps + PUT rentabilité, le bloc est renseigné."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    assert _saisir(client, h, mid, phase="controles",
                   date_jour="2026-07-10", heures=6).status_code == 200
    assert _saisir(client, h, mid, phase="restitution",
                   date_jour="2026-07-15", heures=4).status_code == 200
    r = client.put(
        f"/api/v1/missions/{mid}/rentabilite",
        headers=h,
        json={"honoraires": 800000, "taux_horaire": 40000},
    )
    assert r.status_code == 200, r.text

    out = client.get(f"/api/v1/missions/{mid}/pilotage", headers=h).json()
    assert out["temps"]["total_heures"] == "10"
    assert out["temps"]["par_phase"] == {"controles": "6", "restitution": "4"}
    assert out["rentabilite"] == {
        "honoraires": "800000",
        "cout_estime": "400000",
        "marge_estimee": "400000",
        "taux_marge_pct": "50.0",
    }


def test_pilotage_derniere_execution_par_statut(session):
    """Conclusions de la dernière exécution comptées par statut."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)

    # Une première exécution (ignorée : seule la dernière compte)…
    _creer_execution_conclusions(session, tid, mid, ["non_verifiable"])
    # …puis la dernière, avec plusieurs statuts.
    eid = _creer_execution_conclusions(
        session, tid, mid, ["conforme", "conforme", "anomalie"]
    )

    out = client.get(f"/api/v1/missions/{mid}/pilotage", headers=h).json()
    assert out["derniere_execution"] == {
        "execution_id": eid,
        "conclusions_par_statut": {"anomalie": 1, "conforme": 2},
        "total_conclusions": 3,
    }


def test_pilotage_404_cross_tenant(session):
    """La mission d'un tenant est invisible (404) depuis un autre tenant."""
    _assurer_version(session)
    email_a = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)

    email_b = _cabinet(session)
    h_b, _ = _connexion(client, email_b)
    r = client.get(f"/api/v1/missions/{mid}/pilotage", headers=h_b)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]

    # Le tenant propriétaire, lui, voit sa mission.
    ok = client.get(f"/api/v1/missions/{mid}/pilotage", headers=h_a)
    assert ok.status_code == 200, ok.text


def test_pilotage_401_sans_jeton(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    r = client.get(f"/api/v1/missions/{mid}/pilotage")
    assert r.status_code == 401, r.text
