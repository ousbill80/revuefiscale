"""Projet de lettre de relance déclarative — rendu pur et route."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from backend.plateforme.relance_declarative import (
    EN_TETE_RELANCE,
    MENTION_DECLARATIONS_FOI,
    NOTE_PROJET_RELANCE,
    construire_lettre,
    periode_fr,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _mission(**surcharge) -> dict:
    base = {
        "client": "SA FICTIVE",
        "mission_id": 9,
        "exercice": 2025,
        "tva": {
            "disponible": True,
            "saisies": 10,
            "attendues": 12,
            "manquantes": ["2025-11", "2025-12"],
        },
        "salaires": {
            "disponible": True,
            "saisies": 11,
            "attendues": 12,
            "manquantes": ["2025-12"],
        },
        "statut": "a_completer",
    }
    base.update(surcharge)
    return base


def _contexte(**surcharge) -> dict:
    base = {
        "denomination": "SA FICTIVE",
        "aujourd_hui": date(2026, 7, 28),
        "missions": [_mission()],
    }
    base.update(surcharge)
    return base


def test_lettre_en_tete_date_et_destinataire():
    texte = construire_lettre(_contexte())
    assert texte.startswith(EN_TETE_RELANCE)
    assert "PROJET DE LETTRE — RELANCE DÉCLARATIVE" in texte
    assert "Le 28/07/2026" in texte
    assert "À l'attention de la Direction de SA FICTIVE" in texte


def test_lettre_corps_courtois_et_demande_de_transmission():
    texte = construire_lettre(_contexte())
    # Formulation de service : le cabinet ORGANISE la collecte.
    assert "afin de compléter notre revue" in texte
    assert "nous vous remercions" in texte
    assert "à votre meilleure convenance" in texte


def test_lettre_periodes_tva_et_salaires_par_exercice():
    texte = construire_lettre(_contexte())
    assert "Exercice 2025 (mission #9) :" in texte
    assert "  - TVA : novembre 2025, décembre 2025" in texte
    assert "  - Impôts sur salaires : décembre 2025" in texte


def test_lettre_plusieurs_exercices_listes():
    contexte = _contexte(missions=[
        _mission(),
        _mission(
            mission_id=4,
            exercice=2024,
            tva={"disponible": True, "saisies": 11, "attendues": 12,
                 "manquantes": ["2024-03"]},
            salaires={"disponible": True, "saisies": 12, "attendues": 12,
                      "manquantes": []},
        ),
    ])
    texte = construire_lettre(contexte)
    assert "Exercice 2025 (mission #9) :" in texte
    assert "Exercice 2024 (mission #4) :" in texte
    assert "  - TVA : mars 2024" in texte
    # Bloc salaires complet sur 2024 : la ligne salaires n'y figure pas.
    bloc_2024 = texte.split("Exercice 2024 (mission #4) :")[1]
    assert "Impôts sur salaires" not in bloc_2024.split("\n\n")[0]


def test_lettre_ton_non_accusatoire():
    texte = construire_lettre(_contexte()).lower()
    for mot in ("manquement", "défaillance", "négligence", "retard",
                "mise en demeure", "sanction", "faute"):
        assert mot not in texte


def test_lettre_rappel_declarations_deposees_font_foi():
    texte = construire_lettre(_contexte())
    assert MENTION_DECLARATIONS_FOI in texte
    assert "font foi" in MENTION_DECLARATIONS_FOI


def test_lettre_note_projet_humain_decide_sans_envoi_automatique():
    texte = construire_lettre(_contexte())
    assert texte.rstrip().endswith(NOTE_PROJET_RELANCE)
    assert "PROJET" in NOTE_PROJET_RELANCE
    assert "l'expert-comptable avant tout envoi" in NOTE_PROJET_RELANCE
    assert "l'humain décide" in NOTE_PROJET_RELANCE
    assert "Aucun envoi automatique" in NOTE_PROJET_RELANCE


def test_periode_fr_mois_francais_et_brut_si_illisible():
    assert periode_fr("2025-01") == "janvier 2025"
    assert periode_fr("2024-12") == "décembre 2024"
    # Illisible : restitué tel quel, jamais bloquant.
    assert periode_fr("2025-13") == "2025-13"
    assert periode_fr(None) == ""


def test_lettre_mission_sans_periode_defensive():
    # Défensif : entrée sans manquante (ne devrait pas arriver via la
    # route qui filtre a_completer) → mention neutre, document valide.
    contexte = _contexte(missions=[_mission(
        tva={"disponible": True, "saisies": 12, "attendues": 12,
             "manquantes": []},
        salaires={"disponible": True, "saisies": 12, "attendues": 12,
                  "manquantes": []},
    )])
    texte = construire_lettre(contexte)
    assert "  - Aucune période à transmettre." in texte


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _url(contribuable_id: int) -> str:
    return (
        f"/api/v1/contribuables/{contribuable_id}/relance-declarative.txt"
    )


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-reldec-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="relance declarative")
    publier_version(session, lib, "reldec@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"reldec.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Relance Declarative {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _client_avec_mission(
    session, tenant_id: int, nom: str, exercice: int = 2025,
    statut: str = "en_cours",
) -> tuple[int, int]:
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
            exercice=exercice,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = :s WHERE id = :m"),
            {"m": int(mid), "s": statut},
        )
    return int(cid), int(mid)


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


def test_api_200_entetes_et_periodes_manquantes(session):
    # Exercice 2025 passé, aucune déclaration saisie : toutes les
    # périodes sont à collecter → la lettre les liste.
    tid, email = _cabinet(session)
    cid, mid = _client_avec_mission(session, tid, "PM Relance FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(cid), headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="relance-declarative-{cid}-{jour}.txt"'
    )
    assert r.text.startswith(EN_TETE_RELANCE)
    assert "À l'attention de la Direction de PM Relance FICTIVE" in r.text
    assert f"Exercice 2025 (mission #{mid}) :" in r.text
    assert "janvier 2025" in r.text
    assert "Impôts sur salaires" in r.text
    assert MENTION_DECLARATIONS_FOI in r.text
    assert NOTE_PROJET_RELANCE in r.text


def test_api_coherence_avec_completude_mission(session):
    # 2 périodes TVA saisies : la lettre ne relance QUE les manquantes
    # de la vue mission (aucun recalcul divergent).
    tid, email = _cabinet(session)
    cid, mid = _client_avec_mission(session, tid, "PM Coherence FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    for periode in ("2025-01", "2025-02"):
        rd = client.post(
            f"/api/v1/missions/{mid}/declarations-tva", headers=h,
            json={"periode": periode, "tva_collectee": "1000",
                  "tva_deductible": "0"},
        )
        assert rd.status_code == 200, rd.text

    r = client.get(_url(cid), headers=h)
    assert r.status_code == 200, r.text
    ligne_tva = next(
        ligne for ligne in r.text.splitlines()
        if ligne.startswith("  - TVA : ")
    )
    # Saisies janvier/février 2025 : plus relancées côté TVA.
    assert "janvier 2025" not in ligne_tva
    assert "février 2025" not in ligne_tva
    assert "mars 2025" in ligne_tva


def test_api_404_contribuable_hors_tenant(session):
    tid_a, email_a = _cabinet(session)
    tid_b, _ = _cabinet(session)
    cid_b, _mid = _client_avec_mission(
        session, tid_b, "PM Autre Tenant Relance FICTIVE"
    )
    session.commit()

    client, h = _client_connecte(email_a)
    # Contribuable du tenant B invisible pour A : 404, pas de fuite.
    assert client.get(_url(cid_b), headers=h).status_code == 404


def test_api_409_si_rien_a_relancer(session):
    # Toutes les périodes 2025 saisies (TVA et salaires) : rien à
    # relancer → 409 avec un message français clair.
    tid, email = _cabinet(session)
    cid, mid = _client_avec_mission(session, tid, "PM A Jour FICTIVE")
    session.commit()

    client, h = _client_connecte(email)
    for mois in range(1, 13):
        periode = f"2025-{mois:02d}"
        rt = client.post(
            f"/api/v1/missions/{mid}/declarations-tva", headers=h,
            json={"periode": periode, "tva_collectee": "1000",
                  "tva_deductible": "0"},
        )
        assert rt.status_code == 200, rt.text
        rs = client.post(
            f"/api/v1/missions/{mid}/declarations-salaires", headers=h,
            json={"periode": periode,
                  "masse_salariale_brute": "1000000"},
        )
        assert rs.status_code == 200, rs.text

    r = client.get(_url(cid), headers=h)
    assert r.status_code == 409, r.text
    assert (
        "Aucune période déclarative manquante" in r.json()["detail"]
    )
    assert "sans objet" in r.json()["detail"]


def test_api_missions_cloturees_ignorees(session):
    # Une mission CLÔTURÉE lacunaire ne déclenche aucune relance : la
    # collecte ne s'organise que sur les missions ouvertes.
    tid, email = _cabinet(session)
    cid, _mid = _client_avec_mission(
        session, tid, "PM Cloturee FICTIVE", exercice=2024,
        statut="cloturee",
    )
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(cid), headers=h).status_code == 409


def test_api_journalisation_export(session):
    tid, email = _cabinet(session)
    cid, _mid = _client_avec_mission(session, tid, "PM Journal Relance")
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(cid), headers=h).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'export_relance_declarative'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    charge = lignes[0]["charge_utile"]
    assert charge["contribuable_id"] == cid
    assert charge["format"] == "txt"
    assert charge["nb_missions_a_completer"] == 1


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
