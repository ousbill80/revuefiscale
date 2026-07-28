"""Évolution pluriannuelle de la charge fiscale — vue consultative."""
from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pytest

from backend.plateforme.evolution_charge_fiscale import (
    COMPOSANTES_EVOLUTION,
    NOTE_EVOLUTION_CHARGE_FISCALE,
    SENS_BAISSE,
    SENS_HAUSSE,
    SENS_STABLE,
    STATUT_EVOLUTION_DISPONIBLE,
    STATUT_INDISPONIBLE,
    calculer_variation,
    construire_evolution,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _exercice(exercice: int, mission_id: int, total: str | None,
              disponible: bool = True,
              composantes: dict | None = None) -> dict:
    return {
        "exercice": exercice,
        "mission_id": mission_id,
        "disponible": disponible,
        "total": total,
        "composantes": composantes or {},
    }


def test_indisponible_sans_exercices():
    vue = construire_evolution([])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["exercices"] == []
    assert vue["variations"] == []


def test_indisponible_mono_exercice():
    # Un seul exercice disponible : aucune évolution à lire.
    vue = construire_evolution([_exercice(2025, 7, "2800000")])
    assert vue["disponible"] is False
    assert vue["statut"] == STATUT_INDISPONIBLE
    assert vue["synthese"]["nb_exercices_disponibles"] == 1
    assert vue["variations"] == []


def test_deux_exercices_avec_variation():
    vue = construire_evolution(
        [
            _exercice(2024, 1, "3000000"),
            _exercice(2025, 2, "4000000"),
        ]
    )
    assert vue["disponible"] is True
    assert vue["statut"] == STATUT_EVOLUTION_DISPONIBLE
    assert vue["synthese"]["nb_variations"] == 1
    v = vue["variations"][0]
    assert v["exercice_precedent"] == 2024
    assert v["exercice"] == 2025
    assert v["total"]["variation_absolue"] == "1000000"
    assert v["total"]["variation_relative_pct"] == "33.3"
    assert v["total"]["sens"] == SENS_HAUSSE


def test_base_nulle_variation_relative_none():
    # Base nulle : aucune division inventée, pourcentage None.
    v = calculer_variation("0", "500000")
    assert v is not None
    assert v["variation_absolue"] == "500000"
    assert v["variation_relative_pct"] is None
    assert v["sens"] == SENS_HAUSSE


def test_sens_hausse_baisse_stable():
    assert calculer_variation("100", "150")["sens"] == SENS_HAUSSE
    assert calculer_variation("150", "100")["sens"] == SENS_BAISSE
    stable = calculer_variation("100", "100")
    assert stable["sens"] == SENS_STABLE
    assert stable["variation_absolue"] == "0"
    assert stable["variation_relative_pct"] == "0.0"


def test_variation_montant_indisponible_none():
    # Un des deux montants indisponible : variation None, jamais
    # de valeur inventée.
    assert calculer_variation(None, "100") is None
    assert calculer_variation("100", None) is None
    assert calculer_variation(None, None) is None


def test_exercice_indisponible_tolere_variation_saute():
    # 2024 indisponible : la variation relie les exercices
    # disponibles consécutifs (2023 → 2025), aucune valeur inventée.
    vue = construire_evolution(
        [
            _exercice(2023, 1, "1000000"),
            _exercice(2024, 2, None, disponible=False),
            _exercice(2025, 3, "2000000"),
        ]
    )
    assert vue["disponible"] is True
    assert vue["synthese"]["nb_exercices"] == 3
    assert vue["synthese"]["nb_exercices_disponibles"] == 2
    assert len(vue["variations"]) == 1
    v = vue["variations"][0]
    assert v["exercice_precedent"] == 2023
    assert v["exercice"] == 2025
    assert v["total"]["variation_relative_pct"] == "100.0"


def test_tri_par_exercice_croissant():
    vue = construire_evolution(
        [
            _exercice(2025, 3, "300"),
            _exercice(2023, 1, "100"),
            _exercice(2024, 2, "200"),
        ]
    )
    assert [ligne["exercice"] for ligne in vue["exercices"]] == [
        2023, 2024, 2025,
    ]
    assert [
        (v["exercice_precedent"], v["exercice"])
        for v in vue["variations"]
    ] == [(2023, 2024), (2024, 2025)]


def test_variations_par_composante():
    vue = construire_evolution(
        [
            _exercice(
                2024, 1, "3000000",
                composantes={"is": "2500000", "patente": "500000",
                             "salaires": None, "tva": "800000"},
            ),
            _exercice(
                2025, 2, "4000000",
                composantes={"is": "3500000", "patente": "500000",
                             "salaires": None, "tva": "600000"},
            ),
        ]
    )
    comp = vue["variations"][0]["composantes"]
    assert set(comp) == set(COMPOSANTES_EVOLUTION)
    assert comp["is"]["sens"] == SENS_HAUSSE
    assert comp["is"]["variation_relative_pct"] == "40.0"
    assert comp["patente"]["sens"] == SENS_STABLE
    assert comp["tva"]["sens"] == SENS_BAISSE
    assert comp["tva"]["variation_relative_pct"] == "-25.0"
    # Composante indisponible des deux côtés : variation None.
    assert comp["salaires"] is None


def test_format_pct_point_decimal_une_decimale():
    # Contrat machine : point décimal, 1 décimale (arrondi demi-sup).
    v = calculer_variation("3000000", "4000000")
    assert re.fullmatch(r"-?\d+\.\d", v["variation_relative_pct"])
    assert calculer_variation("3", "4")["variation_relative_pct"] == (
        "33.3"
    )
    assert calculer_variation("3", "2")["variation_relative_pct"] == (
        "-33.3"
    )


def test_cles_stables_toujours_presentes():
    cles = {
        "disponible", "exercices", "variations", "statut", "synthese",
        "note", "references",
    }
    for vue in (
        construire_evolution([]),
        construire_evolution(
            [_exercice(2024, 1, "100"), _exercice(2025, 2, "200")]
        ),
    ):
        assert cles <= set(vue)
        assert vue["note"] == NOTE_EVOLUTION_CHARGE_FISCALE
        assert vue["references"]
        assert vue["synthese"]["statut"] == vue["statut"]
        for ligne in vue["exercices"]:
            assert set(COMPOSANTES_EVOLUTION) <= set(
                ligne["composantes"]
            )


def test_montants_serialises_en_str():
    vue = construire_evolution(
        [
            _exercice(2024, 1, Decimal("3000000.00"),
                      composantes={"is": Decimal("2500000.00")}),
            _exercice(2025, 2, Decimal("4000000.00"),
                      composantes={"is": Decimal("3500000.00")}),
        ]
    )
    for ligne in vue["exercices"]:
        assert isinstance(ligne["total_charge_propre_estimee"], str)
        assert isinstance(
            ligne["composantes"]["is"]["montant_estime"], str
        )
    v = vue["variations"][0]
    assert isinstance(v["total"]["variation_absolue"], str)
    assert isinstance(v["total"]["variation_relative_pct"], str)


def test_tva_jamais_incluse_dans_total():
    vue = construire_evolution(
        [_exercice(2025, 1, "100", composantes={"tva": "50"})]
    )
    composantes = vue["exercices"][0]["composantes"]
    assert composantes["tva"]["incluse_dans_total"] is False
    for cle in ("is", "patente", "salaires"):
        assert composantes[cle]["incluse_dans_total"] is True


def test_note_consultative_non_accusatoire():
    assert "consultative" in NOTE_EVOLUTION_CHARGE_FISCALE
    assert "s'expliquent" in NOTE_EVOLUTION_CHARGE_FISCALE
    assert "activité, taux, assiettes, exonérations" in (
        NOTE_EVOLUTION_CHARGE_FISCALE
    )
    assert "THÉORIQUES" in NOTE_EVOLUTION_CHARGE_FISCALE
    assert "liasses font foi" in NOTE_EVOLUTION_CHARGE_FISCALE
    assert "l'humain analyse" in NOTE_EVOLUTION_CHARGE_FISCALE
    assert "aucun recalcul" in NOTE_EVOLUTION_CHARGE_FISCALE


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

    lib = f"v-evolcf-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="evolution charge fiscale")
    publier_version(session, lib, "evolcf@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"evolcf.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab EvolChargeFiscale {email}",
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
    return f"/api/v1/missions/{mid}/evolution-charge-fiscale"


def test_api_mono_exercice_indisponible(session):
    # Un seul exercice : la vue se sert quand même, statut
    # indisponible, clés stables, aucune variation inventée.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM EvolCF Mono FICTIVE")
    mid = _mission(session, tid, cid, exercice=2025)
    _solde(session, tid, mid, "701", "Ventes FICTIVES", "0", "10000000")
    _solde(session, tid, mid, "601", "Achats FICTIFS", "4000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is False
    assert corps["statut"] == "indisponible"
    assert corps["variations"] == []
    assert corps["synthese"]["nb_exercices"] == 1
    assert corps["note"]
    assert corps["references"]


def test_api_deux_exercices_variation_hausse(session):
    # Deux exercices du MÊME client : projection du panorama de charge
    # fiscale par exercice (aucun recalcul) et variation en hausse.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM EvolCF Pluri FICTIVE")
    mid_2024 = _mission(session, tid, cid, exercice=2024)
    _solde(session, tid, mid_2024, "701", "Ventes FICTIVES",
           "0", "10000000")
    _solde(session, tid, mid_2024, "601", "Achats FICTIFS",
           "4000000", "0")
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
    assert corps["statut"] == "evolution_disponible"
    assert [ligne["exercice"] for ligne in corps["exercices"]] == [
        2024, 2025,
    ]
    assert corps["synthese"]["nb_variations"] == 1
    v = corps["variations"][0]
    assert v["exercice_precedent"] == 2024
    assert v["exercice"] == 2025
    total = v["total"]
    assert total is not None
    assert total["sens"] == "hausse"
    assert Decimal(total["variation_absolue"]) > 0
    # Pourcentage : contrat machine à POINT décimal, 1 décimale.
    assert re.fullmatch(r"-?\d+\.\d", total["variation_relative_pct"])
    # Le total projeté est celui du panorama, jamais recalculé ici :
    # la variation absolue relie exactement les deux totaux restitués.
    t_2024 = Decimal(
        corps["exercices"][0]["total_charge_propre_estimee"]
    )
    t_2025 = Decimal(
        corps["exercices"][1]["total_charge_propre_estimee"]
    )
    assert Decimal(total["variation_absolue"]) == t_2025 - t_2024


def test_api_exercice_sans_balance_tolere(session):
    # 2023 chiffré, 2024 sans balance (ligne indisponible tolérée),
    # 2025 chiffré : la variation relie 2023 → 2025.
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM EvolCF Trou FICTIVE")
    mid_2023 = _mission(session, tid, cid, exercice=2023)
    _solde(session, tid, mid_2023, "701", "Ventes FICTIVES",
           "0", "10000000")
    _mission(session, tid, cid, exercice=2024)
    mid_2025 = _mission(session, tid, cid, exercice=2025)
    _solde(session, tid, mid_2025, "701", "Ventes FICTIVES",
           "0", "20000000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid_2025), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is True
    lignes = corps["exercices"]
    assert [ligne["exercice"] for ligne in lignes] == [2023, 2024, 2025]
    assert lignes[1]["disponible"] is False
    assert lignes[1]["total_charge_propre_estimee"] is None
    assert len(corps["variations"]) == 1
    assert corps["variations"][0]["exercice_precedent"] == 2023
    assert corps["variations"][0]["exercice"] == 2025


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    cid = _contribuable(session, tid, "PM EvolCF Journal FICTIVE")
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
                    "AND action = "
                    "'consultation_evolution_charge_fiscale'"
                ),
                {"m": mid},
            ).all()
        ]
    assert "consultation_evolution_charge_fiscale" in actions


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    cid_a = _contribuable(session, tid_a, "PM EvolCF Cross FICTIVE")
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
