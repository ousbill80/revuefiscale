"""Extension du dossier de synthèse — bloc « rapprochement_acomptes »
(19e bloc), facultatif, SYNTHÉTIQUE : projection du rapprochement
consultatif acomptes saisis / IS théorique, aucun recalcul."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_rapprochement_acomptes_declare_dans_blocs_dossier():
    assert "rapprochement_acomptes" in BLOCS_DOSSIER


def test_assembler_dossier_bloc_rapprochement_manquant_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "rapprochement_acomptes" in dossier
    assert dossier["rapprochement_acomptes"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_bloc_rapprochement_present_compte():
    bloc = {
        "statut": "solde_a_payer_indicatif",
        "is_theorique": "3750000",
        "total_acomptes_saisis": "1000000.00",
        "nb_versements": 1,
        "solde_indicatif": "2750000.00",
        "solde_signe": "2750000.00",
        "approximation": True,
        "minimum_perception_calculable": False,
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "rapprochement_acomptes": bloc}
    )
    assert dossier["rapprochement_acomptes"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_bloc_rapprochement_non_dict_neutralise():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "rapprochement_acomptes": "n/a"}
    )
    assert dossier["rapprochement_acomptes"] is None
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

    lib = f"v-dossier-rapacptes-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-rapacptes")
    publier_version(session, lib, "dossier-rapacptes@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.rapacptes.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier RapAcptes {email}",
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
                "VALUES (:t, 'PM Dossier RapAcptes FICTIVE', 'pm') "
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


def test_api_dossier_bloc_rapprochement_avec_balance(session):
    from backend.plateforme.acomptes import saisir_acompte

    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        # Produits 20 M - charges 5 M : IS théorique 3 750 000.
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '701', 'Ventes FICTIVES', 0, 20000000), "
                "(:t, :m, '601', 'Achats FICTIFS', 5000000, 0)"
            ),
            {"t": tid, "m": mid},
        )
    saisir_acompte(
        session, tid, mid, "acompte_is", "1000000",
        acteur="dossier-rapacptes@test.ci",
        date_versement="2025-04-10",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Clé TOUJOURS présente, projection SYNTHÉTIQUE du module.
    assert "rapprochement_acomptes" in corps
    bloc = corps["rapprochement_acomptes"]
    assert bloc is not None
    assert bloc["statut"] == "solde_a_payer_indicatif"
    assert bloc["is_theorique"] == "3750000"
    assert bloc["nb_versements"] == 1
    assert bloc["approximation"] is True
    assert bloc["minimum_perception_calculable"] is False
    assert bloc["note"]
    # Projection SYNTHÉTIQUE : ni détail des versements ni références.
    assert "acomptes" not in bloc
    assert "references" not in bloc


def test_api_dossier_bloc_rapprochement_sans_balance(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    bloc = r.json()["rapprochement_acomptes"]
    assert bloc is not None
    assert bloc["statut"] == "indisponible"
    assert bloc["is_theorique"] is None


def test_dossier_tolere_echec_du_module_rapprochement(session, monkeypatch):
    # Tolérance par bloc : un échec du module rapprochement_acomptes
    # donne un bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.rapprochement_acomptes as module_ra
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module rapprochement_acomptes en échec simulé")

    monkeypatch.setattr(
        module_ra, "vue_rapprochement_acomptes_mission", _boom
    )
    dossier = dossier_mission(session, tid, mid)
    assert dossier["rapprochement_acomptes"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
