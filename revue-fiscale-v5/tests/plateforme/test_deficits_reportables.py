"""Suivi pluriannuel des déficits reportables — vue consultative."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.deficits_reportables import (
    MOTIF_IMPUTATION_REELLE_NON_CALCULABLE,
    NOTE_DEFICITS_REPORTABLES,
    REGLE_REPORT_INDICATIVE,
    STATUT_AUCUN_DEFICIT,
    STATUT_DEFICITS_A_SUIVRE,
    STATUT_INDISPONIBLE,
    construire_suivi_deficits,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_indisponible_sans_exercices():
    vue = construire_suivi_deficits([])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["exercices"] == []
    assert vue["cumul_indicatif_final"] == "0"


def test_indisponible_exercices_non_chiffrables():
    vue = construire_suivi_deficits(
        [
            {"exercice": 2023, "mission_id": 1, "disponible": False,
             "resultat_fiscal": None},
            {"exercice": 2024, "mission_id": 2, "disponible": False,
             "resultat_fiscal": None},
        ]
    )
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert len(vue["exercices"]) == 2
    assert all(
        ligne["statut"] == "indisponible"
        and ligne["resultat_fiscal_theorique"] is None
        for ligne in vue["exercices"]
    )


def test_mono_exercice_beneficiaire_aucun_deficit():
    vue = construire_suivi_deficits(
        [{"exercice": 2025, "mission_id": 7, "disponible": True,
          "resultat_fiscal": "15000000"}]
    )
    assert vue["disponible"] is True
    assert vue["statut"] == STATUT_AUCUN_DEFICIT
    ligne = vue["exercices"][0]
    assert ligne["statut"] == "benefice"
    assert ligne["deficit_constate"] == "0"
    assert ligne["imputation_theorique"] == "0"
    assert vue["cumul_indicatif_final"] == "0"


def test_deficit_simple_a_suivre():
    vue = construire_suivi_deficits(
        [{"exercice": 2025, "mission_id": 7, "disponible": True,
          "resultat_fiscal": "-6000000"}]
    )
    assert vue["statut"] == STATUT_DEFICITS_A_SUIVRE
    ligne = vue["exercices"][0]
    assert ligne["statut"] == "deficit"
    assert ligne["deficit_constate"] == "6000000"
    assert ligne["cumul_indicatif_deficits"] == "6000000"
    assert vue["cumul_indicatif_final"] == "6000000"
    assert vue["synthese"]["nb_deficits_constates"] == 1


def test_imputation_theorique_plafonnee_au_benefice():
    # Déficit 2023 puis bénéfice 2024 SUPÉRIEUR : cumul absorbé.
    vue = construire_suivi_deficits(
        [
            {"exercice": 2023, "mission_id": 1, "disponible": True,
             "resultat_fiscal": "-6000000"},
            {"exercice": 2024, "mission_id": 2, "disponible": True,
             "resultat_fiscal": "15000000"},
        ]
    )
    assert vue["exercices"][1]["imputation_theorique"] == "6000000"
    assert vue["cumul_indicatif_final"] == "0"
    # Le déficit RESTE constaté (à suivre : l'humain rapproche).
    assert vue["statut"] == STATUT_DEFICITS_A_SUIVRE

    # Bénéfice INFÉRIEUR au cumul : imputation plafonnée au bénéfice,
    # jamais au-delà (l'imputation ne crée pas de déficit).
    vue2 = construire_suivi_deficits(
        [
            {"exercice": 2023, "mission_id": 1, "disponible": True,
             "resultat_fiscal": "-6000000"},
            {"exercice": 2024, "mission_id": 2, "disponible": True,
             "resultat_fiscal": "2000000"},
        ]
    )
    assert vue2["exercices"][1]["imputation_theorique"] == "2000000"
    assert vue2["cumul_indicatif_final"] == "4000000"


def test_plusieurs_exercices_tries_par_exercice_croissant():
    vue = construire_suivi_deficits(
        [
            {"exercice": 2025, "mission_id": 3, "disponible": True,
             "resultat_fiscal": "1000000"},
            {"exercice": 2023, "mission_id": 1, "disponible": True,
             "resultat_fiscal": "-500000"},
            {"exercice": 2024, "mission_id": 2, "disponible": True,
             "resultat_fiscal": "-250000"},
        ]
    )
    assert [ligne["exercice"] for ligne in vue["exercices"]] == [
        2023, 2024, 2025,
    ]
    # Cumul dans l'ordre du temps : 500 000 + 250 000 puis imputation
    # théorique de 750 000 sur le bénéfice 2025.
    assert vue["exercices"][1]["cumul_indicatif_deficits"] == "750000"
    assert vue["exercices"][2]["imputation_theorique"] == "750000"
    assert vue["cumul_indicatif_final"] == "0"


def test_exercice_indisponible_cumul_inchange():
    vue = construire_suivi_deficits(
        [
            {"exercice": 2023, "mission_id": 1, "disponible": True,
             "resultat_fiscal": "-3000000"},
            {"exercice": 2024, "mission_id": 2, "disponible": False,
             "resultat_fiscal": None},
        ]
    )
    ligne_2024 = vue["exercices"][1]
    assert ligne_2024["statut"] == "indisponible"
    assert ligne_2024["deficit_constate"] == "0"
    # Aucun montant inventé : cumul inchangé, ligne non chiffrée.
    assert ligne_2024["cumul_indicatif_deficits"] == "3000000"
    assert vue["cumul_indicatif_final"] == "3000000"


def test_resultat_nul_sans_deficit():
    vue = construire_suivi_deficits(
        [{"exercice": 2025, "mission_id": 7, "disponible": True,
          "resultat_fiscal": "0"}]
    )
    assert vue["statut"] == STATUT_AUCUN_DEFICIT
    assert vue["exercices"][0]["statut"] == "nul"
    assert vue["cumul_indicatif_final"] == "0"


def test_cles_stables_toujours_presentes():
    cles = {
        "disponible", "exercices", "cumul_indicatif_final",
        "approximation", "regle_report", "imputation_reelle", "statut",
        "synthese", "note", "references",
    }
    for vue in (
        construire_suivi_deficits([]),
        construire_suivi_deficits(
            [{"exercice": 2025, "mission_id": 1, "disponible": True,
              "resultat_fiscal": "-100"}]
        ),
    ):
        assert cles <= set(vue)
        assert vue["note"] == NOTE_DEFICITS_REPORTABLES
        assert vue["references"]
        assert vue["synthese"]["statut"] == vue["statut"]
        assert vue["approximation"] is True


def test_montants_serialises_en_str():
    vue = construire_suivi_deficits(
        [
            {"exercice": 2023, "mission_id": 1, "disponible": True,
             "resultat_fiscal": Decimal("-6000000.00")},
            {"exercice": 2024, "mission_id": 2, "disponible": True,
             "resultat_fiscal": Decimal("15000000.00")},
        ]
    )
    assert isinstance(vue["cumul_indicatif_final"], str)
    for ligne in vue["exercices"]:
        assert isinstance(ligne["resultat_fiscal_theorique"], str)
        assert isinstance(ligne["deficit_constate"], str)
        assert isinstance(ligne["imputation_theorique"], str)
        assert isinstance(ligne["cumul_indicatif_deficits"], str)


def test_regle_report_sans_delai_invente():
    vue = construire_suivi_deficits([])
    regle = vue["regle_report"]
    assert regle["principe"] == REGLE_REPORT_INDICATIVE
    # Aucun délai chiffré inventé : le CGI applicable fait foi.
    assert regle["delai_chiffre"] is False
    assert "CGI" in regle["principe"]
    assert "report" in regle["principe"].lower()


def test_imputation_reelle_jamais_calculable():
    for vue in (
        construire_suivi_deficits([]),
        construire_suivi_deficits(
            [{"exercice": 2025, "mission_id": 1, "disponible": True,
              "resultat_fiscal": "-100"}]
        ),
    ):
        imp = vue["imputation_reelle"]
        assert imp["calculable"] is False
        assert imp["motif"] == MOTIF_IMPUTATION_REELLE_NON_CALCULABLE
        assert "liasses" in imp["motif"]


def test_note_approximation_documentee_et_non_accusatoire():
    assert "consultati" in NOTE_DEFICITS_REPORTABLES
    assert "APPROXIMATION ASSUMÉE" in NOTE_DEFICITS_REPORTABLES
    assert "liasses" in NOTE_DEFICITS_REPORTABLES
    assert "aucun recalcul" in NOTE_DEFICITS_REPORTABLES
    assert "décide" in NOTE_DEFICITS_REPORTABLES
    # Jamais accusatoire : à rapprocher, jamais une conclusion.
    assert "à rapprocher" in NOTE_DEFICITS_REPORTABLES
    assert "jamais une conclusion" in NOTE_DEFICITS_REPORTABLES


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

    lib = f"v-defrep-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="deficits reportables")
    publier_version(session, lib, "defrep@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"defrep.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab DeficitsReportables {email}",
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
    return f"/api/v1/missions/{mid}/deficits-reportables"


def test_api_deficit_simple_mono_exercice(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM DeficitsRep FICTIVE")
    mid = _mission(session, tid, cid, exercice=2025)
    # Charges 10 M > produits 4 M : résultat fiscal théorique -6 M.
    _solde(session, tid, mid, "601", "Achats FICTIFS", "10000000", "0")
    _solde(session, tid, mid, "701", "Ventes FICTIVES", "0", "4000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert corps["statut"] == "deficits_a_suivre"
    assert corps["approximation"] is True
    assert corps["synthese"]["nb_exercices"] == 1
    assert corps["synthese"]["nb_deficits_constates"] == 1
    ligne = corps["exercices"][0]
    assert ligne["exercice"] == 2025
    assert Decimal(ligne["resultat_fiscal_theorique"]) == Decimal(
        "-6000000"
    )
    assert Decimal(ligne["deficit_constate"]) == Decimal("6000000")
    assert Decimal(corps["cumul_indicatif_final"]) == Decimal("6000000")
    assert corps["imputation_reelle"]["calculable"] is False
    assert corps["regle_report"]["delai_chiffre"] is False
    assert "consultati" in corps["note"]
    assert corps["references"]


def test_api_mono_exercice_beneficiaire(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM DeficitsRep Benef FICTIVE")
    mid = _mission(session, tid, cid, exercice=2025)
    _solde(session, tid, mid, "701", "Ventes FICTIVES", "0", "20000000")
    _solde(session, tid, mid, "601", "Achats FICTIFS", "5000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["statut"] == "aucun_deficit"
    assert Decimal(corps["cumul_indicatif_final"]) == Decimal("0")
    assert corps["exercices"][0]["statut"] == "benefice"


def test_api_plusieurs_exercices_du_meme_client(session):
    # Historique du MÊME client : déficit 2024 puis bénéfice 2025 —
    # imputation théorique maximale, cumul indicatif absorbé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM DeficitsRep Pluri FICTIVE")
    mid_2024 = _mission(session, tid, cid, exercice=2024)
    _solde(session, tid, mid_2024, "601", "Achats FICTIFS",
           "10000000", "0")
    _solde(session, tid, mid_2024, "701", "Ventes FICTIVES",
           "0", "4000000")
    mid_2025 = _mission(session, tid, cid, exercice=2025)
    _solde(session, tid, mid_2025, "701", "Ventes FICTIVES",
           "0", "20000000")
    _solde(session, tid, mid_2025, "601", "Achats FICTIFS",
           "5000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid_2025), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is True
    assert corps["synthese"]["nb_exercices"] == 2
    assert [ligne["exercice"] for ligne in corps["exercices"]] == [
        2024, 2025,
    ]
    assert Decimal(
        corps["exercices"][0]["deficit_constate"]
    ) == Decimal("6000000")
    assert Decimal(
        corps["exercices"][1]["imputation_theorique"]
    ) == Decimal("6000000")
    assert Decimal(corps["cumul_indicatif_final"]) == Decimal("0")
    # Un déficit constaté reste « à suivre » (liasses à rapprocher).
    assert corps["statut"] == "deficits_a_suivre"


def test_api_exercice_anterieur_sans_balance_tolere(session):
    # 2024 sans balance : ligne indisponible, 2025 chiffrée quand même.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM DeficitsRep Trou FICTIVE")
    _mission(session, tid, cid, exercice=2024)
    mid_2025 = _mission(session, tid, cid, exercice=2025)
    _solde(session, tid, mid_2025, "601", "Achats FICTIFS",
           "3000000", "0")
    _solde(session, tid, mid_2025, "701", "Ventes FICTIVES",
           "0", "1000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid_2025), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is True
    assert corps["exercices"][0]["statut"] == "indisponible"
    assert corps["exercices"][0]["resultat_fiscal_theorique"] is None
    assert corps["exercices"][1]["statut"] == "deficit"
    assert Decimal(corps["cumul_indicatif_final"]) == Decimal("2000000")


def test_api_indisponible_sans_aucune_balance(session):
    # Tolérance : sans historique chiffrable, la vue se sert quand
    # même — disponible=false, clés stables, aucun montant inventé.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM DeficitsRep Vide FICTIVE")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["cumul_indicatif_final"] == "0"
    assert corps["imputation_reelle"]["calculable"] is False
    assert corps["note"]
    assert corps["references"]


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM DeficitsRep Journal FICTIVE")
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
                    "AND action = 'consultation_deficits_reportables'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_deficits_reportables" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM DeficitsRep Cross FICTIVE")
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
