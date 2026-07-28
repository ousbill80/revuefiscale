"""Centre d'alertes — source rapprochement des acomptes IS (info)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.centre_alertes import (
    PLAFOND_ALERTES,
    PLAFOND_MISSIONS_RAPPROCHEMENT_ACOMPTES,
    TYPES_ALERTE,
    alertes_depuis_rapprochement_acomptes,
    assembler_centre,
    normaliser_alerte,
    synthese_alertes,
)
from backend.plateforme.rapprochement_acomptes import (
    construire_rapprochement,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _vue(client: str, mission_id: int, rapprochement: dict) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "rapprochement": rapprochement,
    }


def _rapprochement(
    is_theorique: str | None,
    acomptes: list[dict] | None = None,
    exercice: int = 2025,
) -> dict:
    passage = (
        {"disponible": True, "is_theorique": is_theorique, "imf": {}}
        if is_theorique is not None
        else None
    )
    vue = construire_rapprochement(passage, acomptes or [])
    vue["exercice"] = exercice
    return vue


def _acompte(montant: str, jour: str = "2025-03-15") -> dict:
    return {
        "id": 1,
        "nature": "acompte_is",
        "libelle_nature": "Acomptes IS versés",
        "date_versement": jour,
        "montant": montant,
        "reference_quittance": None,
    }


def test_type_rapprochement_acomptes_dans_le_referentiel():
    assert "rapprochement_acomptes" in TYPES_ALERTE
    a = normaliser_alerte(
        {"type": "rapprochement_acomptes", "gravite": "info"}
    )
    assert a["type"] == "rapprochement_acomptes"
    s = synthese_alertes([a])
    assert s["par_type"]["rapprochement_acomptes"] == 1


def test_solde_a_payer_emet_info_jamais_critique_ni_vigilance():
    vue = _rapprochement("10000000", [_acompte("4000000")])
    assert vue["statut"] == "solde_a_payer_indicatif"
    alertes = alertes_depuis_rapprochement_acomptes(
        [_vue("SA FICTIVE", 7, vue)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "rapprochement_acomptes"
    # JAMAIS critique ni vigilance — préparation de la liquidation,
    # pas un manquement.
    assert a["gravite"] == "info"
    assert a["client"] == "SA FICTIVE"
    assert a["mission_id"] == 7
    assert a["echeance"] is None
    assert a["lien"] == "rapprochement_acomptes"
    assert "solde d'IS indicatif à préparer" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "solde indicatif 6000000 FCFA" in a["libelle"]
    assert (
        "approximation sur acomptes saisis, les quittances font foi"
    ) in a["libelle"]


def test_excedent_emet_info_libelle_a_faire_valoir():
    vue = _rapprochement("10000000", [_acompte("14000000")])
    assert vue["statut"] == "excedent_indicatif"
    alertes = alertes_depuis_rapprochement_acomptes(
        [_vue("SARL FICTIVE", 9, vue)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "rapprochement_acomptes"
    assert a["gravite"] == "info"
    assert "excédent d'acomptes indicatif à faire valoir" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "excédent indicatif 4000000 FCFA" in a["libelle"]
    assert "les quittances font foi" in a["libelle"]


def test_rien_si_equilibre_ou_indisponible():
    equilibre = _rapprochement("10000000", [_acompte("10000000")])
    assert equilibre["statut"] == "equilibre_indicatif"
    indisponible = _rapprochement(None, [_acompte("5000000")])
    assert indisponible["disponible"] is False
    assert indisponible["statut"] == "indisponible"
    alertes = alertes_depuis_rapprochement_acomptes(
        [
            _vue("A", 1, equilibre),
            _vue("B", 2, indisponible),
            _vue("C", 3, {}),
        ]
    )
    assert alertes == []


def test_cles_stables_apres_normalisation():
    vue = _rapprochement("10000000")
    alertes = alertes_depuis_rapprochement_acomptes(
        [_vue("SA FICTIVE", 5, vue)]
    )
    a = normaliser_alerte(alertes[0])
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["type"] == "rapprochement_acomptes"
    assert a["gravite"] == "info"


def test_plafonds_source_et_centre():
    # Plafond de missions examinées par la source — coût borné.
    assert PLAFOND_MISSIONS_RAPPROCHEMENT_ACOMPTES == 200
    # Plafond global du centre : même une avalanche de soldes reste
    # tronquée à PLAFOND_ALERTES.
    vue = _rapprochement("1000")
    vues = [_vue(f"Client {i:03d}", i, vue) for i in range(1, 151)]
    alertes = alertes_depuis_rapprochement_acomptes(vues)
    assert len(alertes) == 150
    from datetime import date

    centre = assembler_centre(alertes, [], date(2026, 7, 28))
    assert len(centre["alertes"]) == PLAFOND_ALERTES
    assert centre["synthese"]["par_type"]["rapprochement_acomptes"] == (
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

    lib = f"v-alrap-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="alertes rapprochement")
    publier_version(session, lib, "alrap@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"alrap.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Alrap {email}",
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


def _acompte_db(session, tenant_id: int, mission_id: int,
                montant: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO acompte_impot (tenant_id, mission_id, "
                "nature, date_versement, montant) "
                "VALUES (:t, :m, 'acompte_is', "
                "CAST('2025-04-15' AS DATE), :mt)"
            ),
            {"t": tenant_id, "m": mission_id, "mt": montant},
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


def test_api_solde_et_excedent_alertes_info_structure_stable(session):
    tid, email = _cabinet(session)
    # Mission bénéficiaire sans acompte : IS théorique 10 000 000
    # (résultat 40 000 000 × 25 %) → solde indicatif à payer.
    mid_solde = _mission_en_cours(session, tid, "PM Alrap Solde FICTIVE")
    _solde(session, tid, mid_solde, "601", "Achats", "10000000", "0")
    _solde(session, tid, mid_solde, "701", "Ventes", "0", "50000000")
    # Mission bénéficiaire avec acomptes saisis supérieurs à l'IS
    # théorique → excédent indicatif à faire valoir.
    mid_exc = _mission_en_cours(session, tid, "PM Alrap Excedent FICTIVE")
    _solde(session, tid, mid_exc, "601", "Achats", "10000000", "0")
    _solde(session, tid, mid_exc, "701", "Ventes", "0", "50000000")
    _acompte_db(session, tid, mid_exc, "14000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    alertes = {
        a["mission_id"]: a
        for a in corps["alertes"]
        if a["type"] == "rapprochement_acomptes"
    }
    assert set(alertes) == {mid_solde, mid_exc}
    a = alertes[mid_solde]
    # JAMAIS critique ni vigilance — point de préparation informatif.
    assert a["gravite"] == "info"
    assert a["client"] == "PM Alrap Solde FICTIVE"
    assert "solde d'IS indicatif à préparer" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "solde indicatif 10000000 FCFA" in a["libelle"]
    assert "les quittances font foi" in a["libelle"]
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["lien"] == "rapprochement_acomptes"
    b = alertes[mid_exc]
    assert b["gravite"] == "info"
    assert "excédent d'acomptes indicatif à faire valoir" in b["libelle"]
    assert "excédent indicatif 4000000" in b["libelle"]
    assert corps["synthese"]["par_type"]["rapprochement_acomptes"] == 2


def test_api_indisponible_aucune_alerte_source_tolerante(
    session, monkeypatch
):
    tid, email = _cabinet(session)
    # Mission sans balance : rapprochement indisponible → rien.
    _mission_en_cours(session, tid, "PM Alrap Vide FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    assert not [
        a for a in corps["alertes"]
        if a["type"] == "rapprochement_acomptes"
    ]
    assert corps["synthese"]["par_type"]["rapprochement_acomptes"] == 0

    # Source en échec : jamais bloquante, simplement signalée.
    import backend.plateforme.rapprochement_acomptes as rap

    def _boom(*args, **kwargs):
        raise RuntimeError("rapprochement indisponible")

    monkeypatch.setattr(
        rap, "vue_rapprochement_acomptes_mission", _boom
    )
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert "rapprochement_acomptes" in corps["sources_en_echec"]
    assert corps["note"]
