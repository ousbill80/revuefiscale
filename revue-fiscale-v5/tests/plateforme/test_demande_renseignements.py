"""Demande de renseignements .docx : sections, numérotation, cloisonnement."""
from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-demande-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="demande-renseignements")
    publier_version(session, lib, "demande@test.ci")


def _cabinet(session):
    email = f"demande.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Demande {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    return email


def _connexion(client: TestClient, email: str) -> tuple[dict[str, str], int]:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return (
        {"Authorization": f"Bearer {login.json()['jeton']}"},
        int(login.json()["tenant_id"]),
    )


def _mission(client: TestClient, h: dict[str, str]) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM Demande FICTIF",
            "ncc": "CI-DEM-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-DEM",
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
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


def _version_brouillon_test(session) -> int:
    """Version NON publiée dédiée aux règles de test.

    Jamais chargée par le moteur (les missions pointent la dernière version
    publiée) : les règles insérées ici ne polluent pas les autres tests.
    """
    from backend.editorial.publication import creer_version_brouillon

    return int(
        creer_version_brouillon(
            session,
            f"v-demande-regles-{uuid.uuid4().hex[:8]}",
            note="regles de test demande-renseignements",
        )
    )


def _creer_regle_version(session, vr: int, regle_id: str, libelle: str) -> int:
    session.execute(
        text(
            "INSERT INTO regle (identifiant, impot, libelle) "
            "VALUES (:i, 'BIC', :l)"
        ),
        {"i": regle_id, "l": libelle},
    )
    return int(
        session.execute(
            text(
                "INSERT INTO regle_version (regle_id, version_referentiel_id, "
                "reference_article, reference_source, millesime, date_effet, "
                "nature, condition_declenchement, expression_resultat, "
                "niveau_risque) "
                "VALUES (:r, :v, 'art. test', 'test', 2025, '2025-01-01', "
                "'reintegration', 'vrai', '0', 'moyen') RETURNING id"
            ),
            {"r": regle_id, "v": vr},
        ).scalar_one()
    )


def _conclusions_non_verifiables(
    session, tenant_id: int, mission_id: int, regles: list[tuple[str, str]]
) -> None:
    """Une exécution + une conclusion non_verifiable par (regle_id, libellé)."""
    vr = _version_brouillon_test(session)
    rvs = [_creer_regle_version(session, vr, rid, lib) for rid, lib in regles]
    with contexte_tenant(session, tenant_id):
        eid = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test@demande') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        for rv in rvs:
            session.execute(
                text(
                    "INSERT INTO conclusion (tenant_id, execution_id, "
                    "regle_version_id, niveau_risque, statut) "
                    "VALUES (:t, :e, :rv, 'moyen', 'non_verifiable')"
                ),
                {"t": tenant_id, "e": eid, "rv": rv},
            )
    session.commit()


def _commentaire_disponible(session, tenant_id: int, mission_id: int) -> None:
    contenu = {
        "resume": "Deux variations significatives relevées.",
        "explications": [
            {
                "poste": "7011",
                "hypothese_explicative": "Baisse d'activité possible.",
                "question_a_poser_au_client": (
                    "Pouvez-vous expliquer la baisse du chiffre d'affaires "
                    "sur le compte 7011 ?"
                ),
                "gravite": "haute",
            },
            {
                "poste": "5121",
                "hypothese_explicative": "Reclassement bancaire possible.",
                "question_a_poser_au_client": (
                    "Merci de justifier la variation du solde bancaire 5121 "
                    "(relevés au 31/12)."
                ),
                "gravite": "moyenne",
            },
        ],
        "alertes_coherence": [],
    }
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO commentaire_revue_analytique "
                "(tenant_id, mission_id, version, statut, contenu) "
                "VALUES (:t, :m, 1, 'disponible', CAST(:ct AS jsonb))"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "ct": json.dumps(contenu, ensure_ascii=False),
            },
        )
    session.commit()


def _xml_document(contenu: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return z.read("word/document.xml").decode("utf-8")


def test_demande_docx_sections_numerotation_regle_id(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)

    suffixe = uuid.uuid4().hex[:6].upper()
    regle_a = f"OBL-36-ETII-{suffixe}"
    regle_b = f"BIC-12-AMORT-{suffixe}"
    _conclusions_non_verifiables(
        session,
        tid,
        mid,
        [
            (regle_a, "État des transactions internationales intragroupes"),
            (regle_b, "Justification des amortissements dérogatoires"),
        ],
    )
    _commentaire_disponible(session, tid, mid)

    resp = client.get(
        f"/api/v1/missions/{mid}/demande-renseignements.docx", headers=h
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    dispo = resp.headers["content-disposition"]
    assert "attachment" in dispo
    assert "demande_renseignements_PM_DEMANDE_FICTIF_2025.docx" in dispo
    assert resp.content[:4] == b"PK\x03\x04"

    xml = _xml_document(resp.content)
    # Sections présentes.
    assert "Demande de renseignements et de documents" in xml
    assert "Questions issues de la revue analytique" in xml
    assert "Pièces et réponses attendues" in xml
    assert "Modalités de réponse" in xml
    # Questions numérotées avec poste et gravité.
    assert "1. Poste 7011 (gravité : haute)" in xml
    assert "2. Poste 5121 (gravité : moyenne)" in xml
    assert "baisse du chiffre d'affaires" in xml
    # Pièces : numérotation CONTINUE après les questions + regle_id + intitulé.
    assert f"3. [{regle_b}]" in xml  # tri par regle_id : BIC avant OBL
    assert f"4. [{regle_a}]" in xml
    assert "État des transactions internationales intragroupes" in xml
    # Modalités : délai indicatif 15 jours.
    assert "15 jours" in xml


def test_demande_sans_commentaire_section_analytique_omise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)

    regle = f"TVA-08-DED-{uuid.uuid4().hex[:6].upper()}"
    _conclusions_non_verifiables(
        session, tid, mid, [(regle, "Justificatifs de TVA déductible")]
    )

    resp = client.get(
        f"/api/v1/missions/{mid}/demande-renseignements.docx", headers=h
    )
    assert resp.status_code == 200, resp.text
    xml = _xml_document(resp.content)
    assert "Questions issues de la revue analytique" not in xml
    assert "Pièces et réponses attendues" in xml
    assert f"1. [{regle}]" in xml
    assert "Justificatifs de TVA déductible" in xml


def test_demande_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)

    h_b, _ = _connexion(client, email_b)
    resp = client.get(
        f"/api/v1/missions/{mid}/demande-renseignements.docx", headers=h_b
    )
    assert resp.status_code == 404


def test_demande_exige_authentification(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    resp = client.get(f"/api/v1/missions/{mid}/demande-renseignements.docx")
    assert resp.status_code in (401, 403)
