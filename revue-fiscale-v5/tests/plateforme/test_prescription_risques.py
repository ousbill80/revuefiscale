"""Analyse de prescription des risques — délai de reprise (pratique LPF CI)."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from backend.plateforme.prescription_risques import (
    analyser_prescription,
    date_prescription,
    exercices_reprenables,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_date_prescription_droit_commun():
    # Exercice 2020 → droit de reprise jusqu'à fin 2023 (N + 3).
    assert date_prescription(2020) == date(2023, 12, 31)
    assert date_prescription(2025) == date(2028, 12, 31)


def test_exercices_reprenables_trois_derniers():
    assert exercices_reprenables(date(2026, 7, 27)) == [2023, 2024, 2025]


def _risque(
    rid: int,
    exercice: int,
    *,
    statut: str = "ouvert",
    montant: str | None = None,
    penalites: str | None = None,
) -> dict:
    return {
        "id": rid,
        "libelle": f"Risque {rid}",
        "impot": "tva",
        "exercice_origine": exercice,
        "statut": statut,
        "montant_estime": montant,
        "penalites_estimees": penalites,
    }


def test_analyser_prescription_classement_et_exposition():
    aujourd_hui = date(2026, 7, 27)
    risques = [
        # 2021 → prescrit le 31/12/2024 < aujourd'hui → à basculer.
        _risque(1, 2021, montant="1000000", penalites="250000"),
        # 2022 → prescrit le 31/12/2025 < aujourd'hui → à basculer (sans montant).
        _risque(2, 2022),
        # 2023 → prescription 31/12/2026, dans les 12 mois → proche.
        _risque(3, 2023, montant="500000"),
        # 2025 → prescription 31/12/2028 → non prescrit.
        _risque(4, 2025, montant="2000000"),
        # Clos (accepté) : ignoré même si ancien.
        _risque(5, 2019, statut="accepte", montant="9000000"),
    ]

    r = analyser_prescription(risques, aujourd_hui)
    assert [i["risque_id"] for i in r["prescrits_a_basculer"]] == [1, 2]
    assert [i["risque_id"] for i in r["proches_prescription"]] == [3]
    assert [i["risque_id"] for i in r["non_prescrits"]] == [4]
    # Exposition = montant + pénalités des seuls prescrits (Decimal exact).
    assert Decimal(r["exposition_prescrite"]) == Decimal("1250000")

    item = r["prescrits_a_basculer"][0]
    assert item["date_prescription"] == "2024-12-31"
    assert item["impot"] == "TVA"
    assert item["montant"] == "1250000"
    assert r["prescrits_a_basculer"][1]["montant"] is None
    assert r["proches_prescription"][0]["date_prescription"] == "2026-12-31"


def test_analyser_prescription_vide():
    r = analyser_prescription([], date(2026, 1, 1))
    assert r["prescrits_a_basculer"] == []
    assert r["proches_prescription"] == []
    assert r["non_prescrits"] == []
    assert r["exposition_prescrite"] == "0"


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
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-prescr-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="prescription-risques")
    publier_version(session, lib, "prescr@test.ci")


def _mission_en_cours(session) -> tuple[int, int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"prescr.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Prescr {email}",
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
                "VALUES (:t, 'PM Prescr FICTIF', 'pm') RETURNING id"
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
    return r.tenant_id, int(mid), int(cid), email


def _creer_risque(
    session,
    tenant_id: int,
    contribuable_id: int,
    *,
    exercice: int,
    montant: int | None = None,
    penalites: int | None = None,
    statut: str = "ouvert",
) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                    "libelle, montant_estime, penalites_estimees, statut, "
                    "exercice_origine) "
                    "VALUES (:t, :c, 'TVA', 'Risque test prescription', "
                    ":mt, :pen, :st, :ex) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "mt": montant,
                    "pen": penalites,
                    "st": statut,
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


def test_api_prescription_risque_ancien_prescrit(session):
    tid, mid, cid, email = _mission_en_cours(session)
    ancien = _creer_risque(
        session, tid, cid, exercice=2018, montant=3_000_000, penalites=750_000
    )
    recent = _creer_risque(session, tid, cid, exercice=2025, montant=100_000)
    # Clos : ne doit pas apparaître dans l'analyse.
    _creer_risque(
        session, tid, cid, exercice=2017, montant=8_000_000, statut="resolu"
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/prescription", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["contribuable_id"] == cid
    assert len(corps["exercices_reprenables"]) == 3
    assert corps["exercices_reprenables"] == sorted(
        corps["exercices_reprenables"]
    )

    ids_prescrits = {
        i["risque_id"] for i in corps["analyse"]["prescrits_a_basculer"]
    }
    assert ancien in ids_prescrits
    assert recent not in ids_prescrits
    assert corps["analyse"]["prescrits_a_basculer"][0][
        "date_prescription"
    ] == "2021-12-31"
    # Exposition = montant + pénalités du risque prescrit.
    assert Decimal(corps["synthese"]["exposition_prescrite"]) >= Decimal(
        "3750000"
    )
    assert corps["synthese"]["prescrits_a_basculer"] >= 1
    assert "hypothese" in corps


def test_api_prescription_alimente_controle_cloture(session):
    """Le point « prescription » du contrôle passe en attention (jamais bloquant)."""
    from backend.plateforme.controle_cloture import evaluer_cloture

    tid, mid, cid, _ = _mission_en_cours(session)
    _creer_risque(session, tid, cid, exercice=2018, montant=3_000_000)

    r = evaluer_cloture(session, tid, mid)
    assert r["points"][-1]["code"] == "prescription"
    assert r["points"][-1]["statut"] == "attention"
    assert "prescrit" in r["points"][-1]["detail"]
    assert "3000000" in r["points"][-1]["detail"]


def test_api_404_cross_tenant(session):
    tid_a, mid_a, _, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"prescr.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Prescr B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/prescription", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/prescription")
    assert r.status_code == 401, r.text
