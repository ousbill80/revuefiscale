"""Actions à mettre en œuvre du cabinet — décisions « retenue » du plan."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.actions_cabinet import (
    PLAFOND_ITEMS,
    actions_retenues_cabinet,
    synthese_actions,
    trier_actions,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _item(
    exposition: str | None,
    client: str = "SA Alpha FICTIVE",
    mission_id: int = 1,
    cle_action: str = "risque:1",
) -> dict:
    return {
        "mission_id": mission_id,
        "client": client,
        "exercice": 2025,
        "cle_action": cle_action,
        "libelle_risque": "TVA déductible non justifiée",
        "impot": "TVA",
        "exposition": exposition,
        "risque_clos": False,
        "decision_note": None,
        "maj_le": None,
    }


def test_tri_exposition_decroissante_puis_client_puis_mission():
    items = [
        _item(None, client="SARL Zêta FICTIVE", mission_id=9, cle_action="risque:9"),
        _item("500000", client="SARL Zêta FICTIVE", mission_id=8, cle_action="risque:8"),
        _item("2000000", client="SA Alpha FICTIVE", mission_id=2, cle_action="risque:2"),
        _item("500000", client="SA Alpha FICTIVE", mission_id=7, cle_action="risque:7"),
        _item("500000", client="SA Alpha FICTIVE", mission_id=3, cle_action="risque:3"),
    ]
    tries = trier_actions(items)
    assert [
        (i["exposition"], i["client"], i["mission_id"]) for i in tries
    ] == [
        ("2000000", "SA Alpha FICTIVE", 2),
        ("500000", "SA Alpha FICTIVE", 3),
        ("500000", "SA Alpha FICTIVE", 7),
        ("500000", "SARL Zêta FICTIVE", 8),
        # Exposition non chiffrée en queue.
        (None, "SARL Zêta FICTIVE", 9),
    ]


def test_synthese_actions():
    items = [
        _item("1500000", client="SA Alpha FICTIVE"),
        _item("250000.50", client="SA Alpha FICTIVE"),
        _item(None, client="SARL Bêta FICTIVE"),
    ]
    assert synthese_actions(items) == {
        "total": 3,
        "clients": 2,
        "exposition_totale": "1750000.50",
    }
    assert synthese_actions([]) == {
        "total": 0,
        "clients": 0,
        "exposition_totale": "0",
    }


def test_plafond_constant():
    # Le plafond limite la liste, pas la synthèse (calculée en amont).
    assert PLAFOND_ITEMS == 50


# ── Tests DB / API ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-actionscab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="actions-cabinet")
    publier_version(session, lib, "actionscab@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Actions {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission(
    session,
    tenant_id: int,
    denomination: str,
    statut: str = "en_cours",
    exercice: int = 2025,
) -> tuple[int, int]:
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
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": statut, "m": mid},
        )
    return int(mid), int(cid)


def _creer_risque(
    session,
    tenant_id: int,
    contribuable_id: int,
    *,
    montant: str | None = None,
    libelle: str | None = None,
) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                    "libelle, montant_estime, probabilite, statut, "
                    "exercice_origine) VALUES (:t, :c, 'TVA', :lib, :mt, "
                    "'possible', 'ouvert', 2025) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "lib": libelle or f"Risque cab {uuid.uuid4().hex[:6]}",
                    "mt": montant,
                },
            ).scalar_one()
        )


def _decider(session, tid: int, mid: int, rid: int, decision: str, note=None):
    from backend.plateforme.plan_actions import decider_action

    decider_action(session, tid, mid, f"risque:{rid}", decision, note=note)


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


def test_actions_cabinet_definition_et_tri(session):
    """Seules les « retenue » ressortent, tous clients, tri exposition."""
    tid, _email = _cabinet(session, "actionscab.def")
    mid_a, cid_a = _mission(session, tid, "SA Alpha FICTIVE")
    mid_z, cid_z = _mission(session, tid, "SARL Zêta FICTIVE")
    r_gros = _creer_risque(session, tid, cid_z, montant="3000000")
    r_petit = _creer_risque(session, tid, cid_a, montant="150000")
    r_sans = _creer_risque(session, tid, cid_a)
    r_fait = _creer_risque(session, tid, cid_a, montant="900000")
    r_ecarte = _creer_risque(session, tid, cid_z)
    _decider(session, tid, mid_z, r_gros, "retenue", note="à régulariser")
    _decider(session, tid, mid_a, r_petit, "retenue")
    _decider(session, tid, mid_a, r_sans, "retenue")
    _decider(session, tid, mid_a, r_fait, "faite")
    _decider(session, tid, mid_z, r_ecarte, "ecartee")
    session.commit()

    out = actions_retenues_cabinet(session, tid)
    assert out["total"] == 3
    # Tri : exposition décroissante, non chiffrée en queue.
    assert [i["cle_action"] for i in out["items"]] == [
        f"risque:{r_gros}",
        f"risque:{r_petit}",
        f"risque:{r_sans}",
    ]
    premier = out["items"][0]
    assert premier["mission_id"] == mid_z
    assert premier["client"] == "SARL Zêta FICTIVE"
    assert premier["exercice"] == 2025
    assert premier["impot"] == "TVA"
    assert premier["exposition"] == "3000000.00"
    assert premier["risque_clos"] is False
    assert premier["decision_note"] == "à régulariser"
    assert premier["maj_le"] is not None
    assert out["items"][2]["exposition"] is None
    assert out["synthese"] == {
        "total": 3,
        "clients": 2,
        "exposition_totale": "3150000.00",
    }
    assert "note" in out


def test_actions_cabinet_risque_clos_reste_liste(session):
    tid, _email = _cabinet(session, "actionscab.clos")
    mid, cid = _mission(session, tid, "PM Clos FICTIF")
    rid = _creer_risque(session, tid, cid, montant="2000000")
    _decider(session, tid, mid, rid, "retenue")
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE risque SET statut = 'resolu' WHERE id = :r"),
            {"r": rid},
        )
    session.commit()

    out = actions_retenues_cabinet(session, tid)
    assert out["total"] == 1
    assert out["items"][0]["cle_action"] == f"risque:{rid}"
    assert out["items"][0]["risque_clos"] is True
    # Le libellé du risque reste joint même clos.
    assert out["items"][0]["libelle_risque"].startswith("Risque cab")


def test_actions_cabinet_tenant_vide_et_plafond(session):
    tid, _email = _cabinet(session, "actionscab.vide")
    session.commit()
    out = actions_retenues_cabinet(session, tid)
    assert out["total"] == 0
    assert out["items"] == []
    assert out["synthese"]["exposition_totale"] == "0"
    # Le plafond limite la liste, pas le total ni la synthèse.
    assert PLAFOND_ITEMS == 50


def test_api_actions_cabinet(session):
    tid, email = _cabinet(session, "actionscab.api")
    mid, cid = _mission(session, tid, "PM API Actions FICTIF")
    rid = _creer_risque(session, tid, cid, montant="500000")
    _decider(session, tid, mid, rid, "retenue", note="provision à passer")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/actions-retenues", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["total"] == 1
    assert corps["items"][0]["mission_id"] == mid
    assert corps["items"][0]["cle_action"] == f"risque:{rid}"
    assert corps["items"][0]["client"] == "PM API Actions FICTIF"
    assert corps["items"][0]["exposition"] == "500000.00"
    assert corps["items"][0]["decision_note"] == "provision à passer"
    assert corps["synthese"] == {
        "total": 1,
        "clients": 1,
        "exposition_totale": "500000.00",
    }
    assert "note" in corps


def test_api_isolation_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "actionscab.a")
    mid_a, cid_a = _mission(session, tid_a, "PM Isolée FICTIF")
    rid_a = _creer_risque(session, tid_a, cid_a, montant="100000")
    _decider(session, tid_a, mid_a, rid_a, "retenue")
    _tid_b, email_b = _cabinet(session, "actionscab.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/actions-retenues", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # Le cabinet B ne voit pas les actions du cabinet A.
    assert corps["total"] == 0
    assert corps["items"] == []


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/actions-retenues")
    assert r.status_code == 401, r.text
