"""Points ouverts (legacy lecture) + conclusion statut/piece — domaine abonné."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BALANCE_JSON = FIXTURES / "balance_fictif_commerce.json"


def _skip_si_migration_absente(session, table: str, mig: str) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = :t"
        ),
        {"t": table},
    ).scalar_one()
    if n == 0:
        pytest.skip(f"migration {mig} non appliquée — lancez make migrate")


def _colonne_existe(session, table: str, colonne: str) -> bool:
    return bool(
        session.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": colonne},
        ).scalar_one_or_none()
    )


def _creer_contribuable(client: TestClient, h: dict, *, ncc: str) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM {ncc}",
            "ncc": ncc,
            "forme": "pm",
            "rccm": f"RCCM-{ncc}",
            "dfe": f"DFE-{ncc}",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    return int(c.json()["id"])


def _mission_avec_conclusion(client: TestClient, h: dict, cid: int) -> tuple[int, int]:
    """Mission + balance + exécution → (mission_id, conclusion_id)."""
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "type_engagement": "preventive",
            "perimetre_impots": ["BIC", "TVA"],
        },
    )
    assert m.status_code == 200, m.text
    mid = int(m.json()["id"])

    if not BALANCE_JSON.is_file():
        pytest.skip(f"fixture absente : {BALANCE_JSON}")
    corps = json.loads(BALANCE_JSON.read_text(encoding="utf-8"))
    bal = client.post(f"/api/v1/missions/{mid}/balance", headers=h, json=corps)
    assert bal.status_code == 200, bal.text

    ex = client.post(
        f"/api/v1/missions/{mid}/executer",
        headers=h,
        json={"reponses": {}},
    )
    assert ex.status_code == 200, ex.text

    rest = client.get(f"/api/v1/missions/{mid}/restitution", headers=h)
    assert rest.status_code == 200, rest.text
    conclusions = rest.json().get("conclusions") or []
    avec_id = [c for c in conclusions if c.get("id") is not None]
    if not avec_id:
        pytest.skip("aucune conclusion déclenchée — référentiel trop vide pour ce test")
    return mid, int(avec_id[0]["id"])


@pytest.fixture
def client_cabinet(session):
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-po-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="points")
        publier_version(session, lib, "po@test.ci")

    email = f"po.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab PO {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}
    return client, h


def test_point_ouvert_ecritures_gone_lecture_ok(session, client_cabinet):
    """R4+ : POST/PATCH → 410 ; GET legacy + filtre encore OK."""
    _skip_si_migration_absente(session, "point_ouvert", "017")
    client, h = client_cabinet

    cid = _creer_contribuable(client, h, ncc="CI-PO-0001")

    refuse_post = client.post(
        "/api/v1/points-ouverts",
        headers=h,
        json={
            "contribuable_id": cid,
            "texte": "Revoir justification dons N-1",
            "statut": "ouvert",
        },
    )
    assert refuse_post.status_code == 410, refuse_post.text
    detail = str(refuse_post.json().get("detail", "")).lower()
    assert "risques" in detail

    moi = client.get("/api/v1/moi", headers=h)
    assert moi.status_code == 200, moi.text
    tenant_id = int(moi.json()["tenant_id"])

    # Ligne historique via SQL (table conservée, RLS) pour tester la lecture
    with contexte_tenant(session, tenant_id):
        pid = session.execute(
            text(
                "INSERT INTO point_ouvert (tenant_id, contribuable_id, texte, statut) "
                "VALUES (:t, :c, 'legacy lecture', 'ouvert') RETURNING id"
            ),
            {"t": tenant_id, "c": cid},
        ).scalar_one()
    session.commit()

    liste = client.get(
        f"/api/v1/points-ouverts?contribuable_id={cid}&statut=ouvert",
        headers=h,
    )
    assert liste.status_code == 200
    assert any(p["id"] == pid for p in liste.json())

    refuse_patch = client.patch(
        f"/api/v1/points-ouverts/{pid}",
        headers=h,
        json={"statut": "clos"},
    )
    assert refuse_patch.status_code == 410, refuse_patch.text
    assert "risques" in str(refuse_patch.json().get("detail", "")).lower()

    encore_ouverts = client.get(
        f"/api/v1/points-ouverts?contribuable_id={cid}&statut=ouvert",
        headers=h,
    )
    assert encore_ouverts.status_code == 200
    assert any(p["id"] == pid for p in encore_ouverts.json())


def test_point_ouvert_rls_inter_cabinets(session):
    _skip_si_migration_absente(session, "point_ouvert", "017")

    a = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab A PO', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    b = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab B PO', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()

    with contexte_tenant(session, a):
        ca = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client A') RETURNING id"
            ),
            {"t": a},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO point_ouvert (tenant_id, contribuable_id, texte) "
                "VALUES (:t, :c, 'secret A')"
            ),
            {"t": a, "c": ca},
        )

    with contexte_tenant(session, b):
        n = session.execute(text("SELECT count(*) FROM point_ouvert")).scalar_one()
        assert n == 0

    effacer_contexte_tenant(session)
    n0 = session.execute(text("SELECT count(*) FROM point_ouvert")).scalar_one()
    assert n0 == 0


def test_conclusion_colonnes_016(session):
    if not _colonne_existe(session, "conclusion", "statut"):
        pytest.skip("migration 016 non appliquée — lancez make migrate")
    if not _colonne_existe(session, "conclusion", "piece_mission_id"):
        pytest.skip("migration 016 non appliquée — lancez make migrate")


def test_patch_conclusion_statut_et_piece(session, client_cabinet, tmp_path, monkeypatch):
    """PATCH statut + piece_mission_id (happy path) ; pièce d'autre mission rejetée."""
    if not _colonne_existe(session, "conclusion", "statut"):
        pytest.skip("migration 016 non appliquée — lancez make migrate")
    _skip_si_migration_absente(session, "piece_mission", "010")

    monkeypatch.setenv("PIECES_DIR", str(tmp_path / "pieces"))
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))

    client, h = client_cabinet
    cid = _creer_contribuable(client, h, ncc=f"CI-PC-{uuid.uuid4().hex[:6]}")
    mid, conclusion_id = _mission_avec_conclusion(client, h, cid)

    # Mission B (même contribuable) pour une pièce « mauvaise mission »
    m2 = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m2.status_code == 200, m2.text
    mid_autre = int(m2.json()["id"])

    piece_ok = client.post(
        f"/api/v1/missions/{mid}/pieces",
        headers=h,
        files={"fichier": ("dossier-ok.txt", b"piece bonne mission", "text/plain")},
        data={"type_piece": "autre"},
    )
    assert piece_ok.status_code == 201, piece_ok.text
    pid_ok = int(piece_ok.json()["id"])

    piece_bad = client.post(
        f"/api/v1/missions/{mid_autre}/pieces",
        headers=h,
        files={"fichier": ("dossier-bad.txt", b"piece autre mission", "text/plain")},
        data={"type_piece": "autre"},
    )
    assert piece_bad.status_code == 201, piece_bad.text
    pid_bad = int(piece_bad.json()["id"])

    happy = client.patch(
        f"/api/v1/missions/{mid}/conclusions/{conclusion_id}",
        headers=h,
        json={"statut": "conforme", "piece_mission_id": pid_ok},
    )
    assert happy.status_code == 200, happy.text
    body = happy.json()
    assert body["statut"] == "conforme"
    assert body["piece_mission_id"] == pid_ok
    assert body["amendee_par"]

    refuse = client.patch(
        f"/api/v1/missions/{mid}/conclusions/{conclusion_id}",
        headers=h,
        json={"piece_mission_id": pid_bad},
    )
    assert refuse.status_code == 400, refuse.text
    detail = str(refuse.json().get("detail", "")).lower()
    assert "appartient" in detail

    # Statut inchangé après rejet pièce — piece_ok conservée
    check = client.patch(
        f"/api/v1/missions/{mid}/conclusions/{conclusion_id}",
        headers=h,
        json={"statut": "anomalie"},
    )
    assert check.status_code == 200, check.text
    assert check.json()["statut"] == "anomalie"
    assert check.json()["piece_mission_id"] == pid_ok


def test_point_ouvert_depuis_conclusion(session, client_cabinet):
    """POST depuis conclusion → 410 (bascule registre /risques)."""
    _skip_si_migration_absente(session, "point_ouvert", "017")
    if not _colonne_existe(session, "conclusion", "statut"):
        pytest.skip("migration 016 non appliquée — lancez make migrate")

    client, h = client_cabinet
    cid = _creer_contribuable(client, h, ncc=f"CI-POC-{uuid.uuid4().hex[:6]}")
    mid, conclusion_id = _mission_avec_conclusion(client, h, cid)

    created = client.post(
        f"/api/v1/missions/{mid}/conclusions/{conclusion_id}/point-ouvert",
        headers=h,
    )
    assert created.status_code == 410, created.text
    assert "risques" in str(created.json().get("detail", "")).lower()

    introuvable = client.post(
        f"/api/v1/missions/{mid}/conclusions/999999001/point-ouvert",
        headers=h,
    )
    assert introuvable.status_code == 410, introuvable.text
