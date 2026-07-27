"""Supervision transverse : alertes par mission, synthèse, cloisonnement."""
from __future__ import annotations

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


def _passer_en_cours(session, tid: int, mid: int) -> None:
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()


def _clore(session, tid: int, mid: int) -> None:
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()


def _viser_phase_complete(client, h, mid: int, phase: str) -> None:
    for role in ("preparateur", "reviseur", "associe"):
        r = client.post(
            f"/api/v1/missions/{mid}/visas",
            headers=h,
            json={"phase": phase, "role": role},
        )
        assert r.status_code == 200, r.text


def _saisir_temps(client, h, mid: int, heures: float = 2.5) -> None:
    r = client.post(
        f"/api/v1/missions/{mid}/temps",
        headers=h,
        json={"phase": "controles", "date_jour": "2026-07-01",
              "heures": heures},
    )
    assert r.status_code == 200, r.text


def _item_suivi(
    session,
    tid: int,
    mid: int,
    cle: str,
    statut: str = "en_attente",
    date_relance: str | None = None,
) -> None:
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "date_relance) VALUES (:t, :m, :c, :c, :s, :d)"
            ),
            {"t": tid, "m": mid, "c": cle, "s": statut, "d": date_relance},
        )
    session.commit()


def _supervision(client, h):
    r = client.get("/api/v1/pilotage/supervision", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _ligne(corps, mid: int):
    ligne = next(
        (m for m in corps["missions"] if m["mission_id"] == mid), None
    )
    assert ligne is not None, corps["missions"]
    return ligne


def test_mission_complete_sans_alerte(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    _passer_en_cours(session, tid, mid)
    _saisir_temps(client, h, mid, heures=3.5)
    _viser_phase_complete(client, h, mid, "restitution")

    corps = _supervision(client, h)
    ligne = _ligne(corps, mid)
    assert ligne["contribuable"] == "PM Demande FICTIF"
    assert ligne["exercice"] == 2025
    assert ligne["statut"] == "en_cours"
    assert ligne["heures_totales"] == "3.5"
    assert ligne["phases_completes"] == 1
    assert ligne["visas_restitution_complets"] is True
    assert ligne["items_en_attente"] == 0
    assert ligne["items_a_relancer"] == 0
    assert ligne["alertes"] == []

    synthese = corps["synthese"]
    assert synthese["missions_actives"] == 1
    assert synthese["sans_aucun_visa"] == 0
    assert synthese["restitution_non_visee"] == 0
    assert synthese["heures_totales"] == "3.5"
    assert synthese["items_a_relancer"] == 0


def test_mission_nue_alertes_visa_et_temps(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    corps = _supervision(client, h)
    ligne = _ligne(corps, mid)
    assert ligne["statut"] == "cadrage"
    assert ligne["heures_totales"] == "0"
    assert ligne["phases_completes"] == 0
    assert ligne["visas_restitution_complets"] is False
    assert "aucun visa posé" in ligne["alertes"]
    assert "aucun temps saisi" in ligne["alertes"]
    # En cadrage, la restitution non visée n'est PAS une alerte.
    assert "restitution non visée" not in ligne["alertes"]
    assert corps["synthese"]["sans_aucun_visa"] == 1
    assert corps["synthese"]["restitution_non_visee"] == 0


def test_restitution_non_visee_hors_cadrage(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    _passer_en_cours(session, tid, mid)
    # Visa partiel sur une autre phase : plus « aucun visa posé ».
    r = client.post(
        f"/api/v1/missions/{mid}/visas",
        headers=h,
        json={"phase": "cadrage", "role": "preparateur"},
    )
    assert r.status_code == 200, r.text

    corps = _supervision(client, h)
    ligne = _ligne(corps, mid)
    assert "aucun visa posé" not in ligne["alertes"]
    assert "restitution non visée" in ligne["alertes"]
    assert corps["synthese"]["restitution_non_visee"] == 1


def test_items_a_relancer_comptes(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    # 2 en attente dont 1 relance échue ; 1 reçu (hors compte).
    _item_suivi(session, tid, mid, "analytique:7011",
                date_relance="2020-01-15")
    _item_suivi(session, tid, mid, "analytique:6222",
                date_relance="2999-12-31")
    _item_suivi(session, tid, mid, "piece:R1", statut="recu")

    corps = _supervision(client, h)
    ligne = _ligne(corps, mid)
    assert ligne["items_en_attente"] == 2
    assert ligne["items_a_relancer"] == 1
    assert "1 item(s) à relancer" in ligne["alertes"]
    assert corps["synthese"]["items_a_relancer"] == 1


def test_mission_cloturee_exclue(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    _clore(session, tid, mid)

    corps = _supervision(client, h)
    assert all(m["mission_id"] != mid for m in corps["missions"])
    assert corps["synthese"]["missions_actives"] == 0
    assert corps["synthese"]["heures_totales"] == "0"


def test_isolation_cross_tenant(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    client = TestClient(app)
    h_a, _tid_a = _connexion(client, email_a)
    mid_a = _mission(client, h_a)

    # Tenant A voit sa mission.
    corps_a = _supervision(client, h_a)
    assert any(m["mission_id"] == mid_a for m in corps_a["missions"])

    # Tenant B fraîchement provisionné : rien ne fuit.
    email_b = _cabinet(session)
    h_b, _tid_b = _connexion(client, email_b)
    corps_b = _supervision(client, h_b)
    assert corps_b["missions"] == []
    assert corps_b["synthese"]["missions_actives"] == 0
    assert "PM Demande FICTIF" not in str(corps_b)


def test_auth_requise(session):
    client = TestClient(app)
    r = client.get("/api/v1/pilotage/supervision")
    assert r.status_code in (401, 403)


def test_alertes_mission_fonction_pure():
    from decimal import Decimal

    from backend.plateforme.supervision_cabinet import alertes_mission

    # Mission saine en cours : rien à signaler.
    assert alertes_mission("en_cours", Decimal("12.5"), 3, True, 0) == []
    # Mission nue en cadrage : visa + temps, pas de restitution.
    assert alertes_mission("cadrage", "0", 0, False, 0) == [
        "aucun visa posé",
        "aucun temps saisi",
    ]
    # Mission en cours sans restitution visée, avec relances échues.
    assert alertes_mission("en_cours", "4", 2, False, 3) == [
        "restitution non visée",
        "3 item(s) à relancer",
    ]
