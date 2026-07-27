"""Relances à faire du cabinet — items du suivi de circularisation échus."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.plateforme.relances_cabinet import (
    PLAFOND_ITEMS,
    generer_csv,
    relances_cabinet,
    synthese_relances,
    trier_relances,
)

# ── Tests purs (sans DB, dates figées) ─────────────────────────────


def _item(
    date_relance: str,
    client: str = "SA Alpha FICTIVE",
    mission_id: int = 1,
    libelle: str = "Balance auxiliaire clients",
) -> dict:
    return {
        "mission_id": mission_id,
        "client": client,
        "exercice": 2025,
        "libelle": libelle,
        "date_relance": date_relance,
        "note": None,
    }


def test_tri_par_date_puis_client_puis_mission():
    items = [
        _item("2025-06-10", client="SARL Zêta FICTIVE", mission_id=9),
        _item("2025-06-01", client="SARL Zêta FICTIVE", mission_id=9),
        _item("2025-06-10", client="SA Alpha FICTIVE", mission_id=7),
        _item("2025-06-10", client="SA Alpha FICTIVE", mission_id=2),
    ]
    tries = trier_relances(items)
    assert [
        (i["date_relance"], i["client"], i["mission_id"]) for i in tries
    ] == [
        ("2025-06-01", "SARL Zêta FICTIVE", 9),
        ("2025-06-10", "SA Alpha FICTIVE", 2),
        ("2025-06-10", "SA Alpha FICTIVE", 7),
        ("2025-06-10", "SARL Zêta FICTIVE", 9),
    ]


def test_synthese_relances():
    items = [
        _item("2025-06-10", client="SA Alpha FICTIVE"),
        _item("2025-06-01", client="SA Alpha FICTIVE"),
        _item("2025-06-05", client="SARL Bêta FICTIVE"),
    ]
    assert synthese_relances(items) == {
        "total": 3,
        "clients": 2,
        "plus_ancienne": "2025-06-01",
    }
    assert synthese_relances([]) == {
        "total": 0,
        "clients": 0,
        "plus_ancienne": None,
    }


# ── Tests purs — export CSV ────────────────────────────────────────


def test_csv_entetes_et_lignes_dans_l_ordre_des_relances():
    relances = {
        "items": [
            _item("2025-06-01", client="SARL Zêta FICTIVE", mission_id=9),
            _item(
                "2025-06-10",
                client="SA Alpha FICTIVE",
                mission_id=2,
                libelle="Grand livre fournisseurs",
            ),
        ]
    }
    csv_txt = generer_csv(relances)
    lignes = csv_txt.splitlines()
    assert lignes[0] == "date_relance;client;mission;exercice;libelle"
    assert lignes[1] == (
        "2025-06-01;SARL Zêta FICTIVE;9;2025;Balance auxiliaire clients"
    )
    assert lignes[2] == (
        "2025-06-10;SA Alpha FICTIVE;2;2025;Grand livre fournisseurs"
    )
    # Ordre des relances conservé (le tri est fait en amont).
    assert [l.split(";")[0] for l in lignes[1:]] == ["2025-06-01", "2025-06-10"]


def test_csv_echappement_point_virgule_guillemets_retour_ligne():
    relances = {
        "items": [
            _item(
                "2025-06-01",
                client='SARL "Un; Deux" FICTIVE',
                libelle="Balance ; grand\nlivre",
            )
        ]
    }
    csv_txt = generer_csv(relances)
    # Valeurs à risque entre guillemets, guillemets internes doublés.
    assert '"SARL ""Un; Deux"" FICTIVE"' in csv_txt
    assert '"Balance ; grand\nlivre"' in csv_txt
    # Relecture par le module csv : les valeurs sont restituées intactes.
    import csv as _csv
    import io as _io

    lignes = list(_csv.reader(_io.StringIO(csv_txt), delimiter=";"))
    assert lignes[1][1] == 'SARL "Un; Deux" FICTIVE'
    assert lignes[1][4] == "Balance ; grand\nlivre"


def test_csv_vide_en_tete_seul():
    assert generer_csv({"items": []}) == (
        "date_relance;client;mission;exercice;libelle\n"
    )
    assert generer_csv({}) == (
        "date_relance;client;mission;exercice;libelle\n"
    )


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

    lib = f"v-relances-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="relances-cabinet")
    publier_version(session, lib, "relances@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Relances {email}",
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
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"s": statut, "m": mid},
        )
    return int(mid)


def _item_suivi(
    session,
    tenant_id: int,
    mission_id: int,
    libelle: str,
    statut: str = "en_attente",
    date_relance: date | None = None,
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                " date_relance) "
                "VALUES (:t, :m, :c, :l, :s, :d)"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "c": f"piece:{uuid.uuid4().hex[:10]}",
                "l": libelle,
                "s": statut,
                "d": date_relance,
            },
        )


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


def test_relances_definition_pilotage(session):
    """Seuls les items en_attente à date de relance échue ressortent."""
    tid, _email = _cabinet(session, "relances.def")
    jour = date(2025, 6, 15)
    mid = _mission(session, tid, "PM Relances FICTIF")
    # À relancer : date échue (hier) et jour même.
    _item_suivi(session, tid, mid, "Grand livre", date_relance=jour - timedelta(days=1))
    _item_suivi(session, tid, mid, "Balance", date_relance=jour)
    # Exclus : sans date, date future, statut reçu malgré date échue.
    _item_suivi(session, tid, mid, "FEC")
    _item_suivi(session, tid, mid, "Contrats", date_relance=jour + timedelta(days=1))
    _item_suivi(
        session, tid, mid, "Statuts", statut="recu",
        date_relance=jour - timedelta(days=10),
    )
    # Exclu : mission clôturée, même avec date échue.
    mid_close = _mission(session, tid, "PM Clôturée FICTIF", statut="cloturee")
    _item_suivi(
        session, tid, mid_close, "Baux", date_relance=jour - timedelta(days=5)
    )
    session.commit()

    r = relances_cabinet(session, tid, aujourd_hui=jour)
    assert r["aujourd_hui"] == "2025-06-15"
    assert r["total"] == 2
    assert [i["libelle"] for i in r["items"]] == ["Grand livre", "Balance"]
    assert all(i["mission_id"] == mid for i in r["items"])
    assert all(i["client"] == "PM Relances FICTIF" for i in r["items"])
    assert all(i["exercice"] == 2025 for i in r["items"])
    assert r["items"][0]["date_relance"] == "2025-06-14"
    assert r["synthese"] == {
        "total": 2,
        "clients": 1,
        "plus_ancienne": "2025-06-14",
    }
    assert "note" in r


def test_relances_tri_date_puis_client(session):
    tid, _email = _cabinet(session, "relances.tri")
    jour = date(2025, 6, 15)
    mid_z = _mission(session, tid, "SARL Zêta FICTIVE")
    mid_a = _mission(session, tid, "SA Alpha FICTIVE")
    _item_suivi(session, tid, mid_z, "Item Z ancien", date_relance=date(2025, 6, 1))
    _item_suivi(session, tid, mid_z, "Item Z récent", date_relance=date(2025, 6, 10))
    _item_suivi(session, tid, mid_a, "Item A", date_relance=date(2025, 6, 10))
    session.commit()

    r = relances_cabinet(session, tid, aujourd_hui=jour)
    assert [(i["date_relance"], i["client"]) for i in r["items"]] == [
        ("2025-06-01", "SARL Zêta FICTIVE"),
        ("2025-06-10", "SA Alpha FICTIVE"),
        ("2025-06-10", "SARL Zêta FICTIVE"),
    ]


def test_relances_tenant_vide_et_plafond(session):
    tid, _email = _cabinet(session, "relances.vide")
    session.commit()
    r = relances_cabinet(session, tid, aujourd_hui=date(2025, 6, 15))
    assert r["total"] == 0
    assert r["items"] == []
    # Le plafond limite la liste, pas le total.
    assert PLAFOND_ITEMS == 50


def test_api_relances_cabinet(session):
    tid, email = _cabinet(session, "relances.api")
    mid = _mission(session, tid, "PM API Relances FICTIF")
    _item_suivi(
        session, tid, mid, "Balance générale",
        date_relance=date.today() - timedelta(days=3),
    )
    _item_suivi(session, tid, mid, "Sans date")  # en_attente sans relance.
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/relances", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["aujourd_hui"] == date.today().isoformat()
    assert corps["total"] == 1
    assert corps["items"][0]["mission_id"] == mid
    assert corps["items"][0]["libelle"] == "Balance générale"
    assert corps["items"][0]["client"] == "PM API Relances FICTIF"
    assert corps["synthese"]["total"] == 1
    assert "note" in corps


def test_api_isolation_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "relances.a")
    mid_a = _mission(session, tid_a, "PM Isolée FICTIF")
    _item_suivi(
        session, tid_a, mid_a, "Item A",
        date_relance=date.today() - timedelta(days=1),
    )
    _tid_b, email_b = _cabinet(session, "relances.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/relances", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # Le cabinet B ne voit pas les relances du cabinet A.
    assert corps["total"] == 0
    assert corps["items"] == []


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/relances")
    assert r.status_code == 401, r.text


def test_api_relances_csv_export(session):
    tid, email = _cabinet(session, "relances.csv")
    mid = _mission(session, tid, "PM CSV Relances FICTIF")
    _item_suivi(
        session, tid, mid, "Balance générale",
        date_relance=date.today() - timedelta(days=3),
    )
    _item_suivi(
        session, tid, mid, "Grand livre",
        date_relance=date.today() - timedelta(days=1),
    )
    _item_suivi(session, tid, mid, "Sans date")  # exclu (pas de relance).
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/relances.csv", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "charset=utf-8" in r.headers["content-type"]
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="relances.csv"'
    )
    # BOM UTF-8 en tête (ouverture directe dans Excel FR).
    assert r.content[:3] == b"\xef\xbb\xbf"
    corps = r.content.decode("utf-8-sig")
    lignes = corps.splitlines()
    assert lignes[0] == "date_relance;client;mission;exercice;libelle"
    assert len(lignes) == 3
    assert all(l.split(";")[2] == str(mid) for l in lignes[1:])
    assert all("PM CSV Relances FICTIF" in l for l in lignes[1:])
    # Tri par date de relance croissante (même tri que le JSON).
    assert lignes[1].endswith("Balance générale")
    assert lignes[2].endswith("Grand livre")

    # Cohérence avec le JSON : autant de lignes que d'items.
    rj = client.get("/api/v1/cabinet/relances", headers=h)
    assert rj.status_code == 200
    assert len(lignes) - 1 == len(rj.json()["items"])


def test_api_relances_csv_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/relances.csv")
    assert r.status_code == 401, r.text
