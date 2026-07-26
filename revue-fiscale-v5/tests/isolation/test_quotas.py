"""Tests S2 — quotas bloquants a la creation de mission."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.billing.service import creer_tenant  # noqa: E402
from backend.editorial.publication import (  # noqa: E402
    creer_version_brouillon,
    publier_version,
)
from backend.main import app  # noqa: E402
from backend.plateforme.auth import emettre_jeton  # noqa: E402
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant  # noqa: E402
from backend.plateforme.missions import QuotaEpuise, creer_mission  # noqa: E402
from backend.plateforme.quotas import lire_quota_periode  # noqa: E402


def _email(prefix: str) -> str:
    return f"{prefix}.{uuid.uuid4().hex[:10]}@example.ci"


def _assurer_version_publiee(session) -> None:
    row = session.execute(
        text(
            "SELECT id FROM version_referentiel "
            "WHERE publiee_le IS NOT NULL ORDER BY id DESC LIMIT 1"
        )
    ).scalar_one_or_none()
    if row is not None:
        return
    lib = f"v-quota-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="test quota")
    publier_version(session, lib, "test@2aaz.ci")


def test_quota_incremente_et_bloque(session):
    _assurer_version_publiee(session)
    email = _email("quota")
    r = creer_tenant(
        session,
        denomination="Cabinet Quota",
        type_tenant="cabinet",
        palier="essentiel",  # 5 missions
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Q') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        # Forcer quota a 1 pour tester vite
        session.execute(
            text(
                "UPDATE quota SET missions_incluses = 1, missions_utilisees = 0 "
                "WHERE tenant_id = :t"
            ),
            {"t": r.tenant_id},
        )
    effacer_contexte_tenant(session)

    mid = creer_mission(
        session,
        r.tenant_id,
        contribuable_id=int(cid),
        exercice=2025,
        profil={"regime": "reel", "forme_juridique": "SA"},
    )
    assert mid > 0

    with contexte_tenant(session, r.tenant_id):
        resume = lire_quota_periode(session, r.tenant_id)
        assert resume is not None
        assert resume.missions_utilisees == 1
        assert resume.bloque is True
        assert resume.alerte_80 is True
    effacer_contexte_tenant(session)

    with pytest.raises(QuotaEpuise):
        creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )


def test_api_mission_403_si_quota_epuise(session):
    _assurer_version_publiee(session)
    email = _email("apiq")
    r = creer_tenant(
        session,
        denomination="Cabinet API Quota",
        type_tenant="cabinet",
        palier="essentiel",
        email_admin=email,
        mot_de_passe_admin="secret12345",
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client API') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        session.execute(
            text(
                "UPDATE quota SET missions_incluses = 0, missions_utilisees = 0 "
                "WHERE tenant_id = :t"
            ),
            {"t": r.tenant_id},
        )
    effacer_contexte_tenant(session)
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
            "contribuable_id": int(cid),
            "type_engagement": "autre",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()
