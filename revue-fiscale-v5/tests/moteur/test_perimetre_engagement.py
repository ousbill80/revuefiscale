"""Filtre perimetre_impots dans selectionner_regles + gel cadrage API."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.moteur.selection import selectionner_regles
from backend.plateforme.missions import ErreurMission, valider_perimetre_impots
from backend.referentiel.depot import RegleChargee
from backend.restitution.passage import Passage
from backend.restitution.rapport import rendre_rapport_markdown
from backend.restitution.risques import ScoreRisque


def _regle(ident: str, impot: str, comptes: list[str]) -> RegleChargee:
    return RegleChargee(
        regle_version_id=1,
        regle_id=ident,
        impot=impot,
        libelle=ident,
        comptes_declencheurs=comptes,
        nature="sans_objet",
        condition_declenchement="solde(701) > 0",
        expression_resultat="0",
        niveau_risque="faible",
        formule_plafonnement=None,
        questions=[],
        a_confirmer=[],
        profils_applicables=[],
    )


def test_selection_tva_exclut_bic():
    regles = [
        _regle("BIC-A", "BIC", ["701"]),
        _regle("TVA-A", "TVA", ["701"]),
        _regle("RAS-A", "RAS", ["701"]),
    ]
    soldes = {"701": Decimal("1")}
    sel = selectionner_regles(regles, soldes, perimetre_impots=["TVA"])
    assert [r.regle_id for r in sel] == ["TVA-A"]


def test_selection_sans_perimetre_conserve_tout():
    regles = [
        _regle("BIC-A", "BIC", ["701"]),
        _regle("TVA-A", "TVA", ["701"]),
    ]
    soldes = {"701": Decimal("1")}
    sel = selectionner_regles(regles, soldes, perimetre_impots=None)
    assert [r.regle_id for r in sel] == ["BIC-A", "TVA-A"]


def test_valider_perimetre_refuse_liste_vide():
    with pytest.raises(ErreurMission):
        valider_perimetre_impots([])


def test_rapport_tva_only_enonce_non_examine():
    md = rendre_rapport_markdown(
        meta={
            "mission_id": 1,
            "exercice": 2025,
            "contribuable_denomination": "FICTIF SA",
            "contribuable_ncc": "CI-X",
            "version_referentiel_id": 9,
            "type_engagement": "preventive",
            "perimetre_impots": ["TVA"],
        },
        passage=Passage(
            lignes=(),
            total_reintegration=Decimal("0"),
            total_deduction=Decimal("0"),
            solde_net=Decimal("0"),
        ),
        conclusions=[],
        score=ScoreRisque(score=0, comptages={}, avertissement="heuristique"),
        extrait_audit=[],
    )
    assert "## Périmètre déclaré" in md
    assert "## Non examiné" in md
    assert "`BIC`" in md
    assert "`TVA`" in md
    assert "Revue préventive" in md


@pytest.mark.db
def test_patch_cadrage_refuse_si_en_cours(session):
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-eng-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="engagement")
        publier_version(session, lib, "eng@test.ci")

    email = f"eng.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Eng {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['jeton']}"}

    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM Eng FICTIF",
            "ncc": "CI-ENG-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-ENG",
            "dfe": "DFE-ENG-1",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    cid = c.json()["id"]

    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": cid,
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "type_engagement": "preventive",
            "perimetre_impots": ["TVA"],
        },
    )
    assert m.status_code == 200, m.text
    body = m.json()
    mid = body["id"]
    assert body["statut"] == "cadrage"
    assert body["revue_partielle"] is True
    assert body["perimetre_impots"] == ["TVA"]

    ok = client.patch(
        f"/api/v1/missions/{mid}/cadrage",
        headers=h,
        json={"perimetre_impots": ["TVA", "RAS"], "seuil_signification": 500000},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["perimetre_impots"] == ["TVA", "RAS"]

    bad_empty = client.patch(
        f"/api/v1/missions/{mid}/cadrage",
        headers=h,
        json={"perimetre_impots": []},
    )
    assert bad_empty.status_code == 400

    p1 = client.patch(
        f"/api/v1/missions/{mid}/statut",
        headers=h,
        json={"statut": "en_cours"},
    )
    assert p1.status_code == 200, p1.text

    frozen = client.patch(
        f"/api/v1/missions/{mid}/cadrage",
        headers=h,
        json={"perimetre_impots": ["BIC"]},
    )
    assert frozen.status_code in (400, 409), frozen.text
    detail = str(frozen.json()["detail"]).lower()
    assert "figé" in detail or "fige" in detail

    frozen_seuil = client.patch(
        f"/api/v1/missions/{mid}/cadrage",
        headers=h,
        json={"seuil_signification": 1},
    )
    assert frozen_seuil.status_code in (400, 409), frozen_seuil.text
    detail_seuil = str(frozen_seuil.json()["detail"]).lower()
    assert "figé" in detail_seuil or "fige" in detail_seuil
    assert "seuil_signification" in detail_seuil

    detail_get = client.get(f"/api/v1/missions/{mid}", headers=h)
    assert detail_get.status_code == 200
    assert detail_get.json()["type_engagement"] == "preventive"
    assert detail_get.json()["perimetre_impots"] == ["TVA", "RAS"]
    assert Decimal(detail_get.json()["seuil_signification"]) == Decimal("500000")
    assert detail_get.json()["statut"] == "en_cours"


@pytest.mark.db
def test_cadrage_isolation_cross_tenant(session):
    """Admin A ne lit / ne patche pas le cadrage d'une mission du cabinet B."""
    from backend.main import app
    from backend.plateforme.provisionnement import (
        derniere_version_publiee,
        provisionner_cabinet,
    )

    if derniere_version_publiee(session) is None:
        from backend.editorial.publication import (
            creer_version_brouillon,
            publier_version,
        )

        lib = f"v-iso-eng-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="engagement-iso")
        publier_version(session, lib, "eng-iso@test.ci")

    email_a = f"iso.a.{uuid.uuid4().hex[:8]}@demo.local"
    email_b = f"iso.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab IsoA {email_a}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_a,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    provisionner_cabinet(
        session,
        denomination=f"Cab IsoB {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client = TestClient(app)
    login_a = client.post(
        "/api/v1/auth/connexion",
        json={"email": email_a, "mot_de_passe": "admin-admin1"},
    )
    assert login_a.status_code == 200, login_a.text
    h_a = {"Authorization": f"Bearer {login_a.json()['jeton']}"}
    login_b = client.post(
        "/api/v1/auth/connexion",
        json={"email": email_b, "mot_de_passe": "admin-admin1"},
    )
    assert login_b.status_code == 200, login_b.text
    h_b = {"Authorization": f"Bearer {login_b.json()['jeton']}"}

    c = client.post(
        "/api/v1/contribuables",
        headers=h_b,
        json={
            "denomination": "PM IsoB FICTIF",
            "ncc": "CI-ISO-B-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-ISOB",
            "dfe": "DFE-ISOB-1",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan",
        },
    )
    assert c.status_code == 200, c.text
    m = client.post(
        "/api/v1/missions",
        headers=h_b,
        json={
            "contribuable_id": c.json()["id"],
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
            "type_engagement": "cac",
            "perimetre_impots": ["TVA"],
        },
    )
    assert m.status_code == 200, m.text
    mid_b = m.json()["id"]

    assert client.get(f"/api/v1/missions/{mid_b}", headers=h_a).status_code == 404
    patch_x = client.patch(
        f"/api/v1/missions/{mid_b}/cadrage",
        headers=h_a,
        json={"perimetre_impots": ["BIC"]},
    )
    # RLS → introuvable (400) — pas de fuite de présence
    assert patch_x.status_code == 400, patch_x.text
    assert "introuvable" in str(patch_x.json().get("detail", "")).lower()
