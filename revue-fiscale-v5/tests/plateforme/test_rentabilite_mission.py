"""Rentabilité de mission : paramètres, marge, validations, cloisonnement."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _mission,
)
from tests.plateforme.test_temps_mission import _saisir  # noqa: E402


def _definir(client, h, mid, **corps):
    return client.put(
        f"/api/v1/missions/{mid}/rentabilite", headers=h, json=corps
    )


def test_definition_et_lecture(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    # 10 h saisies (6 + 4).
    assert _saisir(client, h, mid, phase="controles",
                   date_jour="2026-07-10", heures=6).status_code == 200
    assert _saisir(client, h, mid, phase="restitution",
                   date_jour="2026-07-15", heures=4).status_code == 200

    r = _definir(client, h, mid, honoraires=800000, taux_horaire=40000)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["honoraires"] == "800000"
    assert out["taux_horaire"] == "40000"
    assert out["total_heures"] == "10"
    # Décimal exact : 10 × 40 000 = 400 000 ; marge 400 000 ; 50.0 %.
    assert out["cout_estime"] == "400000"
    assert out["marge_estimee"] == "400000"
    assert out["taux_marge_pct"] == "50.0"

    lu = client.get(f"/api/v1/missions/{mid}/rentabilite", headers=h)
    assert lu.status_code == 200, lu.text
    assert lu.json() == out


def test_marge_negative(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)
    assert _saisir(client, h, mid, heures=10).status_code == 200

    r = _definir(client, h, mid, honoraires=300000, taux_horaire=40000)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["cout_estime"] == "400000"
    assert out["marge_estimee"] == "-100000"
    # −100 000 / 300 000 × 100 = −33.333… → −33.3 (une décimale).
    assert out["taux_marge_pct"] == "-33.3"


def test_parametres_partiels(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)
    assert _saisir(client, h, mid, heures=2).status_code == 200

    # Aucun paramètre : total d'heures seul, tout le reste null.
    vide = client.get(f"/api/v1/missions/{mid}/rentabilite", headers=h)
    assert vide.status_code == 200, vide.text
    from backend.plateforme.rentabilite_mission import NOTE_RENTABILITE

    assert vide.json() == {
        "honoraires": None,
        "taux_horaire": None,
        "total_heures": "2",
        "cout_estime": None,
        "marge_estimee": None,
        "taux_marge_pct": None,
        "pourcentage_consomme": None,
        "seuil": None,
        "note": NOTE_RENTABILITE,
        "heures_par_intervenant": {email: "2"},
    }

    # Taux seul : coût calculé, marge null (pas d'honoraires).
    r = _definir(client, h, mid, taux_horaire=40000)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["honoraires"] is None
    assert out["cout_estime"] == "80000"
    assert out["marge_estimee"] is None
    assert out["taux_marge_pct"] is None

    # Honoraires seuls : ni coût ni marge sans taux horaire.
    r2 = _definir(client, h, mid, honoraires=500000)
    assert r2.status_code == 200, r2.text
    out2 = r2.json()
    assert out2["taux_horaire"] is None
    assert out2["cout_estime"] is None
    assert out2["marge_estimee"] is None
    assert out2["taux_marge_pct"] is None


def test_valeurs_negatives_422(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert _definir(client, h, mid, honoraires=-1).status_code == 422
    assert _definir(client, h, mid, taux_horaire=-40000).status_code == 422
    # Rien n'a été enregistré.
    lu = client.get(f"/api/v1/missions/{mid}/rentabilite", headers=h).json()
    assert lu["honoraires"] is None
    assert lu["taux_horaire"] is None


def test_effacement(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert _definir(
        client, h, mid, honoraires=800000, taux_horaire=40000
    ).status_code == 200
    # Corps vide = effacement des deux paramètres.
    r = _definir(client, h, mid)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["honoraires"] is None
    assert out["taux_horaire"] is None
    assert out["cout_estime"] is None
    assert out["marge_estimee"] is None


def test_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)
    assert _definir(
        client, h_a, mid, honoraires=800000, taux_horaire=40000
    ).status_code == 200

    h_b, _ = _connexion(client, email_b)
    assert _definir(
        client, h_b, mid, honoraires=1, taux_horaire=1
    ).status_code == 404
    assert client.get(
        f"/api/v1/missions/{mid}/rentabilite", headers=h_b
    ).status_code == 404
    # Le tenant légitime garde ses paramètres intacts.
    lu = client.get(
        f"/api/v1/missions/{mid}/rentabilite", headers=h_a
    ).json()
    assert lu["honoraires"] == "800000"
    assert lu["taux_horaire"] == "40000"


def test_auth_requise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(
        f"/api/v1/missions/{mid}/rentabilite"
    ).status_code in (401, 403)
    assert client.put(
        f"/api/v1/missions/{mid}/rentabilite",
        json={"honoraires": 800000},
    ).status_code in (401, 403)


def test_export_csv_contenu(session):
    """CSV « ; » : en-tête, paramètres, temps valorisés, synthèse marge."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    # 10 h saisies (6 + 4) au nom de l'utilisateur connecté.
    assert _saisir(client, h, mid, phase="controles",
                   date_jour="2026-07-10", heures=6).status_code == 200
    assert _saisir(client, h, mid, phase="restitution",
                   date_jour="2026-07-15", heures=4).status_code == 200
    assert _definir(
        client, h, mid, honoraires=800000, taux_horaire=40000
    ).status_code == 200

    r = client.get(f"/api/v1/missions/{mid}/rentabilite.csv", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert (
        f'filename="rentabilite_mission_{mid}.csv"'
        in r.headers["content-disposition"]
    )
    lignes = r.content.decode("utf-8").splitlines()
    assert lignes[0] == "rubrique;cle;heures;montant_fcfa"
    assert "parametre;honoraires;;800000" in lignes
    assert "parametre;taux_horaire;;40000" in lignes
    # Temps valorisés au taux horaire (Decimal exact).
    assert "par_phase;controles;6;240000" in lignes
    assert "par_phase;restitution;4;160000" in lignes
    assert f"par_collaborateur;{email};10;400000" in lignes
    # Synthèse marge : coût 400 000, marge 400 000, taux 50.0 %.
    assert "synthese;total_heures;10;" in lignes
    assert "synthese;cout_estime;;400000" in lignes
    assert "synthese;marge_estimee;;400000" in lignes
    assert "synthese;taux_marge_pct;;50.0" in lignes


def test_export_csv_parametres_absents_422(session):
    """Ni honoraires ni taux horaire → 422 (rien à valoriser)."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)
    assert _saisir(client, h, mid, heures=2).status_code == 200

    r = client.get(f"/api/v1/missions/{mid}/rentabilite.csv", headers=h)
    assert r.status_code == 422, r.text
    assert "paramètres de rentabilité non renseignés" in r.json()["detail"]

    # Taux horaire seul renseigné : l'export redevient possible.
    assert _definir(client, h, mid, taux_horaire=40000).status_code == 200
    ok = client.get(f"/api/v1/missions/{mid}/rentabilite.csv", headers=h)
    assert ok.status_code == 200, ok.text
    lignes = ok.content.decode("utf-8").splitlines()
    assert "parametre;honoraires;;" in lignes
    assert "synthese;cout_estime;;80000" in lignes
    assert "synthese;marge_estimee;;" in lignes


def test_export_csv_cross_tenant_404(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a, _ = _connexion(client, email_a)
    mid = _mission(client, h_a)
    assert _definir(
        client, h_a, mid, honoraires=800000, taux_horaire=40000
    ).status_code == 200

    h_b, _ = _connexion(client, email_b)
    assert client.get(
        f"/api/v1/missions/{mid}/rentabilite.csv", headers=h_b
    ).status_code == 404
    # Le tenant légitime exporte normalement.
    assert client.get(
        f"/api/v1/missions/{mid}/rentabilite.csv", headers=h_a
    ).status_code == 200


def test_export_csv_auth_requise(session):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(
        f"/api/v1/missions/{mid}/rentabilite.csv"
    ).status_code in (401, 403)


def test_calculer_rentabilite_fonction_pure():
    from backend.plateforme.rentabilite_mission import (
        ErreurRentabilite,
        calculer_rentabilite,
    )

    from backend.plateforme.rentabilite_mission import NOTE_RENTABILITE

    # Cas nominal — Decimal exact, arrondi commercial à une décimale.
    out = calculer_rentabilite("800000", "40000", "10.5")
    assert out == {
        "honoraires": "800000",
        "taux_horaire": "40000",
        "total_heures": "10.5",
        "cout_estime": "420000",
        "marge_estimee": "380000",
        "taux_marge_pct": "47.5",  # 380000/800000×100 = 47.5 exact
        "pourcentage_consomme": "52.5",  # 420000/800000×100
        "seuil": "ok",  # < 80 % du budget consommé
        "note": NOTE_RENTABILITE,
    }

    # Tiers périodique : 1/3 → 33.3 (une décimale, ROUND_HALF_UP).
    tiers = calculer_rentabilite("300000", "20000", "5")
    assert tiers["marge_estimee"] == "200000"
    assert tiers["taux_marge_pct"] == "66.7"

    # Honoraires à zéro : marge calculée mais taux null (division par 0).
    zero = calculer_rentabilite("0", "40000", "2")
    assert zero["marge_estimee"] == "-80000"
    assert zero["taux_marge_pct"] is None

    # Paramètres absents.
    rien = calculer_rentabilite(None, None, "3")
    assert rien["cout_estime"] is None
    assert rien["marge_estimee"] is None
    assert rien["taux_marge_pct"] is None

    with pytest.raises(ErreurRentabilite):
        calculer_rentabilite("-1", None, "0")
    with pytest.raises(ErreurRentabilite):
        calculer_rentabilite(None, "abc", "0")


def test_seuil_consommation_fonction_pure():
    """Seuils consultatifs : < 80 ok, 80-100 vigilance, > 100 dépassement."""
    from decimal import Decimal

    from backend.plateforme.rentabilite_mission import seuil_consommation

    assert seuil_consommation(None) is None
    assert seuil_consommation(Decimal("0")) == "ok"
    assert seuil_consommation(Decimal("79.9")) == "ok"
    # Bornes : 80 et 100 inclus dans « vigilance ».
    assert seuil_consommation(Decimal("80")) == "vigilance"
    assert seuil_consommation(Decimal("100")) == "vigilance"
    assert seuil_consommation(Decimal("100.1")) == "depassement"
    assert seuil_consommation(Decimal("150")) == "depassement"


def test_totaux_heures_par_intervenant_fonction_pure():
    from backend.plateforme.rentabilite_mission import (
        totaux_heures_par_intervenant,
    )

    assert totaux_heures_par_intervenant([]) == {}
    entrees = [
        {"collaborateur": "a.kone@cab.ci", "heures": "2.5"},
        {"collaborateur": "b.diallo@cab.ci", "heures": "4"},
        {"collaborateur": "a.kone@cab.ci", "heures": "1.5"},
    ]
    out = totaux_heures_par_intervenant(entrees)
    # Cumul Decimal exact, tri heures décroissantes puis alphabétique.
    assert out == {"a.kone@cab.ci": "4", "b.diallo@cab.ci": "4"}
    assert list(out) == ["a.kone@cab.ci", "b.diallo@cab.ci"]


def test_pourcentage_consomme_et_seuils_purs():
    """% consommé = coût/honoraires ; le seuil suit les bornes 80/100."""
    from backend.plateforme.rentabilite_mission import calculer_rentabilite

    # 79.9 % → ok.
    ok = calculer_rentabilite("1000", "79.9", "10")
    assert ok["pourcentage_consomme"] == "79.9"
    assert ok["seuil"] == "ok"
    # Exactement 80 % → vigilance.
    vig = calculer_rentabilite("1000", "80", "10")
    assert vig["pourcentage_consomme"] == "80.0"
    assert vig["seuil"] == "vigilance"
    # Exactement 100 % → vigilance encore.
    lim = calculer_rentabilite("1000", "100", "10")
    assert lim["pourcentage_consomme"] == "100.0"
    assert lim["seuil"] == "vigilance"
    # > 100 % → dépassement (marge négative).
    dep = calculer_rentabilite("1000", "150", "10")
    assert dep["pourcentage_consomme"] == "150.0"
    assert dep["seuil"] == "depassement"
    assert dep["marge_estimee"] == "-500"
    # Honoraires à zéro : division impossible → pas de %, pas de seuil.
    zero = calculer_rentabilite("0", "40000", "2")
    assert zero["pourcentage_consomme"] is None
    assert zero["seuil"] is None
    # Sans temps saisi : 0 % consommé, budget tenu.
    sans_temps = calculer_rentabilite("800000", "40000", "0")
    assert sans_temps["pourcentage_consomme"] == "0.0"
    assert sans_temps["seuil"] == "ok"


def test_api_rentabilite_seuils_et_intervenants(session):
    """API : % consommé, seuil, heures par intervenant, note consultative."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert _saisir(client, h, mid, phase="controles",
                   date_jour="2026-07-10", heures=6,
                   collaborateur="a.kone@cab.ci").status_code == 200
    assert _saisir(client, h, mid, phase="restitution",
                   date_jour="2026-07-15", heures=4).status_code == 200
    # 10 h × 45 000 = 450 000 sur 500 000 d'honoraires → 90 % vigilance.
    r = _definir(client, h, mid, honoraires=500000, taux_horaire=45000)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["pourcentage_consomme"] == "90.0"
    assert out["seuil"] == "vigilance"
    assert out["heures_par_intervenant"] == {
        "a.kone@cab.ci": "6",
        email: "4",
    }
    assert "consultatif" in out["note"]
    assert "facturation" in out["note"]

    # Honoraires abaissés : 450 000 / 400 000 → 112.5 % dépassement.
    dep = _definir(client, h, mid, honoraires=400000, taux_horaire=45000)
    assert dep.status_code == 200, dep.text
    assert dep.json()["pourcentage_consomme"] == "112.5"
    assert dep.json()["seuil"] == "depassement"


def test_api_rentabilite_sans_temps(session):
    """Mission sans temps saisi : 0 h, 0 % consommé, aucun intervenant."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert _definir(
        client, h, mid, honoraires=800000, taux_horaire=40000
    ).status_code == 200
    out = client.get(f"/api/v1/missions/{mid}/rentabilite", headers=h).json()
    assert out["total_heures"] == "0"
    assert out["cout_estime"] == "0"
    assert out["pourcentage_consomme"] == "0.0"
    assert out["seuil"] == "ok"
    assert out["heures_par_intervenant"] == {}


def test_consultation_journalisee_dans_chronologie(session):
    """Le GET rentabilité laisse une trace lisible dans la chronologie."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _ = _connexion(client, email)
    mid = _mission(client, h)

    assert client.get(
        f"/api/v1/missions/{mid}/rentabilite", headers=h
    ).status_code == 200
    chrono = client.get(f"/api/v1/missions/{mid}/chronologie", headers=h)
    assert chrono.status_code == 200, chrono.text
    evenements = chrono.json()["evenements"]
    evt = next(
        e for e in evenements
        if e["action"] == "consultation_rentabilite_mission"
    )
    assert evt["acteur"] == email
    assert evt["libelle"] == "Consultation de la rentabilité de la mission"
