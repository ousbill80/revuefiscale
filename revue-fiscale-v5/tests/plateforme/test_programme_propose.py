"""Pont consultatif matérialité / risques → programme de travail."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.programme_propose import (
    NOTE_PROGRAMME_PROPOSE,
    STATUT_AUCUNE_PROPOSITION,
    STATUT_PROPOSITIONS,
    STATUT_SEUIL_A_RETENIR,
    construire_vue_programme_propose,
    marquer_deja_couvertes,
    proposer_depuis_comptes,
    proposer_depuis_risques,
    regle_pour_compte,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _cible(compte: str, libelle: str = "") -> dict:
    return {"compte": compte, "libelle": libelle, "classe": compte[:1],
            "solde": "0"}


def test_regle_prefixe_le_plus_long_gagne():
    # 70x → revue du CA, pas la règle générique classe 7.
    assert regle_pour_compte("7011")[1] == "PRO-CA"
    # 77x → règle générique classe 7 (autres produits).
    assert regle_pour_compte("7711")[1] == "PRO-PRODUITS"
    # 44x → comptes d'État, pas la règle générique classe 4.
    assert regle_pour_compte("4451")[1] == "PRO-ETAT"
    # 45x → règle générique tiers.
    assert regle_pour_compte("4511")[1] == "PRO-TIERS"
    # Compte vide ou classe sans règle (9) → None.
    assert regle_pour_compte("") is None
    assert regle_pour_compte("9011") is None


def test_mapping_diligences_types_fiscaliste():
    par_compte = {
        "7011": "PRO-CA",        # CA → assiettes déclaratives TVA/IS
        "4421": "PRO-ETAT",      # État → rapprochements déclaratifs
        "6611": "PRO-REMU",      # rémunérations → ITS, charges sociales
        "4211": "PRO-REMU",      # personnel → même diligence
        "2411": "PRO-IMMO",      # immobilisations → amortissements, TVA
        "3111": "PRO-STOCK",
        "4011": "PRO-FRS",
        "4111": "PRO-CLI",
        "5211": "PRO-TRESO",
        "6011": "PRO-CHARGES",
        "1611": "PRO-FIN",
    }
    for compte, code in par_compte.items():
        assert regle_pour_compte(compte)[1] == code, compte


def test_proposer_depuis_comptes_deduplication_et_justification():
    cibles = [_cible("7011"), _cible("7071"), _cible("4421"),
              _cible("6611"), _cible("4211"), _cible("9011")]
    props = proposer_depuis_comptes(cibles)
    codes = [p["code"] for p in props]
    # Une seule revue du CA malgré deux comptes 70x ; une seule revue
    # des rémunérations pour 66x + 42x ; le compte 9 est ignoré.
    assert codes == ["PRO-CA", "PRO-ETAT", "PRO-REMU"]
    par_code = {p["code"]: p for p in props}
    assert par_code["PRO-CA"]["comptes"] == ["7011", "7071"]
    assert "7011, 7071" in par_code["PRO-CA"]["justification"]
    assert par_code["PRO-REMU"]["comptes"] == ["6611", "4211"]
    assert par_code["PRO-CA"]["libelle"] == (
        "Revue du chiffre d'affaires et des assiettes déclaratives "
        "(TVA/IS)"
    )
    assert all(p["origine"] == "materialite" for p in props)
    assert all(p["phase"] == "controles" for p in props)


def test_proposer_depuis_risques_par_impot():
    risques = [
        {"impot": "TVA", "libelle": "TVA déductible non justifiée",
         "statut": "ouvert"},
        {"impot": "TVA", "libelle": "Prorata erroné",
         "statut": "en_traitement"},
        {"impot": "ITS", "libelle": "Avantages en nature omis",
         "statut": "ouvert"},
        {"impot": "", "libelle": "Sans impôt", "statut": "ouvert"},
    ]
    props = proposer_depuis_risques(risques)
    assert [p["code"] for p in props] == ["PRO-RSQ-ITS", "PRO-RSQ-TVA"]
    par_code = {p["code"]: p for p in props}
    assert par_code["PRO-RSQ-TVA"]["phase"] == "suivi"
    assert par_code["PRO-RSQ-TVA"]["origine"] == "risques"
    assert "2 risques non clos" in par_code["PRO-RSQ-TVA"]["justification"]
    assert "Prorata erroné" in par_code["PRO-RSQ-TVA"]["justification"]
    assert par_code["PRO-RSQ-ITS"]["libelle"] == (
        "Revue du traitement des risques ouverts — ITS"
    )


def test_marquer_deja_couvertes_par_code_et_libelle():
    props = proposer_depuis_comptes([_cible("7011"), _cible("2411")])
    existantes = [
        # Même code (marqueur d'origine d'une acceptation antérieure).
        {"code": "PRO-CA", "libelle": "Autre libellé"},
        # Même libellé (normalisé), code différent.
        {"code": "CTL-99", "libelle": (
            "  revue des immobilisations, amortissements et "
            "TVA immobilisée "
        )},
    ]
    marquees = marquer_deja_couvertes(props, existantes)
    par_code = {p["code"]: p for p in marquees}
    assert par_code["PRO-CA"]["deja_couverte"] is True
    assert par_code["PRO-IMMO"]["deja_couverte"] is True
    # Aucune mutation des propositions d'origine.
    assert all("deja_couverte" not in p for p in props)
    # Sans recouvrement : non couverte.
    libres = marquer_deja_couvertes(props, [{"code": "CAD-01",
                                             "libelle": "Lettre"}])
    assert all(p["deja_couverte"] is False for p in libres)


def test_construire_vue_cles_stables_et_statuts():
    cles = {"seuil_retenu", "propositions", "synthese", "note"}
    # Sans seuil retenu : matérialité muette, statut dédié.
    vue = construire_vue_programme_propose([], [], [], None)
    assert cles <= set(vue)
    assert vue["synthese"]["statut"] == STATUT_SEUIL_A_RETENIR
    assert vue["propositions"] == []
    assert vue["note"] == NOTE_PROGRAMME_PROPOSE
    # Seuil retenu mais rien à proposer.
    vue2 = construire_vue_programme_propose([], [], [], "1000000")
    assert vue2["synthese"]["statut"] == STATUT_AUCUNE_PROPOSITION
    # Propositions disponibles, décompte des couvertes.
    vue3 = construire_vue_programme_propose(
        [_cible("7011")],
        [{"impot": "TVA", "libelle": "R", "statut": "ouvert"}],
        [{"code": "PRO-CA", "libelle": "x"}],
        "1000000",
    )
    assert vue3["synthese"]["statut"] == STATUT_PROPOSITIONS
    assert vue3["synthese"]["nb_propositions"] == 2
    assert vue3["synthese"]["nb_deja_couvertes"] == 1
    assert vue3["synthese"]["nb_a_accepter"] == 1


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_PROGRAMME_PROPOSE
    assert "décide" in NOTE_PROGRAMME_PROPOSE
    assert "acceptation explicite" in NOTE_PROGRAMME_PROPOSE


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from tests.plateforme.test_materialite import (  # noqa: E402
    _cabinet,
    _client_connecte,
    _contribuable,
    _mission,
    _solde,
)


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/programme-propose"


def _risque(session, tenant_id: int, contribuable_id: int, impot: str,
            libelle: str, statut: str = "ouvert") -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, exercice_origine, statut) "
                "VALUES (:t, :c, :i, :l, 2025, :s)"
            ),
            {"t": tenant_id, "c": contribuable_id, "i": impot,
             "l": libelle, "s": statut},
        )


def _mission_ciblee(session):
    """Mission avec balance, seuil retenu (manuel 30 M) et un risque."""
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, f"PM Pont {uuid.uuid4().hex[:6]}")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "2411", "Matériel", "60000000", "0")
    _solde(session, tid, mid, "4421", "État, impôts", "0", "40000000")
    _solde(session, tid, mid, "6611", "Salaires", "35000000", "0")
    _solde(session, tid, mid, "7011", "Ventes", "0", "100000000")
    _solde(session, tid, mid, "5211", "Banque", "1000000", "0")
    _risque(session, tid, cid, "TVA", "TVA déductible non justifiée")
    _risque(session, tid, cid, "IS", "Risque clos", statut="resolu")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        f"/api/v1/missions/{mid}/materialite", headers=h,
        json={"source": "manuel", "montant": "30000000"},
    )
    assert r.status_code == 200, r.text
    return tid, mid, client, h


def test_api_propositions_depuis_ciblage_et_risques(session):
    _tid, mid, client, h = _mission_ciblee(session)

    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["seuil_retenu"] == "30000000.00"
    assert corps["synthese"]["statut"] == "propositions_disponibles"
    par_code = {p["code"]: p for p in corps["propositions"]}
    # 60 M (2411), 40 M (4421), 35 M (6611), 100 M (7011) dépassent
    # 30 M ; la banque (1 M) est sous le seuil → pas de PRO-TRESO.
    assert set(par_code) == {
        "PRO-CA", "PRO-ETAT", "PRO-REMU", "PRO-IMMO", "PRO-RSQ-TVA",
    }
    assert par_code["PRO-CA"]["comptes"] == ["7011"]
    assert par_code["PRO-RSQ-TVA"]["phase"] == "suivi"
    # Le risque résolu (IS) ne propose rien.
    assert "PRO-RSQ-IS" not in par_code
    assert all(p["deja_couverte"] is False
               for p in corps["propositions"])
    assert "consultatif" in corps["note"]


def test_api_sans_seuil_retenu_statut_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Pont Sans Seuil FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "7011", "Ventes", "0", "100000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["seuil_retenu"] is None
    assert corps["synthese"]["statut"] == "seuil_a_retenir"
    assert corps["propositions"] == []
    assert corps["note"]
    # Accepter sans proposition courante → 422.
    assert client.post(
        _url(mid), headers=h, json={"code": "PRO-CA"},
    ).status_code == 422


def test_api_acceptation_cree_la_diligence_dans_le_programme(session):
    tid, mid, client, h = _mission_ciblee(session)

    r = client.post(_url(mid), headers=h, json={"code": "PRO-CA"})
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "creee"
    assert corps["diligence"]["code"] == "PRO-CA"
    assert corps["diligence"]["phase"] == "controles"
    assert corps["diligence"]["origine"] == "materialite"

    # La diligence est bien dans le programme de travail EXISTANT.
    programme = client.get(
        f"/api/v1/missions/{mid}/programme", headers=h
    ).json()
    par_phase = {p["phase"]: p for p in programme["phases"]}
    codes_ctl = [d["code"] for d in par_phase["controles"]["diligences"]]
    assert "PRO-CA" in codes_ctl
    libelles = {d["code"]: d["libelle"]
                for d in par_phase["controles"]["diligences"]}
    assert libelles["PRO-CA"] == (
        "Revue du chiffre d'affaires et des assiettes déclaratives "
        "(TVA/IS)"
    )

    # Une diligence acceptée reste cochable comme les autres.
    coche = client.put(
        f"/api/v1/missions/{mid}/programme/PRO-CA", headers=h,
        json={"fait": True},
    )
    assert coche.status_code == 200, coche.text
    assert coche.json()["diligence"]["fait"] is True

    # Journalisation de l'acceptation.
    with contexte_tenant(session, tid):
        actions = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'acceptation_diligence_proposee'"
            ),
            {"m": mid},
        ).mappings().all()
    assert len(actions) == 1
    assert actions[0]["charge_utile"]["code"] == "PRO-CA"


def test_api_deduplication_deja_couverte_sans_doublon(session):
    _tid, mid, client, h = _mission_ciblee(session)

    assert client.post(
        _url(mid), headers=h, json={"code": "PRO-ETAT"},
    ).json()["statut"] == "creee"

    # Le GET signale la proposition couverte, les autres restent libres.
    corps = client.get(_url(mid), headers=h).json()
    par_code = {p["code"]: p for p in corps["propositions"]}
    assert par_code["PRO-ETAT"]["deja_couverte"] is True
    assert par_code["PRO-CA"]["deja_couverte"] is False
    assert corps["synthese"]["nb_deja_couvertes"] == 1

    # Ré-accepter → deja_couverte, AUCUN doublon en base.
    r2 = client.post(_url(mid), headers=h, json={"code": "PRO-ETAT"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["statut"] == "deja_couverte"
    programme = client.get(
        f"/api/v1/missions/{mid}/programme", headers=h
    ).json()
    tous_codes = [d["code"] for p in programme["phases"]
                  for d in p["diligences"]]
    assert tous_codes.count("PRO-ETAT") == 1


def test_api_422_code_inconnu(session):
    _tid, mid, client, h = _mission_ciblee(session)
    for mauvais in ("PRO-XXX", "", "CAD-01"):
        r = client.post(_url(mid), headers=h, json={"code": mauvais})
        assert r.status_code == 422, r.text


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _client_a, _h_a = _mission_ciblee(session)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url(mid_a), headers=h_b, json={"code": "PRO-CA"},
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(
        _url(1), json={"code": "PRO-CA"}
    ).status_code == 401
