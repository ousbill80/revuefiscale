"""POST /missions/{id}/source-depuis-annexe — réutilisation pièce data room, RLS."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BALANCE_CSV = FIXTURES / "balance_demo.csv"


def _skip_si_piece_mission_absente(session) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'piece_mission'"
        )
    ).scalar_one()
    if n == 0:
        pytest.skip("migration 010 non appliquée — lancez make migrate")


def _monter_stockage_pieces(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIECES_DIR", str(tmp_path / "pieces"))
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))


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


def _creer_mission(client: TestClient, h: dict, cid: int) -> int:
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


def _deposer_balance_annexe(client: TestClient, h: dict, mid: int) -> int:
    if not BALANCE_CSV.is_file():
        pytest.skip(f"fixture absente : {BALANCE_CSV}")
    contenu = BALANCE_CSV.read_bytes()
    dep = client.post(
        f"/api/v1/missions/{mid}/pieces",
        headers=h,
        files={"fichier": ("balance_demo.csv", contenu, "text/csv")},
        data={"type_piece": "balance"},
    )
    assert dep.status_code == 201, dep.text
    body = dep.json()
    assert body["role"] == "annexe"
    assert body["type_piece"] == "balance"
    return int(body["id"])


@pytest.fixture
def client_cabinet(session):
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    _skip_si_piece_mission_absente(session)

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-sda-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="source-depuis-annexe")
        publier_version(session, lib, "sda@test.ci")

    email = f"sda.{uuid.uuid4().hex[:8]}@demo.local"
    prov = provisionner_cabinet(
        session,
        denomination=f"Cab SDA {email}",
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
    body = login.json()
    h = {"Authorization": f"Bearer {body['jeton']}"}
    return client, h, prov.tenant_id, email


def test_source_depuis_annexe_designe_source_active(
    session, client_cabinet, tmp_path, monkeypatch
):
    """Pièce balance déjà en data room → source active + soldes fiabilisés."""
    _monter_stockage_pieces(tmp_path, monkeypatch)
    client, h, tid, _email = client_cabinet

    cid = _creer_contribuable(client, h, ncc=f"CI-SDA-{uuid.uuid4().hex[:6]}")
    mid = _creer_mission(client, h, cid)
    piece_id = _deposer_balance_annexe(client, h, mid)

    resp = client.post(
        f"/api/v1/missions/{mid}/source-depuis-annexe",
        headers=h,
        json={"piece_id": piece_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rapport"]["statut"] == "ok"
    assert body["source_precedente_degradee"] is False
    assert body["piece"] is not None
    assert body["piece"]["role"] == "source_active"
    assert body["piece"]["type_piece"] == "balance"
    assert body["piece"]["nom_fichier"] == "balance_demo.csv"

    with contexte_tenant(session, tid):
        n_soldes = session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mid},
        ).scalar_one()
    effacer_contexte_tenant(session)
    assert int(n_soldes) >= 1


def test_source_depuis_annexe_rls_inter_cabinets(
    session, client_cabinet, tmp_path, monkeypatch
):
    """Un cabinet ne peut pas réutiliser la pièce d'un autre cabinet."""
    _monter_stockage_pieces(tmp_path, monkeypatch)
    client_a, h_a, tid_a, email_a = client_cabinet

    cid_a = _creer_contribuable(client_a, h_a, ncc=f"CI-SDA-A-{uuid.uuid4().hex[:4]}")
    mid_a = _creer_mission(client_a, h_a, cid_a)
    piece_a = _deposer_balance_annexe(client_a, h_a, mid_a)

    from backend.main import app
    from backend.plateforme.provisionnement import provisionner_cabinet

    email_b = f"sda.b.{uuid.uuid4().hex[:8]}@demo.local"
    prov_b = provisionner_cabinet(
        session,
        denomination=f"Cab SDA B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client_b = TestClient(app)
    login_b = client_b.post(
        "/api/v1/auth/connexion",
        json={"email": email_b, "mot_de_passe": "admin-admin1"},
    )
    assert login_b.status_code == 200, login_b.text
    h_b = {"Authorization": f"Bearer {login_b.json()['jeton']}"}

    cid_b = _creer_contribuable(client_b, h_b, ncc=f"CI-SDA-B-{uuid.uuid4().hex[:4]}")
    mid_b = _creer_mission(client_b, h_b, cid_b)

    # Pièce du cabinet A sur mission du cabinet B → refusée
    cross = client_b.post(
        f"/api/v1/missions/{mid_b}/source-depuis-annexe",
        headers=h_b,
        json={"piece_id": piece_a},
    )
    assert cross.status_code == 400, cross.text
    assert "introuvable" in cross.json()["detail"].lower()

    # Mission du cabinet A depuis le cabinet B → 404 (RLS mission)
    foreign = client_b.post(
        f"/api/v1/missions/{mid_a}/source-depuis-annexe",
        headers=h_b,
        json={"piece_id": piece_a},
    )
    assert foreign.status_code == 404, foreign.text

    # Cabinet A conserve l'accès à sa propre pièce
    ok = client_a.post(
        f"/api/v1/missions/{mid_a}/source-depuis-annexe",
        headers=h_a,
        json={"piece_id": piece_a},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["rapport"]["statut"] == "ok"

    # Vérification RLS : cabinet B ne voit pas la pièce A en SQL
    with contexte_tenant(session, prov_b.tenant_id):
        visible = session.execute(
            text("SELECT id FROM piece_mission WHERE id = :p"),
            {"p": piece_a},
        ).scalar_one_or_none()
    effacer_contexte_tenant(session)
    assert visible is None

    with contexte_tenant(session, tid_a):
        visible_a = session.execute(
            text("SELECT id FROM piece_mission WHERE id = :p"),
            {"p": piece_a},
        ).scalar_one_or_none()
    effacer_contexte_tenant(session)
    assert int(visible_a) == piece_a
