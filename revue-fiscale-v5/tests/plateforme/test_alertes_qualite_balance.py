"""Centre d'alertes — source qualité de balance (vigilance / info)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.centre_alertes import (
    PLAFOND_ALERTES,
    PLAFOND_MISSIONS_QUALITE_BALANCE,
    TYPES_ALERTE,
    alertes_depuis_qualite_balance,
    assembler_centre,
    normaliser_alerte,
    synthese_alertes,
)
from backend.plateforme.qualite_balance import evaluer_qualite_balance

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _vue(client: str, mission_id: int, qualite: dict) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "qualite": qualite,
    }


def _qualite(soldes: list[dict], exercice: int = 2025) -> dict:
    vue = evaluer_qualite_balance(soldes)
    vue["exercice"] = exercice
    return vue


def _ligne(compte: str, libelle: str, debit: str, credit: str) -> dict:
    return {
        "compte": compte,
        "libelle": libelle,
        "debit": debit,
        "credit": credit,
    }


def test_type_qualite_balance_dans_le_referentiel():
    assert "qualite_balance" in TYPES_ALERTE
    a = normaliser_alerte({"type": "qualite_balance", "gravite": "info"})
    assert a["type"] == "qualite_balance"
    s = synthese_alertes([a])
    assert s["par_type"]["qualite_balance"] == 1


def test_balance_desequilibree_emet_vigilance_jamais_critique():
    # Débits ≠ crédits : la matière première de la revue est douteuse.
    vue = _qualite([_ligne("601", "Achats", "5000000", "0")])
    assert vue["statut"] == "observations_a_examiner"
    assert vue["equilibre"]["equilibree"] is False
    alertes = alertes_depuis_qualite_balance([_vue("SA FICTIVE", 7, vue)])
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "qualite_balance"
    # Vigilance, JAMAIS critique — observation consultative, l'humain
    # examine et conclut.
    assert a["gravite"] == "vigilance"
    assert a["client"] == "SA FICTIVE"
    assert a["mission_id"] == 7
    assert a["echeance"] is None
    assert a["lien"] == "qualite_balance"
    assert "balance déséquilibrée" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "écart 5000000 FCFA" in a["libelle"]
    assert "à examiner avant toute revue" in a["libelle"]


def test_observations_seules_emettent_info_libelle_compte():
    # Balance équilibrée mais client 411 créditeur : sens inhabituel
    # seulement → info, jamais vigilance.
    vue = _qualite(
        [
            _ligne("411000", "Client FICTIF", "0", "1000000"),
            _ligne("601", "Achats", "1000000", "0"),
        ]
    )
    assert vue["statut"] == "observations_a_examiner"
    assert vue["equilibre"]["equilibree"] is True
    assert vue["synthese"]["nb_observations"] == 1
    alertes = alertes_depuis_qualite_balance(
        [_vue("SARL FICTIVE", 9, vue)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "qualite_balance"
    assert a["gravite"] == "info"
    assert (
        "1 observation de qualité de balance à examiner" in a["libelle"]
    )
    assert "exercice 2025" in a["libelle"]
    assert "sens inhabituels, comptes hors plan" in a["libelle"]


def test_pluriel_observations_info():
    # Deux observations (sens inhabituel + compte hors plan), balance
    # équilibrée → info avec pluriel.
    vue = _qualite(
        [
            _ligne("411000", "Client FICTIF", "0", "1000000"),
            _ligne("XXX", "Compte hors plan", "1000000", "0"),
        ]
    )
    assert vue["equilibre"]["equilibree"] is True
    assert vue["synthese"]["nb_observations"] == 2
    alertes = alertes_depuis_qualite_balance([_vue("A", 1, vue)])
    assert len(alertes) == 1
    assert alertes[0]["gravite"] == "info"
    assert (
        "2 observations de qualité de balance à examiner"
        in alertes[0]["libelle"]
    )


def test_rien_si_sans_observation_ou_indisponible():
    saine = _qualite(
        [
            _ligne("601", "Achats", "1000000", "0"),
            _ligne("701", "Ventes", "0", "1000000"),
        ]
    )
    assert saine["statut"] == "equilibree_sans_observation"
    indisponible = _qualite([])
    assert indisponible["disponible"] is False
    assert indisponible["statut"] == "indisponible"
    alertes = alertes_depuis_qualite_balance(
        [
            _vue("A", 1, saine),
            _vue("B", 2, indisponible),
            _vue("C", 3, {}),
        ]
    )
    assert alertes == []


def test_cles_stables_apres_normalisation():
    vue = _qualite([_ligne("601", "Achats", "5000000", "0")])
    alertes = alertes_depuis_qualite_balance([_vue("SA FICTIVE", 5, vue)])
    a = normaliser_alerte(alertes[0])
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["type"] == "qualite_balance"
    assert a["gravite"] == "vigilance"


def test_plafonds_source_et_centre():
    # Plafond de missions examinées par la source — coût borné.
    assert PLAFOND_MISSIONS_QUALITE_BALANCE == 200
    # Plafond global du centre : même une avalanche d'observations
    # reste tronquée à PLAFOND_ALERTES.
    vue = _qualite([_ligne("601", "Achats", "1000", "0")])
    vues = [_vue(f"Client {i:03d}", i, vue) for i in range(1, 151)]
    alertes = alertes_depuis_qualite_balance(vues)
    assert len(alertes) == 150
    from datetime import date

    centre = assembler_centre(alertes, [], date(2026, 7, 28))
    assert len(centre["alertes"]) == PLAFOND_ALERTES
    assert centre["synthese"]["par_type"]["qualite_balance"] == (
        PLAFOND_ALERTES
    )


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL = "/api/v1/cabinet/alertes"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-alqb-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="alertes qualite balance")
    publier_version(session, lib, "alqb@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"alqb.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Alqb {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission_en_cours(session, tenant_id: int, nom: str) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination, forme) "
                "VALUES (:t, :d, 'pm') RETURNING id"
            ),
            {"t": tenant_id, "d": nom},
        ).scalar_one()
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=int(cid),
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": int(mid)},
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


def test_api_desequilibre_vigilance_et_observations_info(session):
    tid, email = _cabinet(session)
    # Mission déséquilibrée : débits sans crédits → vigilance.
    mid_deseq = _mission_en_cours(session, tid, "PM Alqb Deseq FICTIVE")
    _solde(session, tid, mid_deseq, "601", "Achats", "5000000", "0")
    # Mission équilibrée avec un client 411 créditeur → info.
    mid_obs = _mission_en_cours(session, tid, "PM Alqb Obs FICTIVE")
    _solde(session, tid, mid_obs, "411000", "Client FICTIF",
           "0", "1000000")
    _solde(session, tid, mid_obs, "601", "Achats", "1000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    alertes = {
        a["mission_id"]: a
        for a in corps["alertes"]
        if a["type"] == "qualite_balance"
    }
    assert set(alertes) == {mid_deseq, mid_obs}
    a = alertes[mid_deseq]
    # Vigilance, JAMAIS critique — la matière première est douteuse
    # mais l'observation reste consultative.
    assert a["gravite"] == "vigilance"
    assert a["client"] == "PM Alqb Deseq FICTIVE"
    assert "balance déséquilibrée" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "écart" in a["libelle"]
    assert "à examiner avant toute revue" in a["libelle"]
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["lien"] == "qualite_balance"
    b = alertes[mid_obs]
    assert b["gravite"] == "info"
    assert (
        "observation de qualité de balance à examiner" in b["libelle"]
    )
    assert "sens inhabituels, comptes hors plan" in b["libelle"]
    assert corps["synthese"]["par_type"]["qualite_balance"] == 2


def test_api_indisponible_aucune_alerte_source_tolerante(
    session, monkeypatch
):
    tid, email = _cabinet(session)
    # Mission sans balance : qualité indisponible → rien.
    _mission_en_cours(session, tid, "PM Alqb Vide FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    assert not [
        a for a in corps["alertes"] if a["type"] == "qualite_balance"
    ]
    assert corps["synthese"]["par_type"]["qualite_balance"] == 0

    # Source en échec : jamais bloquante, simplement signalée.
    import backend.plateforme.qualite_balance as qb

    def _boom(*args, **kwargs):
        raise RuntimeError("qualité balance indisponible")

    monkeypatch.setattr(qb, "vue_qualite_balance_mission", _boom)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert "qualite_balance" in corps["sources_en_echec"]
    assert corps["note"]
