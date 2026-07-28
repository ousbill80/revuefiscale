"""Contrôle qualité de la balance importée — vue consultative."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.qualite_balance import (
    NB_CONTROLES,
    NOTE_QUALITE_BALANCE,
    PLAFOND_OBSERVATIONS_PAR_CONTROLE,
    STATUT_EQUILIBREE_SANS_OBSERVATION,
    STATUT_INDISPONIBLE,
    STATUT_OBSERVATIONS,
    detecter_comptes_hors_plan,
    detecter_sens_inhabituels,
    evaluer_qualite_balance,
    verifier_equilibre,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _ligne(compte: str, libelle: str, debit: str, credit: str) -> dict:
    return {
        "compte": compte, "libelle": libelle,
        "debit": debit, "credit": credit,
    }


def test_equilibre_ok():
    eq = verifier_equilibre([
        _ligne("601", "Achats", "1000000", "0"),
        _ligne("401100", "Fournisseurs", "0", "1000000"),
    ])
    assert eq["total_debits"] == Decimal("1000000")
    assert eq["total_credits"] == Decimal("1000000")
    assert eq["ecart"] == Decimal("0")
    assert eq["equilibree"] is True


def test_equilibre_ecart_en_montant():
    eq = verifier_equilibre([
        _ligne("601", "Achats", "1000000", "0"),
        _ligne("401100", "Fournisseurs", "0", "999500"),
    ])
    assert eq["ecart"] == Decimal("500")
    assert eq["equilibree"] is False


def test_sens_caisse_57x_creditrice():
    obs = detecter_sens_inhabituels([
        _ligne("571000", "Caisse siège", "0", "250000"),
        _ligne("571100", "Caisse agence", "300000", "0"),
    ])
    assert len(obs) == 1
    assert obs[0]["compte"] == "571000"
    assert obs[0]["libelle_compte"] == "Caisse siège"
    assert obs[0]["solde"] == Decimal("-250000")
    # Non accusatoire : « à examiner », jamais « erreur ».
    assert "examiner" in obs[0]["observation"]
    assert "erreur" not in obs[0]["observation"].lower()


def test_sens_banque_52x_creditrice_libelle_prudent():
    obs = detecter_sens_inhabituels([
        _ligne("521000", "Banque A", "0", "4000000"),
    ])
    assert len(obs) == 1
    # Simple signalement prudent : un découvert bancaire est possible.
    assert "découvert" in obs[0]["observation"]
    assert "erreur" not in obs[0]["observation"].lower()


def test_sens_fournisseur_401x_debiteur():
    obs = detecter_sens_inhabituels([
        _ligne("401200", "Fournisseur X", "150000", "0"),
        _ligne("401300", "Fournisseur Y", "0", "500000"),
    ])
    assert [o["compte"] for o in obs] == ["401200"]
    assert obs[0]["solde"] == Decimal("150000")
    assert "acomptes" in obs[0]["observation"]


def test_sens_client_411x_crediteur():
    obs = detecter_sens_inhabituels([
        _ligne("411100", "Client Z", "0", "80000"),
        _ligne("411200", "Client W", "700000", "0"),
    ])
    assert [o["compte"] for o in obs] == ["411100"]
    assert "avances" in obs[0]["observation"].lower()


def test_sens_amortissements_28x_debiteurs():
    obs = detecter_sens_inhabituels([
        _ligne("284100", "Amort. matériel", "120000", "0"),
        _ligne("284200", "Amort. mobilier", "0", "900000"),
    ])
    assert [o["compte"] for o in obs] == ["284100"]


def test_sens_capital_101x_debiteur():
    obs = detecter_sens_inhabituels([
        _ligne("101000", "Capital social", "5000000", "0"),
    ])
    assert len(obs) == 1
    assert obs[0]["compte"] == "101000"
    assert "examiner" in obs[0]["observation"]


def test_sens_habituels_aucune_observation():
    # Sens habituels : caisse débitrice, fournisseur créditeur, client
    # débiteur, amortissement créditeur, capital créditeur — rien.
    assert detecter_sens_inhabituels([
        _ligne("571000", "Caisse", "100", "0"),
        _ligne("521000", "Banque", "200", "0"),
        _ligne("401100", "Fournisseurs", "0", "300"),
        _ligne("411100", "Clients", "400", "0"),
        _ligne("284100", "Amortissements", "0", "500"),
        _ligne("101000", "Capital", "0", "600"),
    ]) == []


def test_hors_plan_classe_et_longueur():
    obs = detecter_comptes_hors_plan([
        _ligne("0AB", "Compte étrange", "10", "0"),
        _ligne("X9", "Compte lettre", "0", "10"),
        _ligne("6011234567890", "Numéro trop long", "5", "0"),
        _ligne("601000", "Achats normaux", "100", "0"),
    ])
    assert [o["compte"] for o in obs] == [
        "0AB", "X9", "6011234567890",
    ]
    assert all("examiner" in o["observation"] for o in obs)
    assert all("erreur" not in o["observation"].lower() for o in obs)


def test_plafond_observations_par_controle():
    lignes = [
        _ligne(f"5710{i:03d}", f"Caisse {i}", "0", "1000")
        for i in range(PLAFOND_OBSERVATIONS_PAR_CONTROLE + 10)
    ]
    vue = evaluer_qualite_balance(lignes)
    sens = vue["sens_inhabituels"]
    assert len(sens["observations"]) == PLAFOND_OBSERVATIONS_PAR_CONTROLE
    # Le total détecté n'est jamais masqué.
    assert sens["nb_total"] == PLAFOND_OBSERVATIONS_PAR_CONTROLE + 10
    assert sens["plafonne"] is True


def test_vue_equilibree_sans_observation():
    vue = evaluer_qualite_balance([
        _ligne("601000", "Achats", "1000000", "0"),
        _ligne("401100", "Fournisseurs", "0", "1000000"),
    ])
    assert vue["disponible"] is True
    assert vue["statut"] == STATUT_EQUILIBREE_SANS_OBSERVATION
    assert vue["equilibre"]["equilibree"] is True
    assert vue["synthese"]["nb_observations"] == 0
    assert vue["synthese"]["nb_controles"] == NB_CONTROLES


def test_vue_observations_a_examiner_compte_ecart():
    # Écart d'équilibre + une caisse créditrice = 2 observations.
    vue = evaluer_qualite_balance([
        _ligne("571000", "Caisse", "0", "250000"),
        _ligne("601000", "Achats", "250500", "0"),
    ])
    assert vue["statut"] == STATUT_OBSERVATIONS
    assert vue["equilibre"]["ecart"] == "500"
    assert vue["synthese"]["nb_observations"] == 2


def test_vue_indisponible_sans_balance():
    vue = evaluer_qualite_balance([])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["equilibre"]["ecart"] == "0"
    assert vue["sens_inhabituels"]["observations"] == []
    assert vue["comptes_hors_plan"]["observations"] == []


def test_cles_stables_et_montants_str():
    cles = {
        "disponible", "equilibre", "sens_inhabituels",
        "comptes_hors_plan", "statut", "synthese", "note",
    }
    for vue in (
        evaluer_qualite_balance([]),
        evaluer_qualite_balance([
            _ligne("571000", "Caisse", "0", "250000"),
        ]),
    ):
        assert cles <= set(vue)
        assert isinstance(vue["equilibre"]["total_debits"], str)
        assert isinstance(vue["equilibre"]["total_credits"], str)
        assert isinstance(vue["equilibre"]["ecart"], str)
        assert all(
            isinstance(o["solde"], str)
            for o in vue["sens_inhabituels"]["observations"]
        )
        assert vue["note"] == NOTE_QUALITE_BALANCE
        assert vue["synthese"]["statut"] == vue["statut"]


def test_note_consultative_non_accusatoire():
    assert "orientent" in NOTE_QUALITE_BALANCE.lower() or (
        "oriente" in NOTE_QUALITE_BALANCE.lower()
    )
    assert "découvert bancaire" in NOTE_QUALITE_BALANCE
    assert "avoirs" in NOTE_QUALITE_BALANCE
    assert "acomptes" in NOTE_QUALITE_BALANCE
    assert "conclut" in NOTE_QUALITE_BALANCE
    assert "erreur" not in NOTE_QUALITE_BALANCE.lower()


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

    lib = f"v-qbal-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="qualite balance")
    publier_version(session, lib, "qbal@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"qbal.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab QualiteBalance {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _contribuable(session, tenant_id: int, nom: str) -> int:
    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
    return int(cid)


def _mission(session, tenant_id: int, contribuable_id: int,
             exercice: int = 2025) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=contribuable_id,
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
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


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/qualite-balance"


def test_api_structure_complete(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM QualiteBalance FICTIVE")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "571000", "Caisse FICTIVE", "0", "250000")
    _solde(session, tid, mid, "601000", "Achats FICTIFS", "250000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["equilibre"]["equilibree"] is True
    assert corps["statut"] == "observations_a_examiner"
    obs = corps["sens_inhabituels"]["observations"]
    assert len(obs) == 1
    assert obs[0]["compte"] == "571000"
    assert "examiner" in obs[0]["observation"]
    assert corps["synthese"]["nb_observations"] == 1
    assert "consultati" in corps["note"].lower()


def test_api_tolerance_sans_balance(session):
    # Tolérance : sans balance, la vue se sert quand même —
    # disponible=false, clés stables, aucune observation inventée.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM QualiteBalance Vide FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["sens_inhabituels"]["observations"] == []
    assert corps["comptes_hors_plan"]["observations"] == []
    assert corps["note"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM QualiteBalance Journal FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(mid), headers=h).status_code == 200

    with contexte_tenant(session, tid):
        actions = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT action FROM journal_audit "
                    "WHERE mission_id = :m "
                    "AND action = 'consultation_qualite_balance'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_qualite_balance" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM QualiteBalance Cross FICTIVE")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
