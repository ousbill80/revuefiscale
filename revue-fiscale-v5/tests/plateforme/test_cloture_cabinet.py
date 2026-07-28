"""Préparation à la clôture des missions du cabinet — vue transverse."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.cloture_cabinet import (
    ENTETE_CLOTURE_CSV,
    PLAFOND_MISSIONS,
    PLAFOND_POINTS_ATTENTION,
    generer_csv,
    preparation_cloture_cabinet,
    synthese_bilan,
    synthese_preparation,
    trier_preparation,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _point(libelle: str, statut: str) -> dict:
    return {"code": "x", "libelle": libelle, "statut": statut}


def test_synthese_bilan_compteurs_et_prete():
    bilan = {
        "points": [
            _point("Note de synthèse disponible", "ok"),
            _point("Aucun temps saisi", "attention"),
            _point("2 risque(s) ouvert(s)", "attention"),
        ]
    }
    assert synthese_bilan(bilan) == {
        "nb_ok": 1,
        "nb_attention": 2,
        "prete": False,
        "points_attention": [
            "Aucun temps saisi",
            "2 risque(s) ouvert(s)",
        ],
    }


def test_synthese_bilan_prete_sans_attention():
    bilan = {"points": [_point("Tout va bien", "ok")]}
    out = synthese_bilan(bilan)
    assert out["prete"] is True
    assert out["nb_attention"] == 0
    assert out["points_attention"] == []


def test_synthese_bilan_plafond_points_attention():
    bilan = {
        "points": [_point(f"Point {i}", "attention") for i in range(8)]
    }
    out = synthese_bilan(bilan)
    # Le compteur reste exact, seule la liste des libellés est plafonnée.
    assert out["nb_attention"] == 8
    assert len(out["points_attention"]) == PLAFOND_POINTS_ATTENTION
    assert out["points_attention"][0] == "Point 0"
    assert PLAFOND_POINTS_ATTENTION == 5


def _item(
    prete: bool,
    nb_attention: int,
    client: str = "SA Alpha FICTIVE",
    mission_id: int = 1,
) -> dict:
    return {
        "mission_id": mission_id,
        "client": client,
        "exercice": 2025,
        "nb_ok": 7 - nb_attention,
        "nb_attention": nb_attention,
        "prete": prete,
        "points_attention": [],
    }


def test_tri_pretes_d_abord_puis_attention_croissant():
    items = [
        _item(False, 5, client="SARL Zêta FICTIVE", mission_id=5),
        _item(False, 1, client="SA Bêta FICTIVE", mission_id=3),
        _item(True, 0, client="SARL Zêta FICTIVE", mission_id=9),
        _item(False, 1, client="SA Alpha FICTIVE", mission_id=2),
        _item(True, 0, client="SA Alpha FICTIVE", mission_id=7),
    ]
    tries = trier_preparation(items)
    assert [(i["prete"], i["nb_attention"], i["mission_id"]) for i in tries] == [
        # Prêtes d'abord (ordre client), puis nb_attention croissant.
        (True, 0, 7),
        (True, 0, 9),
        (False, 1, 2),
        (False, 1, 3),
        (False, 5, 5),
    ]


def test_synthese_preparation_compteurs():
    items = [_item(True, 0), _item(False, 2), _item(False, 3)]
    assert synthese_preparation(items) == {
        "en_cours": 3,
        "pretes": 1,
        "a_completer": 2,
    }
    assert synthese_preparation([]) == {
        "en_cours": 0,
        "pretes": 0,
        "a_completer": 0,
    }


def test_plafond_missions_constant():
    # Vue de pilotage bornée — chaque mission déclenche un bilan complet.
    assert PLAFOND_MISSIONS == 20


def test_generer_csv_entete_et_lignes():
    preparation = {
        "items": [
            {
                **_item(True, 0, client="SA Alpha FICTIVE", mission_id=7),
            },
            {
                **_item(
                    False, 2, client="SARL Zêta FICTIVE", mission_id=9
                ),
                "points_attention": [
                    "Aucun temps saisi",
                    "2 risque(s) ouvert(s)",
                ],
            },
        ]
    }
    lignes = generer_csv(preparation).splitlines()
    assert lignes[0] == ";".join(ENTETE_CLOTURE_CSV)
    assert lignes[0] == (
        "client;exercice;statut_preparation;nb_ok;nb_attention;"
        "points_attention"
    )
    assert lignes[1] == "SA Alpha FICTIVE;2025;Prête;7;0;"
    # Points d'attention joints par « | » dans une seule cellule.
    assert lignes[2] == (
        "SARL Zêta FICTIVE;2025;À compléter;5;2;"
        "Aucun temps saisi | 2 risque(s) ouvert(s)"
    )


def test_generer_csv_vide_et_valeurs_manquantes():
    # Liste vide → en-tête seul.
    assert generer_csv({"items": []}).splitlines() == [
        ";".join(ENTETE_CLOTURE_CSV)
    ]
    assert generer_csv({}).splitlines() == [";".join(ENTETE_CLOTURE_CSV)]
    # Valeurs absentes → cellules vides, statut « À compléter » par défaut.
    lignes = generer_csv({"items": [{}]}).splitlines()
    assert lignes[1] == ";;À compléter;;;"


def test_generer_csv_echappe_le_point_virgule():
    preparation = {
        "items": [
            {
                **_item(False, 1, client='SA "Point;Virgule" FICTIVE'),
                "points_attention": ["Libellé ; à échapper"],
            }
        ]
    }
    lignes = generer_csv(preparation).splitlines()
    # Le stdlib entoure de guillemets (doublés) la valeur contenant « ; ».
    assert '"SA ""Point;Virgule"" FICTIVE"' in lignes[1]
    assert '"Libellé ; à échapper"' in lignes[1]


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
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-cloturecab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="cloture-cabinet")
    publier_version(session, lib, "cloturecab@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Clôture {email}",
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


def test_preparation_missions_en_cours_seules(session):
    """Seules les missions « en_cours » ressortent, avec leur bilan."""
    tid, _email = _cabinet(session, "cloturecab.def")
    mid_ec, _cid = _mission(session, tid, "SA En Cours FICTIVE")
    _mission(session, tid, "SA Cadrage FICTIVE", statut="cadrage")
    _mission(session, tid, "SA Clôturée FICTIVE", statut="cloturee")
    session.commit()

    out = preparation_cloture_cabinet(session, tid)
    assert out["synthese"]["en_cours"] == 1
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert item["mission_id"] == mid_ec
    assert item["client"] == "SA En Cours FICTIVE"
    assert item["exercice"] == 2025
    # Mission fraîche : rien n'est fait — tous les points en attention.
    assert item["prete"] is False
    assert item["nb_ok"] >= 0
    assert item["nb_attention"] >= 1
    assert item["nb_attention"] + item["nb_ok"] >= 7
    assert 1 <= len(item["points_attention"]) <= 5
    assert all(isinstance(l, str) and l for l in item["points_attention"])
    assert out["synthese"] == {
        "en_cours": 1,
        "pretes": 0,
        "a_completer": 1,
    }
    assert "note" in out


def test_preparation_tenant_vide(session):
    tid, _email = _cabinet(session, "cloturecab.vide")
    session.commit()
    out = preparation_cloture_cabinet(session, tid)
    assert out["items"] == []
    assert out["synthese"] == {
        "en_cours": 0,
        "pretes": 0,
        "a_completer": 0,
    }
    assert "note" in out


def test_preparation_tri_attention_croissant(session):
    """Deux missions en cours : la plus proche de la clôture d'abord."""
    tid, _email = _cabinet(session, "cloturecab.tri")
    mid_nue, _cid = _mission(session, tid, "SARL Zêta Nue FICTIVE")
    mid_avancee, _cid2 = _mission(session, tid, "SA Avancée FICTIVE")
    # La mission « avancée » a du temps saisi → un point d'attention de
    # moins que la mission nue.
    from datetime import date

    from backend.plateforme.temps_mission import saisir_temps

    saisir_temps(
        session,
        tid,
        mid_avancee,
        collaborateur="associe@test.ci",
        phase="controles",
        date_jour=date(2025, 6, 1),
        heures="2.5",
    )
    session.commit()

    out = preparation_cloture_cabinet(session, tid)
    assert [i["mission_id"] for i in out["items"]] == [mid_avancee, mid_nue]
    assert (
        out["items"][0]["nb_attention"] < out["items"][1]["nb_attention"]
    )


def test_api_preparation_cloture(session):
    tid, email = _cabinet(session, "cloturecab.api")
    mid, _cid = _mission(session, tid, "PM API Clôture FICTIF")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/preparation-cloture", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["synthese"]["en_cours"] == 1
    assert corps["synthese"]["a_completer"] == 1
    assert corps["items"][0]["mission_id"] == mid
    assert corps["items"][0]["client"] == "PM API Clôture FICTIF"
    assert corps["items"][0]["prete"] is False
    assert isinstance(corps["items"][0]["points_attention"], list)
    assert "note" in corps


def test_api_isolation_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "cloturecab.a")
    _mission(session, tid_a, "PM Isolée Clôture FICTIF")
    _tid_b, email_b = _cabinet(session, "cloturecab.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/preparation-cloture", headers=h)
    assert r.status_code == 200, r.text
    # Le cabinet B ne voit pas les missions du cabinet A.
    assert r.json()["items"] == []
    assert r.json()["synthese"]["en_cours"] == 0


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/preparation-cloture")
    assert r.status_code == 401, r.text


def test_api_preparation_cloture_csv(session):
    from datetime import date

    tid, email = _cabinet(session, "cloturecab.csv")
    _mission(session, tid, "PM CSV Clôture FICTIF")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/preparation-cloture.csv", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert (
        f"preparation-cloture-{date.today().isoformat()}.csv"
        in r.headers["content-disposition"]
    )
    # BOM UTF-8 en tête pour l'ouverture directe dans Excel.
    assert r.text.startswith("\ufeff")
    lignes = r.text.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(ENTETE_CLOTURE_CSV)
    # Une ligne pour la mission en cours, « À compléter » (mission nue).
    assert len(lignes) == 2
    assert lignes[1].startswith("PM CSV Clôture FICTIF;2025;À compléter;")


def test_api_preparation_cloture_csv_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/preparation-cloture.csv")
    assert r.status_code == 401, r.text
