"""Courrier d'envoi du rapport .docx : synthèse chiffrée, actions
retenues du plan d'actions, cloisonnement."""
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


def _risque(
    session,
    tenant_id: int,
    contribuable_id: int,
    libelle: str,
    *,
    impot: str = "TVA",
    montant: str | None = None,
    penalites: str | None = None,
) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                    "libelle, montant_estime, penalites_estimees, "
                    "probabilite, statut, exercice_origine) "
                    "VALUES (:t, :c, :imp, :lib, :mt, :pen, 'probable', "
                    "'ouvert', 2025) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "imp": impot,
                    "lib": libelle,
                    "mt": montant,
                    "pen": penalites,
                },
            ).scalar_one()
        )


def _decision(
    session,
    tenant_id: int,
    mission_id: int,
    risque_id: int,
    decision: str,
    note: str | None = None,
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO suivi_plan_actions "
                "(tenant_id, mission_id, cle_action, decision, note) "
                "VALUES (:t, :m, :c, :d, :n)"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": f"risque:{risque_id}",
                "d": decision,
                "n": note,
            },
        )


def _contribuable_id(session, tenant_id: int, mission_id: int) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text("SELECT contribuable_id FROM mission WHERE id = :m"),
                {"m": mission_id},
            ).scalar_one()
        )


# ── Fonctions pures : composition des lignes d'actions convenues ─────


def test_composer_lignes_actions_convenues_complet():
    from backend.plateforme.courrier_envoi_rapport import (
        composer_lignes_actions_convenues,
    )

    lignes = composer_lignes_actions_convenues(
        [
            {
                "libelle_risque": "TVA déduite sans facture",
                "impot": "tva",
                "exposition": "1500000",
                "decision_note": "Rectifier avant fin d'exercice",
            }
        ]
    )
    assert lignes == [
        "TVA déduite sans facture — impôt : TVA — "
        "exposition estimée : 1 500 000 FCFA — "
        "note : Rectifier avant fin d'exercice"
    ]


def test_composer_lignes_actions_convenues_champs_absents():
    """Sans impôt / exposition / note : seuls les champs connus figurent."""
    from backend.plateforme.courrier_envoi_rapport import (
        composer_lignes_actions_convenues,
    )

    lignes = composer_lignes_actions_convenues(
        [
            {
                "libelle_risque": "État intragroupe absent",
                "impot": "",
                "exposition": None,
                "decision_note": None,
            },
            # Risque purgé depuis la décision : libellé de repli.
            {"libelle_risque": "", "impot": "", "exposition": None},
        ]
    )
    assert lignes == [
        "État intragroupe absent",
        "Action retenue au plan d'actions",
    ]
    for ligne in lignes:
        assert "FCFA" not in ligne
        assert "note :" not in ligne


def test_composer_lignes_actions_convenues_vide():
    from backend.plateforme.courrier_envoi_rapport import (
        composer_lignes_actions_convenues,
    )

    assert composer_lignes_actions_convenues([]) == []


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
    # Aucune action retenue → pas de section « Actions convenues ».
    assert "Actions convenues à mettre en œuvre" not in xml


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
    assert "Actions convenues à mettre en œuvre" not in xml


def test_courrier_envoi_actions_retenues_listees(session):
    """Actions « retenue » de la mission listées ; écartées/faites exclues."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    cid = _contribuable_id(session, tid, mid)
    suffixe = uuid.uuid4().hex[:6]

    r_retenu = _risque(
        session,
        tid,
        cid,
        f"Amortissement excessif {suffixe}",
        impot="bic",
        montant="4000000",
        penalites="1000000",
    )
    r_ecarte = _risque(session, tid, cid, f"Risque écarté {suffixe}")
    r_fait = _risque(session, tid, cid, f"Risque déjà traité {suffixe}")
    _decision(
        session, tid, mid, r_retenu, "retenue",
        note="Déposer une déclaration rectificative",
    )
    _decision(session, tid, mid, r_ecarte, "ecartee")
    _decision(session, tid, mid, r_fait, "faite")
    session.commit()

    resp = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx", headers=h)
    assert resp.status_code == 200, resp.text
    xml = _xml_document(resp.content)
    assert "Actions convenues à mettre en œuvre" in xml
    # Action retenue : libellé, impôt, exposition (montant + pénalités), note.
    assert f"Amortissement excessif {suffixe}" in xml
    assert "impôt : BIC" in xml
    assert "exposition estimée : 5 000 000 FCFA" in xml
    assert "note : Déposer une déclaration rectificative" in xml
    # Formulation prudente : le client décide.
    assert "recommandations de notre cabinet" in xml
    assert "votre seule appréciation" in xml
    # Les décisions « écartée » et « faite » ne sont pas rappelées.
    assert f"Risque écarté {suffixe}" not in xml
    assert f"Risque déjà traité {suffixe}" not in xml


def test_courrier_envoi_action_retenue_sans_montant_ni_note(session):
    """Exposition non chiffrée et sans note : ligne réduite au libellé/impôt."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    cid = _contribuable_id(session, tid, mid)
    suffixe = uuid.uuid4().hex[:6]
    rid = _risque(session, tid, cid, f"Justificatif manquant {suffixe}")
    _decision(session, tid, mid, rid, "retenue")
    session.commit()

    resp = client.get(f"/api/v1/missions/{mid}/courrier-envoi.docx", headers=h)
    assert resp.status_code == 200, resp.text
    xml = _xml_document(resp.content)
    assert "Actions convenues à mettre en œuvre" in xml
    assert f"Justificatif manquant {suffixe}" in xml
    assert "impôt : TVA" in xml
    assert "exposition estimée" not in xml
    assert "note :" not in xml


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
