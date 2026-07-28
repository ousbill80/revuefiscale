"""Revue de déductibilité des charges — points de vigilance IS."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.deductibilite import (
    GRAVITE_APPRECIATION,
    GRAVITE_NON_DEDUCTIBLE,
    GRAVITE_PLAFOND,
    NOTE_DEDUCTIBILITE,
    ORDRE_GRAVITES,
    REGLES_DEDUCTIBILITE,
    STATUT_AUCUN_POINT,
    STATUT_INDISPONIBLE,
    STATUT_POINTS_A_APPRECIER,
    balayer_charges,
    construire_vue_deductibilite,
    regle_pour_compte,
    synthese_points,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _balance():
    return [
        # Hors classe 6 : jamais un point de vigilance.
        {"compte": "4111", "libelle": "Clients", "debit": "25000000",
         "credit": "0"},
        {"compte": "7011", "libelle": "Ventes", "debit": "0",
         "credit": "100000000"},
        # Charges sans règle : pas de point.
        {"compte": "6011", "libelle": "Achats", "debit": "40000000",
         "credit": "0"},
        # Amendes et pénalités (non déductibles).
        {"compte": "6471", "libelle": "Pénalités fiscales",
         "debit": "2000000", "credit": "0"},
        {"compte": "6580", "libelle": "Amendes", "debit": "500000",
         "credit": "0"},
        # Cadeaux (préfixe LONG 6257 prime sur assurances 625).
        {"compte": "6257", "libelle": "Cadeaux clientèle",
         "debit": "1500000", "credit": "0"},
        # Assurances (625x hors 6257).
        {"compte": "6251", "libelle": "Assurance multirisque",
         "debit": "3000000", "credit": "0"},
        # Frais de siège (plafond).
        {"compte": "6311", "libelle": "Frais de siège",
         "debit": "10000000", "credit": "0"},
        # Rémunérations (appréciation).
        {"compte": "6611", "libelle": "Salaires", "debit": "20000000",
         "credit": "0"},
        # Provisions (appréciation).
        {"compte": "6911", "libelle": "Dotations provisions",
         "debit": "4000000", "credit": "0"},
        # Charge soldée (débit = crédit) : ignorée.
        {"compte": "6741", "libelle": "Intérêts CCA", "debit": "100",
         "credit": "100"},
    ]


def test_referentiel_8_a_12_regles_documentees():
    assert 8 <= len(REGLES_DEDUCTIBILITE) <= 12
    codes = [r["code"] for r in REGLES_DEDUCTIBILITE]
    assert len(codes) == len(set(codes))
    for r in REGLES_DEDUCTIBILITE:
        assert r["gravite"] in ORDRE_GRAVITES
        assert r["prefixes"]
        assert all(p.startswith("6") for p in r["prefixes"])
        # Règle résumée en français avec référence CGI.
        assert "CGI" in r["regle"]
        assert r["libelle"]


def test_regle_pour_compte_prefixe_le_plus_long():
    # 6257 matche cadeaux (4 car.) ET assurances (625) → cadeaux.
    assert regle_pour_compte("6257")["code"] == "cadeaux_clientele"
    assert regle_pour_compte("62571")["code"] == "cadeaux_clientele"
    # 6251 ne matche que les assurances.
    assert regle_pour_compte("6251")["code"] == "assurances"
    # 6234 cadeaux prime sur loyers 623.
    assert regle_pour_compte("6234")["code"] == "cadeaux_clientele"
    assert regle_pour_compte("6231")["code"] == "loyers"


def test_regle_pour_compte_hors_perimetre():
    # Hors classe 6 : jamais rattaché.
    assert regle_pour_compte("7011") is None
    assert regle_pour_compte("4111") is None
    assert regle_pour_compte("") is None
    # Classe 6 sans préfixe du référentiel.
    assert regle_pour_compte("6011") is None


def test_balayer_charges_points_et_totaux():
    points = balayer_charges(_balance())
    par_code = {p["code"]: p for p in points}
    # Amendes : deux comptes agrégés dans un seul point.
    amendes = par_code["amendes_penalites"]
    assert amendes["gravite"] == GRAVITE_NON_DEDUCTIBLE
    assert amendes["nb_comptes"] == 2
    assert amendes["total_solde"] == Decimal("2500000")
    assert [c["compte"] for c in amendes["comptes"]] == [
        "6471", "6580"
    ]
    # Cadeaux et assurances séparés malgré le préfixe commun 625.
    assert par_code["cadeaux_clientele"]["total_solde"] == Decimal(
        "1500000"
    )
    assert par_code["assurances"]["total_solde"] == Decimal("3000000")
    # Achats 6011 (sans règle) et 6741 soldé : aucun point.
    assert "interets_comptes_courants" not in par_code
    codes = set(par_code)
    assert codes == {
        "amendes_penalites", "cadeaux_clientele", "assurances",
        "frais_siege", "remunerations", "provisions",
    }


def test_balayer_charges_tri_gravite_puis_code():
    points = balayer_charges(_balance())
    gravites = [p["gravite"] for p in points]
    rang = {g: i for i, g in enumerate(ORDRE_GRAVITES)}
    assert gravites == sorted(gravites, key=lambda g: rang[g])
    # Non déductible d'abord, appréciation en dernier.
    assert points[0]["gravite"] == GRAVITE_NON_DEDUCTIBLE
    assert points[-1]["gravite"] == GRAVITE_APPRECIATION
    # À gravité égale : tri par code stable.
    plafonds = [p["code"] for p in points
                if p["gravite"] == GRAVITE_PLAFOND]
    assert plafonds == sorted(plafonds)


def test_balayer_charges_vide():
    assert balayer_charges([]) == []


def test_synthese_points_comptages_et_masses():
    soldes = _balance()
    points = balayer_charges(soldes)
    s = synthese_points(soldes, points)
    assert s["nb_points"] == 6
    # Les trois gravités TOUJOURS présentes.
    assert set(s["nb_par_gravite"]) == set(ORDRE_GRAVITES)
    assert s["nb_par_gravite"][GRAVITE_NON_DEDUCTIBLE] == 1
    assert s["nb_par_gravite"][GRAVITE_PLAFOND] == 2
    assert s["nb_par_gravite"][GRAVITE_APPRECIATION] == 3
    # Total concerné = 2.5 + 1.5 + 3 + 10 + 20 + 4 M.
    assert s["total_soldes_concernes"] == Decimal("41000000")
    # Classe 6 entière (y compris achats et compte soldé).
    assert s["nb_comptes_charges"] == 9
    assert s["total_charges"] == Decimal("81000000")


def test_construire_vue_sans_balance_cles_stables():
    cles = {
        "disponible", "points", "referentiel", "synthese", "note",
    }
    vue = construire_vue_deductibilite([])
    assert cles <= set(vue)
    assert vue["disponible"] is False
    assert vue["points"] == []
    assert vue["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert vue["synthese"]["nb_points"] == 0
    assert set(vue["synthese"]["nb_par_gravite"]) == set(ORDRE_GRAVITES)
    assert vue["synthese"]["total_soldes_concernes"] == "0"
    # Référentiel restitué même sans balance (transparence).
    assert len(vue["referentiel"]) == len(REGLES_DEDUCTIBILITE)
    assert vue["note"] == NOTE_DEDUCTIBILITE


def test_construire_vue_aucun_point():
    # Balance sans compte à risque : statut aucun_point.
    vue = construire_vue_deductibilite([
        {"compte": "6011", "libelle": "Achats", "debit": "1000",
         "credit": "0"},
    ])
    assert vue["disponible"] is True
    assert vue["synthese"]["statut"] == STATUT_AUCUN_POINT
    assert vue["points"] == []


def test_construire_vue_montants_str_et_structure():
    vue = construire_vue_deductibilite(_balance())
    assert vue["synthese"]["statut"] == STATUT_POINTS_A_APPRECIER
    premier = vue["points"][0]
    # Montants sérialisés en str.
    assert premier["total_solde"] == "2500000"
    assert premier["comptes"][0]["solde"] == "2000000"
    assert isinstance(premier["gravite_libelle"], str)
    assert "CGI" in premier["regle"]
    assert vue["synthese"]["total_soldes_concernes"] == "41000000"
    assert vue["synthese"]["total_charges"] == "81000000"


def test_note_consultative_humain_decide():
    assert "consultative" in NOTE_DEDUCTIBILITE
    assert "décide" in NOTE_DEDUCTIBILITE
    assert "AUCUNE réintégration" in NOTE_DEDUCTIBILITE


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

    lib = f"v-ded-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="deductibilite")
    publier_version(session, lib, "ded@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"ded.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Ded {email}",
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
    return f"/api/v1/missions/{mid}/deductibilite"


def _mission_avec_balance(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Ded FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "6011", "Achats", "40000000", "0")
    _solde(session, tid, mid, "6471", "Pénalités fiscales",
           "2000000", "0")
    _solde(session, tid, mid, "6257", "Cadeaux clientèle",
           "1500000", "0")
    _solde(session, tid, mid, "6911", "Dotations provisions",
           "4000000", "0")
    _solde(session, tid, mid, "7011", "Ventes", "0", "100000000")
    session.commit()
    return tid, email, mid


def test_api_points_de_vigilance(session):
    tid, email, mid = _mission_avec_balance(session)

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["synthese"]["statut"] == "points_a_apprecier"
    assert corps["synthese"]["nb_points"] == 3
    assert corps["synthese"]["nb_par_gravite"] == {
        "non_deductible": 1, "plafond": 1, "appreciation": 1,
    }
    assert corps["synthese"]["total_soldes_concernes"] == "7500000.00"
    par_code = {p["code"]: p for p in corps["points"]}
    assert par_code["amendes_penalites"]["total_solde"] == "2000000.00"
    assert par_code["amendes_penalites"]["gravite"] == "non_deductible"
    assert "CGI" in par_code["amendes_penalites"]["regle"]
    assert par_code["cadeaux_clientele"]["comptes"][0]["compte"] == (
        "6257"
    )
    # Référentiel complet toujours restitué.
    assert len(corps["referentiel"]) >= 8
    assert "consultative" in corps["note"]

    # Consultation journalisée.
    with contexte_tenant(session, tid):
        actions = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'consultation_deductibilite'"
            ),
            {"m": mid},
        ).mappings().all()
    assert len(actions) == 1
    assert actions[0]["charge_utile"]["nb_points"] == 3


def test_api_sans_balance_indisponible_mais_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Ded Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["synthese"]["statut"] == "indisponible"
    assert corps["points"] == []
    assert len(corps["referentiel"]) >= 8
    assert corps["note"]


def test_api_404_cross_tenant(session):
    _tid_a, _email_a, mid_a = _mission_avec_balance(session)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
