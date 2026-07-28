"""Fil conducteur de la mission — guide pas-à-pas en lecture seule."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.fil_conducteur import (
    ETAPES_FIL,
    MENTION_NOTE,
    STATUTS_ETAPE,
    assembler_fil,
    statut_cadrage,
    statut_ciblage,
    statut_collecte,
    statut_liquidation,
    statut_restitution,
    statut_revues,
    statut_suivi,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_statut_cadrage_regles():
    # Faite : responsable affecté ET honoraires convenus.
    e = statut_cadrage(
        {"honoraires": "500000"}, {"responsable_email": "chef@cab.ci"}
    )
    assert e["code"] == "cadrage"
    assert e["statut"] == "faite"
    assert "chef@cab.ci" in e["detail"]
    # En cours : un seul des deux.
    assert (
        statut_cadrage({"honoraires": None}, {"responsable_email": "a@b.ci"})[
            "statut"
        ]
        == "en_cours"
    )
    assert (
        statut_cadrage({"honoraires": "1"}, {"responsable_email": None})[
            "statut"
        ]
        == "en_cours"
    )
    # À faire : aucun des deux (sources répondues).
    assert (
        statut_cadrage({"honoraires": None}, {"responsable_email": ""})[
            "statut"
        ]
        == "a_faire"
    )
    # Indisponible : les deux sources en échec.
    assert statut_cadrage(None, None)["statut"] == "indisponible"


def test_statut_collecte_regles():
    assert (
        statut_collecte(
            {
                "taux_completude": "100.00",
                "presentes": 5,
                "essentielles_manquantes": 0,
            }
        )["statut"]
        == "faite"
    )
    e = statut_collecte(
        {
            "taux_completude": "50.00",
            "presentes": 2,
            "essentielles_manquantes": 2,
        }
    )
    assert e["statut"] == "en_cours"
    assert "50,00" in e["detail"]
    assert (
        statut_collecte(
            {
                "taux_completude": "0.00",
                "presentes": 0,
                "essentielles_manquantes": 4,
            }
        )["statut"]
        == "a_faire"
    )
    assert statut_collecte(None)["statut"] == "indisponible"


def test_statut_ciblage_regles():
    seuil = {"seuil_retenu": {"seuil_retenu": "1000000"}}
    assert (
        statut_ciblage(seuil, {"faites": 3, "total": 12})["statut"] == "faite"
    )
    # Le programme initialisé (total > 0) sans diligence cochée ni
    # seuil ne suffit pas : à faire.
    assert (
        statut_ciblage({"seuil_retenu": None}, {"faites": 0, "total": 12})[
            "statut"
        ]
        == "a_faire"
    )
    assert (
        statut_ciblage(seuil, {"faites": 0, "total": 12})["statut"]
        == "en_cours"
    )
    assert (
        statut_ciblage({"seuil_retenu": None}, {"faites": 1, "total": 12})[
            "statut"
        ]
        == "en_cours"
    )
    assert statut_ciblage(None, None)["statut"] == "indisponible"


def test_statut_revues_regles():
    toutes = {
        "rapprochement_tva": {"disponible": True},
        "rapprochement_salaires": {"disponible": True},
        "deductibilite": {"disponible": True},
        "revue_analytique": {"disponible": True},
    }
    assert statut_revues(toutes)["statut"] == "faite"
    partielles = dict(toutes)
    partielles["revue_analytique"] = {"disponible": False}
    e = statut_revues(partielles)
    assert e["statut"] == "en_cours"
    assert "3/4" in e["detail"]
    aucune = {cle: {"disponible": False} for cle in toutes}
    assert statut_revues(aucune)["statut"] == "a_faire"
    # Une source en échec parmi d'autres est ignorée (pas bloquante).
    melange = dict(toutes)
    melange["deductibilite"] = None
    assert statut_revues(melange)["statut"] == "en_cours"
    assert (
        statut_revues(dict.fromkeys(toutes))["statut"]
        == "indisponible"
    )


def test_statut_liquidation_regles():
    assert (
        statut_liquidation(
            {"disponible": True, "nb_retraitements": 2},
            {"disponible": True},
        )["statut"]
        == "faite"
    )
    # Un retraitement saisi suffit à considérer le résultat « établi »
    # même sans balance (disponible=False).
    assert (
        statut_liquidation(
            {"disponible": False, "nb_retraitements": 1},
            {"disponible": False},
        )["statut"]
        == "en_cours"
    )
    assert (
        statut_liquidation(
            {"disponible": False, "nb_retraitements": 0},
            {"disponible": False},
        )["statut"]
        == "a_faire"
    )
    assert statut_liquidation(None, None)["statut"] == "indisponible"


def test_statut_restitution_regles():
    assert (
        statut_restitution({"consigne": True}, {"nb_points": 2})["statut"]
        == "faite"
    )
    assert (
        statut_restitution({"consigne": False}, {"nb_points": 2})["statut"]
        == "en_cours"
    )
    assert (
        statut_restitution({"consigne": True}, {"nb_points": 0})["statut"]
        == "en_cours"
    )
    assert (
        statut_restitution({"consigne": False}, {"nb_points": 0})["statut"]
        == "a_faire"
    )
    assert statut_restitution(None, None)["statut"] == "indisponible"


def test_statut_suivi_regles():
    assert (
        statut_suivi({"total": 0}, {"statut": "a_jour"})["statut"] == "faite"
    )
    assert (
        statut_suivi({"total": 0}, {"statut": "aucun_evenement"})["statut"]
        == "faite"
    )
    assert (
        statut_suivi({"total": 3}, {"statut": "a_jour"})["statut"]
        == "en_cours"
    )
    assert (
        statut_suivi({"total": 0}, {"statut": "echeances_depassees"})[
            "statut"
        ]
        == "en_cours"
    )
    assert statut_suivi(None, None)["statut"] == "indisponible"


def test_assembler_fil_synthese_et_prochaine_etape():
    etapes = [
        {"code": "cadrage", "libelle": "Cadrage", "statut": "faite",
         "detail": "x"},
        {"code": "collecte", "libelle": "Collecte", "statut": "en_cours",
         "detail": "x"},
        {"code": "ciblage", "libelle": "Ciblage", "statut": "a_faire",
         "detail": "x"},
    ]
    fil = assembler_fil(etapes)
    assert fil["synthese"] == {
        "faites": 1,
        "total": 3,
        "prochaine_etape": {"code": "collecte", "libelle": "Collecte"},
    }
    assert fil["note"] == MENTION_NOTE
    assert "consultatif" in fil["note"]
    # Tout fait → aucune prochaine étape suggérée.
    toutes = [dict(e, statut="faite") for e in etapes]
    assert assembler_fil(toutes)["synthese"]["prochaine_etape"] is None


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

    lib = f"v-fil-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="fil-conducteur")
    publier_version(session, lib, "fil@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"fil.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Fil {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    with contexte_tenant(session, r.tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, 'PM Fil FICTIF', 'pm') RETURNING id"
            ),
            {"t": r.tenant_id},
        ).scalar_one()
        mid = creer_mission(
            session,
            r.tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": mid},
        )
    return r.tenant_id, int(mid), email


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


def test_api_fil_conducteur_structure_stable(session):
    tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/fil-conducteur", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()

    # Clés toujours présentes.
    assert corps["mission_id"] == mid
    assert corps["note"]
    assert "consultatif" in corps["note"]
    synthese = corps["synthese"]
    assert set(synthese) == {"faites", "total", "prochaine_etape"}
    assert synthese["total"] == len(ETAPES_FIL)

    # Les 7 étapes, dans l'ordre du process, structure stable.
    etapes = corps["etapes"]
    assert [e["code"] for e in etapes] == [c for c, _ in ETAPES_FIL]
    for e in etapes:
        assert set(e) == {"code", "libelle", "statut", "detail"}
        assert e["statut"] in STATUTS_ETAPE
        assert e["libelle"]
        assert e["detail"]

    # Mission neuve : rien n'est fait — la prochaine étape suggérée est
    # la première non faite (le cadrage, sans responsable ni honoraires).
    assert synthese["faites"] < synthese["total"]
    assert synthese["prochaine_etape"] is not None
    assert synthese["prochaine_etape"]["code"] == "cadrage"


def test_api_fil_conducteur_progression_cadrage_et_restitution(session):
    from backend.plateforme.compte_rendu import enregistrer_compte_rendu
    from backend.plateforme.points_convenus import creer_point_convenu
    from backend.plateforme.responsable_mission import affecter_responsable

    tid, mid, email = _mission_en_cours(session)
    affecter_responsable(session, tid, mid, email, acteur=email)
    creer_point_convenu(
        session, tid, mid, "Régulariser la TVA", "fil@test.ci",
        date_cible="2025-06-30",
    )
    enregistrer_compte_rendu(
        session, tid, mid,
        date_reunion="2026-01-15",
        participants="DG / cabinet",
        points_convenus="Dépôt d'une rectificative.",
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/fil-conducteur", headers=h)
    assert r.status_code == 200, r.text
    par_code = {e["code"]: e for e in r.json()["etapes"]}

    # Cadrage : responsable affecté, honoraires non convenus → en cours.
    assert par_code["cadrage"]["statut"] == "en_cours"
    assert email in par_code["cadrage"]["detail"]
    # Restitution : compte-rendu consigné ET point convenu → faite.
    assert par_code["restitution"]["statut"] == "faite"
    # Suivi : aucun point antérieur ni contrôle → faite.
    assert par_code["suivi"]["statut"] == "faite"
    # Revues : aucune balance ni déclaration → aucune revue disponible.
    assert par_code["revues"]["statut"] == "a_faire"


def test_api_fil_conducteur_404_hors_tenant(session):
    tid1, mid1, _ = _mission_en_cours(session)
    tid2, mid2, email2 = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email2)
    # Mission d'un AUTRE tenant → 404 (RLS), jamais de fuite.
    r = client.get(f"/api/v1/missions/{mid1}/fil-conducteur", headers=h)
    assert r.status_code == 404, r.text
    # Mission inexistante → 404 aussi.
    r = client.get("/api/v1/missions/999999999/fil-conducteur", headers=h)
    assert r.status_code == 404, r.text


def test_api_fil_conducteur_exige_authentification(session):
    tid, mid, _ = _mission_en_cours(session)
    session.commit()

    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get(f"/api/v1/missions/{mid}/fil-conducteur")
    assert r.status_code == 401


def test_api_fil_conducteur_tolerance_source_en_echec(
    session, monkeypatch
):
    # Une source annexe qui explose rend son étape « indisponible »
    # sans jamais bloquer la restitution du fil.
    import backend.plateforme.completude_data_room as cdr

    def _boom(*args, **kwargs):
        raise RuntimeError("source en échec simulée")

    monkeypatch.setattr(cdr, "completude_data_room", _boom)

    tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/fil-conducteur", headers=h)
    assert r.status_code == 200, r.text
    par_code = {e["code"]: e for e in r.json()["etapes"]}
    assert par_code["collecte"]["statut"] == "indisponible"
    # Les autres étapes restent restituées normalement.
    assert par_code["cadrage"]["statut"] in STATUTS_ETAPE
    assert par_code["suivi"]["statut"] in STATUTS_ETAPE
