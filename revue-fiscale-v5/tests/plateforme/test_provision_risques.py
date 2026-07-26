"""Tests — provision pour risques fiscaux (déterministe, SYSCOHADA)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.plateforme.penalites import chiffrer_risque
from backend.plateforme.provision_risques import (
    COMPTE_DOTATION,
    COMPTE_PROVISION,
    MENTION_PROPOSITION,
    calculer_provision_depuis_risques,
)

AUJOURD_HUI = date(2026, 7, 26)
EXERCICE = 2024


def _risque(**kw) -> dict:
    base = {
        "id": 1,
        "impot": "TVA",
        "libelle": "TVA collectée non déclarée",
        "statut": "ouvert",
        "probabilite": "probable",
        "montant_estime": "1000000",
        "penalites_estimees": None,
        "exercice_origine": EXERCICE,
    }
    base.update(kw)
    base["chiffrage_penalites"] = chiffrer_risque(base, AUJOURD_HUI)
    return base


def test_probable_chiffre_provisionne_penalites_incluses():
    r = _risque()
    chiffrage = r["chiffrage_penalites"]
    assert chiffrage is not None
    out = calculer_provision_depuis_risques([r], exercice_courant=2026)

    assert len(out["lignes"]) == 1
    ligne = out["lignes"][0]
    assert ligne["risque_id"] == 1
    assert ligne["impot"] == "TVA"
    assert ligne["exercice"] == EXERCICE
    assert ligne["probabilite"] == "probable"
    assert ligne["statut"] == "ouvert"
    # Pénalités incluses : montant provisionnable = total_estime du chiffrage.
    assert ligne["montant_provisionnable"] == chiffrage["total_estime"]
    assert Decimal(ligne["montant_provisionnable"]) > Decimal(
        ligne["base_droit_simple"]
    )
    assert Decimal(ligne["base_droit_simple"]) + Decimal(
        ligne["penalites_interets"]
    ) == Decimal(ligne["montant_provisionnable"])
    assert out["total_provision"] == chiffrage["total_estime"]
    assert out["passifs_eventuels"] == []


def test_possible_en_passif_eventuel_non_provisionne():
    r = _risque(id=2, probabilite="possible")
    out = calculer_provision_depuis_risques([r], exercice_courant=2026)
    assert out["lignes"] == []
    assert out["total_provision"] == "0"
    assert len(out["passifs_eventuels"]) == 1
    passif = out["passifs_eventuels"][0]
    assert passif["risque_id"] == 2
    assert Decimal(passif["montant_estime"]) > 0
    assert any("passifs éventuels" in h for h in out["hypotheses"])


@pytest.mark.parametrize("statut", ["resolu", "accepte", "prescrit"])
def test_risque_clos_exclu(statut):
    out = calculer_provision_depuis_risques(
        [_risque(statut=statut), _risque(id=9, statut=statut, probabilite="possible")],
        exercice_courant=2026,
    )
    assert out["lignes"] == []
    assert out["passifs_eventuels"] == []
    assert out["total_provision"] == "0"


def test_faible_ni_provisionne_ni_passif():
    out = calculer_provision_depuis_risques(
        [_risque(probabilite="faible")], exercice_courant=2026
    )
    assert out["lignes"] == []
    assert out["passifs_eventuels"] == []


def test_ecriture_equilibree_debit_credit_total():
    risques = [
        _risque(id=1, montant_estime="1000000"),
        _risque(id=2, montant_estime="2500000", impot="IS"),
        _risque(id=3, probabilite="possible"),
        _risque(id=4, statut="resolu"),
    ]
    out = calculer_provision_depuis_risques(risques, exercice_courant=2026)
    total = Decimal(out["total_provision"])
    assert total == sum(
        Decimal(ligne["montant_provisionnable"]) for ligne in out["lignes"]
    )

    ecriture = out["ecriture_proposee"]
    assert "2026" in ecriture["libelle"]
    assert "Provision pour risques fiscaux" in ecriture["libelle"]
    debits = [
        ligne for ligne in ecriture["lignes"] if ligne["sens"] == "debit"
    ]
    credits = [
        ligne for ligne in ecriture["lignes"] if ligne["sens"] == "credit"
    ]
    assert [d["compte"] for d in debits] == [COMPTE_DOTATION]
    assert [c["compte"] for c in credits] == [COMPTE_PROVISION]
    assert sum(Decimal(d["montant"]) for d in debits) == total
    assert sum(Decimal(c["montant"]) for c in credits) == total


def test_mention_indicative_presente():
    out = calculer_provision_depuis_risques([_risque()], exercice_courant=2026)
    assert MENTION_PROPOSITION in out["hypotheses"]
    assert any("expert-comptable" in h for h in out["hypotheses"])
    assert any("0,5 %/mois" in h for h in out["hypotheses"])


def test_probable_en_traitement_provisionne():
    out = calculer_provision_depuis_risques(
        [_risque(statut="en_traitement")], exercice_courant=2026
    )
    assert len(out["lignes"]) == 1
    assert out["lignes"][0]["statut"] == "en_traitement"


def test_probable_sans_chiffrage_cumul_brut():
    r = _risque(montant_estime=None, penalites_estimees="300000")
    assert r["chiffrage_penalites"] is None
    out = calculer_provision_depuis_risques([r], exercice_courant=2026)
    assert out["lignes"][0]["montant_provisionnable"] == "300000"


# ── Endpoint (base requise) ─────────────────────────────────────────


def _provisionner(session) -> tuple[str, str]:
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    if derniere_version_publiee(session) is None:
        lib = f"v-prov-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="provision")
        publier_version(session, lib, "prov@test.ci")

    email = f"prov.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Provision {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return email, "admin-admin1"


def _connexion(client: TestClient, email: str, mdp: str) -> dict:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": mdp},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['jeton']}"}


def _contrib(client: TestClient, h: dict, ncc: str) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM {ncc}",
            "ncc": ncc,
            "forme": "pm",
            "rccm": f"RCCM-{ncc}",
            "forme_juridique": "SARL",
            "regime_fiscal": "reel",
        },
    )
    assert c.status_code == 200, c.text
    return int(c.json()["id"])


@pytest.mark.db
def test_endpoint_provision_200_structure(session):
    from backend.main import app

    email, mdp = _provisionner(session)
    session.commit()
    client = TestClient(app)
    h = _connexion(client, email, mdp)
    ncc = f"CI-PRV-{uuid.uuid4().hex[:6].upper()}"
    cid = _contrib(client, h, ncc)

    # Un risque probable chiffré + un possible.
    for prob, montant in (("probable", "2000000"), ("possible", "500000")):
        r = client.post(
            "/api/v1/risques",
            headers=h,
            json={
                "contribuable_id": cid,
                "impot": "TVA",
                "libelle": f"Risque {prob} test provision",
                "exercice_origine": 2024,
                "probabilite": prob,
                "montant_estime": montant,
            },
        )
        assert r.status_code == 201, r.text

    rep = client.get(
        f"/api/v1/contribuables/{cid}/provision-risques", headers=h
    )
    assert rep.status_code == 200, rep.text
    corps = rep.json()
    assert corps["contribuable_id"] == cid
    assert len(corps["lignes"]) == 1
    assert corps["lignes"][0]["probabilite"] == "probable"
    assert Decimal(corps["total_provision"]) > Decimal("2000000")
    assert len(corps["passifs_eventuels"]) == 1
    ecriture = corps["ecriture_proposee"]
    montants = {
        ligne["sens"]: Decimal(ligne["montant"])
        for ligne in ecriture["lignes"]
    }
    assert montants["debit"] == montants["credit"]
    assert montants["debit"] == Decimal(corps["total_provision"])
    assert MENTION_PROPOSITION in corps["hypotheses"]


@pytest.mark.db
def test_endpoint_provision_404_cross_tenant(session):
    from backend.main import app

    email_a, mdp_a = _provisionner(session)
    email_b, mdp_b = _provisionner(session)
    session.commit()
    client = TestClient(app)
    h_a = _connexion(client, email_a, mdp_a)
    h_b = _connexion(client, email_b, mdp_b)
    ncc = f"CI-PRX-{uuid.uuid4().hex[:6].upper()}"
    cid = _contrib(client, h_a, ncc)

    ok = client.get(
        f"/api/v1/contribuables/{cid}/provision-risques", headers=h_a
    )
    assert ok.status_code == 200, ok.text

    r = client.get(
        f"/api/v1/contribuables/{cid}/provision-risques", headers=h_b
    )
    assert r.status_code == 404, r.text
