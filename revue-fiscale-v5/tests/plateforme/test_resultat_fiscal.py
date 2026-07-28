"""Tableau de passage résultat comptable → résultat fiscal."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.resultat_fiscal import (
    IMF_MINIMUM_PERCEPTION_INDICATIF,
    MOTIF_IMF_DEFICIT,
    MOTIF_IMF_IS_FAIBLE,
    NOTE_RESULTAT_FISCAL,
    SENS_DEDUCTION,
    SENS_REINTEGRATION,
    SENS_REPORT_DEFICITAIRE,
    STATUT_BENEFICIAIRE,
    STATUT_DEFICITAIRE,
    STATUT_INDISPONIBLE,
    STATUT_NUL,
    TAUX_IS_NORMAL,
    ErreurResultatFiscalInvalide,
    arrondir_franc,
    calculer_passage_fiscal,
    extraire_resultat_comptable,
    totaliser_retraitements,
    valider_libelle,
    valider_montant,
    valider_sens,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_valider_sens():
    assert valider_sens("reintegration") == SENS_REINTEGRATION
    assert valider_sens(" deduction ") == SENS_DEDUCTION
    assert valider_sens("report_deficitaire") == SENS_REPORT_DEFICITAIRE
    for mauvais in ("", None, "reint", "REINTEGRATION", "acompte_is"):
        with pytest.raises(ErreurResultatFiscalInvalide):
            valider_sens(mauvais)


def test_valider_libelle():
    assert valider_libelle(" Amendes et pénalités ") == (
        "Amendes et pénalités"
    )
    for mauvais in ("", None, "   "):
        with pytest.raises(ErreurResultatFiscalInvalide):
            valider_libelle(mauvais)
    with pytest.raises(ErreurResultatFiscalInvalide):
        valider_libelle("x" * 301)


def test_valider_montant():
    assert valider_montant(None, "x") == Decimal("0.00")
    assert valider_montant("", "x") == Decimal("0.00")
    assert valider_montant("2500000", "x") == Decimal("2500000.00")
    assert valider_montant("1 000 000", "x") == Decimal("1000000.00")
    with pytest.raises(ErreurResultatFiscalInvalide):
        valider_montant("abc", "x")
    with pytest.raises(ErreurResultatFiscalInvalide):
        valider_montant("-5", "x")


def test_extraire_resultat_comptable_classes_6_7_8():
    soldes = [
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "10000000"},
        {"compte": "601", "libelle": "Achats", "debit": "6000000",
         "credit": "0"},
        {"compte": "661", "libelle": "Personnel", "debit": "2000000",
         "credit": "0"},
        # HAO : produit 82x créditeur, charge 81x débitrice.
        {"compte": "822", "libelle": "Produits cessions", "debit": "0",
         "credit": "500000"},
        {"compte": "812", "libelle": "VNC cessions", "debit": "300000",
         "credit": "0"},
        # Hors résultat : ignoré.
        {"compte": "4411", "libelle": "État, IS", "debit": "0",
         "credit": "999999"},
    ]
    r = extraire_resultat_comptable(soldes)
    assert r["produits_classe7"] == Decimal("10000000")
    assert r["charges_classe6"] == Decimal("8000000")
    assert r["solde_hao_classe8"] == Decimal("200000")
    assert r["resultat_comptable"] == Decimal("2200000")
    assert r["nb_comptes_resultat"] == 5
    assert r["disponible"] is True


def test_extraire_resultat_comptable_indisponible_sans_classe_6_7():
    # Une balance sans comptes 6x/7x ne chiffre pas le passage —
    # même si un compte 8x isolé existe.
    r = extraire_resultat_comptable(
        [{"compte": "811", "libelle": "HAO", "debit": "1", "credit": "0"}]
    )
    assert r["disponible"] is False
    vide = extraire_resultat_comptable([])
    assert vide["disponible"] is False
    assert vide["resultat_comptable"] == Decimal("0")


def test_totaliser_retraitements():
    t = totaliser_retraitements(
        [
            {"sens": "reintegration", "montant": "100"},
            {"sens": "reintegration", "montant": "200"},
            {"sens": "deduction", "montant": "50"},
            {"sens": "inconnu", "montant": "999"},  # ignoré
        ]
    )
    assert t["reintegration"] == Decimal("300")
    assert t["deduction"] == Decimal("50")
    vide = totaliser_retraitements([])
    assert vide["reintegration"] == Decimal("0")


def test_arrondir_franc():
    assert arrondir_franc(Decimal("1234.49")) == Decimal("1234")
    assert arrondir_franc(Decimal("1234.50")) == Decimal("1235")


def _soldes_beneficiaires():
    # Résultat comptable : 100 000 000 - 60 000 000 = 40 000 000.
    return [
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "100000000"},
        {"compte": "601", "libelle": "Achats", "debit": "60000000",
         "credit": "0"},
    ]


def test_passage_beneficiaire_is_25_pct():
    retraitements = [
        {"id": 2, "sens": "deduction", "libelle": "Produits exonérés",
         "montant": "5000000", "reference_cgi": None},
        {"id": 1, "sens": "reintegration", "libelle": "Amendes",
         "montant": "1000000", "reference_cgi": "art. 18 F"},
    ]
    vue = calculer_passage_fiscal(
        _soldes_beneficiaires(), retraitements, None
    )
    assert vue["disponible"] is True
    assert vue["comptable"]["resultat_comptable"] == "40000000"
    assert vue["totaux_retraitements"]["reintegrations"] == "1000000"
    assert vue["totaux_retraitements"]["deductions"] == "5000000"
    # 40 000 000 + 1 000 000 - 5 000 000 = 36 000 000.
    assert vue["resultat_fiscal_avant_report"] == "36000000"
    assert vue["resultat_fiscal"] == "36000000"
    assert vue["taux_is_normal"] == "0.25"
    assert str(TAUX_IS_NORMAL) == "0.25"
    # IS théorique : 36 000 000 × 25 % = 9 000 000 (au franc).
    assert vue["is_theorique"] == "9000000"
    assert vue["synthese"]["statut"] == STATUT_BENEFICIAIRE
    assert vue["imf"]["possible"] is False
    assert vue["imf"]["motif"] is None
    # Réintégrations restituées avant les déductions.
    assert [r["sens"] for r in vue["retraitements"]] == [
        "reintegration", "deduction"
    ]
    assert vue["retraitements"][0]["reference_cgi"] == "art. 18 F"
    assert vue["note"] == NOTE_RESULTAT_FISCAL


def test_passage_is_arrondi_au_franc():
    # Résultat fiscal 101 : IS = 25.25 → 25 (au franc, half-up).
    soldes = [
        {"compte": "701", "libelle": "V", "debit": "0", "credit": "101"},
        {"compte": "601", "libelle": "A", "debit": "0", "credit": "0"},
    ]
    vue = calculer_passage_fiscal(soldes, [], None)
    assert vue["resultat_fiscal"] == "101"
    assert vue["is_theorique"] == "25"


def test_passage_report_deficitaire_plafonne_au_benefice():
    # Avant report : 40 000 000 ; report antérieur 50 000 000 —
    # imputé à hauteur du bénéfice seulement (jamais de déficit créé).
    vue = calculer_passage_fiscal(
        _soldes_beneficiaires(), [], Decimal("50000000")
    )
    assert vue["report_deficitaire"]["saisi"] is True
    assert vue["report_deficitaire"]["anterieur"] == "50000000"
    assert vue["report_deficitaire"]["impute"] == "40000000"
    assert vue["report_deficitaire"]["restant"] == "10000000"
    assert vue["resultat_fiscal"] == "0"
    assert vue["is_theorique"] == "0"
    assert vue["synthese"]["statut"] == STATUT_NUL
    # Résultat nul : signal IMF consultatif.
    assert vue["imf"]["possible"] is True
    assert vue["imf"]["motif"] == MOTIF_IMF_DEFICIT
    # Report partiel : imputé en entier.
    vue2 = calculer_passage_fiscal(
        _soldes_beneficiaires(), [], Decimal("15000000")
    )
    assert vue2["report_deficitaire"]["impute"] == "15000000"
    assert vue2["report_deficitaire"]["restant"] == "0"
    assert vue2["resultat_fiscal"] == "25000000"


def test_passage_report_jamais_impute_sur_deficit():
    retraitements = [
        {"id": 1, "sens": "deduction", "libelle": "Déduction",
         "montant": "45000000", "reference_cgi": None},
    ]
    # Avant report : 40M - 45M = -5 000 000 (déficit) — report intact.
    vue = calculer_passage_fiscal(
        _soldes_beneficiaires(), retraitements, Decimal("2000000")
    )
    assert vue["resultat_fiscal_avant_report"] == "-5000000"
    assert vue["report_deficitaire"]["impute"] == "0"
    assert vue["report_deficitaire"]["restant"] == "2000000"
    assert vue["resultat_fiscal"] == "-5000000"
    assert vue["is_theorique"] == "0"
    assert vue["synthese"]["statut"] == STATUT_DEFICITAIRE
    assert vue["imf"]["possible"] is True
    assert vue["imf"]["motif"] == MOTIF_IMF_DEFICIT


def test_passage_imf_signalee_si_is_faible():
    # Résultat fiscal 4 000 000 → IS 1 000 000 < minimum indicatif
    # 3 000 000 : signal IMF consultatif (IMF non calculé).
    soldes = [
        {"compte": "701", "libelle": "V", "debit": "0",
         "credit": "4000000"},
    ]
    vue = calculer_passage_fiscal(soldes, [], None)
    assert vue["is_theorique"] == "1000000"
    assert vue["imf"]["possible"] is True
    assert vue["imf"]["motif"] == MOTIF_IMF_IS_FAIBLE
    assert vue["imf"]["minimum_perception_indicatif"] == str(
        IMF_MINIMUM_PERCEPTION_INDICATIF
    )
    assert "pourrait s'appliquer" in vue["imf"]["libelle"]


def test_passage_indisponible_cles_stables():
    cles = {
        "disponible", "comptable", "retraitements",
        "totaux_retraitements", "report_deficitaire",
        "resultat_fiscal_avant_report", "resultat_fiscal",
        "taux_is_normal", "is_theorique", "imf", "synthese", "note",
    }
    retraitements = [
        {"id": 1, "sens": "reintegration", "libelle": "Amendes",
         "montant": "100", "reference_cgi": None},
    ]
    vue = calculer_passage_fiscal([], retraitements, Decimal("5"))
    assert cles <= set(vue)
    assert vue["disponible"] is False
    assert vue["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert vue["is_theorique"] == "0"
    assert vue["imf"]["possible"] is False
    # Les retraitements saisis restent listés même sans balance.
    assert vue["synthese"]["nb_retraitements"] == 1
    assert vue["note"] == NOTE_RESULTAT_FISCAL


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_RESULTAT_FISCAL
    assert "décide" in NOTE_RESULTAT_FISCAL


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

    lib = f"v-rfis-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="resultat-fiscal")
    publier_version(session, lib, "rfis@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rfis.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Rfis {email}",
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


def _url_vue(mid: int) -> str:
    return f"/api/v1/missions/{mid}/resultat-fiscal"


def _url_saisie(mid: int) -> str:
    return f"/api/v1/missions/{mid}/retraitements"


def test_api_passage_complet_et_report_plafonne(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Rfis FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "701", "Ventes", "0", "100000000")
    _solde(session, tid, mid, "601", "Achats", "60000000", "0")
    _solde(session, tid, mid, "822", "Produits HAO", "0", "500000")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "reintegration", "libelle": "Amendes fiscales",
              "montant": "1000000", "reference_cgi": "CGI art. 18 F"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["retraitement"]["sens"] == "reintegration"
    assert r1.json()["retraitement"]["montant"] == "1000000.00"
    assert r1.json()["retraitement"]["reference_cgi"] == "CGI art. 18 F"
    r2 = client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "deduction", "libelle": "Produits exonérés",
              "montant": "5000000"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["retraitement"]["reference_cgi"] is None
    r3 = client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "report_deficitaire", "montant": "50000000"},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["report_deficitaire"] == "50000000.00"

    r = client.get(_url_vue(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    # Comptable : 100M - 60M + 0,5M HAO = 40 500 000.
    assert corps["comptable"]["produits_classe7"] == "100000000.00"
    assert corps["comptable"]["charges_classe6"] == "60000000.00"
    assert corps["comptable"]["solde_hao_classe8"] == "500000.00"
    assert corps["comptable"]["resultat_comptable"] == "40500000.00"
    # Avant report : 40,5M + 1M - 5M = 36 500 000.
    assert corps["resultat_fiscal_avant_report"] == "36500000.00"
    # Report 50M plafonné au bénéfice : imputé 36,5M, restant 13,5M.
    assert corps["report_deficitaire"]["impute"] == "36500000.00"
    assert corps["report_deficitaire"]["restant"] == "13500000.00"
    assert corps["resultat_fiscal"] == "0.00"
    assert corps["is_theorique"] == "0"
    assert corps["synthese"]["statut"] == "nul"
    assert corps["imf"]["possible"] is True
    assert "consultatif" in corps["note"]


def test_api_suppression_ligne_par_id(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Rfis Suppr FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "701", "Ventes", "0", "10000000")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "reintegration", "libelle": "À retirer",
              "montant": "9000000"},
    )
    rid = r1.json()["retraitement"]["id"]
    r = client.post(
        _url_saisie(mid), headers=h, json={"supprimer_id": rid}
    )
    assert r.status_code == 200, r.text
    assert r.json()["retraitement_supprime"] == rid
    corps = client.get(_url_vue(mid), headers=h).json()
    assert corps["synthese"]["nb_retraitements"] == 0
    assert corps["resultat_fiscal"] == "10000000.00"
    # Supprimer une ligne inconnue → 404.
    assert client.post(
        _url_saisie(mid), headers=h, json={"supprimer_id": rid}
    ).status_code == 404


def test_api_reprendre_is_du_estime_reutilise_acomptes(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Rfis Reprise FICTIF")
    mid = _mission(session, tid, cid)
    # Résultat fiscal 40 000 000 → IS théorique 10 000 000.
    _solde(session, tid, mid, "701", "Ventes", "0", "100000000")
    _solde(session, tid, mid, "601", "Achats", "60000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        f"/api/v1/missions/{mid}/resultat-fiscal/reprendre-is-du",
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_du_estime"] == "10000000.00"
    assert r.json()["source"] == "resultat_fiscal_theorique"
    # La valeur est bien celle lue par le module acomptes.
    acomptes = client.get(
        f"/api/v1/missions/{mid}/acomptes", headers=h
    ).json()
    assert acomptes["is_du_estime"] == "10000000.00"
    assert acomptes["disponible"] is True


def test_api_reprendre_422_sans_balance(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Rfis Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.post(
        f"/api/v1/missions/{mid}/resultat-fiscal/reprendre-is-du",
        headers=h,
    ).status_code == 422
    # La vue reste stable sans balance.
    corps = client.get(_url_vue(mid), headers=h).json()
    assert corps["disponible"] is False
    assert corps["synthese"]["statut"] == "indisponible"
    assert corps["retraitements"] == []
    assert corps["note"]


def test_api_saisie_422_invalides(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Rfis 422 FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    # Sens inconnu.
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "abattement", "libelle": "x", "montant": "1"},
    ).status_code == 422
    # Libellé manquant pour un retraitement.
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "reintegration", "montant": "1"},
    ).status_code == 422
    # Montant négatif.
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "deduction", "libelle": "x", "montant": "-5"},
    ).status_code == 422
    # Montant illisible.
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "report_deficitaire", "montant": "abc"},
    ).status_code == 422


def test_api_journalisation_saisies_suppression_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Rfis Journal FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "701", "Ventes", "0", "10000000")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "reintegration", "libelle": "Amendes",
              "montant": "100"},
    )
    client.post(
        _url_saisie(mid), headers=h,
        json={"sens": "report_deficitaire", "montant": "500"},
    )
    client.post(
        _url_saisie(mid), headers=h,
        json={"supprimer_id": r1.json()["retraitement"]["id"]},
    )
    client.get(_url_vue(mid), headers=h)
    client.post(
        f"/api/v1/missions/{mid}/resultat-fiscal/reprendre-is-du",
        headers=h,
    )

    with contexte_tenant(session, tid):
        actions = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT action FROM journal_audit "
                    "WHERE mission_id = :m AND action IN "
                    "('saisie_retraitement_fiscal', "
                    "'suppression_retraitement_fiscal', "
                    "'saisie_report_deficitaire', "
                    "'consultation_resultat_fiscal', "
                    "'reprise_is_du_depuis_resultat_fiscal', "
                    "'saisie_is_du_estime') ORDER BY id"
                ),
                {"m": mid},
            ).all()
        ]
    assert "saisie_retraitement_fiscal" in actions
    assert "suppression_retraitement_fiscal" in actions
    assert "saisie_report_deficitaire" in actions
    assert "consultation_resultat_fiscal" in actions
    # La reprise réutilise la saisie du module acomptes (même journal).
    assert "saisie_is_du_estime" in actions
    assert "reprise_is_du_depuis_resultat_fiscal" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM Rfis Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url_vue(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url_saisie(mid_a), headers=h_b,
        json={"sens": "reintegration", "libelle": "x", "montant": "1"},
    ).status_code == 404
    assert client_b.post(
        f"/api/v1/missions/{mid_a}/resultat-fiscal/reprendre-is-du",
        headers=h_b,
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url_vue(1)).status_code == 401
    assert client.post(
        _url_saisie(1), json={"sens": "reintegration"}
    ).status_code == 401
    assert client.post(
        "/api/v1/missions/1/resultat-fiscal/reprendre-is-du"
    ).status_code == 401
