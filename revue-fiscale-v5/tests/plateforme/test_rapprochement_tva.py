"""Rapprochement TVA déclarée (DGI) / comptabilisée (balance 443x/445x)."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.rapprochement_tva import (
    NOTE_RAPPROCHEMENT_TVA,
    SEUIL_SIGNIFICATION_FCFA,
    STATUT_COHERENT,
    STATUT_ECARTS,
    STATUT_INDISPONIBLE,
    ErreurRapprochementTvaInvalide,
    extraire_tva_balance,
    rapprocher_tva,
    totaliser_declarations,
    valider_montant,
    valider_periode,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_valider_periode_formats():
    assert valider_periode("2025-01") == "2025-01"
    assert valider_periode(" 2025-12 ") == "2025-12"
    for mauvaise in ("2025", "2025-13", "2025-00", "25-01", "", None,
                     "2025/01", "2025-1"):
        with pytest.raises(ErreurRapprochementTvaInvalide):
            valider_periode(mauvaise)


def test_valider_montant():
    assert valider_montant(None, "x") == Decimal("0.00")
    assert valider_montant("", "x") == Decimal("0.00")
    assert valider_montant("1500000", "x") == Decimal("1500000.00")
    assert valider_montant(1234.5, "x") == Decimal("1234.50")
    assert valider_montant("1 000 000", "x") == Decimal("1000000.00")
    with pytest.raises(ErreurRapprochementTvaInvalide):
        valider_montant("abc", "x")
    with pytest.raises(ErreurRapprochementTvaInvalide):
        valider_montant("-5", "x")


def test_extraire_tva_balance_natures_et_sens():
    soldes = [
        # 443x TVA facturée : solde créditeur net = collectée.
        {"compte": "4431", "libelle": "TVA facturée ventes",
         "debit": "0", "credit": "18000000"},
        {"compte": "4432", "libelle": "TVA facturée prestations",
         "debit": "500000", "credit": "2500000"},
        # 445x TVA récupérable : solde débiteur net = déductible.
        {"compte": "4452", "libelle": "TVA récup. achats",
         "debit": "9000000", "credit": "1000000"},
        # 444x : position nette (informatif).
        {"compte": "4441", "libelle": "TVA due",
         "debit": "0", "credit": "1200000"},
        # Hors TVA : ignoré.
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "100000000"},
        {"compte": "4421", "libelle": "Impôts sur salaires",
         "debit": "0", "credit": "300000"},
    ]
    extrait = extraire_tva_balance(soldes)
    assert extrait["tva_collectee"] == Decimal("20000000")
    assert extrait["tva_deductible"] == Decimal("8000000")
    assert extrait["tva_nette"] == Decimal("12000000")
    assert extrait["solde_tva_due_ou_credit"] == Decimal("1200000")
    assert [c["compte"] for c in extrait["comptes"]] == [
        "4431", "4432", "4452", "4441"
    ]


def test_totaliser_declarations():
    decls = [
        {"periode": "2025-01", "tva_collectee": "1000000",
         "tva_deductible": "400000"},
        {"periode": "2025-02", "tva_collectee": "2000000",
         "tva_deductible": "600000"},
    ]
    t = totaliser_declarations(decls)
    assert t["tva_collectee"] == Decimal("3000000")
    assert t["tva_deductible"] == Decimal("1000000")
    assert t["tva_nette"] == Decimal("2000000")
    vide = totaliser_declarations([])
    assert vide["tva_nette"] == Decimal("0")


def _soldes_coherents():
    return [
        {"compte": "4431", "libelle": "TVA facturée", "debit": "0",
         "credit": "3000000"},
        {"compte": "4452", "libelle": "TVA récupérable",
         "debit": "1000000", "credit": "0"},
    ]


def test_rapprocher_tva_coherent():
    decls = [
        {"periode": "2025-01", "tva_collectee": "1000000",
         "tva_deductible": "400000"},
        {"periode": "2025-02", "tva_collectee": "2000000",
         "tva_deductible": "600000"},
    ]
    vue = rapprocher_tva(decls, _soldes_coherents())
    assert vue["disponible"] is True
    assert vue["synthese"]["statut"] == STATUT_COHERENT
    assert vue["synthese"]["nb_ecarts_significatifs"] == 0
    assert vue["synthese"]["nb_periodes_declarees"] == 2
    # Montants sérialisés en str.
    assert vue["totaux_declares"]["tva_collectee"] == "3000000"
    assert vue["comptabilise"]["tva_deductible"] == "1000000"
    for ecart in vue["ecarts"]:
        assert ecart["ecart"] == "0"
        assert ecart["significatif"] is False
    assert vue["note"] == NOTE_RAPPROCHEMENT_TVA


def test_rapprocher_tva_ecart_significatif():
    # Déclaré 2 500 000 collectée vs 3 000 000 comptabilisée :
    # écart -500 000 > seuil 100 000 → significatif.
    decls = [
        {"periode": "2025-01", "tva_collectee": "2500000",
         "tva_deductible": "1000000"},
    ]
    vue = rapprocher_tva(decls, _soldes_coherents())
    assert vue["synthese"]["statut"] == STATUT_ECARTS
    par_nature = {e["nature"]: e for e in vue["ecarts"]}
    collectee = par_nature["tva_collectee"]
    assert collectee["declare"] == "2500000"
    assert collectee["comptabilise"] == "3000000"
    assert collectee["ecart"] == "-500000"
    assert collectee["significatif"] is True
    assert par_nature["tva_deductible"]["significatif"] is False
    assert par_nature["tva_nette"]["significatif"] is True
    assert vue["synthese"]["nb_ecarts_significatifs"] == 2


def test_rapprocher_tva_seuil_strict():
    # Écart exactement AU seuil : non significatif (strictement >).
    seuil = SEUIL_SIGNIFICATION_FCFA
    decls = [
        {"periode": "2025-01",
         "tva_collectee": str(Decimal("3000000") - seuil),
         "tva_deductible": "1000000"},
    ]
    vue = rapprocher_tva(decls, _soldes_coherents())
    par_nature = {e["nature"]: e for e in vue["ecarts"]}
    assert par_nature["tva_collectee"]["significatif"] is False
    assert vue["seuil_signification"] == str(seuil)


def test_rapprocher_tva_indisponible_cles_stables():
    cles = {
        "disponible", "seuil_signification", "declarations",
        "totaux_declares", "comptabilise", "ecarts", "synthese", "note",
    }
    # Sans déclaration.
    vue1 = rapprocher_tva([], _soldes_coherents())
    assert cles <= set(vue1)
    assert vue1["disponible"] is False
    assert vue1["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert all(e["significatif"] is False for e in vue1["ecarts"])
    # Sans compte TVA en balance.
    vue2 = rapprocher_tva(
        [{"periode": "2025-01", "tva_collectee": "1", "tva_deductible": "0"}],
        [{"compte": "701", "libelle": "Ventes", "debit": "0",
          "credit": "10"}],
    )
    assert cles <= set(vue2)
    assert vue2["disponible"] is False
    assert vue2["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert vue2["note"] == NOTE_RAPPROCHEMENT_TVA


def test_rapprocher_tva_declarations_triees_par_periode():
    decls = [
        {"periode": "2025-03", "tva_collectee": "3", "tva_deductible": "0"},
        {"periode": "2025-01", "tva_collectee": "1", "tva_deductible": "0"},
        {"periode": "2025-02", "tva_collectee": "2", "tva_deductible": "1"},
    ]
    vue = rapprocher_tva(decls, _soldes_coherents())
    assert [d["periode"] for d in vue["declarations"]] == [
        "2025-01", "2025-02", "2025-03"
    ]
    assert vue["declarations"][1]["tva_nette"] == "1"


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_RAPPROCHEMENT_TVA
    assert "décide" in NOTE_RAPPROCHEMENT_TVA


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

    lib = f"v-rtva-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="rapprochement-tva")
    publier_version(session, lib, "rtva@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rtva.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RTva {email}",
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
    return f"/api/v1/missions/{mid}/rapprochement-tva"


def _url_saisie(mid: int) -> str:
    return f"/api/v1/missions/{mid}/declarations-tva"


def test_api_saisie_puis_rapprochement_ecart(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RTva FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "4431", "TVA facturée", "0", "3000000")
    _solde(session, tid, mid, "4452", "TVA récupérable", "1000000", "0")
    _solde(session, tid, mid, "4441", "TVA due", "0", "2000000")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-01", "tva_collectee": "1500000",
              "tva_deductible": "500000"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["declaration"]["periode"] == "2025-01"
    assert r1.json()["declaration"]["tva_collectee"] == "1500000.00"
    r2 = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-02", "tva_collectee": "1000000",
              "tva_deductible": "500000"},
    )
    assert r2.status_code == 200, r2.text

    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    # Déclaré : 2 500 000 / 1 000 000 — Comptabilisé : 3 000 000 / 1 000 000.
    par_nature = {e["nature"]: e for e in corps["ecarts"]}
    assert par_nature["tva_collectee"]["ecart"] == "-500000.00"
    assert par_nature["tva_collectee"]["significatif"] is True
    assert par_nature["tva_deductible"]["ecart"] == "0.00"
    assert par_nature["tva_deductible"]["significatif"] is False
    assert corps["synthese"]["statut"] == "ecarts_a_expliquer"
    assert corps["synthese"]["nb_periodes_declarees"] == 2
    assert corps["comptabilise"]["solde_tva_due_ou_credit"] == "2000000.00"
    assert "consultatif" in corps["note"]


def test_api_upsert_remplace_la_periode(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RTva Upsert FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-03", "tva_collectee": "100",
              "tva_deductible": "50"},
    )
    r = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-03", "tva_collectee": "999",
              "tva_deductible": "0"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["declaration"]["tva_collectee"] == "999.00"

    corps = client.get(_url(mid), headers=h).json()
    assert corps["synthese"]["nb_periodes_declarees"] == 1
    assert corps["totaux_declares"]["tva_collectee"] == "999.00"


def test_api_sans_donnees_indisponible_mais_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RTva Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["synthese"]["statut"] == "indisponible"
    assert corps["declarations"] == []
    assert corps["ecarts"] != []  # les 3 natures restent présentes
    assert corps["note"]


def test_api_saisie_422_periode_ou_montant_invalides(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RTva 422 FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-13", "tva_collectee": "1"},
    ).status_code == 422
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-01", "tva_collectee": "-5"},
    ).status_code == 422


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM RTva Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url_saisie(mid_a), headers=h_b,
        json={"periode": "2025-01", "tva_collectee": "1"},
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(
        _url_saisie(1), json={"periode": "2025-01"}
    ).status_code == 401
