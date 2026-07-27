"""Lettre d'affirmation de la direction .docx : contenu, cloisonnement."""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from tests.plateforme.test_courrier_envoi import (  # noqa: E402
    _conclusions_mixtes,
)
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _mission,
)


def _xml_document(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return z.read("word/document.xml").decode("utf-8")


def _inserer_risque_ouvert(session, tid: int, mid: int) -> None:
    with contexte_tenant(session, tid):
        cid = session.execute(
            text("SELECT contribuable_id FROM mission WHERE id = :m"),
            {"m": mid},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, probabilite, "
                "exercice_origine) "
                "VALUES (:t, :c, 'TVA', 'TVA collectée non déclarée', "
                "1000000, 'ouvert', 'probable', 2024)"
            ),
            {"t": tid, "c": cid},
        )
    session.commit()


def test_lettre_affirmation_sans_risque_ni_anomalie(session):
    """Mission fraîche : lettre produite, affirmation « aucun » sans compteur."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/lettre-affirmation.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert "lettre_affirmation_PM_DEMANDE_FICTIF_2025.docx" in dispo
    # Word réel (magic bytes ZIP/OOXML).
    assert resp.content[:4] == b"PK\x03\x04"

    xml = _xml_document(resp.content)
    # En-tête CLIENT (expéditeur) et cabinet destinataire.
    assert "PM DEMANDE FICTIF" in xml  # en-tête client en majuscules
    assert "NCC : CI-DEM-0001" in xml
    assert "À l'attention de :" in xml
    # Objet et structure.
    assert "Lettre d'affirmation de la direction" in xml
    assert (
        "Lettre d'affirmation — revue fiscale exercice 2025" in xml
    )
    assert f"mission n° {mid}" in xml
    assert "Affirmations de la direction" in xml
    assert "fichier des" in xml and "critures comptables (FEC)" in xml
    assert "clarations fiscales souscrites" in xml
    assert "passifs fiscaux" in xml
    assert "Le représentant légal" in xml
    assert "Fait à" in xml
    # Sans risque ni anomalie : aucune mention chiffrée.
    assert "risque(s) fiscal(aux) encore ouvert(s)" not in xml
    assert "conclusion(s) en anomalie" not in xml
    assert "nous n'avons connaissance d'aucun" in xml.lower()


def test_lettre_affirmation_avec_risques_et_anomalies_compteurs(session):
    """Risque ouvert + anomalies : la lettre mentionne les NOMBRES."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _conclusions_mixtes(
        session,
        tid,
        mid,
        [
            (f"BIC-01-CONF-{suffixe}", "Charge déductible justifiée", "conforme", None),
            (f"BIC-02-ANO-{suffixe}", "Amortissement excessif", "anomalie", "1500000"),
            (f"TVA-03-ANO-{suffixe}", "TVA déduite sans facture", "anomalie", "500000"),
        ],
    )
    _inserer_risque_ouvert(session, tid, mid)

    resp = client.get(f"/api/v1/missions/{mid}/lettre-affirmation.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.content[:4] == b"PK\x03\x04"
    xml = _xml_document(resp.content)
    assert "1 risque(s) fiscal(aux) encore ouvert(s)" in xml
    assert "2 conclusion(s) en anomalie" in xml
    assert "éléments déjà portés à votre connaissance" in xml
    # Le reste des affirmations demeure.
    assert "Affirmations de la direction" in xml
    assert "Le représentant légal" in xml


def test_lettre_affirmation_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)

    h_b, _ = _connexion(client, email_b)
    resp = client.get(
        f"/api/v1/missions/{mid}/lettre-affirmation.docx", headers=h_b
    )
    assert resp.status_code == 404
    # Le tenant légitime, lui, télécharge normalement.
    ok = client.get(f"/api/v1/missions/{mid}/lettre-affirmation.docx", headers=h_a)
    assert ok.status_code == 200


def test_lettre_affirmation_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/lettre-affirmation.docx")
    assert resp.status_code in (401, 403)
