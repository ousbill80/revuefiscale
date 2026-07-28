"""Historique pluriannuel du client — exposition fiscale et civisme."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.historique_client import (
    CIVISME_AMELIORATION,
    CIVISME_DEGRADATION,
    EXPOSITION_BAISSE,
    EXPOSITION_HAUSSE,
    MENTION_NOTE,
    PLAFOND_EXERCICES,
    TENDANCE_STABLE,
    consolider_exercices,
    qualifier_civisme,
    qualifier_exposition,
    tendance_globale,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _entree(
    mission_id: int,
    exercice: int,
    exposition: str = "0",
    taux: str | None = None,
) -> dict:
    return {
        "mission_id": mission_id,
        "exercice": exercice,
        "statut": "cadrage",
        "exposition_totale": exposition,
        "nb_risques_ouverts": 0,
        "taux_civisme": taux,
    }


def test_consolider_exercices_tri_croissant():
    exercices = consolider_exercices(
        [_entree(30, 2025), _entree(10, 2023), _entree(20, 2024)]
    )
    assert [e["exercice"] for e in exercices] == [2023, 2024, 2025]
    assert consolider_exercices([]) == []


def test_consolider_exercices_dedoublonnage_mission_max():
    # Deux missions sur 2024 : la plus récente (id max) représente
    # l'exercice, quel que soit l'ordre d'arrivée.
    exercices = consolider_exercices(
        [
            _entree(7, 2024, exposition="100"),
            _entree(9, 2024, exposition="200"),
            _entree(8, 2024, exposition="150"),
            _entree(3, 2023),
        ]
    )
    assert [e["exercice"] for e in exercices] == [2023, 2024]
    assert exercices[1]["mission_id"] == 9
    assert exercices[1]["exposition_totale"] == "200"


def test_consolider_exercices_plafond():
    entrees = [_entree(i, 2000 + i) for i in range(1, 15)]
    exercices = consolider_exercices(entrees)
    assert len(exercices) == PLAFOND_EXERCICES
    # Les exercices les plus récents sont conservés.
    assert exercices[0]["exercice"] == 2005
    assert exercices[-1]["exercice"] == 2014


def test_qualifier_exposition_seuil_1_pct():
    assert qualifier_exposition(
        Decimal("1000000"), Decimal("1200000")
    ) == EXPOSITION_HAUSSE
    assert qualifier_exposition(
        Decimal("1000000"), Decimal("800000")
    ) == EXPOSITION_BAISSE
    # ±1 % : stable (inclus), au-delà : tendance.
    assert qualifier_exposition(
        Decimal("1000000"), Decimal("1010000")
    ) == TENDANCE_STABLE
    assert qualifier_exposition(
        Decimal("1000000"), Decimal("990000")
    ) == TENDANCE_STABLE
    assert qualifier_exposition(
        Decimal("1000000"), Decimal("1010001")
    ) == EXPOSITION_HAUSSE
    # Première exposition nulle : toute exposition finale = hausse.
    assert qualifier_exposition(Decimal("0"), Decimal("1")) == (
        EXPOSITION_HAUSSE
    )
    assert qualifier_exposition(Decimal("0"), Decimal("0")) == (
        TENDANCE_STABLE
    )


def test_qualifier_civisme_seuil_1_point():
    assert qualifier_civisme(
        Decimal("60.00"), Decimal("80.00")
    ) == CIVISME_AMELIORATION
    assert qualifier_civisme(
        Decimal("80.00"), Decimal("60.00")
    ) == CIVISME_DEGRADATION
    # ±1 point : stable.
    assert qualifier_civisme(
        Decimal("80.00"), Decimal("80.99")
    ) == TENDANCE_STABLE
    assert qualifier_civisme(
        Decimal("80.00"), Decimal("79.01")
    ) == TENDANCE_STABLE
    # Taux indisponible d'un côté : pas de tendance.
    assert qualifier_civisme(None, Decimal("80.00")) is None
    assert qualifier_civisme(Decimal("80.00"), None) is None


def test_tendance_globale_premier_dernier():
    exercices = consolider_exercices(
        [
            _entree(1, 2022, exposition="2000000", taux="50.00"),
            _entree(2, 2023, exposition="1500000", taux=None),
            _entree(3, 2024, exposition="900000", taux="75.00"),
        ]
    )
    t = tendance_globale(exercices)
    assert t == {
        "exercice_premier": 2022,
        "exercice_dernier": 2024,
        "exposition": EXPOSITION_BAISSE,
        "civisme": CIVISME_AMELIORATION,
    }


def test_tendance_globale_moins_de_deux_exercices():
    assert tendance_globale([]) == {
        "exercice_premier": None,
        "exercice_dernier": None,
        "exposition": None,
        "civisme": None,
    }
    t = tendance_globale([_entree(1, 2024, exposition="100")])
    assert t["exposition"] is None
    assert t["civisme"] is None


# ── Tests DB / API ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.historique_client import (  # noqa: E402
    ErreurHistoriqueClient,
    historique_client,
)
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-histcli-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="historique-client")
    publier_version(session, lib, "histcli@test.ci")


def _cabinet(session, prefixe: str) -> tuple[int, str]:
    _assurer_version(session)
    email = f"{prefixe}.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Histcli {email}",
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
    exercice: int = 2024,
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
                    "lib": f"Risque histcli {uuid.uuid4().hex[:6]}",
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


def test_historique_trois_exercices(session):
    """Trajectoire : exposition par mission, clos exclus, tendance."""
    tid, _email = _cabinet(session, "histcli.trois")
    cid = _contribuable(session, tid, "SA Histcli FICTIVE")
    mid_2022 = _mission(session, tid, cid, 2022)
    mid_2023 = _mission(session, tid, cid, 2023)
    mid_2024 = _mission(session, tid, cid, 2024)
    # 2022 : 2 000 000 ouvert + un résolu (exclu de l'exposition).
    _creer_risque(
        session, tid, cid, mid_2022, montant="2000000", exercice=2022
    )
    _creer_risque(
        session,
        tid,
        cid,
        mid_2022,
        montant="9999999",
        statut="resolu",
        exercice=2022,
    )
    # 2023 : rien. 2024 : 800 000 + 100 000 de pénalités.
    _creer_risque(
        session,
        tid,
        cid,
        mid_2024,
        montant="800000",
        penalites="100000",
        exercice=2024,
    )
    session.commit()

    out = historique_client(session, tid, cid)
    assert out["contribuable_id"] == cid
    assert out["denomination"] == "SA Histcli FICTIVE"
    assert out["note"] == MENTION_NOTE
    assert [e["exercice"] for e in out["exercices"]] == [2022, 2023, 2024]
    e22, e23, e24 = out["exercices"]
    assert e22["mission_id"] == mid_2022
    assert e22["nb_risques_ouverts"] == 1
    assert Decimal(e22["exposition_totale"]) == Decimal("2000000")
    assert e23["mission_id"] == mid_2023
    assert e23["nb_risques_ouverts"] == 0
    assert Decimal(e23["exposition_totale"]) == Decimal("0")
    assert e24["nb_risques_ouverts"] == 1
    assert Decimal(e24["exposition_totale"]) == Decimal("900000")
    # Missions exploitables (régime réel) : taux str Decimal — sans
    # pièce collectée, aucune échéance passée n'est couverte.
    for e in out["exercices"]:
        assert e["taux_civisme"] is not None
        assert Decimal(e["taux_civisme"]) == Decimal("0.00")
    # 2 000 000 → 900 000 : baisse ; civisme 0.00 → 0.00 : stable.
    assert out["tendance"] == {
        "exercice_premier": 2022,
        "exercice_dernier": 2024,
        "exposition": EXPOSITION_BAISSE,
        "civisme": TENDANCE_STABLE,
    }


def test_historique_deduplique_exercice_et_introuvable(session):
    """Deux missions sur le même exercice : la plus récente compte."""
    tid, _email = _cabinet(session, "histcli.dedup")
    cid = _contribuable(session, tid, "PM Dedup FICTIVE")
    mid_a = _mission(session, tid, cid, 2024)
    # La création interdit deux missions ACTIVES sur le même exercice :
    # la première est clôturée avant d'ouvrir la seconde (reprise).
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid_a},
        )
    mid_b = _mission(session, tid, cid, 2024)
    _creer_risque(session, tid, cid, mid_a, montant="111111")
    _creer_risque(session, tid, cid, mid_b, montant="500000")
    session.commit()

    out = historique_client(session, tid, cid)
    assert len(out["exercices"]) == 1
    seul = out["exercices"][0]
    assert seul["mission_id"] == max(mid_a, mid_b)
    assert Decimal(seul["exposition_totale"]) == Decimal("500000")
    # Un seul exercice : pas de trajectoire.
    assert out["tendance"]["exposition"] is None
    assert out["tendance"]["civisme"] is None

    with pytest.raises(ErreurHistoriqueClient):
        historique_client(session, tid, 999_999_999)


def test_api_historique_pluriannuel(session):
    tid, email = _cabinet(session, "histcli.api")
    cid = _contribuable(session, tid, "PM API Histcli FICTIVE")
    mid_2023 = _mission(session, tid, cid, 2023)
    mid_2024 = _mission(session, tid, cid, 2024)
    _creer_risque(
        session, tid, cid, mid_2023, montant="200000", exercice=2023
    )
    _creer_risque(
        session, tid, cid, mid_2024, montant="600000", exercice=2024
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(
        f"/api/v1/contribuables/{cid}/historique-pluriannuel", headers=h
    )
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["contribuable_id"] == cid
    assert [e["exercice"] for e in corps["exercices"]] == [2023, 2024]
    assert corps["tendance"]["exposition"] == EXPOSITION_HAUSSE
    assert corps["note"] == MENTION_NOTE

    # Journal de consultation — sans mission_id, action dédiée.
    with contexte_tenant(session, tid):
        journal = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'consultation_historique_client' "
                "ORDER BY id DESC LIMIT 1"
            ),
        ).mappings().one_or_none()
    assert journal is not None
    assert journal["charge_utile"]["contribuable_id"] == cid
    assert journal["charge_utile"]["nb_exercices"] == 2
    assert journal["charge_utile"]["tendance_exposition"] == (
        EXPOSITION_HAUSSE
    )


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session, "histcli.a")
    cid_a = _contribuable(session, tid_a, "PM Isolée Histcli FICTIVE")
    _tid_b, email_b = _cabinet(session, "histcli.b")
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(
        f"/api/v1/contribuables/{cid_a}/historique-pluriannuel", headers=h
    )
    assert r.status_code == 404, r.text


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/contribuables/1/historique-pluriannuel")
    assert r.status_code == 401, r.text
