"""« Mon tableau de bord » — priorités du jour du collaborateur."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.plateforme.mon_tableau import (
    MENTION_NOTE,
    synthese_mon_tableau,
    trier_missions,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_trier_missions_en_cours_puis_exercice_puis_client():
    missions = [
        {"mission_id": 1, "client": "SA Zeta", "exercice": 2025,
         "statut": "cadrage"},
        {"mission_id": 2, "client": "SA Beta", "exercice": 2024,
         "statut": "en_cours"},
        {"mission_id": 3, "client": "SA Alpha", "exercice": 2025,
         "statut": "en_cours"},
        {"mission_id": 4, "client": "SA Gamma", "exercice": 2025,
         "statut": "en_cours"},
    ]
    assert [m["mission_id"] for m in trier_missions(missions)] == [
        3,  # en_cours, exercice 2025, Alpha
        4,  # en_cours, exercice 2025, Gamma
        2,  # en_cours, exercice 2024
        1,  # cadrage en dernier
    ]
    assert trier_missions([]) == []


def test_trier_missions_stable_a_egalite():
    missions = [
        {"mission_id": 9, "client": "SA Même", "exercice": 2025,
         "statut": "en_cours"},
        {"mission_id": 5, "client": "SA Même", "exercice": 2025,
         "statut": "en_cours"},
    ]
    assert [m["mission_id"] for m in trier_missions(missions)] == [5, 9]


def test_synthese_mon_tableau_compteurs():
    missions = [{"mission_id": 1}, {"mission_id": 2}]
    points = [
        {"point_id": 1, "en_retard": True},
        {"point_id": 2, "en_retard": False},
        {"point_id": 3, "en_retard": True},
    ]
    echeances = [
        {"jours_restants": 3},
        {"jours_restants": 7},
        {"jours_restants": 20},
    ]
    assert synthese_mon_tableau(missions, points, echeances) == {
        "missions": 2,
        "points_a_faire": 3,
        "points_en_retard": 2,
        "echeances_30j": 3,
        "echeances_semaine": 2,
    }
    assert synthese_mon_tableau([], [], []) == {
        "missions": 0,
        "points_a_faire": 0,
        "points_en_retard": 0,
        "echeances_30j": 0,
        "echeances_semaine": 0,
    }
    assert "consultative" in MENTION_NOTE


# ── Tests DB / API ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import (  # noqa: E402
    contexte_tenant,
    effacer_contexte_tenant,
)
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-montab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="mon-tableau")
    publier_version(session, lib, "montab@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab MonTab {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _collaborateur(session, tenant_id: int) -> str:
    """Collaborateur actif dont le mot de passe est connu (connexion)."""
    from backend.plateforme.auth import hasher_mot_de_passe

    email = f"collab.{uuid.uuid4().hex[:8]}@demo.local"
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO utilisateur "
                "(tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'reviseur', :h, TRUE)"
            ),
            {
                "t": tenant_id,
                "e": email,
                "h": hasher_mot_de_passe("admin-admin1"),
            },
        )
    effacer_contexte_tenant(session)
    return email


def _mission(
    session,
    tenant_id: int,
    denomination: str,
    statut: str = "en_cours",
    exercice: int = 2025,
    responsable: str | None = None,
) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": denomination},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text(
                "UPDATE mission SET statut = :s, responsable_email = :r "
                "WHERE id = :m"
            ),
            {"s": statut, "r": responsable, "m": mid},
        )
    effacer_contexte_tenant(session)
    return int(mid)


def _client_connecte(email: str):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['jeton']}"}


def test_api_mon_tableau_voit_ses_missions_et_points(session):
    """Le collaborateur voit SA mission, ses points (retard) — pas celles
    des autres responsables ni les clôturées."""
    from backend.plateforme.points_convenus import creer_point_convenu

    tid, email_admin = _cabinet(session, "montab.moi")
    collab = _collaborateur(session, tid)
    mid = _mission(
        session, tid, "SA Mienne FICTIVE", responsable=collab
    )
    # Mission d'un AUTRE responsable — exclue.
    _mission(
        session,
        tid,
        "SA Autre FICTIVE",
        responsable=email_admin,
    )
    # Mission clôturée du collaborateur — exclue.
    _mission(
        session,
        tid,
        "SA Close FICTIVE",
        statut="cloturee",
        exercice=2023,
        responsable=collab,
    )
    hier = (date.today() - timedelta(days=1)).isoformat()
    creer_point_convenu(
        session, tid, mid, "Régulariser la TVA", "t@test.ci",
        date_cible=hier,
    )
    creer_point_convenu(
        session, tid, mid, "Fournir l'attestation", "t@test.ci"
    )
    session.commit()

    client, h = _client_connecte(collab)
    r = client.get("/api/v1/moi/tableau", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["email"] == collab
    assert [m["client"] for m in corps["missions"]] == ["SA Mienne FICTIVE"]
    assert corps["missions"][0]["statut"] == "en_cours"
    assert corps["missions"][0]["mission_id"] == mid
    libelles = {p["libelle"]: p for p in corps["points"]}
    assert set(libelles) == {
        "Régulariser la TVA",
        "Fournir l'attestation",
    }
    assert libelles["Régulariser la TVA"]["en_retard"] is True
    assert libelles["Fournir l'attestation"]["en_retard"] is False
    assert corps["synthese"]["missions"] == 1
    assert corps["synthese"]["points_a_faire"] == 2
    assert corps["synthese"]["points_en_retard"] == 1
    # Échéances : structure toujours présente (contenu dépend du jour).
    assert isinstance(corps["echeances"], list)
    assert corps["synthese"]["echeances_30j"] == len(corps["echeances"])
    for e in corps["echeances"]:
        assert e["mission_id"] == mid
        assert e["client"] == "SA Mienne FICTIVE"
    assert corps["note"]


def test_api_mon_tableau_sans_mission_affectee_listes_vides(session):
    tid, email_admin = _cabinet(session, "montab.vide")
    # Mission du tenant NON affectée à l'admin.
    _mission(session, tid, "SA Orpheline FICTIVE", responsable=None)
    session.commit()

    client, h = _client_connecte(email_admin)
    r = client.get("/api/v1/moi/tableau", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["missions"] == []
    assert corps["points"] == []
    assert corps["echeances"] == []
    assert corps["synthese"] == {
        "missions": 0,
        "points_a_faire": 0,
        "points_en_retard": 0,
        "echeances_30j": 0,
        "echeances_semaine": 0,
    }


def test_api_mon_tableau_tenant_isole(session):
    """L'utilisateur du tenant B ne voit pas la mission du tenant A,
    même si son email y figure comme responsable (RLS)."""
    tid_a, _email_a = _cabinet(session, "montab.a")
    tid_b, email_b = _cabinet(session, "montab.b")
    # Dans le tenant A, une mission « affectée » à l'email de B
    # (écriture directe — la route de A l'aurait refusée).
    _mission(session, tid_a, "SA Isolée FICTIVE", responsable=email_b)
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/moi/tableau", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["missions"] == []


def test_api_mon_tableau_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get("/api/v1/moi/tableau").status_code == 401
