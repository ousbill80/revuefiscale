"""Chronologie de la mission — journal d'audit en libellés français."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.plateforme.chronologie_mission import (
    ACTION_CONSULTATION,
    LIBELLES_ACTIONS,
    PLAFOND_EVENEMENTS,
    mettre_en_forme,
    traduire_action,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _evt(id_: int, action: str, horodatage: str = "2026-01-01T10:00:00") -> dict:
    return {
        "id": id_,
        "horodatage": horodatage,
        "acteur": "fisc@cabinet.ci",
        "action": action,
    }


def test_traduire_action_libelles_francais_connus():
    assert traduire_action("depot_piece_contribuable") == (
        "Dépôt d'une pièce en data room"
    )
    assert traduire_action("changement_statut") == (
        "Changement de statut de la mission"
    )
    assert traduire_action("decision_plan_action") == (
        "Décision sur une action du plan d'actions"
    )
    assert traduire_action("relance_effectuee") == "Relance effectuée"
    assert traduire_action("export_rentabilite_csv") == (
        "Export CSV de la rentabilité"
    )


def test_traduire_action_fallback_code_brut():
    assert traduire_action("action_inconnue_xyz") == "action_inconnue_xyz"
    assert traduire_action("  execution_moteur  ") == "Exécution de la revue"
    assert traduire_action(None) == ""


def test_libelles_sans_code_technique_en_clair():
    """Chaque libellé connu est une phrase française, pas un code."""
    for code, libelle in LIBELLES_ACTIONS.items():
        assert libelle, code
        assert "_" not in libelle, (code, libelle)


def test_mettre_en_forme_tri_antichronologique():
    evenements = [
        _evt(1, "creation_mission", "2026-01-01T08:00:00"),
        _evt(3, "execution_moteur", "2026-01-02T09:30:00"),
        _evt(2, "import_balance", "2026-01-01T08:00:00"),
    ]
    chrono = mettre_en_forme(evenements)
    # Horodatage décroissant, puis id décroissant à horodatage égal.
    assert [e["id"] for e in chrono] == [3, 2, 1]
    assert chrono[0]["libelle"] == "Exécution de la revue"
    assert chrono[0]["acteur"] == "fisc@cabinet.ci"
    assert chrono[0]["horodatage"] == "2026-01-02T09:30:00"


def test_mettre_en_forme_horodatage_datetime_serialise_iso():
    quand = datetime(2026, 3, 15, 14, 5, tzinfo=timezone.utc)
    chrono = mettre_en_forme(
        [{"id": 7, "horodatage": quand, "acteur": "a@b.ci", "action": "x"}]
    )
    assert chrono[0]["horodatage"] == quand.isoformat()
    assert chrono[0]["libelle"] == "x"  # fallback code brut


def test_mettre_en_forme_plafond():
    evenements = [
        _evt(i, "execution_moteur", f"2026-01-01T10:{i % 60:02d}:00")
        for i in range(1, 151)
    ]
    chrono = mettre_en_forme(evenements)
    assert len(chrono) == PLAFOND_EVENEMENTS == 100
    # Plafond personnalisé : garde les plus récents.
    court = mettre_en_forme(evenements, plafond=3)
    assert len(court) == 3
    assert court[0]["horodatage"] >= court[-1]["horodatage"]


def test_mettre_en_forme_exclut_consultation_chronologie():
    """La consultation de la chronologie ne pollue pas la chronologie."""
    evenements = [
        _evt(1, "creation_mission"),
        _evt(2, ACTION_CONSULTATION),
        _evt(3, "changement_statut"),
    ]
    chrono = mettre_en_forme(evenements)
    assert [e["id"] for e in chrono] == [3, 1]
    assert all(e["action"] != ACTION_CONSULTATION for e in chrono)


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

    lib = f"v-chrono-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="chronologie-mission")
    publier_version(session, lib, "chrono@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"chrono.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Chrono {email}",
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
                "VALUES (:t, 'PM Chrono FICTIF', 'pm') RETURNING id"
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


def test_api_chronologie_evenements_reels_apres_actions(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    # Action réelle journalisée sur la mission : consultation du
    # civisme fiscal (action = consultation_civisme_fiscal).
    r_civ = client.get(f"/api/v1/missions/{mid}/civisme-fiscal", headers=h)
    assert r_civ.status_code == 200, r_civ.text

    r = client.get(f"/api/v1/missions/{mid}/chronologie", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["plafond"] == PLAFOND_EVENEMENTS
    assert corps["total_affiche"] == len(corps["evenements"]) >= 1
    assert "note" in corps

    libelles = [e["libelle"] for e in corps["evenements"]]
    assert "Consultation du civisme fiscal" in libelles
    evt = next(
        e
        for e in corps["evenements"]
        if e["action"] == "consultation_civisme_fiscal"
    )
    assert evt["acteur"] == email
    assert evt["horodatage"]

    # Tri antichronologique (ids du journal décroissants).
    ids = [e["id"] for e in corps["evenements"]]
    assert ids == sorted(ids, reverse=True)


def test_api_chronologie_ne_se_pollue_pas_elle_meme(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.get(f"/api/v1/missions/{mid}/chronologie", headers=h)
    assert r1.status_code == 200, r1.text
    # Seconde consultation : la première (journalisée) reste invisible.
    r2 = client.get(f"/api/v1/missions/{mid}/chronologie", headers=h)
    assert r2.status_code == 200, r2.text
    actions = [e["action"] for e in r2.json()["evenements"]]
    assert ACTION_CONSULTATION not in actions


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"chrono.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Chrono B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/chronologie", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/chronologie")
    assert r.status_code == 401, r.text
