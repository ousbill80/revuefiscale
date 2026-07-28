"""Rapprochement impôts sur salaires déclarés / masse salariale 66x."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.rapprochement_salaires import (
    COMMENTAIRE_MASSE_SUPERIEURE,
    NOTE_RAPPROCHEMENT_SALAIRES,
    SEUIL_SIGNIFICATION_FCFA,
    STATUT_COHERENT,
    STATUT_ECARTS,
    STATUT_INDISPONIBLE,
    ErreurRapprochementSalairesInvalide,
    extraire_salaires_balance,
    rapprocher_salaires,
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
        with pytest.raises(ErreurRapprochementSalairesInvalide):
            valider_periode(mauvaise)


def test_valider_montant():
    assert valider_montant(None, "x") == Decimal("0.00")
    assert valider_montant("", "x") == Decimal("0.00")
    assert valider_montant("1500000", "x") == Decimal("1500000.00")
    assert valider_montant(1234.5, "x") == Decimal("1234.50")
    assert valider_montant("1 000 000", "x") == Decimal("1000000.00")
    with pytest.raises(ErreurRapprochementSalairesInvalide):
        valider_montant("abc", "x")
    with pytest.raises(ErreurRapprochementSalairesInvalide):
        valider_montant("-5", "x")


def test_extraire_salaires_balance_natures_et_sens():
    soldes = [
        # 66x Charges de personnel : solde débiteur net = masse.
        {"compte": "6611", "libelle": "Appointements salaires",
         "debit": "24000000", "credit": "0"},
        {"compte": "6631", "libelle": "Indemnités",
         "debit": "2500000", "credit": "500000"},
        # 447x État, impôts retenus à la source : créditeur (informatif).
        {"compte": "4471", "libelle": "État, ITS retenus",
         "debit": "100000", "credit": "700000"},
        # 42x Personnel : créditeur (informatif).
        {"compte": "4221", "libelle": "Personnel, rémunérations dues",
         "debit": "0", "credit": "1500000"},
        # Hors périmètre : ignoré.
        {"compte": "701", "libelle": "Ventes", "debit": "0",
         "credit": "100000000"},
        {"compte": "4431", "libelle": "TVA facturée", "debit": "0",
         "credit": "300000"},
    ]
    extrait = extraire_salaires_balance(soldes)
    assert extrait["masse_salariale"] == Decimal("26000000")
    assert extrait["solde_etat_retenues"] == Decimal("600000")
    assert extrait["solde_personnel"] == Decimal("1500000")
    assert [c["compte"] for c in extrait["comptes"]] == [
        "6611", "6631", "4471", "4221"
    ]


def test_totaliser_declarations():
    decls = [
        {"periode": "2025-01", "masse_salariale_brute": "2000000",
         "its_retenu": "150000", "contribution_employeur": "50000"},
        {"periode": "2025-02", "masse_salariale_brute": "2200000",
         "its_retenu": "160000", "contribution_employeur": "55000"},
    ]
    t = totaliser_declarations(decls)
    assert t["masse_salariale_brute"] == Decimal("4200000")
    assert t["its_retenu"] == Decimal("310000")
    assert t["contribution_employeur"] == Decimal("105000")
    vide = totaliser_declarations([])
    assert vide["masse_salariale_brute"] == Decimal("0")


def _soldes_coherents():
    return [
        {"compte": "6611", "libelle": "Salaires",
         "debit": "4200000", "credit": "0"},
        {"compte": "4471", "libelle": "État, ITS retenus",
         "debit": "0", "credit": "310000"},
    ]


def _decls_coherentes():
    return [
        {"periode": "2025-01", "masse_salariale_brute": "2000000",
         "its_retenu": "150000", "contribution_employeur": "50000"},
        {"periode": "2025-02", "masse_salariale_brute": "2200000",
         "its_retenu": "160000", "contribution_employeur": "55000"},
    ]


def test_rapprocher_salaires_coherent():
    vue = rapprocher_salaires(_decls_coherentes(), _soldes_coherents())
    assert vue["disponible"] is True
    assert vue["synthese"]["statut"] == STATUT_COHERENT
    assert vue["synthese"]["nb_ecarts_significatifs"] == 0
    assert vue["synthese"]["nb_periodes_declarees"] == 2
    assert vue["synthese"]["nb_comptes_66_balance"] == 1
    # Montants sérialisés en str.
    assert vue["totaux_declares"]["masse_salariale_brute"] == "4200000"
    assert vue["comptabilise"]["masse_salariale"] == "4200000"
    assert vue["comptabilise"]["solde_etat_retenues"] == "310000"
    ecart = vue["ecarts"][0]
    assert ecart["nature"] == "masse_salariale"
    assert ecart["ecart"] == "0"
    assert ecart["significatif"] is False
    assert ecart["commentaire"] == ""
    assert vue["note"] == NOTE_RAPPROCHEMENT_SALAIRES


def test_rapprocher_salaires_masse_comptable_superieure_commentaire():
    # Déclaré 4 200 000 vs comptabilisé 5 000 000 : écart -800 000 —
    # significatif ET commentaire « salaires non déclarés possibles ».
    soldes = [
        {"compte": "6611", "libelle": "Salaires",
         "debit": "5000000", "credit": "0"},
    ]
    vue = rapprocher_salaires(_decls_coherentes(), soldes)
    assert vue["synthese"]["statut"] == STATUT_ECARTS
    ecart = vue["ecarts"][0]
    assert ecart["declare"] == "4200000"
    assert ecart["comptabilise"] == "5000000"
    assert ecart["ecart"] == "-800000"
    assert ecart["significatif"] is True
    assert ecart["commentaire"] == COMMENTAIRE_MASSE_SUPERIEURE
    assert "non déclarés" in ecart["commentaire"]


def test_rapprocher_salaires_masse_declaree_superieure_sans_commentaire():
    # Déclaré > comptabilisé : significatif mais SANS le commentaire
    # « salaires non déclarés » (il vise le sens inverse).
    soldes = [
        {"compte": "6611", "libelle": "Salaires",
         "debit": "3000000", "credit": "0"},
    ]
    vue = rapprocher_salaires(_decls_coherentes(), soldes)
    ecart = vue["ecarts"][0]
    assert ecart["ecart"] == "1200000"
    assert ecart["significatif"] is True
    assert ecart["commentaire"] == ""


def test_rapprocher_salaires_seuil_strict():
    # Écart exactement AU seuil : non significatif (strictement >).
    seuil = SEUIL_SIGNIFICATION_FCFA
    decls = [
        {"periode": "2025-01",
         "masse_salariale_brute": str(Decimal("4200000") - seuil),
         "its_retenu": "0", "contribution_employeur": "0"},
    ]
    vue = rapprocher_salaires(decls, _soldes_coherents())
    assert vue["ecarts"][0]["significatif"] is False
    assert vue["synthese"]["statut"] == STATUT_COHERENT
    assert vue["seuil_signification"] == str(seuil)


def test_rapprocher_salaires_indisponible_cles_stables():
    cles = {
        "disponible", "seuil_signification", "declarations",
        "totaux_declares", "comptabilise", "ecarts", "synthese", "note",
    }
    # Sans déclaration.
    vue1 = rapprocher_salaires([], _soldes_coherents())
    assert cles <= set(vue1)
    assert vue1["disponible"] is False
    assert vue1["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert vue1["ecarts"][0]["significatif"] is False
    # Sans compte 66x en balance (les 447x seuls ne suffisent pas).
    vue2 = rapprocher_salaires(
        [{"periode": "2025-01", "masse_salariale_brute": "1",
          "its_retenu": "0", "contribution_employeur": "0"}],
        [{"compte": "4471", "libelle": "État, ITS", "debit": "0",
          "credit": "10"}],
    )
    assert cles <= set(vue2)
    assert vue2["disponible"] is False
    assert vue2["synthese"]["statut"] == STATUT_INDISPONIBLE
    assert vue2["note"] == NOTE_RAPPROCHEMENT_SALAIRES


def test_rapprocher_salaires_declarations_triees_par_periode():
    decls = [
        {"periode": "2025-03", "masse_salariale_brute": "3",
         "its_retenu": "0", "contribution_employeur": "0"},
        {"periode": "2025-01", "masse_salariale_brute": "1",
         "its_retenu": "0", "contribution_employeur": "0"},
        {"periode": "2025-02", "masse_salariale_brute": "2",
         "its_retenu": "1", "contribution_employeur": "0"},
    ]
    vue = rapprocher_salaires(decls, _soldes_coherents())
    assert [d["periode"] for d in vue["declarations"]] == [
        "2025-01", "2025-02", "2025-03"
    ]
    assert vue["declarations"][1]["its_retenu"] == "1"


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_RAPPROCHEMENT_SALAIRES
    assert "décide" in NOTE_RAPPROCHEMENT_SALAIRES


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

    lib = f"v-rsal-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="rapprochement-salaires")
    publier_version(session, lib, "rsal@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"rsal.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab RSal {email}",
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
    return f"/api/v1/missions/{mid}/rapprochement-salaires"


def _url_saisie(mid: int) -> str:
    return f"/api/v1/missions/{mid}/declarations-salaires"


def test_api_saisie_puis_rapprochement_ecart(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RSal FICTIF")
    mid = _mission(session, tid, cid)
    _solde(session, tid, mid, "6611", "Salaires", "5000000", "0")
    _solde(session, tid, mid, "4471", "État, ITS retenus", "0", "300000")
    _solde(session, tid, mid, "4221", "Personnel, rémun. dues",
           "0", "800000")
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-01", "masse_salariale_brute": "2000000",
              "its_retenu": "150000", "contribution_employeur": "50000"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["declaration"]["periode"] == "2025-01"
    assert (
        r1.json()["declaration"]["masse_salariale_brute"] == "2000000.00"
    )
    r2 = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-02", "masse_salariale_brute": "2200000",
              "its_retenu": "160000", "contribution_employeur": "55000"},
    )
    assert r2.status_code == 200, r2.text

    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    # Déclaré 4 200 000 vs comptabilisé 5 000 000 : écart -800 000 —
    # significatif, avec commentaire « salaires non déclarés » possibles.
    ecart = corps["ecarts"][0]
    assert ecart["nature"] == "masse_salariale"
    assert ecart["declare"] == "4200000.00"
    assert ecart["comptabilise"] == "5000000.00"
    assert ecart["ecart"] == "-800000.00"
    assert ecart["significatif"] is True
    assert "non déclarés" in ecart["commentaire"]
    assert corps["synthese"]["statut"] == "ecarts_a_expliquer"
    assert corps["synthese"]["nb_periodes_declarees"] == 2
    assert corps["totaux_declares"]["its_retenu"] == "310000.00"
    assert corps["comptabilise"]["solde_etat_retenues"] == "300000.00"
    assert corps["comptabilise"]["solde_personnel"] == "800000.00"
    assert "consultatif" in corps["note"]


def test_api_upsert_remplace_la_periode(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RSal Upsert FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-03", "masse_salariale_brute": "100",
              "its_retenu": "10", "contribution_employeur": "5"},
    )
    r = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-03", "masse_salariale_brute": "999",
              "its_retenu": "0", "contribution_employeur": "0"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["declaration"]["masse_salariale_brute"] == "999.00"

    corps = client.get(_url(mid), headers=h).json()
    assert corps["synthese"]["nb_periodes_declarees"] == 1
    assert corps["totaux_declares"]["masse_salariale_brute"] == "999.00"
    assert Decimal(corps["totaux_declares"]["its_retenu"]) == 0


def test_api_journalisation_saisie(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RSal Journal FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-04", "masse_salariale_brute": "500000",
              "its_retenu": "40000", "contribution_employeur": "12000"},
    )
    assert r.status_code == 200, r.text

    with contexte_tenant(session, tid):
        rows = session.execute(
            text(
                "SELECT action, charge_utile FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'saisie_declaration_salaires'"
            ),
            {"m": mid},
        ).mappings().all()
    assert len(rows) == 1
    charge = rows[0]["charge_utile"]
    assert charge["periode"] == "2025-04"
    assert charge["masse_salariale_brute"] == "500000.00"


def test_api_sans_donnees_indisponible_mais_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RSal Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["synthese"]["statut"] == "indisponible"
    assert corps["declarations"] == []
    assert corps["ecarts"] != []  # la nature masse_salariale reste présente
    assert corps["note"]


def test_api_saisie_422_periode_ou_montant_invalides(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM RSal 422 FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-13", "masse_salariale_brute": "1"},
    ).status_code == 422
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-01", "its_retenu": "-5"},
    ).status_code == 422
    assert client.post(
        _url_saisie(mid), headers=h,
        json={"periode": "2025-01", "contribution_employeur": "abc"},
    ).status_code == 422


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM RSal Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url_saisie(mid_a), headers=h_b,
        json={"periode": "2025-01", "masse_salariale_brute": "1"},
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(
        _url_saisie(1), json={"periode": "2025-01"}
    ).status_code == 401
