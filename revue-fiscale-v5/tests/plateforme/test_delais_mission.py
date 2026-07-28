"""Délais de traitement par étape — jalons et durées depuis le journal."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.plateforme.delais_mission import (
    ACTION_CONSULTATION,
    JALONS,
    calculer_durees,
    calculer_jalons,
    duree_totale,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _evt(action: str, horodatage: str) -> dict:
    return {"action": action, "horodatage": horodatage}


def test_jalons_premiere_occurrence_de_chaque_etape():
    evenements = [
        _evt("creation_mission", "2026-01-01T08:00:00"),
        _evt("depot_piece_contribuable", "2026-01-03T10:00:00"),
        # Second dépôt plus tardif : le jalon garde la 1re occurrence.
        _evt("depot_piece_contribuable", "2026-01-05T09:00:00"),
        _evt("telechargement_demande_renseignements", "2026-01-06T14:00:00"),
        _evt("execution_moteur", "2026-01-10T11:00:00"),
        _evt("pose_visa_mission", "2026-01-12T17:00:00"),
        _evt("enregistrement_compte_rendu", "2026-01-15T15:00:00"),
        # Bruit : action sans jalon associé.
        _evt("saisie_temps_mission", "2026-01-04T12:00:00"),
    ]
    jalons = calculer_jalons(evenements)
    assert [j["code"] for j in jalons] == [
        "creation",
        "premier_depot_piece",
        "demande_renseignements",
        "premieres_constatations",
        "premier_visa",
        "restitution",
    ]
    par_code = {j["code"]: j for j in jalons}
    assert par_code["creation"]["date"] == "2026-01-01T08:00:00"
    assert par_code["creation"]["libelle"] == "Création de la mission"
    assert par_code["premier_depot_piece"]["date"] == "2026-01-03T10:00:00"
    assert par_code["restitution"]["date"] == "2026-01-15T15:00:00"
    assert all(j["libelle"] and "_" not in j["libelle"] for j in jalons)


def test_jalons_absents_date_none():
    jalons = calculer_jalons(
        [_evt("creation_mission", "2026-01-01T08:00:00")]
    )
    par_code = {j["code"]: j["date"] for j in jalons}
    assert par_code["creation"] == "2026-01-01T08:00:00"
    assert par_code["premier_depot_piece"] is None
    assert par_code["premier_visa"] is None
    assert par_code["restitution"] is None
    # Aucun événement : tous les jalons existent, tous sans date.
    vides = calculer_jalons([])
    assert len(vides) == len(JALONS) == 6
    assert all(j["date"] is None for j in vides)


def test_jalons_excluent_la_consultation_des_delais():
    jalons = calculer_jalons(
        [_evt(ACTION_CONSULTATION, "2026-01-01T08:00:00")]
    )
    assert all(j["date"] is None for j in jalons)


def test_jalons_horodatage_datetime_et_illisible():
    quand = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)
    jalons = calculer_jalons(
        [
            {"action": "creation_mission", "horodatage": quand},
            {"action": "depot_piece_contribuable", "horodatage": "n/a"},
        ]
    )
    par_code = {j["code"]: j["date"] for j in jalons}
    # Normalisé en UTC naïf, sérialisé ISO.
    assert par_code["creation"] == "2026-03-15T14:00:00"
    # Horodatage illisible → jalon inexploitable, pas de durée fausse.
    assert par_code["premier_depot_piece"] is None


def test_durees_entre_jalons_consecutifs_decimal_arrondi():
    jalons = calculer_jalons(
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            _evt("depot_piece_contribuable", "2026-01-03T12:00:00"),
            _evt("telechargement_demande_renseignements", "2026-01-04T00:00:00"),
            _evt("execution_moteur", "2026-01-04T08:24:00"),
            _evt("pose_visa_mission", "2026-01-10T08:24:00"),
            _evt("enregistrement_compte_rendu", "2026-01-10T08:24:00"),
        ]
    )
    durees = calculer_durees(jalons)
    assert [(d["de"], d["a"]) for d in durees] == [
        ("creation", "premier_depot_piece"),
        ("premier_depot_piece", "demande_renseignements"),
        ("demande_renseignements", "premieres_constatations"),
        ("premieres_constatations", "premier_visa"),
        ("premier_visa", "restitution"),
    ]
    jours = [d["jours"] for d in durees]
    assert jours == ["2.5", "0.5", "0.4", "6.0", "0.0"]
    assert all(isinstance(j, str) for j in jours)
    assert Decimal(jours[0]) == Decimal("2.5")
    # Durée totale : du premier au dernier jalon datés.
    assert duree_totale(jalons) == "9.4"


def test_durees_pontent_les_jalons_absents():
    jalons = calculer_jalons(
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            _evt("execution_moteur", "2026-01-08T00:00:00"),
        ]
    )
    # Dépôt et demande absents : une seule durée, entre jalons datés.
    assert calculer_durees(jalons) == [
        {"de": "creation", "a": "premieres_constatations", "jours": "7.0"}
    ]
    assert duree_totale(jalons) == "7.0"


def test_duree_negative_si_ordre_observe_different():
    jalons = calculer_jalons(
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            # Revue exécutée AVANT la génération de la demande.
            _evt("execution_moteur", "2026-01-02T00:00:00"),
            _evt("telechargement_demande_renseignements", "2026-01-04T12:00:00"),
        ]
    )
    durees = {(d["de"], d["a"]): d["jours"] for d in calculer_durees(jalons)}
    assert durees[("creation", "demande_renseignements")] == "3.5"
    # Valeur factuelle négative : l'étape suivante a précédé.
    assert durees[("demande_renseignements", "premieres_constatations")] == "-2.5"
    assert duree_totale(jalons) == "3.5"


def test_duree_totale_none_si_moins_de_deux_jalons():
    assert duree_totale(calculer_jalons([])) is None
    seul = calculer_jalons([_evt("creation_mission", "2026-01-01T00:00:00")])
    assert duree_totale(seul) is None


# ── Tests API (DB) ─────────────────────────────────────────────────

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

    lib = f"v-delais-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="delais-mission")
    publier_version(session, lib, "delais@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"delais.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Delais {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Delais FICTIF', 'pm') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return r.tenant_id, int(mid), email


def _journaliser(session, tenant_id: int, mission_id: int, action: str) -> None:
    from backend.moteur.journal import append_journal

    with contexte_tenant(session, tenant_id):
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur="delais@test.ci",
            action=action,
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


def test_api_delais_jalons_et_durees(session):
    tid, mid, email = _mission_en_cours(session)
    _journaliser(session, tid, mid, "creation_mission")
    _journaliser(session, tid, mid, "depot_piece_contribuable")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/delais", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert "note" in corps and "consultative" in corps["note"]

    par_code = {j["code"]: j for j in corps["jalons"]}
    assert len(corps["jalons"]) == 6
    assert par_code["creation"]["date"]
    assert par_code["creation"]["libelle"] == "Création de la mission"
    assert par_code["premier_depot_piece"]["date"]
    assert par_code["premier_visa"]["date"] is None
    assert par_code["restitution"]["date"] is None

    # Deux jalons datés seulement : une seule durée (les absents sont
    # pontés, aucune paire non calculable).
    assert len(corps["durees"]) == 1
    d = corps["durees"][0]
    assert (d["de"], d["a"]) == ("creation", "premier_depot_piece")
    assert d["jours"] is not None and Decimal(d["jours"]) >= Decimal("0")
    assert corps["duree_totale_jours"] is not None
    assert Decimal(corps["duree_totale_jours"]) >= Decimal("0")


def test_api_delais_consultation_journalisee_mais_exclue(session):
    tid, mid, email = _mission_en_cours(session)
    _journaliser(session, tid, mid, "creation_mission")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.get(f"/api/v1/missions/{mid}/delais", headers=h)
    assert r1.status_code == 200, r1.text
    # Seconde consultation : la première (journalisée) ne crée aucun jalon.
    r2 = client.get(f"/api/v1/missions/{mid}/delais", headers=h)
    assert r2.status_code == 200, r2.text
    assert r2.json()["jalons"] == r1.json()["jalons"]

    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m AND action = :a"
            ),
            {"m": mid, "a": ACTION_CONSULTATION},
        ).scalar_one()
    assert int(n) >= 2


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"delais.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Delais B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/delais", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/delais")
    assert r.status_code == 401, r.text
