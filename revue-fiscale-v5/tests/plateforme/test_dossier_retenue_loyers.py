"""Extension du dossier de synthèse — bloc « retenue_loyers »
(17e bloc), facultatif, SYNTHÉTIQUE : projection de la vue consultative
de la retenue à la source sur loyers, aucun recalcul."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_retenue_loyers_declare_dans_blocs_dossier():
    assert "retenue_loyers" in BLOCS_DOSSIER


def test_assembler_dossier_bloc_retenue_loyers_manquant_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "retenue_loyers" in dossier
    assert dossier["retenue_loyers"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_bloc_retenue_loyers_present_compte():
    bloc = {
        "statut": "a_qualifier",
        "loyers_bruts": "12000000.00",
        "taux_indicatif": "0.15",
        "retenue_theorique_max": "1800000",
        "repartition_calculable": False,
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "retenue_loyers": bloc}
    )
    assert dossier["retenue_loyers"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_bloc_retenue_loyers_non_dict_neutralise():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "retenue_loyers": "n/a"}
    )
    assert dossier["retenue_loyers"] is None
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

    lib = f"v-dossier-rloy-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-retenue-loyers")
    publier_version(session, lib, "dossier-rloy@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.rloy.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier RetenueLoyers {email}",
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
                "VALUES (:t, 'PM Dossier RetenueLoyers FICTIVE', 'pm') "
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


def test_api_dossier_bloc_retenue_loyers_avec_balance(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '6221', 'Location siège FICTIVE', "
                "12000000, 0)"
            ),
            {"t": tid, "m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Clé TOUJOURS présente, projection SYNTHÉTIQUE du module —
    # 12 000 000 × 15 % = 1 800 000 (maximum théorique indicatif).
    assert "retenue_loyers" in corps
    bloc = corps["retenue_loyers"]
    assert bloc is not None
    assert bloc["statut"] == "a_qualifier"
    assert bloc["loyers_bruts"] == "12000000.00"
    assert bloc["taux_indicatif"] == "0.15"
    assert bloc["retenue_theorique_max"] == "1800000"
    assert bloc["repartition_calculable"] is False
    assert bloc["note"]
    # Projection SYNTHÉTIQUE : ni détail des comptes ni références.
    assert "comptes_loyers" not in bloc
    assert "references" not in bloc


def test_api_dossier_bloc_retenue_loyers_sans_balance(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    bloc = r.json()["retenue_loyers"]
    assert bloc is not None
    assert bloc["statut"] == "indisponible"
    assert bloc["loyers_bruts"] == "0"
    assert bloc["retenue_theorique_max"] == "0"


def test_dossier_tolere_echec_du_module_retenue_loyers(
    session, monkeypatch
):
    # Tolérance par bloc : un échec du module retenue_loyers donne un
    # bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.retenue_loyers as module_rl
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module retenue_loyers en échec simulé")

    monkeypatch.setattr(module_rl, "vue_retenue_loyers_mission", _boom)
    dossier = dossier_mission(session, tid, mid)
    assert dossier["retenue_loyers"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
