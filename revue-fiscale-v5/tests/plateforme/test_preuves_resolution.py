"""Registre des preuves de résolution — API, cloisonnement, contrôle de clôture.

Complète tests/plateforme/test_preuve_resolution.py (unitaires purs) :
ici on couvre les routes /api/v1/risques/{id}/preuves et surtout
l'intégration avec le point « pieces_justificatives » du contrôle de
pré-clôture : un risque « resolu » sans justificatif déposé passe en
« attention » ; après dépôt d'une preuve, le point repasse « ok ».
"""
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
)

PDF_MINIMAL = b"%PDF-1.4\n%preuve de test\n%%EOF\n"


def _risque(session, tenant_id: int, *, statut: str = "resolu") -> int:
    """Contribuable + risque créés en SQL brut, committés pour l'API."""
    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Preuves FICTIF', 'pm') RETURNING id"
            ),
            {"t": tenant_id},
        ).scalar_one()
        rid = session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, exercice_origine) "
                "VALUES (:t, :c, 'TVA', 'Risque preuves test', 100000, "
                ":st, 2025) RETURNING id"
            ),
            {"t": tenant_id, "c": cid, "st": statut},
        ).scalar_one()
    session.commit()
    return int(rid)


def _deposer(client: TestClient, h: dict[str, str], rid: int, *,
             nom: str = "quittance_dgi.pdf",
             brut: bytes = PDF_MINIMAL,
             content_type: str = "application/pdf"):
    return client.post(
        f"/api/v1/risques/{rid}/preuves",
        headers=h,
        files={"fichier": (nom, brut, content_type)},
    )


def test_depot_et_relecture(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    rid = _risque(session, tid)

    r = _deposer(client, h, rid)
    assert r.status_code == 201, r.text
    preuve = r.json()
    assert preuve["risque_id"] == rid
    assert preuve["nom_fichier"] == "quittance_dgi.pdf"
    assert preuve["format"] == "pdf"
    assert preuve["auteur"] == email
    # Verdict IA consultatif : toujours renseigné après dépôt
    # (« indisponible » si aucun fournisseur configuré en test).
    assert preuve["verdict_ia"] in {
        "probante", "insuffisante", "sans_rapport", "indisponible"
    }

    lu = client.get(f"/api/v1/risques/{rid}/preuves", headers=h)
    assert lu.status_code == 200, lu.text
    liste = lu.json()
    assert [p["id"] for p in liste] == [preuve["id"]]
    assert liste[0]["nom_fichier"] == "quittance_dgi.pdf"


def test_format_non_supporte_refuse(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    rid = _risque(session, tid)

    r = _deposer(
        client, h, rid,
        nom="preuve.exe", brut=b"MZ\x90\x00" * 8,
        content_type="application/octet-stream",
    )
    assert r.status_code == 400, r.text
    # Rien n'a été enregistré au registre.
    lu = client.get(f"/api/v1/risques/{rid}/preuves", headers=h)
    assert lu.status_code == 200 and lu.json() == []


def test_risque_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, tid_a = _connexion(client, email_a)
    h_b, _ = _connexion(client, email_b)
    rid = _risque(session, tid_a)

    assert _deposer(client, h_b, rid).status_code == 404
    assert client.get(
        f"/api/v1/risques/{rid}/preuves", headers=h_b
    ).status_code == 404
    # Le tenant légitime, lui, voit un registre vide (rien n'a fuité).
    lu = client.get(f"/api/v1/risques/{rid}/preuves", headers=h_a)
    assert lu.status_code == 200 and lu.json() == []


def test_sans_jeton_401():
    client = TestClient(app)
    assert client.get("/api/v1/risques/1/preuves").status_code == 401
    r = client.post(
        "/api/v1/risques/1/preuves",
        files={"fichier": ("p.pdf", PDF_MINIMAL, "application/pdf")},
    )
    assert r.status_code == 401


def test_controle_cloture_attention_puis_ok_apres_depot(session):
    """Le point pieces_justificatives s'active grâce au registre.

    Risque « resolu » sans preuve → attention ; après dépôt d'un
    justificatif, le même contrôle repasse « ok » sans autre action.
    """
    from backend.plateforme.controle_cloture import evaluer_cloture
    from backend.plateforme.preuve_resolution import enregistrer_preuve
    from tests.plateforme.test_controle_cloture import (
        _creer_conclusion,
        _creer_risque,
        _mission_en_cours,
        _points_par_code,
    )

    tid, mid, cid = _mission_en_cours(session)
    _creer_conclusion(session, tid, mid, statut="conforme")
    rid = _creer_risque(session, tid, cid, montant=250_000, statut="resolu")

    avant = _points_par_code(evaluer_cloture(session, tid, mid))
    assert avant["pieces_justificatives"]["statut"] == "attention"
    assert "sans preuve" in avant["pieces_justificatives"]["detail"]

    enregistrer_preuve(
        session,
        tid,
        rid,
        nom_fichier="declaration_rectificative.pdf",
        content_type="application/pdf",
        brut=PDF_MINIMAL,
        auteur="collab@test.ci",
    )

    apres = _points_par_code(evaluer_cloture(session, tid, mid))
    assert apres["pieces_justificatives"]["statut"] == "ok"
    assert "justificatif" in apres["pieces_justificatives"]["detail"]
