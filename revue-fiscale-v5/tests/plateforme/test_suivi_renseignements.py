"""Suivi de circularisation : liste, UPSERT, relances, cloisonnement."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

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
    _commentaire_disponible,
    _conclusions_non_verifiables,
    _connexion,
    _mission,
)


def _preparer(session, client, h, tid, mid, suffixe):
    """Un commentaire disponible (2 questions) + 2 conclusions non vérifiables."""
    _conclusions_non_verifiables(
        session,
        tid,
        mid,
        [
            (f"OBL-36-ETII-{suffixe}", "État des transactions intragroupes"),
            (f"BIC-12-AMORT-{suffixe}", "Justification des amortissements"),
        ],
    )
    _commentaire_disponible(session, tid, mid)


def test_liste_initiale_items_demande_en_attente(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, client, h, tid, mid, suffixe)

    resp = client.get(f"/api/v1/missions/{mid}/suivi-renseignements", headers=h)
    assert resp.status_code == 200, resp.text
    out = resp.json()
    items = out["items"]
    # Même ordre que le .docx : questions analytiques puis pièces (tri regle_id).
    assert [i["cle_item"] for i in items] == [
        "analytique:7011",
        "analytique:5121",
        f"piece:BIC-12-AMORT-{suffixe}",
        f"piece:OBL-36-ETII-{suffixe}",
    ]
    assert all(i["statut"] == "en_attente" for i in items)
    assert all(i["maj_le"] is None for i in items)
    assert "baisse du chiffre d'affaires" in items[0]["libelle"]
    assert "Justification des amortissements" in items[2]["libelle"]
    assert out["synthese"] == {
        "total": 4,
        "en_attente": 4,
        "recu": 0,
        "sans_objet": 0,
        "a_relancer": 0,
    }


def test_upsert_statut_recu_puis_sans_objet(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, client, h, tid, mid, suffixe)
    cle = f"piece:OBL-36-ETII-{suffixe}"

    r1 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/{cle}",
        headers=h,
        json={"statut": "recu", "note": "reçu par mail"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["item"]["statut"] == "recu"
    assert r1.json()["item"]["note"] == "reçu par mail"
    assert r1.json()["item"]["maj_le"] is not None
    assert r1.json()["synthese"]["recu"] == 1
    assert r1.json()["synthese"]["en_attente"] == 3

    # UPSERT : deuxième PATCH sur la même clé → mise à jour, pas de doublon.
    r2 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/{cle}",
        headers=h,
        json={"statut": "sans_objet"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["item"]["statut"] == "sans_objet"
    assert r2.json()["synthese"] == {
        "total": 4,
        "en_attente": 3,
        "recu": 0,
        "sans_objet": 1,
        "a_relancer": 0,
    }
    session.rollback()  # nouvelle transaction : voir les écritures des requêtes
    with contexte_tenant(session, tid):
        nb = session.execute(
            text(
                "SELECT count(*) FROM suivi_demande_renseignements "
                "WHERE tenant_id = :t AND mission_id = :m AND cle_item = :c"
            ),
            {"t": tid, "m": mid, "c": cle},
        ).scalar_one()
    assert int(nb) == 1


def test_a_relancer_avec_date_passee(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, client, h, tid, mid, suffixe)

    hier = (date.today() - timedelta(days=1)).isoformat()
    demain = (date.today() + timedelta(days=1)).isoformat()
    # En attente + relance échue → à relancer.
    r1 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:7011",
        headers=h,
        json={"statut": "en_attente", "date_relance": hier},
    )
    assert r1.status_code == 200, r1.text
    # En attente + relance future → PAS à relancer.
    r2 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:5121",
        headers=h,
        json={"statut": "en_attente", "date_relance": demain},
    )
    assert r2.status_code == 200, r2.text
    # Reçu + relance échue → PAS à relancer (déjà répondu).
    r3 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/piece:BIC-12-AMORT-{suffixe}",
        headers=h,
        json={"statut": "recu", "date_relance": hier},
    )
    assert r3.status_code == 200, r3.text

    out = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    ).json()
    assert out["synthese"]["a_relancer"] == 1
    par_cle = {i["cle_item"]: i for i in out["items"]}
    assert par_cle["analytique:7011"]["date_relance"] == hier
    assert par_cle["analytique:5121"]["date_relance"] == demain


def test_statut_invalide_rejete(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, client, h, tid, mid, suffixe)

    resp = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:7011",
        headers=h,
        json={"statut": "perdu"},
    )
    assert resp.status_code in (400, 422)


def test_item_inconnu_404(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, client, h, tid, mid, suffixe)

    resp = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/piece:INEXISTANTE",
        headers=h,
        json={"statut": "recu"},
    )
    assert resp.status_code == 404


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, tid_a = _connexion(client, email_a)
    mid = _mission(client, h_a)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, client, h_a, tid_a, mid, suffixe)

    h_b, _ = _connexion(client, email_b)
    assert (
        client.get(
            f"/api/v1/missions/{mid}/suivi-renseignements", headers=h_b
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/missions/{mid}/suivi-renseignements/analytique:7011",
            headers=h_b,
            json={"statut": "recu"},
        ).status_code
        == 404
    )
    # Le tenant légitime, lui, voit et modifie normalement.
    ok = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:7011",
        headers=h_a,
        json={"statut": "recu"},
    )
    assert ok.status_code == 200, ok.text
