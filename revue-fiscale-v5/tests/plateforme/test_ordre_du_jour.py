"""Ordre du jour de la réunion de restitution — sections + API."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.ordre_du_jour import (
    A_COMPLETER_EN_SEANCE,
    MENTION_ORDRE_DU_JOUR,
    NB_ECHEANCES_A_VENIR,
    NB_TOP_RISQUES,
    construire_ordre_du_jour,
    section_actions,
    section_civisme,
    section_echeances,
    section_introduction,
    section_questions,
    section_risques,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _risque(id_: int, montant: str | None, penalites: str | None = None) -> dict:
    return {
        "id": id_,
        "libelle": f"Risque {id_}",
        "impot": "tva",
        "statut": "ouvert",
        "probabilite": "probable",
        "montant_estime": montant,
        "penalites_estimees": penalites,
    }


def test_section_introduction_exercice_et_regime():
    lignes = section_introduction(2025, "reel_simplifie")
    assert lignes[0].startswith("1. Introduction")
    assert "Exercice revu : 2025" in lignes[1]
    assert "réel simplifié" in lignes[1]


def test_section_introduction_sans_donnees_a_completer():
    lignes = section_introduction(None, None)
    assert A_COMPLETER_EN_SEANCE in lignes[1]


def test_section_risques_nombre_exposition_et_top():
    risques = [_risque(i, str(i * 1000)) for i in range(1, 8)]
    lignes = section_risques(risques)
    assert lignes[0].startswith("2. Synthèse des risques")
    assert "Nombre de risques identifiés : 7" in lignes[1]
    # Exposition totale = 1000+…+7000 = 28000 (str Decimal, FCFA).
    assert "Exposition totale estimée : 28000 FCFA." in lignes[2]
    # Top 5 par exposition décroissante : 7000 en tête.
    assert f"top {NB_TOP_RISQUES}" in lignes[3]
    assert "1) Risque 7 (TVA) — 7000 FCFA." in lignes[4]
    # 7 risques → seulement 5 listés (en-tête + 3 lignes + top 5).
    assert len(lignes) == 4 + NB_TOP_RISQUES


def test_section_risques_exposition_non_chiffree():
    lignes = section_risques([_risque(1, None)])
    assert any("exposition non chiffrée" in l for l in lignes)
    assert any("dont 0 à exposition chiffrée" in l for l in lignes)


def test_section_risques_vide_a_completer():
    lignes = section_risques([])
    assert "Aucun risque enregistré" in lignes[1]
    assert A_COMPLETER_EN_SEANCE in lignes[1]


def test_section_actions_compteurs_et_notes():
    plan = [
        {"action": "Action A", "decision": "retenue", "decision_note": "ok"},
        {"action": "Action B", "decision": "ecartee", "decision_note": None},
        {"action": "Action C", "decision": None, "decision_note": None},
    ]
    lignes = section_actions(plan)
    assert lignes[0].startswith("3. Actions proposées")
    assert (
        "3 action(s) — 1 retenue(s), 1 écartée(s), 0 faite(s), "
        "1 sans décision." in lignes[1]
    )
    assert "   - Action A — décision : retenue (note : ok)." in lignes
    assert "   - Action B — décision : écartée." in lignes


def test_section_actions_vide_et_sans_decision():
    assert A_COMPLETER_EN_SEANCE in section_actions([])[1]
    lignes = section_actions([{"action": "X", "decision": None}])
    assert any(A_COMPLETER_EN_SEANCE in l for l in lignes)


def test_section_civisme_taux_et_manquantes():
    lignes = section_civisme(
        {
            "taux_civisme": "66.67",
            "couvertes": 2,
            "manquantes": 1,
            "en_attente": 3,
        }
    )
    assert lignes[0].startswith("4. Civisme déclaratif")
    assert "66.67 %" in lignes[1]
    assert "1 manquante(s)" in lignes[1]
    assert any("à vérifier avec le" in l for l in lignes)
    # Indisponible → à compléter en séance.
    assert A_COMPLETER_EN_SEANCE in section_civisme(None)[1]


def test_section_echeances_trois_prochaines_a_venir():
    jour = date(2026, 1, 10)
    echeances = [
        {
            "impot": "TVA",
            "obligation": f"Déclaration {i}",
            "periode": f"P{i}",
            "date_limite": f"2026-0{i}-15",
        }
        for i in range(1, 6)
    ]
    lignes = section_echeances(echeances, jour)
    assert lignes[0].startswith("5. Prochaines échéances")
    # 5 échéances >= 10/01 → seules les 3 premières sont retenues.
    assert len(lignes) == 1 + NB_ECHEANCES_A_VENIR
    assert "15/01/2026 : TVA — Déclaration 1 (P1)." in lignes[1]
    # Passées uniquement → mention à compléter.
    vide = section_echeances(echeances, date(2027, 1, 1))
    assert A_COMPLETER_EN_SEANCE in vide[1]


def test_section_questions_diverses():
    lignes = section_questions()
    assert lignes[0] == "6. Questions diverses"
    assert A_COMPLETER_EN_SEANCE in lignes[1]


def test_construire_ordre_du_jour_entete_sections_et_mention():
    texte = construire_ordre_du_jour(
        {
            "cabinet": "Cabinet Fictif",
            "contribuable": "PM Démo",
            "exercice": 2025,
            "regime": "reel",
            "aujourd_hui": date(2026, 7, 27),
            "risques": [_risque(1, "5000")],
            "plan": [],
            "civisme": None,
            "echeances": [],
        }
    )
    assert texte.startswith("ORDRE DU JOUR — RÉUNION DE RESTITUTION")
    assert "Cabinet : CABINET FICTIF" in texte
    assert "Client : PM Démo" in texte
    assert "exercice 2025" in texte
    assert "Date d'édition : 27/07/2026" in texte
    for numero in range(1, 7):
        assert f"\n{numero}. " in texte, numero
    # Pied : mention consultative (document de travail, pas un avis).
    assert texte.rstrip().endswith(MENTION_ORDRE_DU_JOUR)
    assert "ne constitue pas un avis fiscal" in texte


def test_construire_ordre_du_jour_sans_risques_mention_a_completer():
    texte = construire_ordre_du_jour(
        {
            "cabinet": None,
            "contribuable": None,
            "exercice": None,
            "regime": None,
            "aujourd_hui": date(2026, 7, 27),
            "risques": [],
            "plan": [],
            "civisme": None,
            "echeances": [],
        }
    )
    assert "Aucun risque enregistré" in texte
    assert A_COMPLETER_EN_SEANCE in texte
    assert MENTION_ORDRE_DU_JOUR in texte


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

    lib = f"v-odj-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="ordre-du-jour")
    publier_version(session, lib, "odj@test.ci")


def _mission_en_cours(session) -> tuple[int, int, str]:
    from backend.plateforme.missions import creer_mission

    _assurer_version(session)
    email = f"odj.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab ODJ {email}",
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
                "VALUES (:t, 'PM ODJ FICTIF', 'pm') RETURNING id"
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
        session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, "
                "origine_mission_id, impot, libelle, montant_estime, "
                "penalites_estimees, probabilite, statut, exercice_origine) "
                "VALUES (:t, :c, :m, 'tva', 'TVA collectée non reversée', "
                "1000000, 250000, 'probable', 'ouvert', 2025)"
            ),
            {"t": r.tenant_id, "c": int(cid), "m": int(mid)},
        )
    return r.tenant_id, int(mid), email


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


def test_api_ordre_du_jour_txt_contenu(session):
    _tid, mid, email = _mission_en_cours(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(f"/api/v1/missions/{mid}/ordre-du-jour.txt", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    assert "charset=utf-8" in r.headers["content-type"]
    assert (
        r.headers["content-disposition"]
        == 'attachment; filename="ordre_du_jour.txt"'
    )
    texte = r.text
    assert texte.startswith("ORDRE DU JOUR — RÉUNION DE RESTITUTION")
    assert "Client : PM ODJ FICTIF" in texte
    assert "exercice 2025" in texte
    assert "Nombre de risques identifiés : 1" in texte
    # Exposition = montant + pénalités = 1 250 000 (NUMERIC(18,2)).
    assert "Exposition totale estimée : 1250000.00 FCFA." in texte
    assert "TVA collectée non reversée (TVA) — 1250000.00 FCFA." in texte
    assert "4. Civisme déclaratif" in texte
    assert "6. Questions diverses" in texte
    assert MENTION_ORDRE_DU_JOUR in texte

    # Téléchargement journalisé — visible dans la chronologie.
    chrono = client.get(f"/api/v1/missions/{mid}/chronologie", headers=h)
    assert chrono.status_code == 200, chrono.text
    actions = [e["action"] for e in chrono.json()["evenements"]]
    assert "telechargement_ordre_du_jour" in actions


def test_api_404_cross_tenant(session):
    _tid_a, mid_a, _ = _mission_en_cours(session)

    _assurer_version(session)
    email_b = f"odj.b.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab ODJ B {email_b}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email_b,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()

    client, h = _client_connecte(email_b)
    r = client.get(f"/api/v1/missions/{mid_a}/ordre-du-jour.txt", headers=h)
    assert r.status_code == 404, r.text
    assert "introuvable" in r.json()["detail"]


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/api/v1/missions/1/ordre-du-jour.txt")
    assert r.status_code == 401, r.text
