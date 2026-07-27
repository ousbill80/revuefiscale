"""Bilan de pré-clôture — points consultatifs ok / attention."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.bilan_cloture import (
    MENTION_NOTE,
    construire_bilan,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _signaux_tous_ok() -> dict:
    return {
        "phases_visees": 4,
        "total_phases": 4,
        "restitution_visee": True,
        "total_heures": "12.50",
        "items_en_attente": 0,
        "items_a_relancer": 0,
        "note_synthese_disponible": True,
        "nb_pieces": 3,
        "risques_ouverts": 0,
    }


def test_construire_bilan_tous_ok_pret():
    bilan = construire_bilan(_signaux_tous_ok())
    assert all(p["statut"] == "ok" for p in bilan["points"])
    assert bilan["synthese"] == {
        "points_ok": len(bilan["points"]),
        "points_attention": 0,
        "pret": True,
    }
    assert bilan["note"] == MENTION_NOTE
    # Chaque point porte code, libellé et statut.
    for p in bilan["points"]:
        assert p["code"] and p["libelle"] and p["statut"] in ("ok", "attention")


def test_construire_bilan_melange_compteurs_et_statuts():
    signaux = _signaux_tous_ok() | {
        "phases_visees": 0,
        "restitution_visee": False,
        "total_heures": "0",
        "items_en_attente": 3,
        "items_a_relancer": 1,
        "note_synthese_disponible": False,
        "nb_pieces": 0,
        "risques_ouverts": 2,
    }
    bilan = construire_bilan(signaux)
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["visas_poses"]["statut"] == "attention"
    assert "0/4" in par_code["visas_poses"]["libelle"]
    assert par_code["restitution_visee"]["statut"] == "attention"
    assert par_code["temps_saisis"]["statut"] == "attention"
    assert par_code["demande_renseignements"]["statut"] == "attention"
    assert "3 item(s)" in par_code["demande_renseignements"]["libelle"]
    assert "1 à relancer" in par_code["demande_renseignements"]["libelle"]
    assert par_code["note_synthese"]["statut"] == "attention"
    assert par_code["data_room"]["statut"] == "attention"
    assert par_code["risques_ouverts"]["statut"] == "attention"
    assert "2 risque(s)" in par_code["risques_ouverts"]["libelle"]

    s = bilan["synthese"]
    assert s["points_ok"] == 0
    assert s["points_attention"] == len(bilan["points"])
    assert s["pret"] is False


def test_construire_bilan_partiel_signal_ok_reste_ok():
    signaux = _signaux_tous_ok() | {"phases_visees": 2, "risques_ouverts": 0}
    bilan = construire_bilan(signaux)
    par_code = {p["code"]: p for p in bilan["points"]}
    # 2/4 phases visées : au moins un visa posé → ok (consultatif).
    assert par_code["visas_poses"]["statut"] == "ok"
    assert "2/4" in par_code["visas_poses"]["libelle"]
    # 0 risque ouvert → ok.
    assert par_code["risques_ouverts"]["statut"] == "ok"
    s = bilan["synthese"]
    assert s["points_ok"] + s["points_attention"] == len(bilan["points"])
    assert s["pret"] is (s["points_attention"] == 0)


def test_construire_bilan_plan_actions_absent_sans_signal():
    # Signal plan d'actions indisponible → point absent (échec silencieux).
    bilan = construire_bilan(_signaux_tous_ok())
    assert "plan_actions" not in {p["code"] for p in bilan["points"]}


def test_construire_bilan_plan_actions_ok_vide_ou_tout_decide():
    # Plan vide → ok.
    bilan = construire_bilan(
        _signaux_tous_ok()
        | {
            "plan_actions_disponible": True,
            "plan_total_actions": 0,
            "plan_sans_decision": 0,
        }
    )
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["plan_actions"]["statut"] == "ok"
    assert "vide" in par_code["plan_actions"]["libelle"]
    assert bilan["synthese"]["pret"] is True

    # Toutes les actions décidées → ok.
    bilan = construire_bilan(
        _signaux_tous_ok()
        | {
            "plan_actions_disponible": True,
            "plan_total_actions": 3,
            "plan_sans_decision": 0,
        }
    )
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["plan_actions"]["statut"] == "ok"
    assert "3 action(s), toutes décidées" in par_code["plan_actions"]["libelle"]
    assert bilan["synthese"]["pret"] is True


def test_construire_bilan_plan_actions_attention_sans_decision():
    bilan = construire_bilan(
        _signaux_tous_ok()
        | {
            "plan_actions_disponible": True,
            "plan_total_actions": 4,
            "plan_sans_decision": 2,
        }
    )
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["plan_actions"]["statut"] == "attention"
    assert "2 action(s) sans décision" in par_code["plan_actions"]["libelle"]
    s = bilan["synthese"]
    assert s["points_attention"] == 1
    assert s["pret"] is False


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

    lib = f"v-bilan-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="bilan-cloture")
    publier_version(session, lib, "bilan@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"bilan.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Bilan {email}",
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
                "VALUES (:t, 'PM Bilan FICTIF', 'pm') RETURNING id"
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


def test_api_bilan_mission_reelle_coherence(session):
    tid, mid, email = _mission_en_cours(session)
    # Un signal favorable concret : une pièce en data room.
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO piece_mission (tenant_id, mission_id, "
                "type_piece, role, nom_fichier, chemin_stockage) "
                "VALUES (:t, :m, 'balance', 'annexe', 'balance_2025.csv', :c)"
            ),
            {"t": tid, "m": mid, "c": f"tests/bilan/{uuid.uuid4().hex}"},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/bilan-cloture", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["statut_mission"] == "en_cours"
    assert corps["note"] == MENTION_NOTE

    par_code = {p["code"]: p for p in corps["points"]}
    # Mission neuve : ni visa, ni temps, ni note de synthèse.
    assert par_code["visas_poses"]["statut"] == "attention"
    assert par_code["restitution_visee"]["statut"] == "attention"
    assert par_code["temps_saisis"]["statut"] == "attention"
    assert par_code["note_synthese"]["statut"] == "attention"
    # Pièce déposée → data room ok ; aucun risque saisi → ok.
    assert par_code["data_room"]["statut"] == "ok"
    assert par_code["risques_ouverts"]["statut"] == "ok"
    # Aucun risque → plan d'actions vide → ok.
    assert par_code["plan_actions"]["statut"] == "ok"
    assert "vide" in par_code["plan_actions"]["libelle"]

    s = corps["synthese"]
    assert s["points_ok"] == sum(
        1 for p in corps["points"] if p["statut"] == "ok"
    )
    assert s["points_attention"] == sum(
        1 for p in corps["points"] if p["statut"] == "attention"
    )
    assert s["pret"] is False  # Des points d'attention subsistent.


def test_bilan_plan_actions_attention_puis_ok_apres_decision(session):
    """Risque non clos sans décision → attention ; décision posée → ok."""
    from backend.plateforme.bilan_cloture import bilan_mission
    from backend.plateforme.plan_actions import decider_action

    tid, mid, _email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        cid = session.execute(
            text("SELECT contribuable_id FROM mission WHERE id = :m"),
            {"m": mid},
        ).scalar_one()
        rid = int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, "
                    "impot, libelle, montant_estime, probabilite, statut, "
                    "exercice_origine) VALUES (:t, :c, 'TVA', "
                    "'Risque bilan plan FICTIF', '1000000', 'possible', "
                    "'ouvert', 2025) RETURNING id"
                ),
                {"t": tid, "c": int(cid)},
            ).scalar_one()
        )

    bilan = bilan_mission(session, tid, mid)
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["plan_actions"]["statut"] == "attention"
    assert "1 action(s) sans décision" in par_code["plan_actions"]["libelle"]

    decider_action(session, tid, mid, f"risque:{rid}", "faite")
    bilan = bilan_mission(session, tid, mid)
    par_code = {p["code"]: p for p in bilan["points"]}
    assert par_code["plan_actions"]["statut"] == "ok"
    assert "1 action(s), toutes décidées" in par_code["plan_actions"]["libelle"]
    # Le risque reste ouvert : ce point-là demeure en attention.
    assert par_code["risques_ouverts"]["statut"] == "attention"


def test_api_bilan_mission_cloturee_renvoye_quand_meme(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/bilan-cloture", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut_mission"] == "cloturee"
    assert corps["points"]
    assert corps["note"] == MENTION_NOTE


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"bilan.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Bilan B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/bilan-cloture", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/bilan-cloture")
    assert r.status_code == 401, r.text
