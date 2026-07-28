"""Extension du dossier de synthèse — bloc « evolution_charge_fiscale »
(22e bloc), facultatif, SYNTHÉTIQUE : projection de l'évolution
pluriannuelle consultative de la charge fiscale, aucun recalcul."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_evolution_declare_dans_blocs_dossier():
    assert "evolution_charge_fiscale" in BLOCS_DOSSIER


def test_assembler_dossier_bloc_evolution_manquant_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "evolution_charge_fiscale" in dossier
    assert dossier["evolution_charge_fiscale"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_bloc_evolution_present_compte():
    bloc = {
        "statut": "evolution_disponible",
        "nb_exercices": 3,
        "nb_exercices_disponibles": 2,
        "nb_variations": 1,
        "derniere_variation_sens": "hausse",
        "derniere_variation_relative_pct": "33.3",
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "evolution_charge_fiscale": bloc}
    )
    assert dossier["evolution_charge_fiscale"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_bloc_evolution_non_dict_neutralise():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "evolution_charge_fiscale": "n/a"}
    )
    assert dossier["evolution_charge_fiscale"] is None
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

    lib = f"v-dossier-evolcf-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-evolution-cf")
    publier_version(session, lib, "dossier-evolcf@test.ci")


def _cabinet_et_contribuable(session) -> tuple[int, int, str]:
    _assurer_version(session)
    email = f"dossier.evolcf.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier EvolCF {email}",
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
                "VALUES (:t, 'PM Dossier EvolCF FICTIVE', 'pm') "
                "RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
    return r.tenant_id, int(cid), email


def _mission(session, tenant_id: int, contribuable_id: int,
             exercice: int) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=contribuable_id,
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return int(mid)


def _solde(session, tenant_id: int, mission_id: int, compte: str,
           libelle: str, debit: str, credit: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO solde_compte (tenant_id, mission_id, "
                "compte, libelle, debit, credit) "
                "VALUES (:t, :m, :c, :l, :d, :cr)"
            ),
            {"t": tenant_id, "m": mission_id, "c": compte, "l": libelle,
             "d": debit, "cr": credit},
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


def test_api_dossier_bloc_evolution_deux_exercices(session):
    tid, cid, email = _cabinet_et_contribuable(session)
    mid_2024 = _mission(session, tid, cid, exercice=2024)
    _solde(session, tid, mid_2024, "701", "Ventes FICTIVES",
           "0", "10000000")
    mid_2025 = _mission(session, tid, cid, exercice=2025)
    _solde(session, tid, mid_2025, "701", "Ventes FICTIVES",
           "0", "20000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid_2025}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Clé TOUJOURS présente, projection SYNTHÉTIQUE du module.
    assert "evolution_charge_fiscale" in corps
    bloc = corps["evolution_charge_fiscale"]
    assert bloc is not None
    assert bloc["statut"] == "evolution_disponible"
    assert bloc["nb_exercices"] == 2
    assert bloc["nb_exercices_disponibles"] == 2
    assert bloc["nb_variations"] == 1
    assert bloc["derniere_variation_sens"] in (
        "hausse", "baisse", "stable",
    )
    assert bloc["note"]
    # Projection SYNTHÉTIQUE : ni tableau détaillé ni références.
    assert "exercices" not in bloc
    assert "variations" not in bloc
    assert "references" not in bloc


def test_api_dossier_bloc_evolution_mono_exercice_indisponible(session):
    tid, cid, email = _cabinet_et_contribuable(session)
    mid = _mission(session, tid, cid, exercice=2025)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    bloc = r.json()["evolution_charge_fiscale"]
    assert bloc is not None
    assert bloc["statut"] == "indisponible"
    assert bloc["nb_variations"] == 0
    assert bloc["derniere_variation_sens"] is None


def test_dossier_tolere_echec_du_module_evolution(session, monkeypatch):
    # Tolérance par bloc : un échec du module evolution_charge_fiscale
    # donne un bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.evolution_charge_fiscale as module_ecf
    from backend.plateforme.dossier_mission import dossier_mission

    tid, cid, _email = _cabinet_et_contribuable(session)
    mid = _mission(session, tid, cid, exercice=2025)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module evolution_charge_fiscale en échec")

    monkeypatch.setattr(
        module_ecf, "vue_evolution_charge_fiscale_mission", _boom
    )
    dossier = dossier_mission(session, tid, mid)
    assert dossier["evolution_charge_fiscale"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
