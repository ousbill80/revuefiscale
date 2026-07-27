"""Courrier d'envoi du rapport .docx : synthèse chiffrée, cloisonnement."""
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
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _creer_regle_version,
    _mission,
    _version_brouillon_test,
)


def _conclusions_mixtes(
    session,
    tenant_id: int,
    mission_id: int,
    regles: list[tuple[str, str, str, str | None]],
) -> None:
    """Une exécution + une conclusion par (regle_id, libellé, statut, montant)."""
    vr = _version_brouillon_test(session)
    with contexte_tenant(session, tenant_id):
        eid = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test@courrier') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        for rid, lib, statut, montant in regles:
            rv = _creer_regle_version(session, vr, rid, lib)
            session.execute(
                text(
                    "INSERT INTO conclusion (tenant_id, execution_id, "
                    "regle_version_id, niveau_risque, statut, montant) "
                    "VALUES (:t, :e, :rv, 'moyen', :s, :mt)"
                ),
                {"t": tenant_id, "e": eid, "rv": rv, "s": statut, "mt": montant},
            )
    session.commit()


def _xml_document(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_courrier_envoi_avec_execution_synthese_chiffree(session):
    """Dernière exécution : compteurs par statut + total FCFA des anomalies."""
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
            (f"OBL-04-NV-{suffixe}", "État intragroupe absent", "non_verifiable", None),
        ],
    )

    resp = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert "courrier_envoi_rapport_PM_DEMANDE_FICTIF_2025.docx" in dispo
    # Word réel (magic bytes ZIP/OOXML).
    assert resp.content[:4] == b"PK\x03\x04"

    xml = _xml_document(resp.content)
    # Structure du courrier : objet, mission, livrables, invitation, signature.
    assert "Courrier d'envoi du rapport de revue fiscale" in xml
    assert "exercice 2025" in xml
    assert f"mission n° {mid}" in xml
    assert "Documents remis" in xml
    assert "Rapport de revue fiscale (version Word et version PDF)" in xml
    assert "Plan d'actions correctives et recommandations" in xml
    assert "Réunion de restitution" in xml
    assert "L'associé signataire" in xml
    # Destinataire avec NCC (renseigné dans la fiche contribuable).
    assert "PM Demande FICTIF" in xml
    assert "NCC : CI-DEM-0001" in xml
    # Synthèse chiffrée de la dernière exécution.
    assert "4 point(s)" in xml
    assert "1 constat(s) conforme(s)" in xml
    assert "2 anomalie(s)" in xml
    assert "2 000 000 FCFA" in xml
    assert "1 constat(s) non vérifiable(s)" in xml
    assert "en cours d'instruction" not in xml


def test_courrier_envoi_sans_execution_mention_instruction(session):
    """Aucune exécution : la lettre est produite quand même (pas d'erreur)."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.content[:4] == b"PK\x03\x04"
    xml = _xml_document(resp.content)
    assert "Courrier d'envoi du rapport de revue fiscale" in xml
    assert "en cours d'instruction" in xml
    # Aucune synthèse chiffrée inventée sans exécution.
    assert "constat(s) conforme(s)" not in xml
    assert "FCFA ;" not in xml


def test_courrier_envoi_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)

    h_b, _ = _connexion(client, email_b)
    resp = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx", headers=h_b)
    assert resp.status_code == 404
    # Le tenant légitime, lui, télécharge normalement.
    ok = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx", headers=h_a)
    assert ok.status_code == 200


def test_courrier_envoi_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx")
    assert resp.status_code in (401, 403)
