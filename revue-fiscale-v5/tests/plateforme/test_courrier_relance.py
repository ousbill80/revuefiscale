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


# ── Courrier de relance texte (.txt) — tests purs, date figée ────────


def test_construire_courrier_contenu_et_numerotation():
    from backend.plateforme.courrier_relance import (
        MENTION_COURRIER_TXT,
        construire_courrier,
    )

    courrier = construire_courrier(
        {
            "cabinet": "Cabinet Fiduciaire Exemple",
            "contribuable": "PM Demande FICTIF",
            "exercice": 2025,
            "aujourd_hui": date(2026, 7, 27),
            "items": [
                {"libelle": "Balance générale N", "date_relance": "2026-07-10"},
                {"libelle": "Grand livre auxiliaire", "date_relance": None},
            ],
        }
    )
    assert "CABINET FIDUCIAIRE EXEMPLE" in courrier
    assert "Le 27/07/2026" in courrier
    assert "À l'attention de la Direction de PM Demande FICTIF" in courrier
    assert (
        "Objet : Relance — pièces et renseignements en attente "
        "(mission 2025)" in courrier
    )
    # 1er courrier (aucune relance passée) : objet SANS rang de relance.
    assert "2e relance" not in courrier
    assert "Nous vous avons déjà relancés" not in courrier
    assert "déjà relancé" not in courrier
    assert "1. Balance générale N (demande du 10/07/2026)" in courrier
    assert "2. Grand livre auxiliaire" in courrier
    assert "2. Grand livre auxiliaire (demande" not in courrier
    # Clôture « sous quinzaine » : 27/07/2026 + 15 jours = 11/08/2026.
    assert "sous quinzaine" in courrier
    assert "au plus tard le 11/08/2026" in courrier
    assert "15 jours calendaires" in courrier
    assert "Madame, Monsieur," in courrier
    assert "salutations distinguées" in courrier
    assert MENTION_COURRIER_TXT in courrier
    # Déterminisme : même contexte → même courrier.
    assert courrier == construire_courrier(
        {
            "cabinet": "Cabinet Fiduciaire Exemple",
            "contribuable": "PM Demande FICTIF",
            "exercice": 2025,
            "aujourd_hui": date(2026, 7, 27),
            "items": [
                {"libelle": "Balance générale N", "date_relance": "2026-07-10"},
                {"libelle": "Grand livre auxiliaire", "date_relance": None},
            ],
        }
    )


def test_construire_courrier_zero_item():
    from backend.plateforme.courrier_relance import construire_courrier

    courrier = construire_courrier(
        {
            "cabinet": "Cabinet X",
            "contribuable": "Client Y",
            "exercice": 2025,
            "aujourd_hui": date(2026, 1, 5),
            "items": [],
        }
    )
    assert "Le 05/01/2026" in courrier
    assert "aucune relance n'est nécessaire" in courrier
    assert "1." not in courrier
    # Sans item ouvert : pas de délai « sous quinzaine » ni de rang.
    assert "sous quinzaine" not in courrier
    assert "2e relance" not in courrier


def test_construire_courrier_deuxieme_relance():
    """nb_relances=1 partout → objet « 2e relance », rappel daté, suffixes."""
    from backend.plateforme.courrier_relance import construire_courrier

    courrier = construire_courrier(
        {
            "cabinet": "Cabinet X",
            "contribuable": "Client Y",
            "exercice": 2025,
            "aujourd_hui": date(2026, 7, 27),
            "items": [
                {
                    "libelle": "Balance générale N",
                    "nb_relances": 1,
                    "derniere_relance_le": "2026-07-10",
                },
                {
                    "libelle": "Grand livre auxiliaire",
                    "nb_relances": 1,
                    "derniere_relance_le": "2026-07-15",
                },
            ],
        }
    )
    assert (
        "Objet : 2e relance — pièces et renseignements en attente "
        "(mission 2025)" in courrier
    )
    # Rappel de la DERNIÈRE relance = max des derniere_relance_le.
    assert "Nous vous avons déjà relancés le 15/07/2026." in courrier
    assert "1. Balance générale N (déjà relancé 1 fois)" in courrier
    assert "2. Grand livre auxiliaire (déjà relancé 1 fois)" in courrier
    # Clôture « sous quinzaine » toujours présente.
    assert "au plus tard le 11/08/2026" in courrier
    # Ton courtois : pas d'objet « Relance — » de premier rang.
    assert "Objet : Relance —" not in courrier


def test_construire_courrier_nb_relances_heterogenes():
    """Rang global = max(nb_relances) + 1, suffixe seulement si relancé."""
    from backend.plateforme.courrier_relance import construire_courrier

    courrier = construire_courrier(
        {
            "cabinet": "Cabinet X",
            "contribuable": "Client Y",
            "exercice": 2025,
            "aujourd_hui": date(2026, 7, 27),
            "items": [
                {"libelle": "Attestation de régularité", "nb_relances": 0},
                {
                    "libelle": "Balance générale N",
                    "nb_relances": 2,
                    "derniere_relance_le": "2026-07-20",
                },
                {
                    "libelle": "Grand livre auxiliaire",
                    "nb_relances": 1,
                    "derniere_relance_le": "2026-07-05",
                },
            ],
        }
    )
    assert "Objet : 3e relance —" in courrier
    assert "Nous vous avons déjà relancés le 20/07/2026." in courrier
    # Suffixe DISCRET par item, uniquement s'il a déjà été relancé.
    assert "1. Attestation de régularité" in courrier
    assert "1. Attestation de régularité (déjà relancé" not in courrier
    assert "2. Balance générale N (déjà relancé 2 fois)" in courrier
    assert "3. Grand livre auxiliaire (déjà relancé 1 fois)" in courrier


# ── Courrier texte — tests API ───────────────────────────────────────


def test_courrier_relance_json_items_ouverts(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    # Un item soldé (reçu) — il ne doit PAS figurer au courrier.
    r1 = client.patch(
        f"/api/v1/missions/{mid}/suivi-renseignements/analytique:5121",
        headers=h,
        json={"statut": "recu"},
    )
    assert r1.status_code == 200, r1.text

    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance", headers=h)
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["mission_id"] == mid
    assert corps["contribuable"] == "PM Demande FICTIF"
    assert str(corps["exercice"]) == "2025"
    assert corps["nb_items_ouverts"] == 3  # 4 items dont 1 reçu
    assert "à relire et adapter par le fiscaliste" in corps["note"]
    courrier = corps["courrier"]
    assert (
        "Objet : Relance — pièces et renseignements en attente "
        "(mission 2025)" in courrier
    )
    assert "1. " in courrier and "3. " in courrier
    assert "Justification des amortissements" in courrier
    assert "5121" not in courrier


def test_courrier_relance_txt_headers(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    suffixe = uuid.uuid4().hex[:6].upper()
    _preparer(session, tid, mid, suffixe)

    resp = client.get(
        f"/api/v1/missions/{mid}/courrier-relance.txt", headers=h
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in resp.headers["content-type"]
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert f'filename="courrier-relance-mission-{mid}.txt"' in dispo
    texte = resp.content.decode("utf-8")
    assert "Relance — pièces et renseignements en attente" in texte
    assert "PM Demande FICTIF" in texte


def test_courrier_relance_txt_zero_item_ouvert(session):
    """Mission sans item : courrier quand même généré, sans relance."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/courrier-relance", headers=h)
    assert resp.status_code == 200, resp.text
    corps = resp.json()
    assert corps["nb_items_ouverts"] == 0
    assert "aucune relance n'est nécessaire" in corps["courrier"]


def test_courrier_relance_txt_cross_tenant_404(session):
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
        client.get(
            f"/api/v1/missions/{mid}/courrier-relance", headers=h_b
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/missions/{mid}/courrier-relance.txt", headers=h_b
        ).status_code
        == 404
    )
    # Le tenant légitime, lui, lit normalement.
    assert (
        client.get(
            f"/api/v1/missions/{mid}/courrier-relance.txt", headers=h_a
        ).status_code
        == 200
    )


def test_courrier_relance_txt_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(
        f"/api/v1/missions/{mid}/courrier-relance"
    ).status_code in (401, 403)
    assert client.get(
        f"/api/v1/missions/{mid}/courrier-relance.txt"
    ).status_code in (401, 403)
