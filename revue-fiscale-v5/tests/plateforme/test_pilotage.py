"""Pilotage portefeuille — structure, exposition cumulée, isolation RLS."""
from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant

pytestmark = pytest.mark.db


def _skip_si_absente(session) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name IN ('risque', 'controle_source_fec')"
        )
    ).scalar_one()
    if n < 2:
        pytest.skip("migrations 020/033 non appliquées — make migrate")


def _provisionner(session) -> tuple[TestClient, dict, int]:
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

        lib = f"v-pilot-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="pilotage")
        publier_version(session, lib, "pilot@test.ci")

    email = f"pilot.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Pilotage {email}",
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
    return (
        client,
        {"Authorization": f"Bearer {body['jeton']}"},
        int(body["tenant_id"]),
    )


@pytest.fixture
def cab(session):
    _skip_si_absente(session)
    return _provisionner(session)


def _contrib(
    client: TestClient, h: dict, nom: str, regime: str = "reel"
) -> int:
    ref = uuid.uuid4().hex[:8].upper()
    r = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": nom,
            "ncc": f"CI-{ref}",
            "rccm": f"RCCM-{ref}",
            "dfe": f"DFE-{ref}",
            "forme": "pm",
            "regime_fiscal": regime,
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert r.status_code == 200, r.text
    return int(r.json()["id"])


def _risque(
    client: TestClient,
    h: dict,
    cid: int,
    libelle: str,
    montant: float | None,
    penalites: float | None = None,
) -> int:
    r = client.post(
        "/api/v1/risques",
        headers=h,
        json={
            "contribuable_id": cid,
            "impot": "TVA",
            "libelle": libelle,
            "exercice_origine": 2023,
            "probabilite": "possible",
            "montant_estime": montant,
            "penalites_estimees": penalites,
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_pilotage_structure_complete(session, cab):
    client, h, _tid = cab
    r = client.get("/api/v1/pilotage", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert set(corps) == {
        "exposition_par_client",
        "missions_a_cloturer",
        "alertes_source",
        "risques_en_retard",
        "echeances_portefeuille",
        "relances_circularisation",
    }
    assert isinstance(corps["exposition_par_client"], list)
    assert isinstance(corps["missions_a_cloturer"], list)
    assert isinstance(corps["alertes_source"], list)
    retards = corps["risques_en_retard"]
    assert set(retards) == {"total", "top"}
    assert retards["total"] == 0
    assert retards["top"] == []
    echeances = corps["echeances_portefeuille"]
    assert set(echeances) == {"total", "lignes"}
    assert echeances["total"] == 0
    assert echeances["lignes"] == []
    relances = corps["relances_circularisation"]
    assert set(relances) == {
        "missions_concernees",
        "items_en_attente",
        "items_a_relancer",
        "missions",
    }
    assert relances["missions_concernees"] == 0
    assert relances["items_en_attente"] == 0
    assert relances["items_a_relancer"] == 0
    assert relances["missions"] == []


def test_exposition_cumulee_risques_ouverts(session, cab):
    client, h, tid = cab
    cid = _contrib(client, h, "SARL Exposition Pilotage")
    _risque(client, h, cid, "TVA déductible douteuse", 1_000_000, 200_000)
    _risque(client, h, cid, "Retenue BNC omise", 500_000)
    # Risque résolu — NE doit PAS compter dans l'exposition ouverte.
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, exercice_origine) "
                "VALUES (:t, :c, 'IS', 'Risque déjà résolu', 9999999, "
                "'resolu', 2023)"
            ),
            {"t": tid, "c": cid},
        )
    session.commit()

    r = client.get("/api/v1/pilotage", headers=h)
    assert r.status_code == 200, r.text
    expo = r.json()["exposition_par_client"]
    ligne = next(
        (e for e in expo if e["contribuable_id"] == cid), None
    )
    assert ligne is not None, expo
    assert ligne["denomination"] == "SARL Exposition Pilotage"
    assert ligne["nb_risques_ouverts"] == 2
    # 1 000 000 + 200 000 pénalités + 500 000 = 1 700 000
    assert float(ligne["exposition_ouverte"]) == pytest.approx(1_700_000)
    assert isinstance(ligne["score"], int)
    assert ligne["score"] > 0
    assert ligne["niveau"] in {"faible", "modere", "eleve", "critique"}


def test_missions_inactives_et_alertes_source(session, cab):
    client, h, tid = cab
    cid = _contrib(client, h, "SA Inactive Pilotage")
    with contexte_tenant(session, tid):
        mid = session.execute(
            text(
                "INSERT INTO mission (tenant_id, contribuable_id, exercice, "
                "statut) VALUES (:t, :c, 2023, 'en_cours') RETURNING id"
            ),
            {"t": tid, "c": cid},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_le, "
                "lancee_par) VALUES (:t, :m, now() - interval '45 days', "
                "'pilote@test.ci')"
            ),
            {"t": tid, "m": mid},
        )
        session.execute(
            text(
                "INSERT INTO controle_source_fec (tenant_id, mission_id, "
                "exercice, controles) VALUES (:t, :m, 2023, "
                "CAST(:ctrl AS jsonb))"
            ),
            {
                "t": tid,
                "m": mid,
                "ctrl": json.dumps(
                    [
                        {
                            "code": "dates_hors_exercice",
                            "libelle": "Dates hors exercice",
                            "statut": "alerte",
                            "compteur": 3,
                        },
                        {
                            "code": "equilibre_pieces",
                            "libelle": "Équilibre des pièces",
                            "statut": "ok",
                            "compteur": 0,
                        },
                    ]
                ),
            },
        )
    session.commit()

    r = client.get("/api/v1/pilotage", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    inactives = [
        m for m in corps["missions_a_cloturer"] if m["mission_id"] == mid
    ]
    assert len(inactives) == 1, corps["missions_a_cloturer"]
    assert inactives[0]["denomination"] == "SA Inactive Pilotage"
    assert inactives[0]["exercice"] == 2023
    assert inactives[0]["jours_inactivite"] >= 45

    alertes = [a for a in corps["alertes_source"] if a["mission_id"] == mid]
    assert len(alertes) == 1, corps["alertes_source"]
    assert alertes[0]["codes_alerte"] == ["dates_hors_exercice"]
    # Le contrôle « ok » ne doit pas remonter.
    assert "equilibre_pieces" not in alertes[0]["codes_alerte"]


def test_echeances_portefeuille_tee_depassee(session, cab, monkeypatch):
    from datetime import date as _date

    # Date de référence gelée : le 26/07, la déclaration TEE mensuelle
    # du 10/07 est dépassée depuis 16 jours et reste visible (< 30 j).
    class _DateFixe(_date):
        @classmethod
        def today(cls):
            return _date(2026, 7, 26)

    monkeypatch.setattr("backend.plateforme.pilotage.date", _DateFixe)

    client, h, _tid = cab
    cid = _contrib(client, h, "Entreprenant TEE Pilotage", regime="tee")
    # Régime inconnu du référentiel → contribuable ignoré silencieusement.
    cid_vide = _contrib(
        client, h, "Sans Régime Pilotage", regime="hors_referentiel"
    )

    r = client.get("/api/v1/pilotage", headers=h)
    assert r.status_code == 200, r.text
    volet = r.json()["echeances_portefeuille"]
    assert set(volet) == {"total", "lignes"}
    lignes = volet["lignes"]
    assert volet["total"] >= len(lignes) >= 1
    assert len(lignes) <= 15
    # Structure de chaque ligne + tri par date croissante.
    for ligne in lignes:
        assert set(ligne) == {
            "contribuable_id",
            "denomination",
            "code",
            "libelle",
            "date_limite",
            "jours_restants",
            "statut",
        }
        assert ligne["statut"] in {"imminente", "depassee"}
    assert [x["date_limite"] for x in lignes] == sorted(
        x["date_limite"] for x in lignes
    )
    depassees_tee = [
        x
        for x in lignes
        if x["contribuable_id"] == cid
        and x["code"] == "tee_mensuelle"
        and x["statut"] == "depassee"
    ]
    assert depassees_tee, lignes
    assert depassees_tee[0]["denomination"] == "Entreprenant TEE Pilotage"
    assert depassees_tee[0]["date_limite"] == "2026-07-10"
    assert depassees_tee[0]["jours_restants"] == -16
    # Le contribuable sans régime ne produit aucune ligne.
    assert all(x["contribuable_id"] != cid_vide for x in lignes)


def _mission(session, tid: int, cid: int, statut: str = "en_cours") -> int:
    with contexte_tenant(session, tid):
        return session.execute(
            text(
                "INSERT INTO mission (tenant_id, contribuable_id, exercice, "
                "statut) VALUES (:t, :c, 2024, :s) RETURNING id"
            ),
            {"t": tid, "c": cid, "s": statut},
        ).scalar_one()


def _suivi(
    session,
    tid: int,
    mid: int,
    cle: str,
    statut: str,
    date_relance: str | None = None,
    maj_le: str | None = None,
) -> None:
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO suivi_demande_renseignements "
                "(tenant_id, mission_id, cle_item, libelle, statut, "
                "date_relance, maj_le) "
                "VALUES (:t, :m, :c, :c, :s, :d, "
                "COALESCE(CAST(:maj AS timestamptz), now()))"
            ),
            {
                "t": tid,
                "m": mid,
                "c": cle,
                "s": statut,
                "d": date_relance,
                "maj": maj_le,
            },
        )


def test_relances_circularisation_mission_a_relancer(session, cab):
    client, h, tid = cab
    cid = _contrib(client, h, "SARL Circularisation Pilotage")
    mid = _mission(session, tid, cid)
    # 2 en attente (dont 1 relance échue), 1 reçu, 1 sans objet.
    _suivi(
        session,
        tid,
        mid,
        "analytique:7011",
        "en_attente",
        date_relance="2020-01-15",
        maj_le="2024-01-10T08:00:00+00:00",
    )
    _suivi(
        session,
        tid,
        mid,
        "analytique:6222",
        "en_attente",
        date_relance="2999-12-31",
        maj_le="2024-03-01T08:00:00+00:00",
    )
    _suivi(session, tid, mid, "piece:R1", "recu")
    _suivi(session, tid, mid, "piece:R2", "sans_objet")
    session.commit()

    r = client.get("/api/v1/pilotage", headers=h)
    assert r.status_code == 200, r.text
    volet = r.json()["relances_circularisation"]
    assert volet["missions_concernees"] == 1
    assert volet["items_en_attente"] == 2
    assert volet["items_a_relancer"] == 1
    assert len(volet["missions"]) == 1
    ligne = volet["missions"][0]
    assert ligne["mission_id"] == mid
    assert ligne["client"] == "SARL Circularisation Pilotage"
    assert ligne["exercice"] == 2024
    assert ligne["en_attente"] == 2
    assert ligne["recu"] == 1
    assert ligne["a_relancer"] == 1
    # Plus ancienne attente = maj_le minimal des items en_attente.
    assert ligne["plus_ancienne_attente"].startswith("2024-01-10")


def test_relances_circularisation_exclusions(session, cab):
    client, h, tid = cab
    cid = _contrib(client, h, "SA Exclusions Circularisation")
    # Mission clôturée avec en_attente → exclue.
    mid_close = _mission(session, tid, cid, statut="cloturee")
    _suivi(
        session, tid, mid_close, "analytique:7011", "en_attente",
        date_relance="2020-01-01",
    )
    # Mission en cours sans aucun en_attente → exclue.
    mid_recu = _mission(session, tid, cid)
    _suivi(session, tid, mid_recu, "piece:R1", "recu")
    _suivi(session, tid, mid_recu, "piece:R2", "sans_objet")
    session.commit()

    r = client.get("/api/v1/pilotage", headers=h)
    assert r.status_code == 200, r.text
    volet = r.json()["relances_circularisation"]
    ids = [m["mission_id"] for m in volet["missions"]]
    assert mid_close not in ids
    assert mid_recu not in ids
    assert volet["missions_concernees"] == 0
    assert volet["items_en_attente"] == 0
    assert volet["items_a_relancer"] == 0


def test_relances_circularisation_isolation_cross_tenant(session, cab):
    client, h, tid = cab
    cid = _contrib(client, h, "Circularisation Secrète Tenant A")
    mid = _mission(session, tid, cid)
    _suivi(
        session, tid, mid, "analytique:7011", "en_attente",
        date_relance="2020-01-01",
    )
    session.commit()

    # Tenant A voit sa mission.
    ra = client.get("/api/v1/pilotage", headers=h)
    assert ra.status_code == 200
    assert any(
        m["mission_id"] == mid
        for m in ra.json()["relances_circularisation"]["missions"]
    )

    # Tenant B : rien ne fuit.
    _client_b, h_b, _tid_b = _provisionner(session)
    rb = client.get("/api/v1/pilotage", headers=h_b)
    assert rb.status_code == 200, rb.text
    volet_b = rb.json()["relances_circularisation"]
    assert volet_b == {
        "missions_concernees": 0,
        "items_en_attente": 0,
        "items_a_relancer": 0,
        "missions": [],
    }
    assert "Circularisation Secrète Tenant A" not in rb.text


def test_isolation_cross_tenant(session, cab):
    client_a, h_a, _tid_a = cab
    cid = _contrib(client_a, h_a, "Confidentiel Tenant A")
    _risque(client_a, h_a, cid, "Risque secret tenant A", 750_000)

    # Tenant A voit bien sa ligne.
    ra = client_a.get("/api/v1/pilotage", headers=h_a)
    assert ra.status_code == 200
    assert any(
        e["contribuable_id"] == cid
        for e in ra.json()["exposition_par_client"]
    )

    # Tenant B, fraîchement provisionné : rien du tenant A ne fuit.
    _client_b, h_b, _tid_b = _provisionner(session)
    rb = client_a.get("/api/v1/pilotage", headers=h_b)
    assert rb.status_code == 200, rb.text
    corps_b = rb.json()
    assert corps_b["exposition_par_client"] == []
    assert corps_b["missions_a_cloturer"] == []
    assert corps_b["alertes_source"] == []
    assert corps_b["risques_en_retard"] == {"total": 0, "top": []}
    # Le volet échéances est lui aussi cloisonné : le contribuable du
    # tenant A (régime réel → échéances mensuelles) ne fuit pas.
    assert corps_b["echeances_portefeuille"] == {"total": 0, "lignes": []}
    assert "Confidentiel Tenant A" not in rb.text
