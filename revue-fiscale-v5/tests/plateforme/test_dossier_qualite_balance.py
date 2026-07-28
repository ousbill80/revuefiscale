"""Extension du dossier de synthèse — bloc « qualite_balance »
(21e bloc), facultatif, SYNTHÉTIQUE : projection de la vue consultative
du contrôle qualité de la balance importée, aucun recalcul."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_qualite_balance_declare_dans_blocs_dossier():
    assert "qualite_balance" in BLOCS_DOSSIER


def test_assembler_dossier_bloc_qualite_balance_manquant_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "qualite_balance" in dossier
    assert dossier["qualite_balance"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_bloc_qualite_balance_present_compte():
    bloc = {
        "statut": "observations_a_examiner",
        "equilibree": True,
        "ecart_equilibre": "0",
        "nb_sens_inhabituels": 1,
        "nb_comptes_hors_plan": 0,
        "nb_observations": 1,
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "qualite_balance": bloc}
    )
    assert dossier["qualite_balance"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_bloc_qualite_balance_non_dict_neutralise():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "qualite_balance": "n/a"}
    )
    assert dossier["qualite_balance"] is None
    assert dossier["blocs_disponibles"] == 1


# ── Tests API / DB ─────────────────────────────────────────────────

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

    lib = f"v-dossier-qbal-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-qualite-balance")
    publier_version(session, lib, "dossier-qbal@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.qbal.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier QualiteBalance {email}",
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
                "VALUES (:t, 'PM Dossier QualiteBalance FICTIVE', 'pm') "
                "RETURNING id"
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


def test_api_dossier_bloc_qualite_balance_avec_balance(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '571000', 'Caisse FICTIVE', 0, 250000), "
                "(:t, :m, '601000', 'Achats FICTIFS', 250000, 0)"
            ),
            {"t": tid, "m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Clé TOUJOURS présente, projection SYNTHÉTIQUE du module —
    # balance équilibrée mais caisse créditrice = 1 observation.
    assert "qualite_balance" in corps
    bloc = corps["qualite_balance"]
    assert bloc is not None
    assert bloc["statut"] == "observations_a_examiner"
    assert bloc["equilibree"] is True
    assert bloc["nb_sens_inhabituels"] == 1
    assert bloc["nb_comptes_hors_plan"] == 0
    assert bloc["nb_observations"] == 1
    assert bloc["note"]
    # Projection SYNTHÉTIQUE : jamais le détail des observations.
    assert "sens_inhabituels" not in bloc
    assert "comptes_hors_plan" not in bloc


def test_api_dossier_bloc_qualite_balance_sans_balance(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    bloc = r.json()["qualite_balance"]
    assert bloc is not None
    assert bloc["statut"] == "indisponible"
    assert bloc["nb_observations"] == 0


def test_dossier_tolere_echec_du_module_qualite_balance(
    session, monkeypatch
):
    # Tolérance par bloc : un échec du module qualite_balance donne
    # un bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.qualite_balance as module_qb
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module qualite_balance en échec simulé")

    monkeypatch.setattr(
        module_qb, "vue_qualite_balance_mission", _boom
    )
    dossier = dossier_mission(session, tid, mid)
    assert dossier["qualite_balance"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
