"""Centre d'alertes — source déficits reportables (suivi informatif)."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.centre_alertes import (
    PLAFOND_ALERTES,
    PLAFOND_MISSIONS_DEFICITS,
    TYPES_ALERTE,
    alertes_depuis_deficits_reportables,
    assembler_centre,
    normaliser_alerte,
    synthese_alertes,
)
from backend.plateforme.deficits_reportables import (
    construire_suivi_deficits,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _vue(client: str, mission_id: int, deficits: dict) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "deficits": deficits,
    }


def _suivi(resultat_fiscal: str | None, exercice: int = 2025) -> dict:
    vue = construire_suivi_deficits(
        [
            {
                "exercice": exercice,
                "mission_id": 1,
                "disponible": resultat_fiscal is not None,
                "resultat_fiscal": resultat_fiscal,
            }
        ]
    )
    vue["exercice"] = exercice
    return vue


def test_type_deficits_reportables_dans_le_referentiel():
    assert "deficits_reportables" in TYPES_ALERTE
    a = normaliser_alerte(
        {"type": "deficits_reportables", "gravite": "info"}
    )
    assert a["type"] == "deficits_reportables"
    s = synthese_alertes([a])
    assert s["par_type"]["deficits_reportables"] == 1


def test_deficits_a_suivre_emet_info_jamais_critique_ni_vigilance():
    suivi = _suivi("-40000000")
    assert suivi["statut"] == "deficits_a_suivre"
    assert suivi["cumul_indicatif_final"] == "40000000"
    alertes = alertes_depuis_deficits_reportables(
        [_vue("SA FICTIVE", 7, suivi)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "deficits_reportables"
    # JAMAIS critique ni vigilance — point de suivi, pas un manquement.
    assert a["gravite"] == "info"
    assert a["client"] == "SA FICTIVE"
    assert a["mission_id"] == 7
    assert a["echeance"] is None
    assert a["lien"] == "deficits_reportables"
    assert "déficits fiscaux théoriques à suivre" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "cumul indicatif 40000000 FCFA" in a["libelle"]
    assert (
        "approximation à imputation théorique maximale, "
        "les liasses font foi"
    ) in a["libelle"]


def test_rien_si_aucun_deficit_ou_indisponible():
    # Bénéficiaire : aucun déficit constaté.
    benefice = _suivi("40000000")
    assert benefice["statut"] == "aucun_deficit"
    # Indisponible : aucun exercice chiffrable.
    indisponible = _suivi(None)
    assert indisponible["disponible"] is False
    assert indisponible["statut"] == "indisponible"
    alertes = alertes_depuis_deficits_reportables(
        [
            _vue("A", 1, benefice),
            _vue("B", 2, indisponible),
            _vue("C", 3, {}),
        ]
    )
    assert alertes == []


def test_plafonds_source_et_centre():
    # Plafond de missions examinées par la source — coût borné.
    assert PLAFOND_MISSIONS_DEFICITS == 200
    # Plafond global du centre : même une avalanche de suivis reste
    # tronquée à PLAFOND_ALERTES.
    suivi = _suivi("-1000")
    vues = [_vue(f"Client {i:03d}", i, suivi) for i in range(1, 151)]
    alertes = alertes_depuis_deficits_reportables(vues)
    assert len(alertes) == 150
    from datetime import date

    centre = assembler_centre(alertes, [], date(2026, 7, 28))
    assert len(centre["alertes"]) == PLAFOND_ALERTES
    assert centre["synthese"]["par_type"]["deficits_reportables"] == (
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

    lib = f"v-aldef-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="alertes deficits")
    publier_version(session, lib, "aldef@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"aldef.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Aldef {email}",
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


def _point_en_retard(session, tenant_id: int, mission_id: int) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle, date_cible) "
                "VALUES (:t, :m, :lib, CAST(:dc AS DATE))"
            ),
            {"t": tenant_id, "m": mission_id,
             "lib": "Rapprocher les liasses déposées", "dc": "2020-01-15"},
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


def test_api_deficit_emet_alerte_info_structure_stable(session):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Aldef Deficit FICTIVE")
    # Charges 50 000 000 > produits 10 000 000 → déficit 40 000 000.
    _solde(session, tid, mid, "601", "Achats", "50000000", "0")
    _solde(session, tid, mid, "701", "Ventes", "0", "10000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    alertes = [
        a for a in corps["alertes"]
        if a["type"] == "deficits_reportables"
    ]
    assert len(alertes) == 1
    a = alertes[0]
    # JAMAIS critique ni vigilance — point de suivi informatif.
    assert a["gravite"] == "info"
    assert a["client"] == "PM Aldef Deficit FICTIVE"
    assert a["mission_id"] == mid
    assert "déficits fiscaux théoriques à suivre" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    # Montant brut du module (Decimal sérialisé str) — pas reformaté.
    assert "cumul indicatif 40000000.00 FCFA" in a["libelle"]
    assert "les liasses font foi" in a["libelle"]
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["lien"] == "deficits_reportables"
    assert corps["synthese"]["par_type"]["deficits_reportables"] == 1


def test_api_benefice_et_indisponible_aucune_alerte(session):
    tid, email = _cabinet(session)
    # Mission bénéficiaire : aucun déficit à suivre.
    mid_ok = _mission_en_cours(session, tid, "PM Aldef Benefice FICTIVE")
    _solde(session, tid, mid_ok, "601", "Achats", "10000000", "0")
    _solde(session, tid, mid_ok, "701", "Ventes", "0", "50000000")
    # Mission indisponible : aucune balance importée.
    _mission_en_cours(session, tid, "PM Aldef Vide FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    assert not [
        a for a in corps["alertes"]
        if a["type"] == "deficits_reportables"
    ]
    assert corps["synthese"]["par_type"]["deficits_reportables"] == 0


def test_api_source_deficits_en_echec_jamais_bloquante(
    session, monkeypatch
):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Aldef Panne FICTIVE")
    _point_en_retard(session, tid, mid)
    session.commit()

    import backend.plateforme.deficits_reportables as dfr

    def _boom(*args, **kwargs):
        raise RuntimeError("suivi des déficits indisponible")

    monkeypatch.setattr(dfr, "vue_deficits_reportables_mission", _boom)

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # La source en échec est signalée, les autres alertes restent là.
    assert "deficits_reportables" in corps["sources_en_echec"]
    assert any(
        a["type"] == "point_convenu" for a in corps["alertes"]
    )
    assert corps["note"]
