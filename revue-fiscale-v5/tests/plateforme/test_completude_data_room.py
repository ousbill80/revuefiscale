"""Complétude de la data room — socle documentaire de la revue."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.plateforme.completude_data_room import (
    MAX_EXEMPLES,
    evaluer_completude,
    referentiel_attendus,
    synthese_completude,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _p(type_piece: str, nom: str) -> dict:
    return {"type_piece": type_piece, "nom_fichier": nom}


def test_referentiel_par_regime():
    reel = referentiel_attendus("reel")
    assert [a["code"] for a in reel] == [
        "etats_financiers",
        "balance_generale",
        "grand_livre_ou_fec",
        "declarations_fiscales",
    ]
    # Essentielles au réel : EF, balance, grand livre/FEC — pas les
    # déclarations (le détail relève du civisme fiscal).
    assert [a["essentielle"] for a in reel] == [True, True, True, False]
    assert referentiel_attendus("reel_simplifie") == reel

    ime = referentiel_attendus("ime")
    assert [a["code"] for a in ime] == [
        "etats_financiers",
        "declarations_simplifiees",
        "journal_recettes_depenses",
    ]
    tee = referentiel_attendus("tee")
    assert [a["code"] for a in tee] == [
        "declarations_simplifiees",
        "journal_recettes_depenses",
    ]
    # Régime inconnu ou vide → référentiel le plus complet (prudent).
    assert referentiel_attendus(None) == reel
    assert referentiel_attendus("exotique") == reel


def test_evaluer_completude_reel_presences_et_exemples():
    pieces = [
        _p("etats_financiers", "EF_2025.pdf"),
        _p("balance", "balance_2025.csv"),
        _p("fec", "fec_2025.txt"),
        # Déclaration reconnue par tokens du nom (type « autre »).
        _p("autre", "Déclaration TVA janvier 2025.pdf"),
        # « autre » sans token déclaratif : ne satisfait rien.
        _p("autre", "notes internes.pdf"),
    ]
    evaluation = evaluer_completude("reel", pieces)
    par_code = {e["code"]: e for e in evaluation}
    assert par_code["etats_financiers"]["presente"] is True
    assert par_code["etats_financiers"]["exemples"] == ["EF_2025.pdf"]
    assert par_code["balance_generale"]["nb_pieces"] == 1
    # FEC accepté au titre « grand livre ou FEC ».
    assert par_code["grand_livre_ou_fec"]["presente"] is True
    d = par_code["declarations_fiscales"]
    assert d["presente"] is True and d["nb_pieces"] == 1
    assert d["exemples"] == ["Déclaration TVA janvier 2025.pdf"]


def test_evaluer_completude_manquantes_et_taux():
    evaluation = evaluer_completude(
        "reel", [_p("etats_financiers", "EF.pdf")]
    )
    s = synthese_completude(evaluation)
    assert s["attendues"] == 4
    assert s["presentes"] == 1
    assert s["essentielles_manquantes"] == 2
    # 1 essentielle présente sur 3 → 33.33.
    assert s["taux_completude"] == "33.33"
    assert Decimal(s["taux_completude"]) == Decimal("33.33")

    complete = evaluer_completude(
        "reel",
        [
            _p("etats_financiers", "EF.pdf"),
            _p("balance", "bal.csv"),
            _p("grand_livre", "gl.csv"),
        ],
    )
    assert synthese_completude(complete)["taux_completude"] == "100.00"
    assert synthese_completude(complete)["essentielles_manquantes"] == 0


def test_evaluer_completude_exemples_plafonnes():
    pieces = [_p("balance", f"balance_{i}.csv") for i in range(6)]
    evaluation = evaluer_completude("reel", pieces)
    b = next(e for e in evaluation if e["code"] == "balance_generale")
    assert b["nb_pieces"] == 6
    assert len(b["exemples"]) == MAX_EXEMPLES == 3
    assert b["exemples"][0] == "balance_0.csv"


def test_evaluer_completude_tee_declarations_essentielles():
    # TEE sans aucune pièce : la déclaration simplifiée (essentielle)
    # manque ; le journal (facultatif) ne pèse pas sur le taux.
    s = synthese_completude(evaluer_completude("tee", []))
    assert s == {
        "attendues": 2,
        "presentes": 0,
        "essentielles_manquantes": 1,
        "taux_completude": "0.00",
    }
    avec = evaluer_completude(
        "tee", [_p("autre", "declaration_tee_janvier_2025.pdf")]
    )
    assert synthese_completude(avec)["taux_completude"] == "100.00"


def test_synthese_sans_essentielle_100():
    # Aucune essentielle attendue → rien d'indispensable : 100.00.
    assert synthese_completude(
        [
            {
                "code": "x",
                "libelle": "X",
                "essentielle": False,
                "presente": False,
                "nb_pieces": 0,
                "exemples": [],
            }
        ]
    )["taux_completude"] == "100.00"


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

    lib = f"v-compdr-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="completude-data-room")
    publier_version(session, lib, "compdr@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"compdr.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Compdr {email}",
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
                "VALUES (:t, 'PM Compdr FICTIF', 'pm') RETURNING id"
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
                "c": f"tests/compdr/{uuid.uuid4().hex}",
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


def test_api_completude_pieces_data_room(session):
    tid, mid, email = _mission_en_cours(session)
    _deposer_piece(
        session, tid, mid, type_piece="etats_financiers", nom="EF_2025.pdf"
    )
    _deposer_piece(session, tid, mid, type_piece="balance", nom="bal_2025.csv")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/completude-data-room", headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["regime"] == "reel"
    assert "note" in corps

    par_code = {a["code"]: a for a in corps["attendus"]}
    assert par_code["etats_financiers"]["presente"] is True
    assert par_code["etats_financiers"]["exemples"] == ["EF_2025.pdf"]
    assert par_code["balance_generale"]["presente"] is True
    assert par_code["grand_livre_ou_fec"]["presente"] is False

    s = corps["synthese"]
    assert s["attendues"] == 4
    assert s["presentes"] == 2
    assert s["essentielles_manquantes"] == 1
    # 2 essentielles présentes sur 3.
    assert s["taux_completude"] == "66.67"

    # Consultation journalisée avec la synthèse en charge utile.
    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'consultation_completude_data_room'"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(n) >= 1


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"compdr.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Compdr B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/completude-data-room", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/completude-data-room")
    assert r.status_code == 401, r.text
