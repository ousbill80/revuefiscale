"""Lettre de mission .docx : contenu, en-têtes HTTP et cloisonnement tenant."""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.main import app  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-lettre-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="lettre-mission")
    publier_version(session, lib, "lettre@test.ci")


def _cabinet(session):
    email = f"lettre.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Lettre {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    return email


def _connexion(client: TestClient, email: str) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['jeton']}"}


def _mission_cadree(client: TestClient, h: dict[str, str]) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM Lettre FICTIF",
            "ncc": "CI-LETTRE-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-LETTRE",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan Plateau",
        },
    )
    assert c.status_code == 200, c.text
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": c.json()["id"],
            "type_engagement": "preventive",
            "perimetre_impots": ["BIC", "TVA"],
            "exclusions_declarees": "Douanes exclues du périmètre.",
            "seuil_signification": 500000,
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


def _xml_document(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_lettre_mission_docx_contenu(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/lettre-mission.docx", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    dispo = resp.headers["content-disposition"]
    assert "lettre_mission_PM_LETTRE_FICTIF_2025.docx" in dispo
    assert resp.content[:4] == b"PK\x03\x04"

    xml = _xml_document(resp.content)
    # Type d'engagement (libellé du cadrage) présent dans le document.
    assert "Revue préventive" in xml
    # Périmètre coché + exclusions déclarées + mention normes.
    assert "Taxe sur la valeur ajoutée" in xml
    assert "Douanes exclues du périmètre." in xml
    assert "ne constitue pas un audit ni une certification" in xml
    # Seuil renseigné → section présente ; champs manquants jamais inventés.
    assert "Seuil de signification" in xml
    assert "[à compléter]" in xml


def test_lettre_mission_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a = _connexion(client, email_a)
    mid = _mission_cadree(client, h_a)

    h_b = _connexion(client, email_b)
    resp = client.get(f"/api/v1/missions/{mid}/lettre-mission.docx", headers=h_b)
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Lettre de mission IMPRIMABLE (JSON) — GET /missions/{id}/lettre
# ═══════════════════════════════════════════════════════════════════

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.lettre_mission import (  # noqa: E402
    BLOCS_LETTRE,
    MENTION_LU_APPROUVE,
    MENTION_NOTE_LETTRE,
    TEXTE_HONORAIRES_A_CONVENIR,
    TEXTE_HONORAIRES_CONVENUS,
    assembler_lettre,
)

_IDENTITE_TEST = {
    "mission_id": 7,
    "exercice": 2025,
    "statut": "cadrage",
    "cabinet": "Cabinet Test",
    "contribuable": "PM Test FICTIF",
    "ncc": "CI-0001",
    "regime": "reel",
    "honoraires": None,
}


def test_assembler_lettre_cles_stables():
    lettre = assembler_lettre(
        _IDENTITE_TEST, [], genere_le="2026-07-28T10:00:00+00:00"
    )
    for cle in BLOCS_LETTRE:
        assert cle in lettre
    assert lettre["identite"]["cabinet"] == "Cabinet Test"
    assert lettre["perimetre"]["regime"] == "reel"
    assert lettre["perimetre"]["obligations"] == []
    assert lettre["genere_le"] == "2026-07-28T10:00:00+00:00"
    assert lettre["note"] == MENTION_NOTE_LETTRE
    assert "responsable de sa lettre de mission" in lettre["note"]


def test_assembler_lettre_deduplication_obligations():
    # L'échéancier répète chaque obligation (mensuelle : 12 lignes) —
    # la lettre ne cite chaque couple (impôt, obligation) qu'une fois,
    # SANS les dates.
    echeances = [
        {
            "impot": "TVA",
            "obligation": "Déclaration et paiement de la TVA du mois",
            "periode": f"m{i} 2025",
            "date_limite": f"2025-{i:02d}-15",
        }
        for i in range(1, 13)
    ] + [
        {
            "impot": "Patente",
            "obligation": "Déclaration et paiement de la contribution des patentes",
            "periode": "exercice 2025",
            "date_limite": "2025-03-15",
        },
        {
            "impot": "TVA",
            "obligation": "Déclaration et paiement de la TVA du mois",
            "periode": "déc. 2025",
            "date_limite": "2026-01-15",
        },
    ]
    lettre = assembler_lettre(_IDENTITE_TEST, echeances)
    obligations = lettre["perimetre"]["obligations"]
    assert len(obligations) == 2
    assert obligations[0] == {
        "impot": "TVA",
        "obligation": "Déclaration et paiement de la TVA du mois",
    }
    assert obligations[1]["impot"] == "Patente"
    # Aucune date dans la lettre (document contractuel, pas calendrier).
    assert all("date_limite" not in o and "periode" not in o for o in obligations)


def test_assembler_lettre_textes_standard_presents():
    lettre = assembler_lettre(_IDENTITE_TEST, [])
    assert "revue fiscale consultative" in lettre["objet"]
    assert "ne constitue pas un audit ni une certification" in lettre["limites"]
    assert "seul décideur" in lettre["limites"]
    assert "pratique déclarative usuelle" in lettre["perimetre"]["texte"]
    assert "s'engage" in lettre["obligations_reciproques"]
    assert "secret professionnel" in lettre["confidentialite"]
    # Signatures : deux cadres, cabinet et client.
    sig = lettre["signatures"]
    assert sig["cabinet"]["titre"] == "Pour le Cabinet"
    assert sig["cabinet"]["denomination"] == "Cabinet Test"
    assert sig["client"]["denomination"] == "PM Test FICTIF"
    assert sig["mention"] == MENTION_LU_APPROUVE


def test_assembler_lettre_honoraires_convenus_ou_a_convenir():
    sans = assembler_lettre(_IDENTITE_TEST, [])
    assert sans["honoraires"]["montant"] is None
    assert sans["honoraires"]["texte"] == TEXTE_HONORAIRES_A_CONVENIR

    avec = assembler_lettre(
        {**_IDENTITE_TEST, "honoraires": "2500000.00"}, []
    )
    assert avec["honoraires"]["montant"] == "2500000.00"
    assert avec["honoraires"]["texte"] == TEXTE_HONORAIRES_CONVENUS


# ── API (DB) ───────────────────────────────────────────────────────


def test_api_lettre_imprimable_blocs(session):
    _assurer_version(session)
    email = f"lettre.{uuid.uuid4().hex[:8]}@demo.local"
    prov = provisionner_cabinet(
        session,
        denomination=f"Cab Lettre {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission_cadree(client, h)

    r = client.get(f"/api/v1/missions/{mid}/lettre", headers=h)
    assert r.status_code == 200, r.text
    lettre = r.json()

    for cle in BLOCS_LETTRE:
        assert cle in lettre

    ident = lettre["identite"]
    assert ident["mission_id"] == mid
    assert ident["exercice"] == 2025
    assert ident["contribuable"] == "PM Lettre FICTIF"
    assert ident["cabinet"].startswith("Cab Lettre")
    assert ident["regime"] == "reel"

    # Obligations du régime réel, dédupliquées (une ligne par couple
    # impôt/obligation malgré les 12 échéances mensuelles), sans dates.
    obligations = lettre["perimetre"]["obligations"]
    couples = [(o["impot"], o["obligation"]) for o in obligations]
    assert len(couples) == len(set(couples))
    impots = {o["impot"] for o in obligations}
    assert "TVA" in impots
    assert "Patente" in impots
    assert all("date_limite" not in o for o in obligations)

    # Textes standard et signatures présents.
    assert "ne constitue pas un audit ni une certification" in lettre["limites"]
    assert lettre["signatures"]["client"]["denomination"] == "PM Lettre FICTIF"
    assert lettre["honoraires"]["montant"] is None
    assert lettre["note"] == MENTION_NOTE_LETTRE

    # Consultation journalisée (pattern dossier de synthèse).
    with contexte_tenant(session, prov.tenant_id):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m AND action = "
                "'consultation_lettre_mission'"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(n) >= 1


def test_api_lettre_imprimable_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a = _connexion(client, email_a)
    mid = _mission_cadree(client, h_a)

    h_b = _connexion(client, email_b)
    r = client.get(f"/api/v1/missions/{mid}/lettre", headers=h_b)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_lettre_imprimable_401_sans_jeton(session):
    r = TestClient(app).get("/api/v1/missions/1/lettre")
    assert r.status_code == 401, r.text
