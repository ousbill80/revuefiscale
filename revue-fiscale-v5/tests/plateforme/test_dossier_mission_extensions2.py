"""Extensions du dossier de synthèse — acomptes IS et rapprochement
des impôts sur salaires (blocs facultatifs SYNTHÉTIQUES)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

NOUVEAUX_BLOCS = ("acomptes", "rapprochement_salaires")

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_nouveaux_blocs_declares_dans_blocs_dossier():
    for cle in NOUVEAUX_BLOCS:
        assert cle in BLOCS_DOSSIER


def test_assembler_dossier_nouveaux_blocs_manquants_valent_none():
    # Assemblage sans les nouveaux blocs : clés présentes, valeur None.
    dossier = assembler_dossier({"identite": {"mission_id": 1}})
    for cle in NOUVEAUX_BLOCS:
        assert cle in dossier
        assert dossier[cle] is None
    assert dossier["blocs_disponibles"] == 1


def test_assembler_dossier_nouveaux_blocs_presents_comptes():
    blocs = {"identite": {"mission_id": 1}}
    blocs.update(
        {cle: {"synthese": {"statut": "x"}} for cle in NOUVEAUX_BLOCS}
    )
    dossier = assembler_dossier(blocs)
    for cle in NOUVEAUX_BLOCS:
        assert dossier[cle] == {"synthese": {"statut": "x"}}
    assert dossier["blocs_disponibles"] == 3


def test_assembler_dossier_bloc_non_dict_neutralise():
    dossier = assembler_dossier(
        {"identite": {"mission_id": 1}, "acomptes": "n/a"}
    )
    assert dossier["acomptes"] is None
    assert dossier["rapprochement_salaires"] is None
    assert dossier["blocs_disponibles"] == 1


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
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-dossier-ext2-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-mission-ext2")
    publier_version(session, lib, "dossier-ext2@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.ext2.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier Ext2 {email}",
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
                "VALUES (:t, 'PM Dossier Ext2 FICTIF', 'pm') RETURNING id"
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


def test_api_dossier_contient_les_deux_nouvelles_cles(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Les 2 nouvelles clés sont TOUJOURS présentes (même à null).
    for cle in NOUVEAUX_BLOCS:
        assert cle in corps

    # Mission sans saisie ni balance : les blocs se construisent quand
    # même (tolérance) avec un statut explicite.
    ac = corps["acomptes"]
    assert ac is not None
    assert ac["synthese"]["statut"] == "indisponible"
    assert ac["position"]["statut"] == "indisponible"
    assert ac["is_du_estime"] is None
    assert ac["totaux_verses"]["total"] == "0"
    assert ac["note"]

    sal = corps["rapprochement_salaires"]
    assert sal is not None
    assert sal["synthese"]["statut"] == "indisponible"
    assert sal["ecarts_significatifs"] == []
    assert sal["note"]


def test_api_dossier_blocs_synthetiques_avec_donnees(session):
    from backend.plateforme.acomptes import saisir_acompte
    from backend.plateforme.rapprochement_salaires import (
        saisir_declaration_salaires,
    )

    tid, mid, email = _mission_en_cours(session)
    saisir_acompte(
        session,
        tid,
        mid,
        "acompte_is",
        "1500000",
        "ext2@test.ci",
        date_versement="2025-04-15",
        reference_quittance="Q-FICTIVE-001",
    )
    saisir_acompte(
        session, tid, mid, "is_du_estime", "2000000", "ext2@test.ci"
    )
    # Déclaration de salaires sans balance : rapprochement indisponible
    # (assumé), mais la période nourrit la synthèse.
    saisir_declaration_salaires(
        session,
        tid,
        mid,
        "2025-03",
        "5000000",
        "400000",
        "60000",
        "ext2@test.ci",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    ac = corps["acomptes"]
    assert ac["synthese"]["nb_versements"] == 1
    assert ac["is_du_estime"] == "2000000.00"
    assert ac["totaux_verses"]["total"] == "1500000.00"
    assert ac["position"]["statut"] == "solde_a_payer"
    assert ac["position"]["montant"] == "500000.00"
    assert ac["position"]["solde_important"] is True
    # Projection synthétique : pas de restitution intégrale.
    assert "acomptes" not in ac
    assert "balance" not in ac

    sal = corps["rapprochement_salaires"]
    assert sal["synthese"]["nb_periodes_declarees"] == 1
    assert "declarations" not in sal
    assert "comptabilise" not in sal

    # Les blocs historiques restent servis (non-régression).
    assert corps["identite"]["mission_id"] == mid
    assert corps["blocs_disponibles"] >= 6
