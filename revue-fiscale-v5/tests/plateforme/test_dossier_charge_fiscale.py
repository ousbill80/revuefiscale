"""Extension du dossier de synthèse — bloc « charge_fiscale » (14e
bloc, facultatif, SYNTHÉTIQUE : synthèse du panorama consultatif de la
charge fiscale estimée, aucun recalcul)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_charge_fiscale_declare_dans_blocs_dossier():
    assert "charge_fiscale" in BLOCS_DOSSIER


def test_assembler_dossier_charge_fiscale_manquante_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "charge_fiscale" in dossier
    assert dossier["charge_fiscale"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_charge_fiscale_presente_comptee():
    bloc = {
        "total_charge_propre_estimee": "1300000",
        "composantes_incluses_total": ["patente"],
        "composantes_indisponibles": ["is", "salaires", "tva"],
        "synthese": {"statut": "partiel"},
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "charge_fiscale": bloc}
    )
    assert dossier["charge_fiscale"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_charge_fiscale_non_dict_neutralisee():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "charge_fiscale": "n/a"}
    )
    assert dossier["charge_fiscale"] is None
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

    lib = f"v-dossier-cf-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-charge-fiscale")
    publier_version(session, lib, "dossier-charge-fiscale@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.cf.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier Charge Fiscale {email}",
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
                "VALUES (:t, 'PM Dossier Charge Fiscale FICTIVE', 'pm') "
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


def test_api_dossier_contient_bloc_charge_fiscale_sans_donnees(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # La clé « charge_fiscale » est TOUJOURS présente et le bloc se
    # construit même sans balance ni déclarations (statut explicite,
    # aucun montant inventé).
    assert "charge_fiscale" in corps
    cf = corps["charge_fiscale"]
    assert cf is not None
    assert cf["synthese"]["statut"] == "indisponible"
    assert cf["synthese"]["libelle_statut"]
    assert cf["synthese"]["nb_composantes_disponibles"] == 0
    assert cf["synthese"]["total_partiel"] is True
    assert cf["total_charge_propre_estimee"] == "0"
    assert cf["composantes_incluses_total"] == []
    assert sorted(cf["composantes_indisponibles"]) == sorted(
        ["is", "patente", "salaires", "tva", "acomptes"]
    )
    assert cf["note"]

    # Projection SYNTHÉTIQUE : ni détail des composantes ni références.
    assert "composantes" not in cf
    assert "references" not in cf


def test_api_dossier_charge_fiscale_estimee_depuis_balance(session):
    tid, mid, email = _mission_en_cours(session)
    with contexte_tenant(session, tid):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES (:t, :m, '701000', 'Ventes FICTIVES', 0, 200000000)"
            ),
            {"t": tid, "m": mid},
        )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    cf = r.json()["charge_fiscale"]

    # La patente est estimable depuis la balance (0,5 % de 200 000 000
    # = 1 000 000 FCFA) : panorama partiel, patente incluse au total.
    assert cf["synthese"]["statut"] == "partiel"
    assert cf["synthese"]["nb_composantes_disponibles"] >= 1
    assert "patente" in cf["composantes_incluses_total"]
    assert "patente" not in cf["composantes_indisponibles"]
    assert cf["note"]


def test_dossier_tolere_echec_du_module_charge_fiscale(
    session, monkeypatch
):
    # Tolérance par bloc : un échec du module charge_fiscale donne un
    # bloc None sans jamais bloquer la remise du dossier.
    import backend.plateforme.charge_fiscale as module_cf
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module charge_fiscale en échec simulé")

    monkeypatch.setattr(module_cf, "charge_fiscale_mission", _boom)
    dossier = dossier_mission(session, tid, mid)
    assert dossier["charge_fiscale"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
