"""Dossier de travail ZIP : contenu, résilience par pièce, cloisonnement."""
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
from backend.plateforme import archive_mission  # noqa: E402
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


def _telecharger_zip(client, h, mid):
    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip", headers=h)
    assert resp.status_code == 200, resp.text
    return resp


def test_zip_valide_contenu_et_sommaire(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    resp = _telecharger_zip(client, h, mid)
    # ZIP valide (magic) + en-têtes de téléchargement.
    assert resp.content[:4] == b"PK\x03\x04"
    assert resp.headers["content-type"].startswith("application/zip")
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert "dossier_travail_PM_DEMANDE_FICTIF_2025.zip" in dispo

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "00_sommaire.txt" in noms
        assert "02_rapport_restitution.docx" in noms
        assert "03_rapport_restitution.pdf" in noms
        assert "06_suivi_circularisation.csv" in noms
        # Livrables annexes attendus sur cette mission (items présents).
        assert "01_lettre_mission.docx" in noms
        assert "04_rapport_risques.pdf" in noms
        assert "05_demande_renseignements.docx" in noms
        assert "07_controle_cloture.txt" in noms

        # Chaque format est réellement celui annoncé.
        assert z.read("02_rapport_restitution.docx")[:4] == b"PK\x03\x04"
        assert z.read("03_rapport_restitution.pdf")[:5] == b"%PDF-"
        assert z.read("04_rapport_risques.pdf")[:5] == b"%PDF-"

        # CSV : en-tête « ; » + items du suivi (mêmes clés que l'endpoint).
        csv_txt = z.read("06_suivi_circularisation.csv").decode("utf-8")
        assert csv_txt.splitlines()[0] == "cle_item;libelle;statut;date_relance;note"
        assert "analytique:7011" in csv_txt
        assert f"piece:OBL-36-ETII-{suffixe}" in csv_txt
        assert ";en_attente;" in csv_txt

        # Contrôle de clôture lisible.
        ctrl = z.read("07_controle_cloture.txt").decode("utf-8")
        assert "CONTRÔLE QUALITÉ DE PRÉ-CLÔTURE" in ctrl
        assert "Clôture recommandée" in ctrl

        # Une seule exécution et aucun risque : 08 et 09 sont omises.
        assert "08_comparatif_executions.txt" not in noms
        assert "09_provision_risques.txt" not in noms

        # Sommaire : identification + pièces incluses + omissions motivées.
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert "DOSSIER DE TRAVAIL" in sommaire
        assert "PM Demande FICTIF" in sommaire
        assert "2025" in sommaire
        assert "PIÈCES INCLUSES (7)" in sommaire
        assert "PIÈCES OMISES (2)" in sommaire
        assert "08_comparatif_executions.txt : OMISE" in sommaire
        assert "09_provision_risques.txt : OMISE" in sommaire
        assert "Généré le" in sommaire


def test_comparatif_et_provision_inclus_quand_disponibles(session):
    """Deux exécutions + un risque ouvert probable → pièces 08 et 09."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)
    # Seconde exécution (règles différentes → nouveaux/disparus).
    _conclusions_non_verifiables(
        session,
        tid,
        mid,
        [(f"TVA-05-DED-{suffixe}", "Déductions de TVA à justifier")],
    )
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

    resp = _telecharger_zip(client, h, mid)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "08_comparatif_executions.txt" in noms
        assert "09_provision_risques.txt" in noms

        comparatif = z.read("08_comparatif_executions.txt").decode("utf-8")
        assert "COMPARATIF DES DEUX DERNIÈRES EXÉCUTIONS" in comparatif
        assert f"TVA-05-DED-{suffixe}" in comparatif
        assert f"OBL-36-ETII-{suffixe}" in comparatif
        assert "RÈGLES DISPARUES" in comparatif
        assert "Synthèse :" in comparatif
        assert "Delta montant des anomalies" in comparatif

        provision = z.read("09_provision_risques.txt").decode("utf-8")
        assert "PROVISION POUR RISQUES FISCAUX" in provision
        assert "TVA collectée non déclarée" in provision
        assert "Total provision proposée" in provision
        assert "DEBIT  6911" in provision
        assert "CREDIT 1918" in provision

        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert "PIÈCES INCLUSES (9)" in sommaire
        assert "PIÈCES OMISES (0)" in sommaire


def test_piece_en_echec_est_omise_et_notee(session, monkeypatch):
    """Un rendu qui lève n'empêche jamais l'archive : pièce omise + motif."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    def _boom(*_a, **_k):
        raise RuntimeError("panne simulée du rendu Word")

    monkeypatch.setattr(archive_mission, "rendre_rapport_docx", _boom)
    resp = _telecharger_zip(client, h, mid)
    assert resp.content[:4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "02_rapport_restitution.docx" not in noms
        # Les autres pièces restent produites (indépendance des pièces).
        assert "03_rapport_restitution.pdf" in noms
        assert "06_suivi_circularisation.csv" in noms
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert (
            "02_rapport_restitution.docx : OMISE — panne simulée du rendu Word"
            in sommaire
        )
        # Panne Word + 08 (une seule exécution) + 09 (aucun risque).
        assert "PIÈCES OMISES (3)" in sommaire


def test_dossier_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)

    h_b, _ = _connexion(client, email_b)
    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip", headers=h_b)
    assert resp.status_code == 404
    # Le tenant légitime, lui, télécharge normalement.
    assert _telecharger_zip(client, h_a, mid).status_code == 200


def test_dossier_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip")
    assert resp.status_code in (401, 403)
