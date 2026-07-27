"""Plan d'actions post-revue — dérivation consultative depuis les risques."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from backend.plateforme.plan_actions import (
    MENTION_NOTE,
    SEUIL_EXPOSITION_HAUTE,
    deriver_action,
    deriver_plan,
    synthese_plan,
)

# ── Tests purs (sans DB, dates figées) ─────────────────────────────

_JOUR = date(2026, 7, 1)


def _risque(
    rid: int,
    *,
    probabilite: str = "possible",
    montant: str | None = None,
    penalites: str | None = None,
    exercice: int = 2025,
    statut: str = "ouvert",
) -> dict:
    return {
        "id": rid,
        "libelle": f"Risque {rid}",
        "impot": "TVA",
        "exercice_origine": exercice,
        "statut": statut,
        "probabilite": probabilite,
        "montant_estime": montant,
        "penalites_estimees": penalites,
    }


def test_deriver_action_declaration_rectificative_haute():
    # Probable + exposition chiffrée ≥ seuil → rectificative, haute.
    item = deriver_action(
        _risque(1, probabilite="probable", montant="6000000"), _JOUR
    )
    assert item["type_action"] == "declaration_rectificative"
    assert item["priorite"] == "haute"
    assert item["exposition"] == "6000000"
    assert any("exposition chiffrée élevée" in m for m in item["motifs"])


def test_deriver_action_seuil_atteint_par_cumul_penalites():
    # 4 000 000 + 1 000 000 = 5 000 000 = seuil → haute (cumul Decimal).
    item = deriver_action(
        _risque(2, montant="4000000", penalites="1000000"), _JOUR
    )
    assert Decimal(item["exposition"]) == SEUIL_EXPOSITION_HAUTE
    assert item["priorite"] == "haute"
    assert item["type_action"] == "provision_a_documenter"


def test_deriver_action_prescription_proche_force_haute():
    # Exercice 2023 → prescription 2026-12-31, dans les 12 mois → haute.
    item = deriver_action(_risque(3, montant="100000", exercice=2023), _JOUR)
    assert item["date_prescription"] == "2026-12-31"
    assert item["priorite"] == "haute"
    assert any("dans les 12 mois" in m for m in item["motifs"])


def test_deriver_action_prescription_depassee():
    # Exercice 2022 → prescription 2025-12-31, dépassée → haute + motif.
    item = deriver_action(_risque(4, exercice=2022), _JOUR)
    assert item["priorite"] == "haute"
    assert any("dépassée" in m for m in item["motifs"])


def test_deriver_action_provision_moyenne():
    # Possible + exposition modeste, prescription lointaine → moyenne.
    item = deriver_action(_risque(5, montant="100000"), _JOUR)
    assert item["type_action"] == "provision_a_documenter"
    assert item["priorite"] == "moyenne"


def test_deriver_action_probable_sans_montant():
    # Probable sans chiffrage → collecter les justificatifs, moyenne.
    item = deriver_action(_risque(6, probabilite="probable"), _JOUR)
    assert item["type_action"] == "justificatif_a_collecter"
    assert item["priorite"] == "moyenne"
    assert item["exposition"] is None


def test_deriver_action_faible_point_a_discuter_basse():
    item = deriver_action(_risque(7, probabilite="faible"), _JOUR)
    assert item["type_action"] == "point_a_discuter"
    assert item["priorite"] == "basse"


def test_deriver_plan_exclut_clos_et_ordonne_par_priorite():
    risques = [
        _risque(1, probabilite="faible"),                       # basse
        _risque(2, montant="100000"),                           # moyenne
        _risque(3, montant="9000000"),                          # haute
        _risque(4, exercice=2022),                              # haute (plus ancien)
        _risque(5, statut="resolu", montant="500000"),          # exclu
        _risque(6, statut="accepte"),                           # exclu
        _risque(7, statut="en_traitement", montant="200000"),   # moyenne
    ]
    plan = deriver_plan(risques, _JOUR)
    assert [i["risque_id"] for i in plan] == [4, 3, 2, 7, 1]
    assert [i["priorite"] for i in plan] == [
        "haute", "haute", "moyenne", "moyenne", "basse",
    ]


def test_synthese_plan_compteurs_et_exposition_decimal():
    plan = deriver_plan(
        [
            _risque(1, montant="9000000"),
            _risque(2, montant="100000", penalites="0.50"),
            _risque(3, probabilite="faible"),
        ],
        _JOUR,
    )
    s = synthese_plan(plan)
    assert s["total_actions"] == 3
    assert s["par_priorite"] == {"haute": 1, "moyenne": 1, "basse": 1}
    # Somme Decimal exacte (aucun float) : 9 000 000 + 100 000.50.
    assert s["exposition_totale"] == "9100000.50"
    assert Decimal(s["exposition_totale"]) == Decimal("9100000.50")

    vide = synthese_plan([])
    assert vide["total_actions"] == 0
    assert vide["exposition_totale"] == "0"


def test_mention_consultative_explicite():
    assert "consultatif" in MENTION_NOTE
    assert "décide" in MENTION_NOTE


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

    lib = f"v-plan-actions-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="plan-actions")
    publier_version(session, lib, "plan.actions@test.ci")


def _mission_en_cours(session) -> tuple[int, int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"plan.actions.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Plan Actions {email}",
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
                "VALUES (:t, 'PM Plan Actions FICTIF', 'pm') RETURNING id"
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
    probabilite: str = "possible",
    montant: str | None = None,
    exercice: int = 2025,
    statut: str = "ouvert",
) -> int:
    with contexte_tenant(session, tenant_id):
        return int(
            session.execute(
                text(
                    "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                    "libelle, montant_estime, probabilite, statut, "
                    "exercice_origine) VALUES (:t, :c, 'TVA', :lib, :mt, "
                    ":prob, :st, :ex) RETURNING id"
                ),
                {
                    "t": tenant_id,
                    "c": contribuable_id,
                    "lib": f"Risque test {uuid.uuid4().hex[:6]}",
                    "mt": montant,
                    "prob": probabilite,
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


def test_api_plan_actions_derive_depuis_risques(session):
    tid, mid, cid, email = _mission_en_cours(session)
    rid_haut = _creer_risque(
        session, tid, cid, probabilite="probable", montant="10000000"
    )
    rid_moyen = _creer_risque(session, tid, cid, montant="150000")
    _creer_risque(session, tid, cid, statut="resolu", montant="500000")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/plan-actions", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["contribuable_id"] == cid
    assert corps["note"] == MENTION_NOTE

    par_id = {i["risque_id"]: i for i in corps["plan"]}
    # Le risque résolu est exclu du plan.
    assert set(par_id) == {rid_haut, rid_moyen}
    assert par_id[rid_haut]["type_action"] == "declaration_rectificative"
    assert par_id[rid_haut]["priorite"] == "haute"
    assert par_id[rid_moyen]["type_action"] == "provision_a_documenter"
    assert par_id[rid_moyen]["priorite"] == "moyenne"
    # Priorité haute en tête du plan.
    assert corps["plan"][0]["risque_id"] == rid_haut

    s = corps["synthese"]
    assert s["total_actions"] == 2
    assert s["par_priorite"]["haute"] == 1
    assert s["par_priorite"]["moyenne"] == 1
    assert Decimal(s["exposition_totale"]) == Decimal("10150000")


def test_api_plan_actions_sans_risque(session):
    _tid, mid, _cid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/plan-actions", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["plan"] == []
    assert corps["synthese"]["total_actions"] == 0
    assert corps["synthese"]["exposition_totale"] == "0"


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _cid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"plan.actions.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Plan Actions B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/plan-actions", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/plan-actions")
    assert r.status_code == 401, r.text
