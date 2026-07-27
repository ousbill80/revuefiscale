"""Réponses client : saisie, upsert, lien exécution, cloisonnement, auth."""
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
    _commentaire_disponible,
    _conclusions_non_verifiables,
    _connexion,
    _mission,
)


def _preparer(session, tid, mid, suffixe):
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


def test_enregistrement_reponse_passe_item_recu(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)
    cle = f"piece:OBL-36-ETII-{suffixe}"

    resp = client.put(
        f"/api/v1/missions/{mid}/reponses/{cle}",
        headers=h,
        json={
            "contenu": "État intragroupe transmis en PJ.",
            "pieces_recues": "etat_intragroupe_2025.pdf",
        },
    )
    assert resp.status_code == 200, resp.text
    rep = resp.json()["reponse"]
    assert rep["cle_item"] == cle
    assert rep["contenu"] == "État intragroupe transmis en PJ."
    assert rep["pieces_recues"] == "etat_intragroupe_2025.pdf"
    assert rep["saisie_par"] == email
    assert rep["saisie_le"] is not None

    # L'item de suivi est automatiquement passé « recu ».
    suivi = client.get(
        f"/api/v1/missions/{mid}/suivi-renseignements", headers=h
    ).json()
    par_cle = {i["cle_item"]: i for i in suivi["items"]}
    assert par_cle[cle]["statut"] == "recu"
    assert suivi["synthese"]["recu"] == 1
    assert suivi["synthese"]["en_attente"] == 3


def test_upsert_deuxieme_saisie_ecrase(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)
    cle = "analytique:7011"

    r1 = client.put(
        f"/api/v1/missions/{mid}/reponses/{cle}",
        headers=h,
        json={"contenu": "Première explication.", "pieces_recues": "v1.pdf"},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.put(
        f"/api/v1/missions/{mid}/reponses/{cle}",
        headers=h,
        json={"contenu": "Explication corrigée."},
    )
    assert r2.status_code == 200, r2.text
    rep = r2.json()["reponse"]
    assert rep["contenu"] == "Explication corrigée."
    assert rep["pieces_recues"] is None

    session.rollback()  # nouvelle transaction : voir les écritures des requêtes
    with contexte_tenant(session, tid):
        rows = session.execute(
            text(
                "SELECT contenu FROM reponse_client "
                "WHERE tenant_id = :t AND mission_id = :m AND cle_item = :c"
            ),
            {"t": tid, "m": mid, "c": cle},
        ).scalars().all()
    assert rows == ["Explication corrigée."]


def test_cle_item_inconnu_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    resp = client.put(
        f"/api/v1/missions/{mid}/reponses/piece:INEXISTANTE",
        headers=h,
        json={"contenu": "réponse hors sujet"},
    )
    assert resp.status_code == 422


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, tid_a = _connexion(client, email_a)
    mid = _mission(client, h_a)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid_a, mid, suffixe)

    h_b, _ = _connexion(client, email_b)
    assert (
        client.put(
            f"/api/v1/missions/{mid}/reponses/analytique:7011",
            headers=h_b,
            json={"contenu": "tentative hors tenant"},
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/missions/{mid}/reponses", headers=h_b).status_code
        == 404
    )
    # Le tenant légitime, lui, saisit et lit normalement.
    ok = client.put(
        f"/api/v1/missions/{mid}/reponses/analytique:7011",
        headers=h_a,
        json={"contenu": "explication du client"},
    )
    assert ok.status_code == 200, ok.text


def test_liste_reponses_avec_statut_derniere_execution(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)
    cle_piece = f"piece:BIC-12-AMORT-{suffixe}"

    for cle, contenu in [
        (cle_piece, "Tableau d'amortissement joint."),
        ("analytique:7011", "Baisse liée à la perte d'un client."),
    ]:
        r = client.put(
            f"/api/v1/missions/{mid}/reponses/{cle}",
            headers=h,
            json={"contenu": contenu},
        )
        assert r.status_code == 200, r.text

    out = client.get(f"/api/v1/missions/{mid}/reponses", headers=h)
    assert out.status_code == 200, out.text
    reponses = out.json()["reponses"]
    # Triées par cle_item : analytique avant piece.
    assert [r["cle_item"] for r in reponses] == ["analytique:7011", cle_piece]
    par_cle = {r["cle_item"]: r for r in reponses}
    # Item analytique : pas de règle associée.
    assert par_cle["analytique:7011"]["regle_id"] is None
    assert par_cle["analytique:7011"]["statut_derniere_execution"] is None
    # Item pièce : regle_id déduit + statut de la dernière exécution.
    assert par_cle[cle_piece]["regle_id"] == f"BIC-12-AMORT-{suffixe}"
    assert (
        par_cle[cle_piece]["statut_derniere_execution"] == "non_verifiable"
    )
    assert par_cle[cle_piece]["saisie_par"] == email


def test_auth_requise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(f"/api/v1/missions/{mid}/reponses").status_code in (
        401,
        403,
    )
    assert client.put(
        f"/api/v1/missions/{mid}/reponses/analytique:7011",
        json={"contenu": "sans jeton"},
    ).status_code in (401, 403)
