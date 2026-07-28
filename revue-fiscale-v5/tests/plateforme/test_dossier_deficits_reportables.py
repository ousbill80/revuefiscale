"""Extension du dossier de synthèse — bloc « deficits_reportables »
(18e bloc), facultatif, SYNTHÉTIQUE : projection du suivi pluriannuel
consultatif des déficits reportables, aucun recalcul."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_deficits_reportables_declare_dans_blocs_dossier():
    assert "deficits_reportables" in BLOCS_DOSSIER


def test_assembler_dossier_bloc_deficits_manquant_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "deficits_reportables" in dossier
    assert dossier["deficits_reportables"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_bloc_deficits_present_compte():
    bloc = {
        "statut": "deficits_a_suivre",
        "nb_exercices": 2,
        "nb_deficits_constates": 1,
        "cumul_indicatif_final": "6000000.00",
        "approximation": True,
        "imputation_reelle_calculable": False,
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "deficits_reportables": bloc}
    )
    assert dossier["deficits_reportables"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_bloc_deficits_non_dict_neutralise():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "deficits_reportables": "n/a"}
    )
    assert dossier["deficits_reportables"] is None
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

    lib = f"v-dossier-defrep-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-deficits")
    publier_version(session, lib, "dossier-defrep@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.defrep.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier DeficitsRep {email}",
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
                "VALUES (:t, 'PM Dossier DeficitsRep FICTIVE', 'pm') "
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


def test_api_dossier_bloc_deficits_avec_balance_deficitaire(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        # Charges 10 M > produits 4 M : déficit théorique de 6 M.
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '601', 'Achats FICTIFS', 10000000, 0), "
                "(:t, :m, '701', 'Ventes FICTIVES', 0, 4000000)"
            ),
            {"t": tid, "m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Clé TOUJOURS présente, projection SYNTHÉTIQUE du module.
    assert "deficits_reportables" in corps
    bloc = corps["deficits_reportables"]
    assert bloc is not None
    assert bloc["statut"] == "deficits_a_suivre"
    assert bloc["nb_exercices"] == 1
    assert bloc["nb_deficits_constates"] == 1
    assert bloc["approximation"] is True
    assert bloc["imputation_reelle_calculable"] is False
    assert bloc["note"]
    # Projection SYNTHÉTIQUE : ni tableau détaillé ni références.
    assert "exercices" not in bloc
    assert "references" not in bloc


def test_api_dossier_bloc_deficits_sans_balance(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    bloc = r.json()["deficits_reportables"]
    assert bloc is not None
    assert bloc["statut"] == "indisponible"
    assert bloc["cumul_indicatif_final"] == "0"


def test_dossier_tolere_echec_du_module_deficits(session, monkeypatch):
    # Tolérance par bloc : un échec du module deficits_reportables
    # donne un bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.deficits_reportables as module_dr
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module deficits_reportables en échec simulé")

    monkeypatch.setattr(
        module_dr, "vue_deficits_reportables_mission", _boom
    )
    dossier = dossier_mission(session, tid, mid)
    assert dossier["deficits_reportables"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
