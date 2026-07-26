"""Échéancier déclaratif indicatif — fonction pure + endpoint (RLS)."""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.plateforme.echeancier_fiscal import (
    HORIZON_JOURS_DEFAUT,
    OBLIGATIONS_PAR_REGIME,
    normaliser_regime,
    prochaines_echeances,
)

# ── Fonction pure ────────────────────────────────────────────────────


def test_mensuelle_roule_sur_90_jours():
    """RNI : la TVA mensuelle produit ~3 occurrences à venir sur 90 j."""
    ref = date(2026, 7, 1)
    eches = prochaines_echeances("reel", ref, horizon_jours=90)
    tva = [e for e in eches if e["code"] == "tva_mensuelle"]
    a_venir = [e for e in tva if e["jours_restants"] >= 0]
    assert len(a_venir) == 3  # 15/07, 15/08, 15/09
    assert [e["date_limite"] for e in a_venir] == [
        "2026-07-15",
        "2026-08-15",
        "2026-09-15",
    ]
    for e in tva:
        assert e["periodicite"] == "mensuelle"
        assert "TVA" in e["impots"]


def test_annuelle_dans_horizon():
    """Résultat annuel (30/04, clôture décembre) visible depuis février."""
    ref = date(2026, 2, 15)
    eches = prochaines_echeances("reel", ref, horizon_jours=90)
    resultat = [e for e in eches if e["code"] == "resultat_annuel"]
    assert len(resultat) == 1
    assert resultat[0]["date_limite"] == "2026-04-30"
    assert resultat[0]["statut"] == "a_venir"
    assert resultat[0]["jours_restants"] == (date(2026, 4, 30) - ref).days


def test_annuelle_hors_horizon():
    """Résultat annuel absent quand la date limite est > horizon."""
    ref = date(2026, 7, 1)  # 30/04 passé depuis > 30 j, prochain en 2027.
    eches = prochaines_echeances("reel", ref, horizon_jours=90)
    assert not [e for e in eches if e["code"] == "resultat_annuel"]


def test_annuelle_decalee_par_mois_cloture():
    """Clôture juin : résultat (déc + 4 mois) attendu fin octobre."""
    ref = date(2026, 9, 1)
    eches = prochaines_echeances(
        "reel", ref, horizon_jours=90, mois_cloture=6
    )
    resultat = [e for e in eches if e["code"] == "resultat_annuel"]
    assert len(resultat) == 1
    assert resultat[0]["date_limite"] == "2026-10-30"


def test_statut_imminente_sous_15_jours():
    ref = date(2026, 7, 5)  # TVA du 15/07 dans 10 jours.
    eches = prochaines_echeances("reel_simplifie", ref, horizon_jours=90)
    tva = [e for e in eches if e["code"] == "tva_mensuelle"]
    prochaine = next(e for e in tva if e["jours_restants"] >= 0)
    assert prochaine["date_limite"] == "2026-07-15"
    assert prochaine["jours_restants"] == 10
    assert prochaine["statut"] == "imminente"


def test_statut_depassee_recente_visible():
    ref = date(2026, 7, 20)  # TVA du 15/07 dépassée depuis 5 jours.
    eches = prochaines_echeances("reel", ref, horizon_jours=90)
    depassees = [e for e in eches if e["statut"] == "depassee"]
    assert any(e["date_limite"] == "2026-07-15" for e in depassees)
    assert all(e["jours_restants"] < 0 for e in depassees)


def test_regime_inconnu_liste_vide_sans_erreur():
    ref = date(2026, 7, 1)
    assert prochaines_echeances("forfait_martien", ref) == []
    assert prochaines_echeances(None, ref) == []
    assert prochaines_echeances("", ref) == []


def test_alias_regimes_normalises():
    assert normaliser_regime("RNI") == "reel"
    assert normaliser_regime("rsi") == "reel_simplifie"
    assert normaliser_regime(" tee ") == "tee"
    assert normaliser_regime("tce") == "tee"
    assert normaliser_regime("inconnu") is None


def test_tee_mensuelle_et_ime_trimestrielle():
    ref = date(2026, 7, 1)
    tee = prochaines_echeances("tee", ref, horizon_jours=90)
    assert tee and all(e["code"] == "tee_mensuelle" for e in tee)
    ime = prochaines_echeances("ime", ref, horizon_jours=90)
    # Trimestrielle : échéances uniquement en janv/avr/juil/oct.
    assert ime and all(
        e["date_limite"][5:7] in {"01", "04", "07", "10"} for e in ime
    )


def test_tri_par_date_et_referentiel_coherent():
    ref = date(2026, 3, 1)
    eches = prochaines_echeances("reel", ref, horizon_jours=90)
    dates = [e["date_limite"] for e in eches]
    assert dates == sorted(dates)
    codes_referentiel = {
        o["code"] for obs in OBLIGATIONS_PAR_REGIME.values() for o in obs
    }
    assert all(e["code"] in codes_referentiel for e in eches)


# ── Endpoint (base requise) ──────────────────────────────────────────

pytestmark_db = pytest.mark.db


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
        lib = f"v-eche-{uuid.uuid4().hex[:8]}"
        creer_version_brouillon(session, lib, note="echeancier")
        publier_version(session, lib, "eche@test.ci")

    email = f"eche.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Écheancier {email}",
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


def _contrib(client: TestClient, h: dict, ncc: str, regime: str) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": f"PM {ncc}",
            "ncc": ncc,
            "forme": "pm",
            "rccm": f"RCCM-{ncc}",
            "forme_juridique": "SARL",
            "regime_fiscal": regime,
        },
    )
    assert c.status_code == 200, c.text
    return int(c.json()["id"])


@pytest.mark.db
def test_endpoint_echeancier_200_structure(session):
    from backend.main import app

    email, mdp = _provisionner(session)
    session.commit()
    client = TestClient(app)
    h = _connexion(client, email, mdp)
    ncc = f"CI-ECH-{uuid.uuid4().hex[:6].upper()}"
    cid = _contrib(client, h, ncc, "reel")

    r = client.get(f"/api/v1/contribuables/{cid}/echeancier", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["contribuable_id"] == cid
    assert corps["regime"] == "reel"
    assert corps["reference"] == date.today().isoformat()
    assert corps["horizon_jours"] == HORIZON_JOURS_DEFAUT
    assert corps["indicatif"] is True
    assert isinstance(corps["echeances"], list)
    assert corps["echeances"], "RNI doit produire des échéances sur 90 j"
    premiere = corps["echeances"][0]
    for cle in (
        "code",
        "libelle",
        "periodicite",
        "impots",
        "date_limite",
        "jours_restants",
        "statut",
    ):
        assert cle in premiere
    assert premiere["statut"] in {"a_venir", "imminente", "depassee"}


@pytest.mark.db
def test_endpoint_echeancier_404_cross_tenant(session):
    from backend.main import app

    email_a, mdp_a = _provisionner(session)
    email_b, mdp_b = _provisionner(session)
    session.commit()
    client = TestClient(app)
    h_a = _connexion(client, email_a, mdp_a)
    h_b = _connexion(client, email_b, mdp_b)
    ncc = f"CI-ECX-{uuid.uuid4().hex[:6].upper()}"
    cid = _contrib(client, h_a, ncc, "tee")

    # Le tenant A voit sa fiche.
    ok = client.get(f"/api/v1/contribuables/{cid}/echeancier", headers=h_a)
    assert ok.status_code == 200, ok.text

    # Le tenant B reçoit 404 (RLS) — pas de fuite d'existence.
    r = client.get(f"/api/v1/contribuables/{cid}/echeancier", headers=h_b)
    assert r.status_code == 404, r.text
