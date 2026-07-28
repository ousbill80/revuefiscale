"""Seuil de matérialité et ciblage des travaux depuis la balance."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.materialite import (
    NOTE_MATERIALITE,
    STATUT_INDISPONIBLE,
    STATUT_SEUIL_A_RETENIR,
    STATUT_TRAVAUX_CIBLES,
    ErreurMaterialiteInvalide,
    agreger_balance,
    cibler_comptes,
    construire_vue_materialite,
    couverture_par_classe,
    proposer_seuils,
    valider_seuil_manuel,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _balance():
    return [
        # Classe 2 — immobilisations (actif).
        {"compte": "2411", "libelle": "Matériel", "debit": "60000000",
         "credit": "0"},
        # Classe 4 — tiers (client débiteur, fournisseur créditeur).
        {"compte": "4111", "libelle": "Clients", "debit": "25000000",
         "credit": "0"},
        {"compte": "4011", "libelle": "Fournisseurs", "debit": "0",
         "credit": "8000000"},
        # Classe 5 — trésorerie.
        {"compte": "5211", "libelle": "Banque", "debit": "15000000",
         "credit": "0"},
        # Classe 6 — charges.
        {"compte": "6011", "libelle": "Achats", "debit": "70000000",
         "credit": "0"},
        {"compte": "6611", "libelle": "Salaires", "debit": "20000000",
         "credit": "0"},
        # Classe 7 — produits (dont CA 70x).
        {"compte": "7011", "libelle": "Ventes", "debit": "0",
         "credit": "100000000"},
        {"compte": "7071", "libelle": "Produits accessoires",
         "debit": "0", "credit": "5000000"},
        {"compte": "7711", "libelle": "Intérêts reçus", "debit": "0",
         "credit": "1000000"},
    ]


def test_agreger_balance_bases():
    a = agreger_balance(_balance())
    # CA = comptes 70x créditeurs nets : 100 000 000 + 5 000 000.
    assert a["chiffre_affaires"] == Decimal("105000000")
    # Résultat approché = classe 7 (106 M) - classe 6 (90 M).
    assert a["resultat"] == Decimal("16000000")
    # Total bilan approché = soldes débiteurs classes 1-5 :
    # 60 M + 25 M + 15 M (le fournisseur créditeur est exclu).
    assert a["total_bilan"] == Decimal("100000000")


def test_agreger_balance_vide():
    a = agreger_balance([])
    assert a["chiffre_affaires"] == Decimal("0")
    assert a["resultat"] == Decimal("0")
    assert a["total_bilan"] == Decimal("0")


def test_proposer_seuils_referentiels():
    props = {p["referentiel"]: p for p in proposer_seuils(_balance())}
    assert set(props) == {"ca", "resultat", "bilan"}
    # 1 % du CA.
    assert props["ca"]["seuil_propose"] == Decimal("1050000")
    assert props["ca"]["calculable"] is True
    assert props["ca"]["taux"] == "0.01"
    # 5 % du résultat.
    assert props["resultat"]["seuil_propose"] == Decimal("800000")
    # 1 % du total bilan.
    assert props["bilan"]["seuil_propose"] == Decimal("1000000")


def test_proposer_seuils_resultat_deficitaire_valeur_absolue():
    # Perte de 10 M : la base résultat reste utilisable (|résultat|).
    soldes = [
        {"compte": "6011", "libelle": "Achats", "debit": "30000000",
         "credit": "0"},
        {"compte": "7011", "libelle": "Ventes", "debit": "0",
         "credit": "20000000"},
    ]
    props = {p["referentiel"]: p for p in proposer_seuils(soldes)}
    assert props["resultat"]["seuil_propose"] == Decimal("500000")
    assert props["resultat"]["calculable"] is True
    # Pas d'actif → bilan non calculable, seuil absent.
    assert props["bilan"]["calculable"] is False
    assert props["bilan"]["seuil_propose"] is None


def test_proposer_seuils_balance_vide_non_calculables():
    props = proposer_seuils([])
    assert len(props) == 3
    assert all(p["calculable"] is False for p in props)
    assert all(p["seuil_propose"] is None for p in props)


def test_valider_seuil_manuel():
    assert valider_seuil_manuel("1500000") == Decimal("1500000.00")
    assert valider_seuil_manuel("1 000 000") == Decimal("1000000.00")
    assert valider_seuil_manuel(1234.5) == Decimal("1234.50")
    for mauvais in (None, "", "abc", "0", "-5"):
        with pytest.raises(ErreurMaterialiteInvalide):
            valider_seuil_manuel(mauvais)


def test_cibler_comptes_strictement_superieur_au_seuil():
    cibles = cibler_comptes(_balance(), Decimal("15000000"))
    # 5211 = 15 M : AU seuil, non ciblé (strictement supérieur).
    assert [c["compte"] for c in cibles] == [
        "2411", "4111", "6011", "6611", "7011"
    ]
    par_compte = {c["compte"]: c for c in cibles}
    # Solde signé : produit créditeur négatif.
    assert par_compte["7011"]["solde"] == Decimal("-100000000")
    assert par_compte["7011"]["classe"] == "7"


def test_cibler_comptes_tri_classe_puis_masse():
    cibles = cibler_comptes(_balance(), Decimal("1000000"))
    classes = [c["classe"] for c in cibles]
    assert classes == sorted(classes)
    # Dans la classe 6 : achats (70 M) avant salaires (20 M).
    en_6 = [c["compte"] for c in cibles if c["classe"] == "6"]
    assert en_6 == ["6011", "6611"]


def test_couverture_par_classe_et_globale():
    soldes = _balance()
    cibles = cibler_comptes(soldes, Decimal("15000000"))
    couv = couverture_par_classe(soldes, cibles)
    par_classe = {c["classe"]: c for c in couv["par_classe"]}
    # Classe 4 : masse 33 M, ciblée 25 M (clients seulement).
    assert par_classe["4"]["masse"] == Decimal("33000000")
    assert par_classe["4"]["masse_ciblee"] == Decimal("25000000")
    assert par_classe["4"]["taux_couverture"] == "75.8"
    assert par_classe["4"]["nb_comptes"] == 2
    assert par_classe["4"]["nb_comptes_cibles"] == 1
    # Classe 5 : banque au seuil, non ciblée.
    assert par_classe["5"]["masse_ciblee"] == Decimal("0")
    assert par_classe["5"]["taux_couverture"] == "0.0"
    # Global : 275 M ciblés / 304 M de masses.
    assert couv["masse_totale"] == Decimal("304000000")
    assert couv["masse_ciblee"] == Decimal("275000000")
    assert couv["taux_global"] == "90.5"


def test_construire_vue_sans_balance_cles_stables():
    cles = {
        "disponible", "agregats", "propositions", "seuil_retenu",
        "comptes_cibles", "couverture", "synthese", "note",
    }
    vue = construire_vue_materialite([], None)
    assert cles <= set(vue)
    assert vue["disponible"] is False
    assert vue["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert vue["seuil_retenu"] is None
    assert vue["comptes_cibles"] == []
    assert vue["note"] == NOTE_MATERIALITE


def test_construire_vue_seuil_a_retenir_puis_cible():
    vue1 = construire_vue_materialite(_balance(), None)
    assert vue1["disponible"] is True
    assert vue1["synthese"]["statut"] == STATUT_SEUIL_A_RETENIR
    assert vue1["comptes_cibles"] == []
    assert len(vue1["propositions"]) == 3

    retenu = {
        "seuil_retenu": "15000000", "source": "manuel",
        "referentiel": "", "commentaire": "", "decide_par": "x@y.ci",
        "cree_le": None, "mis_a_jour_le": None,
    }
    vue2 = construire_vue_materialite(_balance(), retenu)
    assert vue2["synthese"]["statut"] == STATUT_TRAVAUX_CIBLES
    assert vue2["synthese"]["nb_comptes_cibles"] == 5
    assert vue2["synthese"]["taux_couverture_global"] == "90.5"
    # Montants sérialisés en str.
    assert vue2["agregats"]["chiffre_affaires"] == "105000000"
    assert vue2["comptes_cibles"][0]["solde"] == "60000000"


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_MATERIALITE
    assert "décide" in NOTE_MATERIALITE


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

    lib = f"v-mat-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="materialite")
    publier_version(session, lib, "mat@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"mat.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Mat {email}",
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
    return f"/api/v1/missions/{mid}/materialite"


def _mission_avec_balance(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Mat FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "2411", "Matériel", "60000000", "0")
    _solde(session, tid, mid, "4111", "Clients", "25000000", "0")
    _solde(session, tid, mid, "6011", "Achats", "70000000", "0")
    _solde(session, tid, mid, "7011", "Ventes", "0", "100000000")
    session.commit()
    return tid, email, mid


def test_api_propositions_puis_confirmation(session):
    _tid, email, mid = _mission_avec_balance(session)

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["seuil_retenu"] is None
    assert corps["synthese"]["statut"] == "seuil_a_retenir"
    par_ref = {p["referentiel"]: p for p in corps["propositions"]}
    assert par_ref["ca"]["seuil_propose"] == "1000000"

    # Confirmation de la proposition CA (clic humain).
    r2 = client.post(
        _url(mid), headers=h,
        json={"source": "proposition", "referentiel": "ca"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["seuil_retenu"]["seuil_retenu"] == "1000000.00"
    assert r2.json()["seuil_retenu"]["source"] == "proposition"
    assert r2.json()["seuil_retenu"]["referentiel"] == "ca"

    corps2 = client.get(_url(mid), headers=h).json()
    assert corps2["synthese"]["statut"] == "travaux_cibles"
    # Tous les comptes (60/25/70/100 M) dépassent 1 M → couverture 100 %.
    assert corps2["synthese"]["nb_comptes_cibles"] == 4
    assert corps2["couverture"]["taux_global"] == "100.0"
    classes = [c["classe"] for c in corps2["couverture"]["par_classe"]]
    assert classes == ["2", "4", "6", "7"]
    assert "consultatif" in corps2["note"]


def test_api_seuil_manuel_remplace_la_proposition(session):
    _tid, email, mid = _mission_avec_balance(session)

    client, h = _client_connecte(email)
    client.post(
        _url(mid), headers=h,
        json={"source": "proposition", "referentiel": "bilan"},
    )
    r = client.post(
        _url(mid), headers=h,
        json={"source": "manuel", "montant": "30000000",
              "commentaire": "Seuil arrêté en réunion d'orientation."},
    )
    assert r.status_code == 200, r.text
    retenu = r.json()["seuil_retenu"]
    assert retenu["seuil_retenu"] == "30000000.00"
    assert retenu["source"] == "manuel"
    assert retenu["referentiel"] == ""

    corps = client.get(_url(mid), headers=h).json()
    # Seuls 60 M et 70 M et 100 M dépassent 30 M.
    assert corps["synthese"]["nb_comptes_cibles"] == 3
    assert corps["seuil_retenu"]["commentaire"] == (
        "Seuil arrêté en réunion d'orientation."
    )


def test_api_journalisation_retenue_seuil(session):
    tid, email, mid = _mission_avec_balance(session)

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid), headers=h,
        json={"source": "manuel", "montant": "5000000"},
    )
    assert r.status_code == 200, r.text
    with contexte_tenant(session, tid):
        actions = session.execute(
            text(
                "SELECT action, charge_utile FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'retenue_seuil_materialite'"
            ),
            {"m": mid},
        ).mappings().all()
    assert len(actions) == 1
    assert actions[0]["charge_utile"]["seuil_retenu"] == "5000000.00"
    assert actions[0]["charge_utile"]["source"] == "manuel"


def test_api_sans_balance_indisponible_mais_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Mat Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["synthese"]["statut"] == "indisponible"
    assert len(corps["propositions"]) == 3
    assert all(p["calculable"] is False for p in corps["propositions"])
    assert corps["note"]
    # Confirmer une proposition non calculable → 422 ; manuel accepté.
    assert client.post(
        _url(mid), headers=h,
        json={"source": "proposition", "referentiel": "ca"},
    ).status_code == 422
    assert client.post(
        _url(mid), headers=h,
        json={"source": "manuel", "montant": "1000000"},
    ).status_code == 200


def test_api_422_saisies_invalides(session):
    _tid, email, mid = _mission_avec_balance(session)

    client, h = _client_connecte(email)
    # Source inconnue.
    assert client.post(
        _url(mid), headers=h, json={"source": "llm"},
    ).status_code == 422
    # Référentiel inconnu.
    assert client.post(
        _url(mid), headers=h,
        json={"source": "proposition", "referentiel": "ebitda"},
    ).status_code == 422
    # Montant manuel absent, nul ou négatif.
    assert client.post(
        _url(mid), headers=h, json={"source": "manuel"},
    ).status_code == 422
    assert client.post(
        _url(mid), headers=h,
        json={"source": "manuel", "montant": "0"},
    ).status_code == 422
    assert client.post(
        _url(mid), headers=h,
        json={"source": "manuel", "montant": "-5"},
    ).status_code == 422


def test_api_404_cross_tenant(session):
    _tid_a, _email_a, mid_a = _mission_avec_balance(session)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url(mid_a), headers=h_b,
        json={"source": "manuel", "montant": "1"},
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(
        _url(1), json={"source": "manuel", "montant": "1"}
    ).status_code == 401
