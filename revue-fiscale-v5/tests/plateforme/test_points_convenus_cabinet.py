"""Points convenus en attente au niveau cabinet — vue transverse."""
from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from backend.plateforme.points_convenus_cabinet import (
    ENTETE_POINTS_CSV,
    PLAFOND_ITEMS,
    SEUIL_ANCIEN_JOURS,
    anciennete_jours,
    generer_csv,
    plafonner_points,
    points_convenus_cabinet,
    synthese_points_cabinet,
    trier_points,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_anciennete_jours_calcul():
    jour = date(2025, 6, 10)
    assert anciennete_jours(datetime(2025, 6, 5, 14, 30), jour) == 5
    assert anciennete_jours(date(2025, 6, 10), jour) == 0
    assert anciennete_jours("2025-05-01T09:00:00+00:00", jour) == 40
    assert anciennete_jours("2025-04-01", jour) == 70


def test_anciennete_jours_jamais_negative_et_defensive():
    jour = date(2025, 6, 10)
    # Création « future » (horloge décalée) → 0, jamais négatif.
    assert anciennete_jours(datetime(2025, 6, 15), jour) == 0
    # Valeur illisible → 0 (défensif, jamais bloquant).
    assert anciennete_jours("pas-une-date", jour) == 0
    assert anciennete_jours(None, jour) == 0


def _item(
    anciennete: int,
    client: str = "SA Alpha FICTIVE",
    point_id: int = 1,
    libelle: str = "Régulariser la TVA",
    statut_mission: str = "en_cours",
) -> dict:
    return {
        "client": client,
        "mission_id": 1,
        "exercice": 2025,
        "statut_mission": statut_mission,
        "point_id": point_id,
        "libelle": libelle,
        "anciennete_jours": anciennete,
        "cree_le": "2025-06-01T00:00:00+00:00",
    }


def test_tri_plus_ancien_puis_client_puis_id():
    items = [
        _item(5, client="SARL Zêta FICTIVE", point_id=9),
        _item(40, client="SARL Zêta FICTIVE", point_id=4),
        _item(40, client="SA Alpha FICTIVE", point_id=7),
        _item(40, client="SA Alpha FICTIVE", point_id=2),
    ]
    tries = trier_points(items)
    assert [(i["anciennete_jours"], i["client"], i["point_id"]) for i in tries] == [
        (40, "SA Alpha FICTIVE", 2),
        (40, "SA Alpha FICTIVE", 7),
        (40, "SARL Zêta FICTIVE", 4),
        (5, "SARL Zêta FICTIVE", 9),
    ]


def test_plafonner_points_coupe_les_plus_recents():
    items = trier_points(
        [_item(i, point_id=i) for i in range(PLAFOND_ITEMS + 20)]
    )
    out = plafonner_points(items)
    assert len(out) == PLAFOND_ITEMS
    assert PLAFOND_ITEMS == 100
    # Le plus ancien reste en tête ; seuls les plus récents sont coupés.
    assert out[0]["anciennete_jours"] == PLAFOND_ITEMS + 19
    assert out[-1]["anciennete_jours"] == 20


def test_synthese_compteurs():
    items = [
        _item(0),
        _item(30),  # Borne : 30 jours pile n'est PAS « ancien ».
        _item(31, client="SARL Zêta FICTIVE"),
        _item(90, client="SARL Zêta FICTIVE"),
    ]
    assert synthese_points_cabinet(items) == {
        "total": 4,
        "anciens_30j": 2,
        "clients": 2,
        "en_retard": 0,
    }
    assert synthese_points_cabinet([]) == {
        "total": 0,
        "anciens_30j": 0,
        "clients": 0,
        "en_retard": 0,
    }
    assert SEUIL_ANCIEN_JOURS == 30


def test_generer_csv_entete_et_ligne():
    vue = {"items": [_item(40, point_id=3)]}
    lignes = generer_csv(vue).splitlines()
    assert lignes[0] == ";".join(ENTETE_POINTS_CSV)
    assert lignes[0] == (
        "anciennete_jours;client;exercice;libelle;date_cible;"
        "statut_mission;cree_le"
    )
    assert lignes[1] == (
        "40;SA Alpha FICTIVE;2025;Régulariser la TVA;;en_cours;"
        "2025-06-01T00:00:00+00:00"
    )


def test_generer_csv_vide_et_valeurs_manquantes():
    # Liste vide → en-tête seul.
    assert generer_csv({"items": []}).splitlines() == [
        ";".join(ENTETE_POINTS_CSV)
    ]
    assert generer_csv({}).splitlines() == [";".join(ENTETE_POINTS_CSV)]
    # Valeurs absentes → cellules vides ; ancienneté 0 conservée.
    lignes = generer_csv({"items": [{"anciennete_jours": 0}]}).splitlines()
    assert lignes[1] == "0;;;;;;"


def test_generer_csv_echappe_le_point_virgule():
    vue = {
        "items": [
            _item(
                12,
                client='SA "Point;Virgule" FICTIVE',
                libelle="Régler la TVA ; puis l'ITS",
            )
        ]
    }
    lignes = generer_csv(vue).splitlines()
    # Le stdlib entoure de guillemets (doublés) la valeur contenant « ; ».
    assert '"SA ""Point;Virgule"" FICTIVE"' in lignes[1]
    assert "\"Régler la TVA ; puis l'ITS\"" in lignes[1]


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

    lib = f"v-pconvcab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="points-convenus-cabinet")
    publier_version(session, lib, "pconvcab@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab PConvCab {email}",
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


def test_lecture_points_a_faire_missions_eligibles(session):
    """Seuls les points « a_faire » des missions en_cours/cloturee."""
    from backend.plateforme.points_convenus import (
        changer_statut_point_convenu,
        creer_point_convenu,
    )

    tid, _email = _cabinet(session, "pconvcab.lect")
    mid = _mission(session, tid, "SA Suivi FICTIVE")
    mid_clot = _mission(
        session, tid, "SARL Clôturée FICTIVE", statut="cloturee"
    )
    creer_point_convenu(
        session, tid, mid, "Régulariser la TVA de mai", "t@test.ci"
    )
    fait = creer_point_convenu(
        session, tid, mid, "Point déjà traité", "t@test.ci"
    )
    changer_statut_point_convenu(
        session, tid, int(fait["point"]["id"]), "fait", "t@test.ci"
    )
    creer_point_convenu(
        session, tid, mid_clot, "Relancer l'attestation", "t@test.ci"
    )
    session.commit()

    out = points_convenus_cabinet(session, tid, date.today())
    assert out["aujourd_hui"] == date.today().isoformat()
    # Le point « fait » est exclu ; la mission clôturée reste suivie.
    assert {i["libelle"] for i in out["items"]} == {
        "Régulariser la TVA de mai",
        "Relancer l'attestation",
    }
    par_libelle = {i["libelle"]: i for i in out["items"]}
    item = par_libelle["Régulariser la TVA de mai"]
    assert item["client"] == "SA Suivi FICTIVE"
    assert item["mission_id"] == mid
    assert item["exercice"] == 2025
    assert item["statut_mission"] == "en_cours"
    assert item["anciennete_jours"] == 0
    assert item["cree_le"]
    assert par_libelle["Relancer l'attestation"]["statut_mission"] == (
        "cloturee"
    )
    assert out["synthese"] == {
        "total": 2,
        "anciens_30j": 0,
        "clients": 2,
        "en_retard": 0,
    }
    assert "note" in out


def test_lecture_anciennete_et_tri_plus_ancien_d_abord(session):
    from backend.plateforme.points_convenus import creer_point_convenu

    tid, _email = _cabinet(session, "pconvcab.tri")
    mid = _mission(session, tid, "SA Ancienneté FICTIVE")
    ancien = creer_point_convenu(
        session, tid, mid, "Point ancien", "t@test.ci"
    )
    creer_point_convenu(session, tid, mid, "Point récent", "t@test.ci")
    # Vieillit artificiellement le premier point (45 jours).
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "UPDATE point_convenu "
                "SET cree_le = now() - interval '45 days' WHERE id = :p"
            ),
            {"p": int(ancien["point"]["id"])},
        )
    session.commit()

    out = points_convenus_cabinet(session, tid, date.today())
    assert [i["libelle"] for i in out["items"]] == [
        "Point ancien",
        "Point récent",
    ]
    assert out["items"][0]["anciennete_jours"] == 45
    assert out["synthese"] == {
        "total": 2,
        "anciens_30j": 1,
        "clients": 1,
        "en_retard": 0,
    }


def test_lecture_tenant_vide(session):
    tid, _email = _cabinet(session, "pconvcab.vide")
    session.commit()
    out = points_convenus_cabinet(session, tid, date.today())
    assert out["items"] == []
    assert out["synthese"] == {
        "total": 0,
        "anciens_30j": 0,
        "clients": 0,
        "en_retard": 0,
    }
    assert "note" in out


def test_api_points_convenus_liste(session):
    from backend.plateforme.points_convenus import creer_point_convenu

    tid, email = _cabinet(session, "pconvcab.api")
    mid = _mission(session, tid, "PM API PConv FICTIF")
    creer_point_convenu(
        session, tid, mid, "Transmettre l'état 302", "t@test.ci"
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/points-convenus", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["aujourd_hui"] == date.today().isoformat()
    assert "note" in corps
    assert corps["synthese"]["total"] == len(corps["items"]) == 1
    item = corps["items"][0]
    assert item["client"] == "PM API PConv FICTIF"
    assert item["libelle"] == "Transmettre l'état 302"
    assert item["mission_id"] == mid
    assert item["statut_mission"] == "en_cours"
    assert item["anciennete_jours"] == 0


def test_api_isolation_cross_tenant(session):
    from backend.plateforme.points_convenus import creer_point_convenu

    tid_a, _email_a = _cabinet(session, "pconvcab.a")
    mid_a = _mission(session, tid_a, "PM Isolée PConv FICTIF")
    creer_point_convenu(session, tid_a, mid_a, "Point isolé", "t@test.ci")
    _tid_b, email_b = _cabinet(session, "pconvcab.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/points-convenus", headers=h)
    assert r.status_code == 200, r.text
    # Le cabinet B ne voit pas les points du cabinet A.
    assert r.json()["items"] == []
    assert r.json()["synthese"]["total"] == 0


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/points-convenus")
    assert r.status_code == 401, r.text
    r = client.get("/api/v1/cabinet/points-convenus.csv")
    assert r.status_code == 401, r.text


def test_api_points_convenus_csv(session):
    from backend.plateforme.points_convenus import creer_point_convenu

    tid, email = _cabinet(session, "pconvcab.csv")
    mid = _mission(session, tid, "PM CSV PConv FICTIF")
    creer_point_convenu(
        session, tid, mid, "Justifier l'écart de TVA", "t@test.ci"
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/points-convenus.csv", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert (
        f"points-convenus-{date.today().isoformat()}.csv"
        in r.headers["content-disposition"]
    )
    # BOM UTF-8 en tête pour l'ouverture directe dans Excel.
    assert r.text.startswith("\ufeff")
    lignes = r.text.lstrip("\ufeff").splitlines()
    assert lignes[0] == ";".join(ENTETE_POINTS_CSV)
    assert "Justifier l'écart de TVA" in lignes[1]
    # Une ligne par item de la route JSON (mêmes données).
    corps = client.get("/api/v1/cabinet/points-convenus", headers=h).json()
    assert len(lignes) == 1 + len(corps["items"])
