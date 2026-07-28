"""Délais moyens de traitement du cabinet — moyennes par transition."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.delais_cabinet import (
    TRANSITIONS,
    agreger_delais,
    duree_creation_dernier,
    durees_canoniques,
    moyenne_jours,
)
from backend.plateforme.delais_mission import JALONS, calculer_jalons

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _evt(action: str, horodatage: str) -> dict:
    return {"action": action, "horodatage": horodatage}


def _mission(mission_id: int, evenements: list[dict]) -> dict:
    return {
        "mission_id": mission_id,
        "client": f"Client {mission_id}",
        "jalons": calculer_jalons(evenements),
    }


def test_transitions_canoniques_couvrent_tous_les_jalons():
    assert len(TRANSITIONS) == len(JALONS) - 1 == 5
    assert [(de, a) for de, a, _l1, _l2 in TRANSITIONS] == [
        ("creation", "premier_depot_piece"),
        ("premier_depot_piece", "demande_renseignements"),
        ("demande_renseignements", "premieres_constatations"),
        ("premieres_constatations", "premier_visa"),
        ("premier_visa", "restitution"),
    ]
    # Libellés français, jamais les codes techniques.
    assert all("_" not in l1 and "_" not in l2 for _de, _a, l1, l2 in TRANSITIONS)


def test_durees_canoniques_ecartent_les_durees_pontees():
    # Dépôt absent : creation → constatations est une durée PONTÉE,
    # elle ne doit PAS compter dans l'agrégat.
    jalons = calculer_jalons(
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            _evt("telechargement_demande_renseignements", "2026-01-05T00:00:00"),
            _evt("execution_moteur", "2026-01-08T00:00:00"),
        ]
    )
    durees = durees_canoniques(jalons)
    assert durees == {
        ("demande_renseignements", "premieres_constatations"): "3.0"
    }


def test_moyenne_jours_arrondi_et_vide():
    assert moyenne_jours([]) is None
    assert moyenne_jours(["2.0"]) == "2.0"
    # (2.0 + 3.0 + 3.1) / 3 = 2.7 (arrondi 0.1, HALF_UP).
    assert moyenne_jours(["2.0", "3.0", "3.1"]) == "2.7"
    # 0.25 → 0.3 (HALF_UP, pas banquier).
    assert moyenne_jours(["0.2", "0.3"]) == "0.3"
    m = moyenne_jours(["1.0", "2.0"])
    assert isinstance(m, str) and Decimal(m) == Decimal("1.5")


def test_agrege_moyennes_par_transition_et_nb_missions():
    m1 = _mission(
        1,
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            _evt("depot_piece_contribuable", "2026-01-03T00:00:00"),
            _evt("telechargement_demande_renseignements", "2026-01-04T00:00:00"),
        ],
    )
    m2 = _mission(
        2,
        [
            _evt("creation_mission", "2026-02-01T00:00:00"),
            _evt("depot_piece_contribuable", "2026-02-05T00:00:00"),
        ],
    )
    agg = agreger_delais([m1, m2])
    assert agg["nb_missions"] == 2
    par_paire = {(t["de"], t["a"]): t for t in agg["transitions"]}
    t1 = par_paire[("creation", "premier_depot_piece")]
    # (2.0 + 4.0) / 2 = 3.0 sur 2 missions.
    assert t1["moyenne_jours"] == "3.0"
    assert t1["nb_missions"] == 2
    assert t1["libelle_de"] == "Création de la mission"
    assert t1["libelle_a"] == "Premier dépôt de pièce en data room"
    t2 = par_paire[("premier_depot_piece", "demande_renseignements")]
    assert t2["moyenne_jours"] == "1.0"
    assert t2["nb_missions"] == 1
    # Durée totale moyenne : m1 = 3.0 j, m2 = 4.0 j → 3.5.
    assert agg["duree_totale_moyenne_jours"] == "3.5"


def test_transition_sans_observation_moyenne_none():
    m = _mission(1, [_evt("creation_mission", "2026-01-01T00:00:00")])
    agg = agreger_delais([m])
    assert all(t["moyenne_jours"] is None for t in agg["transitions"])
    assert all(t["nb_missions"] == 0 for t in agg["transitions"])
    assert agg["duree_totale_moyenne_jours"] is None
    assert agg["transition_la_plus_lente"] is None
    # Toutes les transitions restent listées, même sans observation.
    assert len(agg["transitions"]) == 5


def test_transition_la_plus_lente_moyenne_maximale():
    m = _mission(
        1,
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            _evt("depot_piece_contribuable", "2026-01-03T00:00:00"),
            _evt("telechargement_demande_renseignements", "2026-01-10T00:00:00"),
            _evt("execution_moteur", "2026-01-11T00:00:00"),
        ],
    )
    agg = agreger_delais([m])
    lente = agg["transition_la_plus_lente"]
    assert lente is not None
    assert (lente["de"], lente["a"]) == (
        "premier_depot_piece",
        "demande_renseignements",
    )
    assert lente["moyenne_jours"] == "7.0"


def test_duree_creation_dernier_jalon_date():
    jalons = calculer_jalons(
        [
            _evt("creation_mission", "2026-01-01T00:00:00"),
            _evt("execution_moteur", "2026-01-08T12:00:00"),
        ]
    )
    assert duree_creation_dernier(jalons) == "7.5"
    # Création seule datée : rien à mesurer.
    seul = calculer_jalons([_evt("creation_mission", "2026-01-01T00:00:00")])
    assert duree_creation_dernier(seul) is None
    # Création non datée : pas de point de départ.
    sans_creation = calculer_jalons(
        [
            _evt("depot_piece_contribuable", "2026-01-02T00:00:00"),
            _evt("execution_moteur", "2026-01-05T00:00:00"),
        ]
    )
    assert duree_creation_dernier(sans_creation) is None
    assert duree_creation_dernier([]) is None


def test_agrege_liste_vide():
    agg = agreger_delais([])
    assert agg["nb_missions"] == 0
    assert agg["duree_totale_moyenne_jours"] is None
    assert agg["transition_la_plus_lente"] is None
    assert len(agg["transitions"]) == 5


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

    lib = f"v-delaiscab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="delais-cabinet")
    publier_version(session, lib, "delaiscab@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"delaiscab.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab DelaisCab {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _nouvelle_mission(session, tenant_id: int, nom: str) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": f"PM {nom} FICTIF"},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return int(mid)


def _journaliser(session, tenant_id: int, mission_id: int, action: str) -> None:
    from backend.moteur.journal import append_journal

    with contexte_tenant(session, tenant_id):
        append_journal(
            session,
            tenant_id=tenant_id,
            mission_id=mission_id,
            acteur="delaiscab@test.ci",
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


def test_api_delais_cabinet_agrege_les_missions(session):
    tid, email = _cabinet(session)
    m1 = _nouvelle_mission(session, tid, "Alpha")
    m2 = _nouvelle_mission(session, tid, "Beta")
    _journaliser(session, tid, m1, "creation_mission")
    _journaliser(session, tid, m1, "depot_piece_contribuable")
    _journaliser(session, tid, m2, "creation_mission")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get("/api/v1/cabinet/delais", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["nb_missions"] == 2
    assert "note" in corps and "consultative" in corps["note"]

    par_paire = {(t["de"], t["a"]): t for t in corps["transitions"]}
    assert len(corps["transitions"]) == 5
    t1 = par_paire[("creation", "premier_depot_piece")]
    # Seule m1 a les deux jalons datés : une seule mission observée.
    assert t1["nb_missions"] == 1
    assert t1["moyenne_jours"] is not None
    assert Decimal(t1["moyenne_jours"]) >= Decimal("0")
    assert t1["libelle_de"] == "Création de la mission"
    # Aucune mission n'a la suite du processus.
    t2 = par_paire[("premier_depot_piece", "demande_renseignements")]
    assert t2["nb_missions"] == 0 and t2["moyenne_jours"] is None

    lente = corps["transition_la_plus_lente"]
    assert lente is not None
    assert (lente["de"], lente["a"]) == ("creation", "premier_depot_piece")
    assert corps["duree_totale_moyenne_jours"] is not None


def test_api_delais_cabinet_consultation_journalisee_mais_exclue(session):
    tid, email = _cabinet(session)
    mid = _nouvelle_mission(session, tid, "Gamma")
    _journaliser(session, tid, mid, "creation_mission")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.get("/api/v1/cabinet/delais", headers=h)
    assert r1.status_code == 200, r1.text
    # Seconde consultation : les consultations journalisées (mission_id
    # NULL et consultation_* par mission) ne créent aucune observation.
    r2 = client.get(f"/api/v1/missions/{mid}/delais", headers=h)
    assert r2.status_code == 200, r2.text
    r3 = client.get("/api/v1/cabinet/delais", headers=h)
    assert r3.status_code == 200, r3.text
    assert r3.json()["transitions"] == r1.json()["transitions"]

    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE action = 'consultation_delais_cabinet'"
            ),
        ).scalar_one()
    assert int(n) >= 2


def test_api_delais_cabinet_isolation_tenant(session):
    # Le tenant B, sans mission, ne voit rien des missions du tenant A.
    tid_a, _email_a = _cabinet(session)
    ma = _nouvelle_mission(session, tid_a, "Isole")
    _journaliser(session, tid_a, ma, "creation_mission")
    _journaliser(session, tid_a, ma, "depot_piece_contribuable")

    _tid_b, email_b = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get("/api/v1/cabinet/delais", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["nb_missions"] == 0
    assert all(t["nb_missions"] == 0 for t in corps["transitions"])
    assert corps["transition_la_plus_lente"] is None


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/cabinet/delais")
    assert r.status_code == 401, r.text
