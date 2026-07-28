"""Suivi des acomptes IS versés / IS dû estimé — position de solde."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from backend.plateforme.acomptes import (
    NATURE_ACOMPTE_IS,
    NATURE_CREDIT_REPORTE,
    NATURE_IS_DU_ESTIME,
    NATURE_RETENUE_SOURCE,
    NOTE_ACOMPTES_IS,
    SEUIL_SOLDE_RESIDUEL_FCFA,
    STATUT_CREDIT_A_REPORTER,
    STATUT_EQUILIBRE,
    STATUT_INDISPONIBLE,
    STATUT_SOLDE_A_PAYER,
    ErreurAcomptesInvalide,
    calculer_position_is,
    extraire_soldes_impot_balance,
    totaliser_acomptes,
    valider_date_versement,
    valider_montant,
    valider_nature,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_valider_nature():
    assert valider_nature("acompte_is") == NATURE_ACOMPTE_IS
    assert valider_nature(" retenue_source ") == NATURE_RETENUE_SOURCE
    assert valider_nature("credit_reporte") == NATURE_CREDIT_REPORTE
    assert valider_nature("is_du_estime") == NATURE_IS_DU_ESTIME
    for mauvaise in ("", None, "acompte", "IS", "tva_collectee"):
        with pytest.raises(ErreurAcomptesInvalide):
            valider_nature(mauvaise)


def test_valider_date_versement():
    assert valider_date_versement("2025-04-15") == date(2025, 4, 15)
    assert valider_date_versement(date(2025, 6, 10)) == date(2025, 6, 10)
    for mauvaise in ("", None, "15/04/2025", "2025-13-01", "2025"):
        with pytest.raises(ErreurAcomptesInvalide):
            valider_date_versement(mauvaise)


def test_valider_montant():
    assert valider_montant(None, "x") == Decimal("0.00")
    assert valider_montant("", "x") == Decimal("0.00")
    assert valider_montant("2500000", "x") == Decimal("2500000.00")
    assert valider_montant(1234.5, "x") == Decimal("1234.50")
    assert valider_montant("1 000 000", "x") == Decimal("1000000.00")
    with pytest.raises(ErreurAcomptesInvalide):
        valider_montant("abc", "x")
    with pytest.raises(ErreurAcomptesInvalide):
        valider_montant("-5", "x")


def test_totaliser_acomptes_par_nature():
    acomptes = [
        {"nature": "acompte_is", "montant": "1000000"},
        {"nature": "acompte_is", "montant": "2000000"},
        {"nature": "retenue_source", "montant": "300000"},
        {"nature": "credit_reporte", "montant": "150000"},
        {"nature": "inconnue", "montant": "999999"},  # ignorée
    ]
    t = totaliser_acomptes(acomptes)
    assert t["acompte_is"] == Decimal("3000000")
    assert t["retenue_source"] == Decimal("300000")
    assert t["credit_reporte"] == Decimal("150000")
    assert t["total"] == Decimal("3450000")
    vide = totaliser_acomptes([])
    assert vide["total"] == Decimal("0")
    assert vide["acompte_is"] == Decimal("0")


def test_extraire_soldes_impot_balance():
    soldes = [
        {"compte": "4411", "libelle": "État, IS", "debit": "500000",
         "credit": "2000000"},
        {"compte": "4441", "libelle": "État, autres impôts",
         "debit": "0", "credit": "300000"},
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "10000000"},  # ignoré
        {"compte": "4452", "libelle": "TVA récupérable",
         "debit": "1000000", "credit": "0"},  # ignoré
    ]
    extrait = extraire_soldes_impot_balance(soldes)
    assert extrait["solde_441x"] == Decimal("1500000")
    assert extrait["solde_444x"] == Decimal("300000")
    assert [c["compte"] for c in extrait["comptes"]] == ["4411", "4441"]
    assert extrait["comptes"][0]["prefixe"] == "441"


def _acomptes_type():
    return [
        {"id": 1, "nature": "acompte_is", "date_versement": "2025-04-15",
         "montant": "1000000", "reference_quittance": "Q-001"},
        {"id": 2, "nature": "acompte_is", "date_versement": "2025-06-15",
         "montant": "1000000", "reference_quittance": None},
        {"id": 3, "nature": "retenue_source",
         "date_versement": "2025-03-01", "montant": "500000",
         "reference_quittance": None},
    ]


def test_position_solde_a_payer_important():
    # Dû 5 000 000 - versé 2 500 000 = 2 500 000 à payer (> seuil).
    vue = calculer_position_is(
        _acomptes_type(), Decimal("5000000"), []
    )
    assert vue["disponible"] is True
    assert vue["is_du_estime"] == "5000000"
    assert vue["totaux_verses"]["acompte_is"] == "2000000"
    assert vue["totaux_verses"]["retenue_source"] == "500000"
    assert vue["totaux_verses"]["credit_reporte"] == "0"
    assert vue["totaux_verses"]["total"] == "2500000"
    assert vue["position"]["statut"] == STATUT_SOLDE_A_PAYER
    assert vue["position"]["montant"] == "2500000"
    assert vue["position"]["solde_signe"] == "2500000"
    assert vue["position"]["solde_important"] is True
    assert vue["synthese"]["solde_important"] is True
    assert vue["note"] == NOTE_ACOMPTES_IS


def test_position_credit_a_reporter():
    # Dû 2 000 000 - versé 2 500 000 = crédit 500 000 à reporter.
    vue = calculer_position_is(
        _acomptes_type(), Decimal("2000000"), []
    )
    assert vue["position"]["statut"] == STATUT_CREDIT_A_REPORTER
    assert vue["position"]["solde_signe"] == "-500000"
    assert vue["position"]["montant"] == "500000"
    assert vue["position"]["solde_important"] is True


def test_position_equilibre_et_seuil_strict():
    # Dû = versé : équilibre, jamais important.
    vue = calculer_position_is(
        _acomptes_type(), Decimal("2500000"), []
    )
    assert vue["position"]["statut"] == STATUT_EQUILIBRE
    assert vue["position"]["solde_important"] is False
    # Solde exactement AU seuil : non important (strictement >).
    vue2 = calculer_position_is(
        _acomptes_type(),
        Decimal("2500000") + SEUIL_SOLDE_RESIDUEL_FCFA,
        [],
    )
    assert vue2["position"]["statut"] == STATUT_SOLDE_A_PAYER
    assert vue2["position"]["solde_important"] is False
    assert vue2["seuil_solde_residuel"] == str(SEUIL_SOLDE_RESIDUEL_FCFA)


def test_position_indisponible_sans_du_cles_stables():
    cles = {
        "disponible", "seuil_solde_residuel", "acomptes",
        "totaux_verses", "is_du_estime", "is_du_source", "position",
        "balance", "synthese", "note",
    }
    vue = calculer_position_is(_acomptes_type(), None, [])
    assert cles <= set(vue)
    assert vue["disponible"] is False
    assert vue["is_du_estime"] is None
    assert vue["is_du_source"] == "saisie_fiscaliste"
    assert vue["position"]["statut"] == STATUT_INDISPONIBLE
    assert vue["position"]["solde_important"] is False
    # Les totaux versés restent chiffrés même sans dû estimé.
    assert vue["totaux_verses"]["total"] == "2500000"
    assert vue["synthese"]["nb_versements"] == 3
    assert vue["note"] == NOTE_ACOMPTES_IS
    # Sans aucune donnée : clés toujours présentes.
    vue2 = calculer_position_is([], None, [])
    assert cles <= set(vue2)
    assert vue2["totaux_verses"]["total"] == "0"


def test_position_acomptes_tries_et_balance_informative():
    soldes = [
        {"compte": "4411", "libelle": "État, IS", "debit": "0",
         "credit": "1200000"},
        {"compte": "4441", "libelle": "Autres impôts", "debit": "100000",
         "credit": "0"},
    ]
    vue = calculer_position_is(
        _acomptes_type(), Decimal("3000000"), soldes
    )
    # Tri par date de versement.
    assert [a["date_versement"] for a in vue["acomptes"]] == [
        "2025-03-01", "2025-04-15", "2025-06-15"
    ]
    assert vue["acomptes"][1]["reference_quittance"] == "Q-001"
    assert vue["acomptes"][0]["libelle_nature"] == (
        "Retenues à la source subies"
    )
    assert vue["balance"]["solde_441x"] == "1200000"
    assert vue["balance"]["solde_444x"] == "-100000"
    assert vue["synthese"]["nb_comptes_impot_balance"] == 2


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_ACOMPTES_IS
    assert "décide" in NOTE_ACOMPTES_IS


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

    lib = f"v-acis-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="acomptes-is")
    publier_version(session, lib, "acis@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"acis.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab AcIs {email}",
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
    return f"/api/v1/missions/{mid}/acomptes"


def test_api_saisie_puis_position_solde_a_payer(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM AcIs FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "4411", "État, IS", "0", "1200000")
    _solde(session, tid, mid, "4441", "État, autres impôts", "0", "300000")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "date_versement": "2025-04-15",
              "montant": "1000000", "reference_quittance": "Q-2025-001"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["acompte"]["nature"] == "acompte_is"
    assert r1.json()["acompte"]["montant"] == "1000000.00"
    assert r1.json()["acompte"]["reference_quittance"] == "Q-2025-001"
    r2 = client.post(
        _url(mid), headers=h,
        json={"nature": "retenue_source", "date_versement": "2025-03-01",
              "montant": "500000"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["acompte"]["reference_quittance"] is None
    r3 = client.post(
        _url(mid), headers=h,
        json={"nature": "is_du_estime", "montant": "5000000"},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["is_du_estime"] == "5000000.00"

    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["is_du_estime"] == "5000000.00"
    assert corps["totaux_verses"]["acompte_is"] == "1000000.00"
    assert corps["totaux_verses"]["retenue_source"] == "500000.00"
    assert corps["totaux_verses"]["total"] == "1500000.00"
    # Position : 5 000 000 - 1 500 000 = 3 500 000 à payer (> seuil).
    assert corps["position"]["statut"] == "solde_a_payer"
    assert corps["position"]["montant"] == "3500000.00"
    assert corps["position"]["solde_important"] is True
    # Balance informative 441x/444x.
    assert corps["balance"]["solde_441x"] == "1200000.00"
    assert corps["balance"]["solde_444x"] == "300000.00"
    assert corps["synthese"]["nb_comptes_impot_balance"] == 2
    assert "consultatif" in corps["note"]


def test_api_credit_a_reporter_et_upsert_remplace(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM AcIs Credit FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "date_versement": "2025-04-15",
              "montant": "100"},
    )
    # Re-saisir même nature + même date REMPLACE (correction humaine).
    r = client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "date_versement": "2025-04-15",
              "montant": "3000000", "reference_quittance": "Q-9"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["acompte"]["montant"] == "3000000.00"
    # IS dû estimé re-saisi : remplacé aussi.
    client.post(
        _url(mid), headers=h,
        json={"nature": "is_du_estime", "montant": "9999999"},
    )
    client.post(
        _url(mid), headers=h,
        json={"nature": "is_du_estime", "montant": "2000000"},
    )

    corps = client.get(_url(mid), headers=h).json()
    assert corps["synthese"]["nb_versements"] == 1
    assert corps["totaux_verses"]["total"] == "3000000.00"
    assert corps["is_du_estime"] == "2000000.00"
    # 2 000 000 - 3 000 000 = crédit d'impôt 1 000 000 à reporter.
    assert corps["position"]["statut"] == "credit_a_reporter"
    assert corps["position"]["montant"] == "1000000.00"
    assert corps["position"]["solde_important"] is True


def test_api_sans_du_estime_indisponible_mais_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM AcIs Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["is_du_estime"] is None
    assert corps["synthese"]["statut"] == "indisponible"
    assert corps["acomptes"] == []
    assert corps["totaux_verses"]["total"] == "0"
    assert corps["balance"]["comptes"] == []
    assert corps["note"]


def test_api_saisie_422_invalides(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM AcIs 422 FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    # Nature inconnue.
    assert client.post(
        _url(mid), headers=h,
        json={"nature": "impot_foncier", "date_versement": "2025-01-01",
              "montant": "1"},
    ).status_code == 422
    # Date manquante pour un versement.
    assert client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "montant": "1"},
    ).status_code == 422
    # Date illisible.
    assert client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "date_versement": "15/04/2025",
              "montant": "1"},
    ).status_code == 422
    # Montant négatif.
    assert client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "date_versement": "2025-04-15",
              "montant": "-5"},
    ).status_code == 422


def test_api_journalisation_saisies_et_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM AcIs Journal FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    client.post(
        _url(mid), headers=h,
        json={"nature": "acompte_is", "date_versement": "2025-04-15",
              "montant": "1000000"},
    )
    client.post(
        _url(mid), headers=h,
        json={"nature": "is_du_estime", "montant": "3000000"},
    )
    client.get(_url(mid), headers=h)

    with contexte_tenant(session, tid):
        actions = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT action FROM journal_audit "
                    "WHERE mission_id = :m AND action IN "
                    "('saisie_acompte_impot', 'saisie_is_du_estime', "
                    "'consultation_acomptes_is') ORDER BY id"
                ),
                {"m": mid},
            ).all()
        ]
    assert "saisie_acompte_impot" in actions
    assert "saisie_is_du_estime" in actions
    assert "consultation_acomptes_is" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM AcIs Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url(mid_a), headers=h_b,
        json={"nature": "acompte_is", "date_versement": "2025-01-01",
              "montant": "1"},
    ).status_code == 404
    assert client_b.post(
        _url(mid_a), headers=h_b,
        json={"nature": "is_du_estime", "montant": "1"},
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(
        _url(1), json={"nature": "acompte_is"}
    ).status_code == 401
