"""Suivi des contrôles fiscaux et contentieux — délais de riposte LPF."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.controles_fiscaux import (
    NOTE_CONTROLES_FISCAUX,
    SEUIL_PROCHE_JOURS,
    STATUT_A_VENIR,
    STATUT_DEPASSEE,
    STATUT_PROCHE,
    STATUT_SANS_DELAI,
    SYNTHESE_A_JOUR,
    SYNTHESE_AUCUN,
    SYNTHESE_DEPASSEES,
    SYNTHESE_PROCHES,
    TYPES_EVENEMENT,
    ErreurControleFiscalInvalide,
    ajouter_mois,
    calculer_delai_riposte,
    construire_chronologie,
    referentiel_types,
    statut_echeance,
    synthese_controles,
    valider_date_evenement,
    valider_montant_en_jeu,
    valider_type_evenement,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_valider_type_evenement():
    assert valider_type_evenement("avis_verification") == "avis_verification"
    assert valider_type_evenement(" mise_en_demeure ") == "mise_en_demeure"
    for mauvais in ("", None, "controle", "AVIS_VERIFICATION"):
        with pytest.raises(ErreurControleFiscalInvalide):
            valider_type_evenement(mauvais)


def test_valider_date_evenement():
    assert valider_date_evenement("2026-03-15") == date(2026, 3, 15)
    assert valider_date_evenement(" 2026-01-02 ") == date(2026, 1, 2)
    for mauvaise in ("", None, "15/03/2026", "2026-13-01", "1985-01-01"):
        with pytest.raises(ErreurControleFiscalInvalide):
            valider_date_evenement(mauvaise)


def test_valider_montant_en_jeu():
    from decimal import Decimal

    assert valider_montant_en_jeu(None) is None
    assert valider_montant_en_jeu("") is None
    assert valider_montant_en_jeu("2500000") == Decimal("2500000.00")
    assert valider_montant_en_jeu("1 000 000") == Decimal("1000000.00")
    with pytest.raises(ErreurControleFiscalInvalide):
        valider_montant_en_jeu("abc")
    with pytest.raises(ErreurControleFiscalInvalide):
        valider_montant_en_jeu("-1")


def test_ajouter_mois_borne_fin_de_mois():
    assert ajouter_mois(date(2025, 8, 31), 6) == date(2026, 2, 28)
    assert ajouter_mois(date(2023, 8, 31), 6) == date(2024, 2, 29)
    assert ajouter_mois(date(2025, 1, 15), 6) == date(2025, 7, 15)
    assert ajouter_mois(date(2025, 12, 31), 6) == date(2026, 6, 30)


def test_delais_lpf_notification_30_jours():
    d = calculer_delai_riposte("notification_redressement", date(2026, 1, 10))
    assert d["duree"] == "30 jours"
    assert d["echeance"] == "2026-02-09"
    assert "30 jours" in d["objet"]
    assert "art. 22" in d["reference"]


def test_delais_lpf_mise_en_demeure_10_jours():
    d = calculer_delai_riposte("mise_en_demeure", date(2026, 1, 10))
    assert d["duree"] == "10 jours"
    assert d["echeance"] == "2026-01-20"


def test_delais_lpf_reclamation_6_mois_depuis_amr():
    d = calculer_delai_riposte(
        "avis_mise_en_recouvrement", date(2025, 8, 31)
    )
    assert d["duree"] == "6 mois"
    assert d["echeance"] == "2026-02-28"
    assert "art. 183" in d["reference"]


def test_delais_lpf_sans_delai():
    for t in ("avis_verification", "degrevement", "recours_juridictionnel"):
        d = calculer_delai_riposte(t, date(2026, 1, 10))
        assert d["duree"] is None
        assert d["echeance"] is None
        assert d["objet"]  # jamais vide : l'humain sait quoi surveiller


def test_statut_echeance():
    jour = date(2026, 2, 1)
    assert statut_echeance(None, jour) == {
        "statut": STATUT_SANS_DELAI,
        "jours_restants": None,
    }
    s = statut_echeance("2026-03-01", jour)
    assert s["statut"] == STATUT_A_VENIR
    assert s["jours_restants"] == 28
    # Bord : exactement au seuil « proche » (J+7) et au jour J.
    assert statut_echeance("2026-02-08", jour)["statut"] == STATUT_PROCHE
    assert statut_echeance("2026-02-01", jour)["statut"] == STATUT_PROCHE
    d = statut_echeance("2026-01-31", jour)
    assert d["statut"] == STATUT_DEPASSEE
    assert d["jours_restants"] == -1
    assert SEUIL_PROCHE_JOURS == 7


def test_construire_chronologie_tri_et_delais():
    jour = date(2026, 2, 5)
    evenements = [
        {"id": 2, "type_evenement": "notification_redressement",
         "date_evenement": "2026-01-10", "montant_en_jeu": "12500000",
         "commentaire": "TVA et BIC 2024"},
        {"id": 1, "type_evenement": "avis_verification",
         "date_evenement": "2025-12-15", "montant_en_jeu": None,
         "commentaire": ""},
    ]
    chrono = construire_chronologie(evenements, jour)
    assert [e["type_evenement"] for e in chrono] == [
        "avis_verification", "notification_redressement"
    ]
    avis, notif = chrono
    assert avis["echeance"]["statut"] == STATUT_SANS_DELAI
    assert avis["montant_en_jeu"] is None
    assert notif["delai_riposte"]["echeance"] == "2026-02-09"
    assert notif["echeance"]["statut"] == STATUT_PROCHE
    assert notif["echeance"]["jours_restants"] == 4
    assert notif["montant_en_jeu"] == "12500000"
    assert notif["libelle"] == "Notification (provisoire) de redressement"


def test_construire_chronologie_type_inconnu():
    with pytest.raises(ErreurControleFiscalInvalide):
        construire_chronologie(
            [{"type_evenement": "x", "date_evenement": "2026-01-01"}],
            date(2026, 1, 1),
        )


def test_synthese_statuts_et_montant_total():
    jour = date(2026, 3, 1)
    # Vide.
    vide = synthese_controles([])
    assert vide["statut"] == SYNTHESE_AUCUN
    assert vide["nb_evenements"] == 0
    assert vide["montant_total_en_jeu"] == "0"
    assert vide["dernier_evenement"] is None
    # Dépassée prioritaire sur proche.
    chrono = construire_chronologie(
        [
            {"id": 1, "type_evenement": "notification_redressement",
             "date_evenement": "2026-01-10", "montant_en_jeu": "1000000"},
            {"id": 2, "type_evenement": "reclamation_contentieuse",
             "date_evenement": "2026-02-05", "montant_en_jeu": "500000"},
        ],
        jour,
    )
    s = synthese_controles(chrono)
    assert s["statut"] == SYNTHESE_DEPASSEES
    assert s["nb_echeances_depassees"] == 1
    assert s["nb_echeances_proches"] == 1
    assert s["montant_total_en_jeu"] == "1500000"
    assert s["dernier_evenement"]["type_evenement"] == (
        "reclamation_contentieuse"
    )
    # Proche sans dépassée.
    chrono2 = construire_chronologie(
        [{"id": 1, "type_evenement": "mise_en_demeure",
          "date_evenement": "2026-02-25"}],
        jour,
    )
    assert synthese_controles(chrono2)["statut"] == SYNTHESE_PROCHES
    # À jour (échéance lointaine ou sans délai).
    chrono3 = construire_chronologie(
        [{"id": 1, "type_evenement": "avis_mise_en_recouvrement",
          "date_evenement": "2026-02-25"}],
        jour,
    )
    assert synthese_controles(chrono3)["statut"] == SYNTHESE_A_JOUR


def test_referentiel_types_complet():
    ref = referentiel_types()
    assert {r["type_evenement"] for r in ref} == set(TYPES_EVENEMENT)
    par_type = {r["type_evenement"]: r for r in ref}
    assert par_type["notification_redressement"]["delai"] == "30 jours"
    assert par_type["avis_mise_en_recouvrement"]["delai"] == "6 mois"
    assert par_type["avis_verification"]["delai"] is None
    assert all(r["objet_delai"] and r["reference"] for r in ref)


def test_note_consultative_humain_decide():
    assert "consultatif" in NOTE_CONTROLES_FISCAUX
    assert "décide" in NOTE_CONTROLES_FISCAUX


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

    lib = f"v-cfx-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="controles-fiscaux")
    publier_version(session, lib, "cfx@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"cfx.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Cfx {email}",
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
    return f"/api/v1/missions/{mid}/controles"


def test_api_consigner_puis_chronologie(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Cfx FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r1 = client.post(
        _url(mid), headers=h,
        json={"type_evenement": "avis_verification",
              "date_evenement": "2025-11-03",
              "commentaire": "Vérification générale 2023-2024"},
    )
    assert r1.status_code == 200, r1.text
    ev1 = r1.json()["evenement"]
    assert ev1["type_evenement"] == "avis_verification"
    assert ev1["delai_riposte"]["echeance"] is None
    assert ev1["montant_en_jeu"] is None
    assert "consultatif" in r1.json()["note"]

    r2 = client.post(
        _url(mid), headers=h,
        json={"type_evenement": "notification_redressement",
              "date_evenement": "2026-01-12",
              "montant_en_jeu": "45000000",
              "commentaire": "Rappels TVA + IS"},
    )
    assert r2.status_code == 200, r2.text
    ev2 = r2.json()["evenement"]
    assert ev2["delai_riposte"]["duree"] == "30 jours"
    assert ev2["delai_riposte"]["echeance"] == "2026-02-11"
    assert ev2["montant_en_jeu"] == "45000000.00"

    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert [e["type_evenement"] for e in corps["evenements"]] == [
        "avis_verification", "notification_redressement"
    ]
    # Notification du 12/01/2026 : échéance 11/02/2026, dépassée au
    # jour du test (2026) ou à venir — le statut reste cohérent avec
    # aujourd_hui retourné par l'API.
    assert corps["synthese"]["nb_evenements"] == 2
    assert corps["synthese"]["montant_total_en_jeu"] == "45000000.00"
    assert corps["synthese"]["dernier_evenement"]["type_evenement"] == (
        "notification_redressement"
    )
    assert corps["types_evenement"]
    assert corps["aujourd_hui"]
    assert "consultatif" in corps["note"]


def test_api_vide_mais_contrat_stable(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Cfx Vide FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    cles = {"mission_id", "exercice", "aujourd_hui", "evenements",
            "synthese", "types_evenement", "note"}
    assert cles <= set(corps)
    assert corps["evenements"] == []
    assert corps["synthese"]["statut"] == "aucun_evenement"
    assert corps["synthese"]["dernier_evenement"] is None
    assert corps["note"]


def test_api_journalisation_consignation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Cfx Journal FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    r = client.post(
        _url(mid), headers=h,
        json={"type_evenement": "mise_en_demeure",
              "date_evenement": "2026-02-02"},
    )
    assert r.status_code == 200, r.text
    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit WHERE mission_id = :m "
                "AND action = 'consignation_evenement_controle_fiscal'"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(n) == 1


def test_api_422_saisies_invalides(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Cfx 422 FICTIF")
    mid = _mission(session, tid, cid)
    session.commit()

    client, h = _client_connecte(email)
    assert client.post(
        _url(mid), headers=h,
        json={"type_evenement": "inconnu", "date_evenement": "2026-01-01"},
    ).status_code == 422
    assert client.post(
        _url(mid), headers=h,
        json={"type_evenement": "mise_en_demeure",
              "date_evenement": "01/02/2026"},
    ).status_code == 422
    assert client.post(
        _url(mid), headers=h,
        json={"type_evenement": "mise_en_demeure",
              "date_evenement": "2026-01-01", "montant_en_jeu": "-5"},
    ).status_code == 422


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM Cfx Cross FICTIF")
    mid_a = _mission(session, tid_a, cid_a)
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404
    assert client_b.post(
        _url(mid_a), headers=h_b,
        json={"type_evenement": "avis_verification",
              "date_evenement": "2026-01-01"},
    ).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
    assert client.post(
        _url(1),
        json={"type_evenement": "avis_verification",
              "date_evenement": "2026-01-01"},
    ).status_code == 401
