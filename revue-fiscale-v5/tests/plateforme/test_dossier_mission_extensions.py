"""Extensions du dossier de synthèse — rapprochement TVA, contrôles
fiscaux et matérialité (blocs facultatifs SYNTHÉTIQUES)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.dossier_mission import (
    BLOCS_DOSSIER,
    assembler_dossier,
)

NOUVEAUX_BLOCS = ("rapprochement_tva", "controles_fiscaux", "materialite")

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
    blocs.update({cle: {"synthese": {"statut": "x"}} for cle in NOUVEAUX_BLOCS})
    dossier = assembler_dossier(blocs)
    for cle in NOUVEAUX_BLOCS:
        assert dossier[cle] == {"synthese": {"statut": "x"}}
    assert dossier["blocs_disponibles"] == 4


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

    lib = f"v-dossier-ext-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="dossier-mission-ext")
    publier_version(session, lib, "dossier-ext@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"dossier.ext.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Dossier Ext {email}",
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
                "VALUES (:t, 'PM Dossier Ext FICTIF', 'pm') RETURNING id"
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


def test_api_dossier_contient_les_trois_nouvelles_cles(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Les 3 nouvelles clés sont TOUJOURS présentes (même à null).
    for cle in NOUVEAUX_BLOCS:
        assert cle in corps

    # Mission sans donnée TVA/contrôle/balance : les blocs se
    # construisent quand même (tolérance) avec un statut explicite.
    tva = corps["rapprochement_tva"]
    assert tva is not None
    assert tva["synthese"]["statut"] == "indisponible"
    assert tva["ecarts_significatifs"] == []
    assert tva["note"]

    ctrl = corps["controles_fiscaux"]
    assert ctrl is not None
    assert ctrl["synthese"]["statut"] == "aucun_evenement"
    assert ctrl["echeances_a_surveiller"] == []
    assert ctrl["note"]

    mat = corps["materialite"]
    assert mat is not None
    assert mat["synthese"]["statut"] == "indisponible"
    assert mat["seuil_retenu"] is None
    assert mat["couverture"]["taux_global"] is not None
    assert mat["note"]


def test_api_dossier_blocs_synthetiques_avec_donnees(session):
    from backend.plateforme.controles_fiscaux import consigner_evenement
    from backend.plateforme.rapprochement_tva import saisir_declaration_tva

    tid, mid, email = _mission_en_cours(session)
    # TVA déclarée sans balance : rapprochement indisponible (assumé),
    # mais l'événement de contrôle nourrit la chronologie.
    saisir_declaration_tva(
        session, tid, mid, "2025-03", "1000000", "400000", "ext@test.ci"
    )
    consigner_evenement(
        session,
        tid,
        mid,
        "notification_redressement",
        "2020-01-15",
        "2500000",
        "Notification FICTIVE",
        "ext@test.ci",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/dossier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    tva = corps["rapprochement_tva"]
    assert tva["synthese"]["nb_periodes_declarees"] == 1
    # Projection synthétique : pas de restitution intégrale.
    assert "declarations" not in tva
    assert "comptabilise" not in tva

    ctrl = corps["controles_fiscaux"]
    assert ctrl["synthese"]["statut"] == "echeances_depassees"
    assert ctrl["synthese"]["montant_total_en_jeu"] == "2500000.00"
    surveiller = ctrl["echeances_a_surveiller"]
    assert len(surveiller) == 1
    assert surveiller[0]["statut"] == "depassee"
    assert surveiller[0]["echeance"] == "2020-02-14"
    assert "evenements" not in ctrl
    assert "types_evenement" not in ctrl

    mat = corps["materialite"]
    assert "propositions" not in mat
    assert "comptes_cibles" not in mat

    # Les blocs historiques restent servis (non-régression).
    assert corps["identite"]["mission_id"] == mid
    assert corps["blocs_disponibles"] >= 6
