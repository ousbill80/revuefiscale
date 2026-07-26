"""Courrier de relance .docx : items en attente, délai 8 jours, cloisonnement."""
from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _commentaire_disponible,
    _conclusions_non_verifiables,
    _connexion,
    _mission,
)


def _preparer(session, tid, mid, suffixe):
    """2 questions analytiques + 2 conclusions non vérifiables."""
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


def _xml_document(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_relance_docx_items_en_attente_seulement(session):
    """Le courrier liste les items en attente numérotés, PAS les reçus/sans objet."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    # Un item reçu, un sans objet — ils ne doivent PAS figurer au courrier.
    r1 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/piece:OBL-36-ETII-{suffixe}",
        headers=h,
        json={"statut": "recu", "note": "reçu par mail"},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:5121",
        headers=h,
        json={"statut": "sans_objet"},
    )
    assert r2.status_code == 200, r2.text
    # Un item en attente avec date de relance planifiée.
    relance = (date.today() - timedelta(days=6)).isoformat()
    r3 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:7011",
        headers=h,
        json={"statut": "en_attente", "date_relance": relance},
    )
    assert r3.status_code == 200, r3.text

    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert "relance_PM_DEMANDE_FICTIF_2025.docx" in dispo
    assert resp.content[:4] == b"PK\x03\x04"

    xml = _xml_document(resp.content)
    # En-tête / objet / rappel courtois.
    assert "Relance — demande de renseignements et de documents" in xml
    assert "PM Demande FICTIF" in xml
    assert "délai indicatif de 15 jours" in xml
    assert "Éléments toujours en attente" in xml
    # Items en attente numérotés (ordre du suivi : 7011 puis BIC).
    assert "1. Poste 7011" in xml
    assert f"2. [BIC-12-AMORT-{suffixe}]" in xml
    assert "Justification des amortissements" in xml
    # Date de relance planifiée mentionnée.
    date_fr = date.fromisoformat(relance).strftime("%d/%m/%Y")
    assert f"relance prévue le {date_fr}" in xml
    # Items reçus / sans objet ABSENTS.
    assert f"OBL-36-ETII-{suffixe}" not in xml
    assert "5121" not in xml
    # Clôture : nouveau délai de 8 jours + conséquences.
    assert "8 jours" in xml
    assert "non vérifiables" in xml
    assert "réserves" in xml


def test_relance_aucun_item_en_attente_409(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    # Tout est reçu ou sans objet → la relance est sans objet.
    for cle, statut in [
        ("analytique:7011", "recu"),
        ("analytique:5121", "recu"),
        (f"piece:BIC-12-AMORT-{suffixe}", "sans_objet"),
        (f"piece:OBL-36-ETII-{suffixe}", "recu"),
    ]:
        r = client.patch(
            f"/api/v1/missions/{mid}/suivi-renseignements/{cle}",
            headers=h,
            json={"statut": statut},
        )
        assert r.status_code == 200, r.text

    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance.docx", headers=h)
    assert resp.status_code == 409, resp.text
    assert "aucun item en attente" in resp.json()["detail"]


def test_relance_mission_sans_items_409(session):
    """Mission sans aucune source d'items — pas de relance possible."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance.docx", headers=h)
    assert resp.status_code == 409, resp.text


def test_relance_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, tid_a = _connexion(client, email_a)
    mid = _mission(client, h_a)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid_a, mid, suffixe)

    h_b, _ = _connexion(client, email_b)
    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance.docx", headers=h_b)
    assert resp.status_code == 404
    # Le tenant légitime, lui, télécharge normalement.
    ok = client.get(f"/api/v1/missions/{mid}/courrier-relance.docx", headers=h_a)
    assert ok.status_code == 200, ok.text


def test_relance_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance.docx")
    assert resp.status_code in (401, 403)
