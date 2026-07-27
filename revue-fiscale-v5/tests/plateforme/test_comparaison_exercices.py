"""Comparaison inter-exercices d'un contribuable — N vs N-1."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.comparaison_exercices import (
    MENTION_NOTE,
    RAISON_AUCUNE_MISSION,
    RAISON_UN_SEUL_EXERCICE,
    TENDANCE_AMELIORATION,
    TENDANCE_DEGRADATION,
    TENDANCE_STABLE,
    agreger_par_impot,
    comparer_agregats,
    qualifier_tendance,
    synthese_comparaison,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _risque(impot: str, montant=None, penalites=None) -> dict:
    return {
        "impot": impot,
        "montant_estime": montant,
        "penalites_estimees": penalites,
    }


def test_agreger_par_impot():
    agregats = agreger_par_impot(
        [
            _risque("TVA", "1000000", "200000"),
            _risque("tva", "500000"),
            _risque("BIC", penalites="300000"),
            # Non chiffré : compte dans le nombre, exposition 0.
            _risque("BIC"),
            # Impôt vide → regroupé sous AUTRE.
            _risque("", "50000"),
        ]
    )
    assert agregats == {
        "TVA": {"nb_ouverts": 2, "exposition": Decimal("1700000")},
        "BIC": {"nb_ouverts": 2, "exposition": Decimal("300000")},
        "AUTRE": {"nb_ouverts": 1, "exposition": Decimal("50000")},
    }
    assert agreger_par_impot([]) == {}


def test_qualifier_tendance():
    assert qualifier_tendance(1, Decimal("0")) == TENDANCE_DEGRADATION
    assert qualifier_tendance(0, Decimal("100")) == TENDANCE_DEGRADATION
    # Prudence : la hausse d'un indicateur prime la baisse de l'autre.
    assert qualifier_tendance(-2, Decimal("100")) == TENDANCE_DEGRADATION
    assert qualifier_tendance(-1, Decimal("0")) == TENDANCE_AMELIORATION
    assert qualifier_tendance(0, Decimal("-50")) == TENDANCE_AMELIORATION
    assert qualifier_tendance(0, Decimal("0")) == TENDANCE_STABLE


def test_comparer_agregats_deltas_et_union_impots():
    recent = agreger_par_impot(
        [_risque("TVA", "3000000"), _risque("ITS", "400000")]
    )
    precedent = agreger_par_impot(
        [
            _risque("TVA", "1000000"),
            _risque("TVA", "500000"),
            _risque("BIC", "200000"),
        ]
    )
    lignes = comparer_agregats(recent, precedent)
    # Union triée alphabétiquement : BIC, ITS, TVA.
    assert [ligne["impot"] for ligne in lignes] == ["BIC", "ITS", "TVA"]
    bic, its, tva = lignes
    # BIC : disparu au récent → amélioration.
    assert bic["nb_ouverts_recent"] == 0
    assert bic["delta_nb_ouverts"] == -1
    assert bic["delta_exposition"] == "-200000"
    assert bic["tendance"] == TENDANCE_AMELIORATION
    # ITS : nouveau → dégradation.
    assert its["nb_ouverts_precedent"] == 0
    assert its["delta_nb_ouverts"] == 1
    assert its["delta_exposition"] == "400000"
    assert its["tendance"] == TENDANCE_DEGRADATION
    # TVA : moins de risques mais exposition en hausse → dégradation.
    assert tva["nb_ouverts_recent"] == 1
    assert tva["nb_ouverts_precedent"] == 2
    assert tva["delta_nb_ouverts"] == -1
    assert tva["exposition_recente"] == "3000000"
    assert tva["exposition_precedente"] == "1500000"
    assert tva["delta_exposition"] == "1500000"
    assert tva["tendance"] == TENDANCE_DEGRADATION


def test_synthese_comparaison():
    recent = agreger_par_impot([_risque("TVA", "800000")])
    precedent = agreger_par_impot(
        [_risque("TVA", "1000000"), _risque("BIC", "500000")]
    )
    s = synthese_comparaison(recent, precedent)
    assert s == {
        "nb_ouverts_recent": 1,
        "nb_ouverts_precedent": 2,
        "delta_nb_ouverts": -1,
        "exposition_recente": "800000",
        "exposition_precedente": "1500000",
        "delta_exposition": "-700000",
        "tendance": TENDANCE_AMELIORATION,
    }
    assert synthese_comparaison({}, {}) == {
        "nb_ouverts_recent": 0,
        "nb_ouverts_precedent": 0,
        "delta_nb_ouverts": 0,
        "exposition_recente": "0",
        "exposition_precedente": "0",
        "delta_exposition": "0",
        "tendance": TENDANCE_STABLE,
    }


# ── Tests DB / API ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.comparaison_exercices import (  # noqa: E402
    ErreurComparaisonExercices,
    comparaison_contribuable,
)
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-compex-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="comparaison-exercices")
    publier_version(session, lib, "compex@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Compex {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _contribuable(session, tenant_id: int, denomination: str) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO contribuable (tenant_id, denomination, forme) "
                    "VALUES (:t, :d, 'pm') RETURNING id"
                ),
                {"t": tenant_id, "d": denomination},
            ).scalar_one()
        )


def _mission(session, tenant_id: int, cid: int, exercice: int) -> int:
    from backend.plateforme.missions import creer_mission

    with contexte_tenant(session, tenant_id):
        mid = creer_mission(
            session,
            tenant_id,
            contribuable_id=cid,
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
    return int(mid)


def _creer_risque(
    session,
    tenant_id: int,
    cid: int,
    mid: int,
    *,
    impot: str = "TVA",
    montant: str | None = None,
    penalites: str | None = None,
    statut: str = "ouvert",
    exercice: int = 2025,
) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, "
                    "origine_mission_id, impot, libelle, montant_estime, "
                    "penalites_estimees, probabilite, statut, "
                    "exercice_origine) VALUES (:t, :c, :m, :i, :lib, :mt, "
                    ":pen, 'possible', :s, :ex) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": cid,
                    "m": mid,
                    "i": impot,
                    "lib": f"Risque compex {uuid.uuid4().hex[:6]}",
                    "mt": montant,
                    "pen": penalites,
                    "s": statut,
                    "ex": exercice,
                },
            ).scalar_one()
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


def test_comparaison_deux_exercices(session):
    """N vs N-1 : deltas par impôt, tendance, risques clos exclus."""
    tid, _email = _cabinet(session, "compex.deux")
    cid = _contribuable(session, tid, "SA Compex FICTIVE")
    mid_2024 = _mission(session, tid, cid, 2024)
    mid_2025 = _mission(session, tid, cid, 2025)
    # 2024 : un risque TVA ouvert (1 000 000) + un résolu (exclu).
    _creer_risque(
        session, tid, cid, mid_2024, montant="1000000", exercice=2024
    )
    _creer_risque(
        session,
        tid,
        cid,
        mid_2024,
        montant="9999999",
        statut="resolu",
        exercice=2024,
    )
    # 2025 : TVA en hausse (pénalités incluses) + un BIC nouveau.
    _creer_risque(
        session, tid, cid, mid_2025, montant="1500000", penalites="300000"
    )
    _creer_risque(session, tid, cid, mid_2025, impot="BIC", montant="200000")
    session.commit()

    out = comparaison_contribuable(session, tid, cid)
    assert out["disponible"] is True
    assert out["raison"] is None
    assert out["contribuable"]["denomination"] == "SA Compex FICTIVE"
    assert out["exercice_recent"] == {
        "exercice": 2025,
        "mission_id": mid_2025,
        "statut_mission": "cadrage",
    }
    assert out["exercice_precedent"]["exercice"] == 2024
    assert out["exercice_precedent"]["mission_id"] == mid_2024
    bic, tva = out["par_impot"]
    assert bic["impot"] == "BIC"
    assert bic["delta_nb_ouverts"] == 1
    assert bic["delta_exposition"] == "200000.00"
    assert bic["tendance"] == TENDANCE_DEGRADATION
    assert tva["impot"] == "TVA"
    assert tva["nb_ouverts_recent"] == 1
    assert tva["nb_ouverts_precedent"] == 1
    assert tva["exposition_recente"] == "1800000.00"
    assert tva["exposition_precedente"] == "1000000.00"
    assert tva["delta_exposition"] == "800000.00"
    assert tva["tendance"] == TENDANCE_DEGRADATION
    assert out["synthese"]["nb_ouverts_recent"] == 2
    assert out["synthese"]["nb_ouverts_precedent"] == 1
    assert out["synthese"]["delta_nb_ouverts"] == 1
    assert out["synthese"]["delta_exposition"] == "1000000.00"
    assert out["synthese"]["tendance"] == TENDANCE_DEGRADATION
    assert out["note"] == MENTION_NOTE


def test_comparaison_un_seul_exercice(session):
    """Un seul exercice revu → indisponible avec raison explicite."""
    tid, _email = _cabinet(session, "compex.seul")
    cid = _contribuable(session, tid, "PM Seul Exercice FICTIF")
    _mission(session, tid, cid, 2025)
    session.commit()

    out = comparaison_contribuable(session, tid, cid)
    assert out["disponible"] is False
    assert out["raison"] == RAISON_UN_SEUL_EXERCICE
    assert out["note"] == MENTION_NOTE
    assert "synthese" not in out


def test_comparaison_sans_mission_et_introuvable(session):
    tid, _email = _cabinet(session, "compex.vide")
    cid = _contribuable(session, tid, "PM Sans Mission FICTIF")
    session.commit()

    out = comparaison_contribuable(session, tid, cid)
    assert out["disponible"] is False
    assert out["raison"] == RAISON_AUCUNE_MISSION

    with pytest.raises(ErreurComparaisonExercices):
        comparaison_contribuable(session, tid, 999_999_999)


def test_api_comparaison_deux_exercices(session):
    tid, email = _cabinet(session, "compex.api")
    cid = _contribuable(session, tid, "PM API Compex FICTIF")
    mid_2023 = _mission(session, tid, cid, 2023)
    mid_2024 = _mission(session, tid, cid, 2024)
    _creer_risque(
        session, tid, cid, mid_2023, montant="500000", exercice=2023
    )
    _creer_risque(
        session, tid, cid, mid_2024, montant="250000", exercice=2024
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(
        f"/api/v1/contribuables/{cid}/comparaison-exercices", headers=h
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is True
    assert corps["exercice_recent"]["exercice"] == 2024
    assert corps["exercice_precedent"]["exercice"] == 2023
    assert corps["synthese"]["delta_exposition"] == "-250000.00"
    assert corps["synthese"]["tendance"] == TENDANCE_AMELIORATION
    assert corps["note"] == MENTION_NOTE


def test_api_comparaison_indisponible(session):
    tid, email = _cabinet(session, "compex.api.indispo")
    cid = _contribuable(session, tid, "PM Indispo FICTIF")
    _mission(session, tid, cid, 2025)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(
        f"/api/v1/contribuables/{cid}/comparaison-exercices", headers=h
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["disponible"] is False
    assert corps["raison"] == RAISON_UN_SEUL_EXERCICE


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "compex.a")
    cid_a = _contribuable(session, tid_a, "PM Isolée Compex FICTIF")
    _tid_b, email_b = _cabinet(session, "compex.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(
        f"/api/v1/contribuables/{cid_a}/comparaison-exercices", headers=h
    )
    assert r.status_code == 404, r.text


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/contribuables/1/comparaison-exercices")
    assert r.status_code == 401, r.text
