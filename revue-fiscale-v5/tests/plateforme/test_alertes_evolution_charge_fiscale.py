"""Centre d'alertes — source évolution de la charge fiscale (info)."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pytest

from backend.plateforme.centre_alertes import (
    PLAFOND_MISSIONS_EVOLUTION_CHARGE_FISCALE,
    SEUIL_VARIATION_NOTABLE_PCT,
    TYPES_ALERTE,
    alertes_depuis_evolution_charge_fiscale,
    normaliser_alerte,
    synthese_alertes,
)
from backend.plateforme.evolution_charge_fiscale import construire_evolution

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _vue(client: str, mission_id: int, evolution: dict) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "evolution": evolution,
    }


def _evolution(totaux: list[tuple[int, str | None]]) -> dict:
    """Vue d'évolution construite par le module EXISTANT (aucun mock)."""
    exercices = [
        {
            "exercice": ex,
            "mission_id": i + 1,
            "disponible": total is not None,
            "total": total,
            "composantes": {},
        }
        for i, (ex, total) in enumerate(totaux)
    ]
    return construire_evolution(exercices)


def test_type_evolution_charge_fiscale_dans_le_referentiel():
    assert "evolution_charge_fiscale" in TYPES_ALERTE
    a = normaliser_alerte(
        {"type": "evolution_charge_fiscale", "gravite": "info"}
    )
    assert a["type"] == "evolution_charge_fiscale"
    s = synthese_alertes([a])
    assert s["par_type"]["evolution_charge_fiscale"] == 1


def test_constantes_seuil_et_plafond():
    assert SEUIL_VARIATION_NOTABLE_PCT == Decimal("25")
    assert PLAFOND_MISSIONS_EVOLUTION_CHARGE_FISCALE == 200


def test_hausse_au_dela_du_seuil_emet_info_jamais_vigilance():
    # 1 000 000 → 1 325 000 : +32,5 % — au-delà du seuil de 25 %.
    vue = _evolution([(2023, "1000000"), (2024, "1325000")])
    assert vue["disponible"] is True
    assert vue["variations"][0]["total"]["variation_relative_pct"] == (
        "32.5"
    )
    alertes = alertes_depuis_evolution_charge_fiscale(
        [_vue("SA FICTIVE", 7, vue)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "evolution_charge_fiscale"
    # info, JAMAIS vigilance ni critique — estimation indicative
    # pluriannuelle, la variation s'explique, l'humain analyse.
    assert a["gravite"] == "info"
    assert a["client"] == "SA FICTIVE"
    assert a["mission_id"] == 7
    assert a["echeance"] is None
    assert a["lien"] == "evolution_charge_fiscale"
    # Virgule française dans le libellé (le JSON machine garde le
    # point, l'affichage humain la virgule).
    assert "en hausse de 32,5 %" in a["libelle"]
    assert "32.5" not in a["libelle"]
    assert "entre 2023 et 2024" in a["libelle"]
    assert "évolution à examiner avec le client" in a["libelle"]
    assert "estimation indicative" in a["libelle"]


def test_baisse_au_dela_du_seuil_emet_info():
    # 1 000 000 → 700 000 : -30,0 % — l'ampleur absolue dépasse 25 %.
    vue = _evolution([(2023, "1000000"), (2024, "700000")])
    alertes = alertes_depuis_evolution_charge_fiscale(
        [_vue("SARL FICTIVE", 9, vue)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["gravite"] == "info"
    assert "en baisse de 30,0 %" in a["libelle"]
    assert "entre 2023 et 2024" in a["libelle"]


def test_seuil_exact_emet_alerte():
    # +25,0 % exactement : le seuil est inclusif (≥).
    vue = _evolution([(2023, "1000000"), (2024, "1250000")])
    alertes = alertes_depuis_evolution_charge_fiscale(
        [_vue("A", 1, vue)]
    )
    assert len(alertes) == 1
    assert alertes[0]["gravite"] == "info"
    assert "en hausse de 25,0 %" in alertes[0]["libelle"]


def test_rien_si_sous_seuil_stable_pct_absent_ou_indisponible():
    # Sous le seuil : +10,0 %.
    sous_seuil = _evolution([(2023, "1000000"), (2024, "1100000")])
    # Stable : aucune variation de sens.
    stable = _evolution([(2023, "1000000"), (2024, "1000000")])
    assert stable["variations"][0]["total"]["sens"] == "stable"
    # Base nulle : pourcentage None — aucune alerte inventée.
    base_nulle = _evolution([(2023, "0"), (2024, "500000")])
    assert base_nulle["variations"][0]["total"][
        "variation_relative_pct"
    ] is None
    # Indisponible : un seul exercice.
    indisponible = _evolution([(2024, "1000000")])
    assert indisponible["disponible"] is False
    alertes = alertes_depuis_evolution_charge_fiscale(
        [
            _vue("A", 1, sous_seuil),
            _vue("B", 2, stable),
            _vue("C", 3, base_nulle),
            _vue("D", 4, indisponible),
            _vue("E", 5, {}),
        ]
    )
    assert alertes == []


def test_seule_la_derniere_variation_compte():
    # +100 % entre 2022 et 2023 mais +5 % entre 2023 et 2024 : la
    # DERNIÈRE variation est sous le seuil → rien (le passé notable
    # reste consultable dans la vue dédiée).
    vue = _evolution(
        [(2022, "1000000"), (2023, "2000000"), (2024, "2100000")]
    )
    assert len(vue["variations"]) == 2
    alertes = alertes_depuis_evolution_charge_fiscale(
        [_vue("A", 1, vue)]
    )
    assert alertes == []


def test_cles_stables_apres_normalisation():
    vue = _evolution([(2023, "1000000"), (2024, "1500000")])
    alertes = alertes_depuis_evolution_charge_fiscale(
        [_vue("SA FICTIVE", 5, vue)]
    )
    a = normaliser_alerte(alertes[0])
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["type"] == "evolution_charge_fiscale"
    assert a["gravite"] == "info"


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

    lib = f"v-alecf-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(
        session, lib, note="alertes evolution charge fiscale"
    )
    publier_version(session, lib, "alecf@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"alecf.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Alecf {email}",
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


def _mission_en_cours(session, tenant_id: int, contribuable_id: int,
                      exercice: int) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=contribuable_id,
            exercice=exercice,
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


def _declaration(session, tenant_id: int, mission_id: int,
                 periode: str, tva_collectee: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO declaration_tva (tenant_id, mission_id, "
                "periode, tva_collectee, tva_deductible) "
                "VALUES (:t, :m, :p, :c, 0)"
            ),
            {"t": tenant_id, "m": mission_id, "p": periode,
             "c": tva_collectee},
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
             "lib": "Expliquer l'évolution de la charge fiscale",
             "dc": "2020-01-15"},
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


def test_api_hausse_notable_une_alerte_info_par_client(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Alecf Pluri FICTIVE")
    # 2024 : bénéfice modeste ; 2025 : bénéfice bien plus élevé —
    # variation du total de charge propre largement au-dessus de 25 %.
    mid_2024 = _mission_en_cours(session, tid, cid, exercice=2024)
    _solde(session, tid, mid_2024, "701", "Ventes FICTIVES",
           "0", "10000000")
    _solde(session, tid, mid_2024, "601", "Achats FICTIFS",
           "4000000", "0")
    mid_2025 = _mission_en_cours(session, tid, cid, exercice=2025)
    _solde(session, tid, mid_2025, "701", "Ventes FICTIVES",
           "0", "20000000")
    _solde(session, tid, mid_2025, "601", "Achats FICTIFS",
           "5000000", "0")
    # La TVA déclarée reste hors du total de charge propre.
    _declaration(session, tid, mid_2025, "2025-01", "1800000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    alertes = [
        a for a in corps["alertes"]
        if a["type"] == "evolution_charge_fiscale"
    ]
    # UNE alerte par client (dernier exercice) — jamais une par mission.
    assert len(alertes) == 1
    a = alertes[0]
    # info, JAMAIS vigilance ni critique — estimation indicative.
    assert a["gravite"] == "info"
    assert a["client"] == "PM Alecf Pluri FICTIVE"
    assert a["mission_id"] == mid_2025
    # Virgule française dans le libellé, point machine banni.
    assert re.search(r"en hausse de \d+,\d %", a["libelle"])
    assert not re.search(r"\d+\.\d", a["libelle"])
    assert "entre 2024 et 2025" in a["libelle"]
    assert "évolution à examiner avec le client" in a["libelle"]
    assert "estimation indicative" in a["libelle"]
    # Structure stable du contrat.
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert a["echeance"] is None
    assert a["lien"] == "evolution_charge_fiscale"
    assert corps["synthese"]["par_type"]["evolution_charge_fiscale"] == 1


def test_api_sous_seuil_et_indisponible_aucune_alerte(session):
    tid, email = _cabinet(session)
    # Client A : variation modeste (~+5 %) — sous le seuil de 25 %.
    cid_a = _contribuable(session, tid, "PM Alecf Modeste FICTIVE")
    mid_2024 = _mission_en_cours(session, tid, cid_a, exercice=2024)
    _solde(session, tid, mid_2024, "701", "Ventes FICTIVES",
           "0", "10000000")
    _solde(session, tid, mid_2024, "601", "Achats FICTIFS",
           "4000000", "0")
    mid_2025 = _mission_en_cours(session, tid, cid_a, exercice=2025)
    _solde(session, tid, mid_2025, "701", "Ventes FICTIVES",
           "0", "10500000")
    _solde(session, tid, mid_2025, "601", "Achats FICTIFS",
           "4200000", "0")
    # Client B : un seul exercice sans balance — évolution indisponible.
    cid_b = _contribuable(session, tid, "PM Alecf Vide FICTIVE")
    _mission_en_cours(session, tid, cid_b, exercice=2025)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    assert not [
        a for a in corps["alertes"]
        if a["type"] == "evolution_charge_fiscale"
    ]
    assert corps["synthese"]["par_type"]["evolution_charge_fiscale"] == 0


def test_api_source_en_echec_jamais_bloquante(session, monkeypatch):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM Alecf Panne FICTIVE")
    mid = _mission_en_cours(session, tid, cid, exercice=2025)
    _point_en_retard(session, tid, mid)
    session.commit()

    import backend.plateforme.evolution_charge_fiscale as ecf

    def _boom(*args, **kwargs):
        raise RuntimeError("évolution charge fiscale indisponible")

    monkeypatch.setattr(
        ecf, "vue_evolution_charge_fiscale_mission", _boom
    )

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # La source en échec est signalée, les autres alertes restent là.
    assert "evolution_charge_fiscale" in corps["sources_en_echec"]
    assert any(
        a["type"] == "point_convenu" for a in corps["alertes"]
    )
    assert corps["note"]
