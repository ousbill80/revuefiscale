"""Lot 2 — statut conclusion + rattachement pièce (API, RBAC, RLS)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.main import app
from backend.plateforme.auth import emettre_jeton, hasher_mot_de_passe
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.provisionnement import (
    derniere_version_publiee,
    provisionner_cabinet,
)

pytestmark = pytest.mark.db


def _skip_si_016_absente(session) -> None:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'conclusion' AND column_name = 'statut'"
        )
    ).scalar_one()
    if n == 0:
        pytest.skip("migration 016 non appliquée — lancez make migrate")


def _assurer_version(session) -> int:
    vid = derniere_version_publiee(session)
    if vid is not None:
        return int(vid)
    from backend.editorial.publication import (
        charger_regle_yaml,
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-concl-{uuid.uuid4().hex[:8]}"
    v = creer_version_brouillon(session, lib, note="conclusion lot2")
    suffix = uuid.uuid4().hex[:6].upper()
    charger_regle_yaml(
        session,
        v,
        {
            "identifiant": f"TST-CONCL-{suffix}",
            "impot": "BIC",
            "reference_legale": "TEST SYNTHETIQUE — non CGI",
            "date_effet": "2026-01-01",
            "profils_applicables": ["reel"],
            "comptes_declencheurs": ["6582"],
            "nature": "permanente",
            "condition_declenchement": "solde(6582) > 0",
            "conditions_fond": "sans objet",
            "formule_plafonnement": "sans objet",
            "questions_generees": [],
            "resultat": "solde(6582)",
            "niveau_risque": "faible",
            "effets_croises": [],
            "a_confirmer": ["test"],
        },
    )
    publier_version(session, lib, "concl@test.ci")
    vid = derniere_version_publiee(session)
    assert vid is not None
    return int(vid)


def _regle_version_id(session, version_id: int) -> int:
    rvid = session.execute(
        text(
            "SELECT id FROM regle_version "
            "WHERE version_referentiel_id = :v ORDER BY id LIMIT 1"
        ),
        {"v": version_id},
    ).scalar_one_or_none()
    if rvid is not None:
        return int(rvid)

    # Version publiée sans règles (CI partielle) : injecte une règle synthétique.
    from backend.editorial.publication import (
        charger_regle_yaml,
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-concl-r-{uuid.uuid4().hex[:8]}"
    v = creer_version_brouillon(session, lib, note="conclusion lot2 regle")
    suffix = uuid.uuid4().hex[:6].upper()
    charger_regle_yaml(
        session,
        v,
        {
            "identifiant": f"TST-CONCL-{suffix}",
            "impot": "BIC",
            "reference_legale": "TEST SYNTHETIQUE — non CGI",
            "date_effet": "2026-01-01",
            "profils_applicables": ["reel"],
            "comptes_declencheurs": ["6582"],
            "nature": "permanente",
            "condition_declenchement": "solde(6582) > 0",
            "conditions_fond": "sans objet",
            "formule_plafonnement": "sans objet",
            "questions_generees": [],
            "resultat": "solde(6582)",
            "niveau_risque": "faible",
            "effets_croises": [],
            "a_confirmer": ["test"],
        },
    )
    publier_version(session, lib, "concl@test.ci")
    rvid = session.execute(
        text(
            "SELECT id FROM regle_version "
            "WHERE version_referentiel_id = :v ORDER BY id LIMIT 1"
        ),
        {"v": v},
    ).scalar_one()
    return int(rvid)


def _inserer_conclusion(
    session,
    *,
    tenant_id: int,
    mission_id: int,
    regle_version_id: int,
    statut: str = "anomalie",
) -> int:
    with contexte_tenant(session, tenant_id):
        exec_id = session.execute(
            text(
                "INSERT INTO execution (tenant_id, mission_id, lancee_par) "
                "VALUES (:t, :m, 'test-lot2') RETURNING id"
            ),
            {"t": tenant_id, "m": mission_id},
        ).scalar_one()
        cid = session.execute(
            text(
                "INSERT INTO conclusion "
                "(tenant_id, execution_id, regle_version_id, montant, sens, "
                "niveau_risque, statut) "
                "VALUES (:t, :e, :rv, 1000, 'reintegration', 'moyen', :st) "
                "RETURNING id"
            ),
            {
                "t": tenant_id,
                "e": exec_id,
                "rv": regle_version_id,
                "st": statut,
            },
        ).scalar_one()
    effacer_contexte_tenant(session)
    return int(cid)


def _inserer_piece(session, *, tenant_id: int, mission_id: int) -> int:
    with contexte_tenant(session, tenant_id):
        pid = session.execute(
            text(
                "INSERT INTO piece_mission "
                "(tenant_id, mission_id, type_piece, role, nom_fichier, "
                "chemin_stockage) "
                "VALUES (:t, :m, 'autre', 'annexe', 'justif.pdf', :chemin) "
                "RETURNING id"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "chemin": f"{tenant_id}/{mission_id}/justif.pdf",
            },
        ).scalar_one()
    effacer_contexte_tenant(session)
    return int(pid)


def _mission_avec_conclusion(session):
    _skip_si_016_absente(session)
    version_id = _assurer_version(session)
    rvid = _regle_version_id(session, version_id)

    email = f"concl.{uuid.uuid4().hex[:8]}@demo.local"
    prov = provisionner_cabinet(
        session,
        denomination=f"Cab Concl {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, prov.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Concl') RETURNING id"
            ),
            {"t": prov.tenant_id},
        ).scalar_one()
        mid = session.execute(
            text(
                "INSERT INTO mission "
                "(tenant_id, contribuable_id, exercice, profil, "
                "version_referentiel_id, statut) "
                "VALUES (:t, :c, 2025, '{}', :v, 'en_cours') RETURNING id"
            ),
            {"t": prov.tenant_id, "c": cid, "v": version_id},
        ).scalar_one()
        lec = session.execute(
            text(
                "INSERT INTO utilisateur "
                "(tenant_id, email, role, password_hash, actif) "
                "VALUES (:t, :e, 'lecteur', :h, TRUE) RETURNING id"
            ),
            {
                "t": prov.tenant_id,
                "e": f"lec.{uuid.uuid4().hex[:8]}@demo.local",
                "h": hasher_mot_de_passe("x"),
            },
        ).scalar_one()
    effacer_contexte_tenant(session)

    conclusion_id = _inserer_conclusion(
        session,
        tenant_id=prov.tenant_id,
        mission_id=int(mid),
        regle_version_id=rvid,
    )
    piece_id = _inserer_piece(
        session, tenant_id=prov.tenant_id, mission_id=int(mid)
    )
    session.commit()
    return {
        "tenant_id": prov.tenant_id,
        "admin_id": prov.utilisateur_id,
        "lecteur_id": int(lec),
        "email": email,
        "mission_id": int(mid),
        "conclusion_id": conclusion_id,
        "piece_id": piece_id,
        "regle_version_id": rvid,
        "version_id": version_id,
    }


def test_patch_conclusion_statut_et_piece_happy_path(session):
    ctx = _mission_avec_conclusion(session)
    jeton = emettre_jeton(
        utilisateur_id=ctx["admin_id"],
        tenant_id=ctx["tenant_id"],
        role="admin",
        email=ctx["email"],
    )
    client = TestClient(app)
    h = {"Authorization": f"Bearer {jeton}"}
    mid = ctx["mission_id"]
    cid = ctx["conclusion_id"]

    get0 = client.get(f"/api/v1/missions/{mid}/conclusions/{cid}", headers=h)
    assert get0.status_code == 200, get0.text
    assert get0.json()["statut"] == "anomalie"
    assert get0.json()["piece_mission_id"] is None

    patch = client.patch(
        f"/api/v1/missions/{mid}/conclusions/{cid}",
        headers=h,
        json={"statut": "conforme", "piece_mission_id": ctx["piece_id"]},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["statut"] == "conforme"
    assert body["piece_mission_id"] == ctx["piece_id"]
    assert body["amendee_par"] == ctx["email"]

    get1 = client.get(f"/api/v1/missions/{mid}/conclusions/{cid}", headers=h)
    assert get1.status_code == 200
    assert get1.json()["statut"] == "conforme"
    assert get1.json()["piece_mission_id"] == ctx["piece_id"]

    clear = client.patch(
        f"/api/v1/missions/{mid}/conclusions/{cid}",
        headers=h,
        json={"piece_mission_id": None},
    )
    assert clear.status_code == 200, clear.text
    assert clear.json()["piece_mission_id"] is None
    assert clear.json()["statut"] == "conforme"


def test_lecteur_lit_mais_ne_patche_pas_conclusion(session):
    ctx = _mission_avec_conclusion(session)
    j_lec = emettre_jeton(
        utilisateur_id=ctx["lecteur_id"],
        tenant_id=ctx["tenant_id"],
        role="lecteur",
        email="lecteur@test.ci",
    )
    j_rev = emettre_jeton(
        utilisateur_id=ctx["admin_id"],
        tenant_id=ctx["tenant_id"],
        role="reviseur",
        email="reviseur@test.ci",
    )
    client = TestClient(app)
    mid = ctx["mission_id"]
    cid = ctx["conclusion_id"]

    assert (
        client.get(
            f"/api/v1/missions/{mid}/conclusions/{cid}",
            headers={"Authorization": f"Bearer {j_lec}"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/missions/{mid}/conclusions/{cid}",
            headers={"Authorization": f"Bearer {j_lec}"},
            json={"statut": "conforme"},
        ).status_code
        == 403
    )
    ok = client.patch(
        f"/api/v1/missions/{mid}/conclusions/{cid}",
        headers={"Authorization": f"Bearer {j_rev}"},
        json={"statut": "non_verifiable"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["statut"] == "non_verifiable"


def test_conclusion_rls_inter_cabinets(session):
    ctx_a = _mission_avec_conclusion(session)
    version_id = ctx_a["version_id"]
    rvid = ctx_a["regle_version_id"]

    email_b = f"conclb.{uuid.uuid4().hex[:8]}@demo.local"
    prov_b = provisionner_cabinet(
        session,
        denomination=f"Cab Concl B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, prov_b.tenant_id):
        cid_b = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client B') RETURNING id"
            ),
            {"t": prov_b.tenant_id},
        ).scalar_one()
        mid_b = session.execute(
            text(
                "INSERT INTO mission "
                "(tenant_id, contribuable_id, exercice, profil, "
                "version_referentiel_id, statut) "
                "VALUES (:t, :c, 2025, '{}', :v, 'en_cours') RETURNING id"
            ),
            {"t": prov_b.tenant_id, "c": cid_b, "v": version_id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    _inserer_conclusion(
        session,
        tenant_id=prov_b.tenant_id,
        mission_id=int(mid_b),
        regle_version_id=rvid,
    )
    session.commit()

    jeton_b = emettre_jeton(
        utilisateur_id=prov_b.utilisateur_id,
        tenant_id=prov_b.tenant_id,
        role="admin",
        email=email_b,
    )
    client = TestClient(app)
    h = {"Authorization": f"Bearer {jeton_b}"}

    # Cabinet B ne voit pas la conclusion du cabinet A
    get_a = client.get(
        f"/api/v1/missions/{ctx_a['mission_id']}/conclusions/{ctx_a['conclusion_id']}",
        headers=h,
    )
    assert get_a.status_code == 404, get_a.text

    patch_a = client.patch(
        f"/api/v1/missions/{ctx_a['mission_id']}/conclusions/{ctx_a['conclusion_id']}",
        headers=h,
        json={"statut": "conforme"},
    )
    assert patch_a.status_code == 404, patch_a.text


def test_piece_hors_mission_refusee(session):
    ctx = _mission_avec_conclusion(session)
    version_id = ctx["version_id"]

    with contexte_tenant(session, ctx["tenant_id"]):
        cid2 = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Autre client') RETURNING id"
            ),
            {"t": ctx["tenant_id"]},
        ).scalar_one()
        mid2 = session.execute(
            text(
                "INSERT INTO mission "
                "(tenant_id, contribuable_id, exercice, profil, "
                "version_referentiel_id, statut) "
                "VALUES (:t, :c, 2025, '{}', :v, 'cadrage') RETURNING id"
            ),
            {"t": ctx["tenant_id"], "c": cid2, "v": version_id},
        ).scalar_one()
    effacer_contexte_tenant(session)
    piece_autre = _inserer_piece(
        session, tenant_id=ctx["tenant_id"], mission_id=int(mid2)
    )
    session.commit()

    jeton = emettre_jeton(
        utilisateur_id=ctx["admin_id"],
        tenant_id=ctx["tenant_id"],
        role="admin",
        email=ctx["email"],
    )
    client = TestClient(app)
    bad = client.patch(
        f"/api/v1/missions/{ctx['mission_id']}/conclusions/{ctx['conclusion_id']}",
        headers={"Authorization": f"Bearer {jeton}"},
        json={"piece_mission_id": piece_autre},
    )
    assert bad.status_code == 400, bad.text
    assert "n'appartient pas" in bad.json()["detail"]
