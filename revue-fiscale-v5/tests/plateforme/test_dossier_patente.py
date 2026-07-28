"""Extension du dossier de synthèse — bloc « patente » (13e bloc,
facultatif, SYNTHÉTIQUE : synthèse de l'estimation consultative de la
contribution des patentes, aucun recalcul)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_bloc_patente_declare_dans_blocs_dossier():
    assert "patente" in BLOCS_DOSSIER


def test_assembler_dossier_patente_manquante_vaut_none():
    # Assemblage sans le bloc : clé présente, valeur None (contrat
    # stable côté frontend).
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    assert "patente" in dossier
    assert dossier["patente"] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_patente_presente_comptee():
    bloc = {
        "synthese": {"statut": "estimation_partielle"},
        "estimation_totale_partielle": "300000",
        "plancher_applique": True,
        "note": "n",
    }
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "patente": bloc}
    )
    assert dossier["patente"] == bloc
    assert dossier["blocs_disponibles"] == 2


def test_assembler_dossier_patente_non_dict_neutralisee():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "patente": "n/a"}
    )
    assert dossier["patente"] is None
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

    lib = f"v-dossier-pat-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-patente")
    publier_version(session, lib, "dossier-patente@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.pat.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier Patente {email}",
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
                "VALUES (:t, 'PM Dossier Patente FICTIVE', 'pm') "
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


def test_api_dossier_contient_bloc_patente_sans_balance(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # La clé « patente » est TOUJOURS présente et le bloc se construit
    # même sans balance (statut explicite, aucun montant inventé).
    assert "patente" in corps
    pat = corps["patente"]
    assert pat is not None
    assert pat["synthese"]["statut"] == "indisponible"
    assert pat["synthese"]["libelle_statut"]
    assert pat["synthese"]["nb_comptes_ca"] == 0
    assert pat["estimation_totale_partielle"] == "0"
    assert pat["plancher_applique"] is False
    assert pat["note"]

    # Projection SYNTHÉTIQUE : ni détail des comptes ni références.
    assert "comptes_ca" not in pat
    assert "references" not in pat


def test_api_dossier_patente_estimee_depuis_balance(session):
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
    pat = r.json()["patente"]

    # 0,5 % de 200 000 000 = 1 000 000 FCFA (au-dessus du plancher).
    assert pat["synthese"]["statut"] == "estimation_partielle"
    assert pat["synthese"]["nb_comptes_ca"] == 1
    assert pat["estimation_totale_partielle"] == "1000000"
    assert pat["plancher_applique"] is False
    assert pat["note"]


def test_dossier_tolere_echec_du_module_patente(session, monkeypatch):
    # Tolérance par bloc : un échec du module patente donne un bloc
    # None sans jamais bloquer la remise du dossier.
    import backend.plateforme.patente as module_patente
    from backend.plateforme.dossier_mission import dossier_mission

    tid, mid, _email = _mission_en_cours(session)
    session.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("module patente en échec simulé")

    monkeypatch.setattr(module_patente, "vue_patente_mission", _boom)
    dossier = dossier_mission(session, tid, mid)
    assert dossier["patente"] is None
    assert dossier["identite"]["mission_id"] == mid
    assert dossier["note"]
