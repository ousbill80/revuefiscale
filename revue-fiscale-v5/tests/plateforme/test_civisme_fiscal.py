"""Civisme fiscal — rapprochement échéancier / pièces collectées."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from backend.plateforme.civisme_fiscal import (
    elements_depuis_pieces,
    rapprocher,
    synthese_rapprochement,
)
from backend.plateforme.echeancier_fiscal import construire_echeancier

# ── Tests purs (sans DB, dates figées) ─────────────────────────────


def _echeance(impot: str, periode: str, date_limite: str) -> dict:
    return {
        "impot": impot,
        "obligation": f"Obligation {impot}",
        "periode": periode,
        "date_limite": date_limite,
    }


def test_rapprocher_couverte_manquante_en_attente():
    echeances = [
        _echeance("TVA", "janvier 2025", "2025-02-15"),
        _echeance("TVA", "février 2025", "2025-03-15"),
        _echeance("États financiers", "exercice 2025", "2026-04-30"),
    ]
    elements = [
        # Impôt comparé sans casse ni accents ; période exacte.
        {"impot": "tva", "periode": "janvier 2025", "source": "data room : d.pdf"},
        # Sans période : couvre toutes les périodes de l'impôt.
        {"impot": "etats financiers", "periode": None, "source": "data room : ef.pdf"},
    ]

    r = rapprocher(echeances, elements, date(2026, 3, 1))
    assert [i["statut"] for i in r] == ["couverte", "manquante", "couverte"]
    assert r[0]["source"] == "data room : d.pdf"
    assert r[1]["source"] is None
    assert r[2]["source"] == "data room : ef.pdf"
    assert r[1]["date_limite"] == "2025-03-15"

    # Même échéancier plus tôt : la TVA de février n'est pas encore due.
    r2 = rapprocher(echeances, elements, date(2025, 3, 1))
    assert [i["statut"] for i in r2] == ["couverte", "en_attente", "couverte"]


def test_rapprocher_element_sans_periode_couvre_tout_l_impot():
    echeances = construire_echeancier(2025, "reel")
    elements = [{"impot": "TVA", "periode": None, "source": "s"}]
    r = rapprocher(echeances, elements, date(2026, 7, 27))
    tva = [i for i in r if i["impot"] == "TVA"]
    assert len(tva) == 12
    assert all(i["statut"] == "couverte" for i in tva)
    # Les autres impôts ne sont pas couverts par cet élément.
    assert all(
        i["statut"] != "couverte" for i in r if i["impot"] != "TVA"
    )


def test_synthese_taux_civisme_decimal():
    r = [
        {"statut": "couverte", "date_limite": "2025-02-15"},
        {"statut": "couverte", "date_limite": "2025-03-15"},
        {"statut": "manquante", "date_limite": "2025-04-15"},
        {"statut": "en_attente", "date_limite": "2099-01-15"},
    ]
    s = synthese_rapprochement(r)
    assert s["couvertes"] == 2
    assert s["manquantes"] == 1
    assert s["en_attente"] == 1
    # 2 / 3 × 100 arrondi à 0.01 — les « en_attente » sont hors taux.
    assert s["taux_civisme"] == "66.67"
    assert Decimal(s["taux_civisme"]) == Decimal("66.67")

    # Rien d'exigible → rien à reprocher.
    assert synthese_rapprochement([])["taux_civisme"] == "100.00"


def test_elements_depuis_pieces_correspondance_deterministe():
    pieces = [
        {"type_piece": "etats_financiers", "nom_fichier": "EF_2025.pdf"},
        {"type_piece": "balance", "nom_fichier": "balance_2025.csv"},
        {"type_piece": "fec", "nom_fichier": "fec_2025.txt"},
        {
            "type_piece": "autre",
            "nom_fichier": "Déclaration TVA janvier 2025.pdf",
        },
        {"type_piece": "autre", "nom_fichier": "notes internes.pdf"},
    ]
    elements = elements_depuis_pieces(pieces, 2025)
    # Balance/FEC (comptables) et notes (aucun impôt reconnu) : ignorés.
    assert len(elements) == 2
    assert elements[0] == {
        "impot": "États financiers",
        "periode": None,
        "source": "data room : EF_2025.pdf",
    }
    assert elements[1]["impot"] == "TVA"
    assert elements[1]["periode"] == "janvier 2025"
    assert "Déclaration TVA janvier 2025.pdf" in elements[1]["source"]


def test_elements_depuis_pieces_autre_sans_mois_couvre_l_impot():
    elements = elements_depuis_pieces(
        [{"type_piece": "autre", "nom_fichier": "patente_2025.pdf"}], 2025
    )
    assert elements == [
        {
            "impot": "Patente",
            "periode": None,
            "source": "data room : patente_2025.pdf",
        }
    ]


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

    lib = f"v-civisme-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="civisme-fiscal")
    publier_version(session, lib, "civisme@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"civisme.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Civisme {email}",
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
                "VALUES (:t, 'PM Civisme FICTIF', 'pm') RETURNING id"
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
    return r.tenant_id, int(mid), email


def _deposer_piece(
    session, tenant_id: int, mission_id: int, *, type_piece: str, nom: str
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO piece_mission (tenant_id, mission_id, "
                "type_piece, role, nom_fichier, chemin_stockage) "
                "VALUES (:t, :m, :tp, 'annexe', :n, :c)"
            ),
            {
                "t": tenant_id,
                "m": mission_id,
                "tp": type_piece,
                "n": nom,
                "c": f"tests/civisme/{uuid.uuid4().hex}",
            },
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


def test_api_civisme_rapprochement_pieces_data_room(session):
    tid, mid, email = _mission_en_cours(session)
    _deposer_piece(
        session, tid, mid, type_piece="etats_financiers", nom="EF_2025.pdf"
    )
    _deposer_piece(
        session, tid, mid, type_piece="autre", nom="declaration_patente_2025.pdf"
    )
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/civisme-fiscal", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["aujourd_hui"]
    assert "note" in corps

    par_impot = {}
    for item in corps["rapprochement"]:
        par_impot.setdefault(item["impot"], []).append(item)
    # États financiers : couverts par la pièce EF (quel que soit le jour).
    ef = par_impot["États financiers"]
    assert all(i["statut"] == "couverte" for i in ef)
    assert "EF_2025.pdf" in ef[0]["source"]
    # Patente : couverte par la pièce « autre » via son nom de fichier.
    assert all(i["statut"] == "couverte" for i in par_impot["Patente"])
    # TVA janvier 2025 (limite 15/02/2025, passée) : aucune pièce → manquante.
    tva_janvier = next(
        i for i in par_impot["TVA"] if i["periode"] == "janvier 2025"
    )
    assert tva_janvier["statut"] == "manquante"
    assert tva_janvier["source"] is None

    s = corps["synthese"]
    assert s["couvertes"] >= 2
    assert s["manquantes"] >= 1
    assert s["couvertes"] + s["en_attente"] + s["manquantes"] == len(
        corps["rapprochement"]
    )
    assert Decimal("0") <= Decimal(s["taux_civisme"]) <= Decimal("100")


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"civisme.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Civisme B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/civisme-fiscal", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/civisme-fiscal")
    assert r.status_code == 401, r.text
