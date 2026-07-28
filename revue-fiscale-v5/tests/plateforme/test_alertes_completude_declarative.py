"""Centre d'alertes — source complétude déclarative (périodes omises)."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.centre_alertes import (
    TYPES_ALERTE,
    alertes_depuis_completude,
    normaliser_alerte,
    synthese_alertes,
)
from backend.plateforme.completude_declarative import construire_completude

# ── Tests purs (sans DB) ───────────────────────────────────────────

JOUR = date(2026, 7, 28)

PERIODES_2025 = [f"2025-{m:02d}" for m in range(1, 13)]


def _vue(client: str, mission_id: int, completude: dict) -> dict:
    return {
        "client": client,
        "mission_id": mission_id,
        "completude": completude,
    }


def test_type_completude_dans_le_referentiel():
    assert "completude_declarative" in TYPES_ALERTE
    a = normaliser_alerte(
        {"type": "completude_declarative", "gravite": "critique"}
    )
    assert a["type"] == "completude_declarative"
    s = synthese_alertes([a])
    assert s["par_type"]["completude_declarative"] == 1


def test_lacunaire_emet_vigilance_avec_detail_par_impot():
    completude = construire_completude(
        2025, JOUR, PERIODES_2025[:10], PERIODES_2025
    )
    assert completude["synthese"]["statut_global"] == "lacunaire"
    alertes = alertes_depuis_completude(
        [_vue("SA FICTIVE", 7, completude)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["type"] == "completude_declarative"
    assert a["gravite"] == "vigilance"
    assert a["client"] == "SA FICTIVE"
    assert a["mission_id"] == 7
    assert a["echeance"] is None
    assert a["lien"] == "completude_declarative"
    assert "lacunaire" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "TVA : 2 périodes manquantes" in a["libelle"]


def test_aucune_saisie_emet_critique_les_deux_impots():
    completude = construire_completude(2025, JOUR, [], [])
    assert completude["synthese"]["statut_global"] == "aucune_saisie"
    alertes = alertes_depuis_completude(
        [_vue("SARL FICTIVE", 3, completude)]
    )
    assert len(alertes) == 1
    a = alertes[0]
    assert a["gravite"] == "critique"
    assert "aucune déclaration" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert "TVA : 12 périodes manquantes" in a["libelle"]
    assert "impôts sur salaires : 12 périodes manquantes" in a["libelle"]


def test_rien_si_complet_sans_periode_echue_ou_indisponible():
    complet = construire_completude(
        2025, JOUR, PERIODES_2025, PERIODES_2025
    )
    assert complet["synthese"]["statut_global"] == "complet"
    futur = construire_completude(2027, JOUR, [], [])
    assert futur["synthese"]["statut_global"] == "sans_periode_echue"
    indisponible = construire_completude(2025, JOUR, None, None)
    assert indisponible["disponible"] is False
    alertes = alertes_depuis_completude(
        [
            _vue("A", 1, complet),
            _vue("B", 2, futur),
            _vue("C", 3, indisponible),
        ]
    )
    assert alertes == []


def test_bloc_illisible_tolere_seul_le_bloc_lisible_compte():
    # TVA illisible (None), salaires partiels → lacunaire, détail
    # uniquement sur le bloc lisible.
    completude = construire_completude(
        2025, JOUR, None, PERIODES_2025[:6]
    )
    alertes = alertes_depuis_completude([_vue("D", 4, completude)])
    assert len(alertes) == 1
    assert "impôts sur salaires : 6 périodes manquantes" in (
        alertes[0]["libelle"]
    )
    assert "TVA" not in alertes[0]["libelle"]


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

    lib = f"v-alcomp-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="alertes complétude")
    publier_version(session, lib, "alcomp@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"alcomp.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Alcomp {email}",
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


def _saisir_declarations(
    session, tenant_id: int, mission_id: int,
    mois_tva: list[int], mois_salaires: list[int],
) -> None:
    with contexte_tenant(session, tenant_id):
        for m in mois_tva:
            session.execute(
                text(
                    "INSERT INTO declaration_tva "
                    "(tenant_id, mission_id, periode) "
                    "VALUES (:t, :m, :p)"
                ),
                {"t": tenant_id, "m": mission_id, "p": f"2025-{m:02d}"},
            )
        for m in mois_salaires:
            session.execute(
                text(
                    "INSERT INTO declaration_salaires "
                    "(tenant_id, mission_id, periode) "
                    "VALUES (:t, :m, :p)"
                ),
                {"t": tenant_id, "m": mission_id, "p": f"2025-{m:02d}"},
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
             "lib": "Classer les quittances TVA", "dc": "2020-01-15"},
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


def test_api_aucune_saisie_alerte_critique(session):
    tid, email = _cabinet(session)
    _mission_en_cours(session, tid, "PM Alcomp Vide FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    alertes = [
        a for a in corps["alertes"]
        if a["type"] == "completude_declarative"
    ]
    assert len(alertes) == 1
    a = alertes[0]
    assert a["gravite"] == "critique"
    assert a["client"] == "PM Alcomp Vide FICTIVE"
    assert "aucune déclaration" in a["libelle"]
    assert "exercice 2025" in a["libelle"]
    assert set(a) == {
        "type", "gravite", "client", "mission_id", "libelle",
        "echeance", "lien",
    }
    assert corps["synthese"]["par_type"]["completude_declarative"] == 1


def test_api_lacunaire_alerte_vigilance(session):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Alcomp Lacune FICTIVE")
    # TVA saisie sauf décembre, salaires complets → lacunaire.
    _saisir_declarations(
        session, tid, mid, list(range(1, 12)), list(range(1, 13))
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    alertes = [
        a for a in r.json()["alertes"]
        if a["type"] == "completude_declarative"
    ]
    assert len(alertes) == 1
    assert alertes[0]["gravite"] == "vigilance"
    assert "lacunaire" in alertes[0]["libelle"]
    assert "TVA : 1 période manquante" in alertes[0]["libelle"]


def test_api_complet_aucune_alerte_completude(session):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Alcomp Complet FICTIVE")
    _saisir_declarations(
        session, tid, mid, list(range(1, 13)), list(range(1, 13))
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["sources_en_echec"] == []
    assert not [
        a for a in corps["alertes"]
        if a["type"] == "completude_declarative"
    ]


def test_api_source_completude_en_echec_jamais_bloquante(
    session, monkeypatch
):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Alcomp Panne FICTIVE")
    _point_en_retard(session, tid, mid)
    session.commit()

    import backend.plateforme.completude_declarative as cd

    def _boom(*args, **kwargs):
        raise RuntimeError("complétude déclarative indisponible")

    monkeypatch.setattr(cd, "completude_declarative_mission", _boom)

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # La source en échec est signalée, les autres alertes restent là.
    assert "completude_declarative" in corps["sources_en_echec"]
    assert any(
        a["type"] == "point_convenu" for a in corps["alertes"]
    )
    assert corps["note"]
