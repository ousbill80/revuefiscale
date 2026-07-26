"""Gardes de création de mission — exercice, doublon, engagement, objectifs."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.missions import (
    ErreurMission,
    ErreurMissionDoublon,
    creer_mission,
)

PROFIL = {"regime": "reel", "forme_juridique": "SA"}


def test_exercice_futur_refuse():
    futur = date.today().year + 1
    with pytest.raises(ErreurMission) as exc:
        creer_mission(
            None,  # refusé avant tout accès session
            1,
            contribuable_id=1,
            exercice=futur,
            profil=dict(PROFIL),
        )
    assert "n'est pas encore clos" in str(exc.value)


def test_exercice_courant_passe_la_garde_exercice():
    # L'exercice courant / ancien (même prescrit) ne déclenche PAS la garde —
    # l'appel échoue plus loin (session None), preuve que la borne est passée.
    for exercice in (date.today().year, 2005):
        with pytest.raises(Exception) as exc:
            creer_mission(
                None,
                1,
                contribuable_id=1,
                exercice=exercice,
                profil=dict(PROFIL),
            )
        assert "n'est pas encore clos" not in str(exc.value)


# --- Tests DB (mêmes prérequis que tests/isolation) -----------------------


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _tenant_et_contribuable(session, denomination="SOCIETE GARDE SA"):
    sa = pytest.importorskip("sqlalchemy")
    text = sa.text
    from backend.billing.service import creer_tenant
    from backend.editorial.publication import creer_version_brouillon, publier_version
    from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

    deja = session.execute(
        text(
            "SELECT id FROM version_referentiel "
            "WHERE publiee_le IS NOT NULL LIMIT 1"
        )
    ).scalar_one_or_none()
    if deja is None:
        lib = f"v-garde-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="test gardes")
        publier_version(session, lib, "test@2aaz.ci")

    email = _email("garde")
    r = creer_tenant(
        session,
        denomination="Cabinet Gardes",
        type_tenant="cabinet",
        palier="essentiel",
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, :d) RETURNING id"
            ),
            {"t": r.tenant_id, "d": denomination},
        ).scalar_one()
    effacer_contexte_tenant(session)
    return r, int(cid), email


@pytest.mark.db
def test_doublon_mission_meme_client_exercice_refuse(session):
    r, cid, _ = _tenant_et_contribuable(session)
    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=cid,
        exercice=2025,
        profil=dict(PROFIL),
        type_engagement="preventive",
    )
    assert mid > 0

    with pytest.raises(ErreurMissionDoublon) as exc:
        creer_mission(
            session,
            r.tenant_id,
            contribuable_id=cid,
            exercice=2025,
            profil=dict(PROFIL),
            type_engagement="preventive",
        )
    msg = str(exc.value)
    assert "existe déjà" in msg
    assert "SOCIETE GARDE SA" in msg
    assert f"#{mid}" in msg
    assert "2025" in msg


@pytest.mark.db
def test_doublon_autorise_apres_cloture(session):
    from backend.plateforme.missions import changer_statut_mission

    r, cid, _ = _tenant_et_contribuable(session)
    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=cid,
        exercice=2024,
        profil=dict(PROFIL),
        type_engagement="cac",
    )
    changer_statut_mission(session, r.tenant_id, mid, "en_cours")
    changer_statut_mission(session, r.tenant_id, mid, "cloturee")
    mid2 = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=cid,
        exercice=2024,
        profil=dict(PROFIL),
        type_engagement="cac",
    )
    assert mid2 > mid

    # Réouverture de la clôturée bloquée tant que la nouvelle est active.
    with pytest.raises(ErreurMission):
        changer_statut_mission(session, r.tenant_id, mid, "en_cours")


@pytest.mark.db
def test_api_type_engagement_requis_400(session):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.plateforme.auth import emettre_jeton

    r, cid, email = _tenant_et_contribuable(session)
    session.commit()
    jeton = emettre_jeton(
        utilisateur_id=r.utilisateur_id,
        tenant_id=r.tenant_id,
        role="admin",
        email=email,
    )
    client = TestClient(app)
    resp = client.post(
        "/api/v1/missions",
        headers={"Authorization": f"Bearer {jeton}"},
        json={
            "contribuable_id": cid,
            "exercice": 2025,
            "profil": dict(PROFIL),
        },
    )
    assert resp.status_code == 400
    assert "type d'engagement" in resp.json()["detail"].lower()


@pytest.mark.db
def test_objectifs_vides_filtres(session):
    from backend.plateforme.missions import lire_mission

    r, cid, _ = _tenant_et_contribuable(session)
    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=cid,
        exercice=2023,
        profil=dict(PROFIL),
        type_engagement="due_diligence",
        objectifs=[
            {"libelle": "  Sécuriser la TVA  "},
            {"libelle": "   "},
            {"libelle": ""},
        ],
    )
    detail = lire_mission(session, r.tenant_id, mid)
    libelles = [o["libelle"] for o in detail["objectifs"]]
    assert libelles == ["Sécuriser la TVA"]
