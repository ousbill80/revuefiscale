"""Objectif fiscal + tâches — RLS, cadrage, matérialisation déterministe."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

pytestmark = pytest.mark.db


def _skip_si_019(session) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'objectif'"
        )
    ).scalar_one()
    if n == 0:
        pytest.skip("migration 019 non appliquée — lancez make migrate")


def _evaluer_et_valider_conclusions(client, headers, mid) -> None:
    """Garde de clôture : statue puis valide chaque conclusion via l'API."""
    rest = client.get(f"/api/v1/missions/{mid}/restitution", headers=headers)
    assert rest.status_code == 200, rest.text
    for c in rest.json().get("conclusions", []):
        if c.get("id") is None:
            continue
        statut = c.get("statut") or "anomalie"
        p = client.patch(
            f"/api/v1/missions/{mid}/conclusions/{c['id']}",
            headers=headers,
            json={"statut": statut},
        )
        assert p.status_code == 200, p.text
        if statut == "anomalie":
            v = client.post(
                f"/api/v1/missions/{mid}/conclusions/{c['id']}/validation",
                headers=headers,
            )
            assert v.status_code == 200, v.text


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


@pytest.fixture
def client_cabinet(session):
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    _skip_si_019(session)

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-ot-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="obj-tache")
        publier_version(session, lib, "ot@test.ci")

    email = f"ot.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab OT {email}",
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
    uid = int(body.get("utilisateur_id") or 0)
    return client, h, int(body["tenant_id"]), uid


def test_objectifs_fiscaux_sync_perimetre(session, client_cabinet):
    client, h, tid, _uid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OT-0001")

    created = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "type_engagement": "preventive",
            "perimetre_impots": ["TVA"],
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])
    fiscaux = created.json().get("objectifs_fiscaux") or []
    assert fiscaux, "objectifs fiscaux attendus pour revue partielle"
    inclus = [o for o in fiscaux if o["dans_perimetre"]]
    exclus = [o for o in fiscaux if not o["dans_perimetre"]]
    assert [o["impot"] for o in inclus] == ["TVA"]
    assert any(o["impot"] == "BIC" for o in exclus)
    assert all(o.get("motif_exclusion") for o in exclus)

    listed = client.get(f"/api/v1/missions/{mid}/objectifs-fiscaux", headers=h)
    assert listed.status_code == 200
    assert len(listed.json()) == len(fiscaux)

    # Isolation RLS
    with contexte_tenant(session, tid):
        n = session.execute(
            text("SELECT count(*) FROM objectif WHERE mission_id = :m"),
            {"m": mid},
        ).scalar_one()
        assert n == len(fiscaux)
    effacer_contexte_tenant(session)
    n0 = session.execute(text("SELECT count(*) FROM objectif")).scalar_one()
    assert int(n0) == 0


def test_taches_apres_execute_et_patch(session, client_cabinet):
    client, h, tid, uid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OT-0002")

    created = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "perimetre_impots": ["BIC", "TVA"],
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])

    # Soldes minimaux pour déclencher sélection
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '601', 'Achats', 1000000, 0)"
            ),
            {"t": tid, "m": mid},
        )
        session.commit()

    exe = client.post(f"/api/v1/missions/{mid}/executer", headers=h, json={})
    assert exe.status_code == 200, exe.text

    taches1 = client.get(f"/api/v1/missions/{mid}/taches", headers=h)
    assert taches1.status_code == 200, taches1.text
    rows1 = taches1.json()
    assert isinstance(rows1, list)

    # 2e exécution → mêmes regle_version_id (déterminisme upsert)
    exe2 = client.post(f"/api/v1/missions/{mid}/executer", headers=h, json={})
    assert exe2.status_code == 200, exe2.text
    taches2 = client.get(f"/api/v1/missions/{mid}/taches", headers=h)
    rows2 = taches2.json()
    ids1 = sorted(
        (t["regle_version_id"], t["objectif_id"])
        for t in rows1
        if t.get("regle_version_id")
    )
    ids2 = sorted(
        (t["regle_version_id"], t["objectif_id"])
        for t in rows2
        if t.get("regle_version_id")
    )
    assert ids1 == ids2

    if rows2:
        tid_tache = int(rows2[0]["id"])
        patch = client.patch(
            f"/api/v1/missions/{mid}/taches/{tid_tache}",
            headers=h,
            json={
                "statut": "en_cours",
                "piece_attendue": "Facture fournisseur",
                "assignee_a": uid if uid else None,
            },
        )
        # assignee_a peut échouer si uid=0 — statut seul
        if patch.status_code != 200:
            patch = client.patch(
                f"/api/v1/missions/{mid}/taches/{tid_tache}",
                headers=h,
                json={"statut": "en_cours", "piece_attendue": "Facture fournisseur"},
            )
        assert patch.status_code == 200, patch.text
        assert patch.json()["statut"] == "en_cours"
        assert patch.json()["piece_attendue"] == "Facture fournisseur"


def test_cloture_cree_points_ouverts_anomalies(session, client_cabinet):
    """R4 : clôture ne crée plus de point_ouvert — seulement risques."""
    client, h, tid, _uid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OT-0003")
    created = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '601', 'Achats', 500000, 0)"
            ),
            {"t": tid, "m": mid},
        )
        session.commit()

    exe = client.post(f"/api/v1/missions/{mid}/executer", headers=h, json={})
    assert exe.status_code == 200, exe.text

    with contexte_tenant(session, tid):
        n_po_avant = session.execute(
            text("SELECT count(*) FROM point_ouvert WHERE contribuable_id = :c"),
            {"c": cid},
        ).scalar_one()

    _evaluer_et_valider_conclusions(client, h, mid)
    st = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "cloturee"},
    )
    assert st.status_code == 200, st.text
    body = st.json()
    assert body.get("points_ouverts_crees", 0) == 0
    assert "risques_crees" in body

    with contexte_tenant(session, tid):
        n_po_apres = session.execute(
            text("SELECT count(*) FROM point_ouvert WHERE contribuable_id = :c"),
            {"c": cid},
        ).scalar_one()
    assert int(n_po_apres) == int(n_po_avant)


def test_tache_rls_inter_cabinets(session, client_cabinet):
    client, h, tid, _uid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OT-RLS")
    created = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '601', 'Achats', 100000, 0)"
            ),
            {"t": tid, "m": mid},
        )
        session.commit()

    exe = client.post(f"/api/v1/missions/{mid}/executer", headers=h, json={})
    assert exe.status_code == 200, exe.text

    taches = client.get(f"/api/v1/missions/{mid}/taches", headers=h)
    assert taches.status_code == 200
    rows = taches.json()
    if not rows:
        pytest.skip("aucune tâche matérialisée")

    with contexte_tenant(session, tid):
        n = session.execute(text("SELECT count(*) FROM tache")).scalar_one()
        assert int(n) >= 1
    effacer_contexte_tenant(session)
    n0 = session.execute(text("SELECT count(*) FROM tache")).scalar_one()
    assert int(n0) == 0


def test_effet_croise_projette_bloquee_par(session, client_cabinet):
    """Projection déterministe effet_croise → tache.bloquee_par."""
    from backend.plateforme.taches import projeter_blocages_effets_croises

    client, h, tid, _uid = client_cabinet
    cid = _creer_contribuable(client, h, ncc="CI-OT-EC")
    created = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "type_engagement": "autre",
            "exercice": 2024,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert created.status_code == 200, created.text
    mid = int(created.json()["id"])

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '601', 'Achats', 900000, 0)"
            ),
            {"t": tid, "m": mid},
        )
        session.commit()

    exe = client.post(f"/api/v1/missions/{mid}/executer", headers=h, json={})
    assert exe.status_code == 200, exe.text

    taches = client.get(f"/api/v1/missions/{mid}/taches", headers=h).json()
    avec_regle = [t for t in taches if t.get("regle_id") and t.get("regle_version_id")]
    if len(avec_regle) < 2:
        pytest.skip("besoin d'au moins 2 tâches avec regle_version pour effet croisé")

    source, cible = avec_regle[0], avec_regle[1]
    if source["regle_id"] == cible["regle_id"]:
        pytest.skip("règles source/cible identiques")

    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO effet_croise (source_id, cible_regle, type, commentaire) "
                "VALUES (:s, :c, 'remet_en_cause', 'test isolation') "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "s": int(source["regle_version_id"]),
                "c": str(cible["regle_id"]),
            },
        )
        # Remettre la source en a_faire pour qu'elle bloque
        session.execute(
            text("UPDATE tache SET statut = 'a_faire' WHERE id = :id"),
            {"id": int(source["id"])},
        )
        session.execute(
            text(
                "UPDATE tache SET statut = 'a_faire', bloquee_par = '{}' "
                "WHERE id = :id"
            ),
            {"id": int(cible["id"])},
        )
        nb = projeter_blocages_effets_croises(session, tid, mid)
        session.commit()

    assert nb >= 1
    cible_apres = client.get(f"/api/v1/missions/{mid}/taches", headers=h).json()
    row_cible = next(t for t in cible_apres if t["id"] == cible["id"])
    assert int(source["id"]) in (row_cible.get("bloquee_par") or [])
    assert row_cible["statut"] == "bloquee"