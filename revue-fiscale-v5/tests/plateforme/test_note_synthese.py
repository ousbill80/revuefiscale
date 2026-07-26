"""Note de synthèse de mission : coercition pure + endpoints versionnés."""
from __future__ import annotations

import json
import uuid

import pytest

from backend.plateforme.note_synthese import (
    ELEMENTS_MAX,
    GRAVITE_DEFAUT,
    ErreurNoteSynthese,
    _parser_json_llm,
    normaliser_contenu_note,
    regles_du_contexte,
)

REGLES = {"R-TVA-001", "R-BIC-042", "R-ITS-007"}


# ── Normalisation pure ─────────────────────────────────────────────


def test_contenu_complet_valide():
    brut = {
        "contexte": "  Revue préventive exercice 2025, périmètre BIC/TVA.  ",
        "constats": [
            {
                "regle_id": "R-TVA-001",
                "resume": "TVA déductible non justifiée.",
                "montant": "1200000",
                "gravite": "haute",
            }
        ],
        "exposition": "Exposition estimée 1 200 000 FCFA.",
        "points_attention": ["Contrôles FEC : 2 alertes."],
        "recommandations": ["Régulariser la TVA déductible."],
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert out["contexte"] == "Revue préventive exercice 2025, périmètre BIC/TVA."
    assert out["constats"] == [
        {
            "regle_id": "R-TVA-001",
            "resume": "TVA déductible non justifiée.",
            "montant": "1200000",
            "gravite": "haute",
        }
    ]
    assert out["exposition"] == "Exposition estimée 1 200 000 FCFA."
    assert out["points_attention"] == ["Contrôles FEC : 2 alertes."]
    assert out["recommandations"] == ["Régulariser la TVA déductible."]


def test_constat_regle_inconnue_retire():
    brut = {
        "constats": [
            {"regle_id": "R-INVENTEE-999", "resume": "Constat inventé."},
            {"regle_id": "", "resume": "Sans règle."},
            {"regle_id": "R-BIC-042", "resume": "Constat sourcé."},
        ]
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert [c["regle_id"] for c in out["constats"]] == ["R-BIC-042"]


@pytest.mark.parametrize("gravite", ["critique", "", None, 3, "URGENT"])
def test_gravite_invalide_devient_moyenne(gravite):
    brut = {
        "constats": [
            {"regle_id": "R-TVA-001", "resume": "Écart.", "gravite": gravite}
        ]
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert out["constats"][0]["gravite"] == GRAVITE_DEFAUT == "moyenne"


def test_gravite_normalisee_casse():
    brut = {
        "constats": [
            {"regle_id": "R-TVA-001", "resume": "d", "gravite": " Haute "}
        ]
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert out["constats"][0]["gravite"] == "haute"


def test_constat_sans_resume_ignore_et_montant_optionnel():
    brut = {
        "constats": [
            {"regle_id": "R-TVA-001", "resume": "  "},
            {"regle_id": "R-TVA-001"},
            "chaîne brute",
            None,
            {"regle_id": "R-BIC-042", "resume": "ok", "montant": None},
            {"regle_id": "R-ITS-007", "resume": "ok2", "montant": 500},
        ]
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert [(c["regle_id"], c["montant"]) for c in out["constats"]] == [
        ("R-BIC-042", None),
        ("R-ITS-007", "500"),
    ]


def test_listes_textes_nettoyees():
    brut = {
        "points_attention": ["  a  ", "", None, {"objet": "x"}, ["liste"]],
        "recommandations": [1, "b"],
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert out["points_attention"] == ["a"]
    assert out["recommandations"] == ["1", "b"]


def test_structures_invalides_tolerees():
    for brut in (None, [], "texte", 42, {"constats": "pas une liste"}):
        out = normaliser_contenu_note(brut, REGLES)
        assert out == {
            "contexte": "",
            "constats": [],
            "exposition": "",
            "points_attention": [],
            "recommandations": [],
        }


def test_constats_plafonnes():
    brut = {
        "constats": [
            {"regle_id": "R-TVA-001", "resume": f"c{i}"}
            for i in range(ELEMENTS_MAX + 10)
        ]
    }
    out = normaliser_contenu_note(brut, REGLES)
    assert len(out["constats"]) == ELEMENTS_MAX


def test_regles_du_contexte():
    contexte = {
        "constats": [
            {"regle_id": "R-TVA-001"},
            {"regle_id": " "},
            {"regle_id": "R-BIC-042"},
        ]
    }
    assert regles_du_contexte(contexte) == {"R-TVA-001", "R-BIC-042"}
    assert regles_du_contexte({}) == set()


def test_parser_json_tolerant():
    assert _parser_json_llm('{"contexte": "ok"}') == {"contexte": "ok"}
    assert _parser_json_llm('Voici :\n```json\n{"contexte": "ok"}\n```') == {
        "contexte": "ok"
    }
    with pytest.raises(ErreurNoteSynthese):
        _parser_json_llm("aucun json ici")
    with pytest.raises(ErreurNoteSynthese):
        _parser_json_llm('["liste", "pas objet"]')


# ── Endpoints (base + LLM mocké) ───────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import creer_version_brouillon, publier_version

    lib = f"v-note-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="note-synthese")
    publier_version(session, lib, "note@test.ci")


def _cabinet(session):
    email = f"note.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab Note {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    return email


def _connexion(client: TestClient, email: str) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['jeton']}"}


def _mission(client: TestClient, h: dict[str, str]) -> int:
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM Note FICTIF",
            "ncc": "CI-NOTE-0001",
            "forme": "pm",
            "rccm": "CI-RCCM-NOTE",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan Plateau",
        },
    )
    assert c.status_code == 200, c.text
    m = client.post(
        "/api/v1/missions",
        headers=h,
        json={
            "contribuable_id": c.json()["id"],
            "type_engagement": "preventive",
            "exercice": 2025,
            "profil": {"regime": "reel", "forme_juridique": "SA"},
        },
    )
    assert m.status_code == 200, m.text
    return int(m.json()["id"])


def _mock_llm(monkeypatch, reponse: dict) -> None:
    from backend.socle import llm_providers

    monkeypatch.setattr(llm_providers, "providers_configures", lambda: True)
    monkeypatch.setattr(
        llm_providers,
        "appeler_chat",
        lambda *a, **k: (json.dumps(reponse, ensure_ascii=False), "mock", ()),
    )


def test_liste_vide_et_404_cross_tenant(session):
    _assurer_version(session)
    email_a = _cabinet(session)
    email_b = _cabinet(session)
    client = TestClient(app)
    h_a = _connexion(client, email_a)
    mid = _mission(client, h_a)

    vide = client.get(f"/api/v1/missions/{mid}/notes-synthese", headers=h_a)
    assert vide.status_code == 200, vide.text
    assert vide.json() == []

    h_b = _connexion(client, email_b)
    assert (
        client.get(
            f"/api/v1/missions/{mid}/notes-synthese", headers=h_b
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/missions/{mid}/note-synthese", headers=h_b
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/missions/{mid}/notes-synthese/1", headers=h_a
        ).status_code
        == 404
    )


def test_generation_llm_mocke_v1_puis_v2(session, monkeypatch):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission(client, h)

    _mock_llm(
        monkeypatch,
        {
            "contexte": "Revue préventive 2025 de PM Note FICTIF.",
            "constats": [
                {
                    "regle_id": "R-INVENTEE-999",
                    "resume": "Constat non sourcé — doit être retiré.",
                    "gravite": "haute",
                }
            ],
            "exposition": "Aucune exposition chiffrée fournie.",
            "points_attention": ["Aucun contrôle FEC disponible."],
            "recommandations": ["Importer la balance puis exécuter la revue."],
        },
    )

    r1 = client.post(f"/api/v1/missions/{mid}/note-synthese", headers=h)
    assert r1.status_code == 201, r1.text
    n1 = r1.json()
    assert n1["statut"] == "disponible"
    assert n1["version"] == 1
    assert n1["mission_id"] == mid
    # Traçabilité stricte : regle_id inconnu du contexte → constat RETIRÉ.
    assert n1["contenu"]["constats"] == []
    assert n1["contenu"]["contexte"].startswith("Revue préventive 2025")
    assert n1["contenu"]["recommandations"] == [
        "Importer la balance puis exécuter la revue."
    ]

    r2 = client.post(f"/api/v1/missions/{mid}/note-synthese", headers=h)
    assert r2.status_code == 201, r2.text
    assert r2.json()["version"] == 2
    assert r2.json()["statut"] == "disponible"

    liste = client.get(f"/api/v1/missions/{mid}/notes-synthese", headers=h)
    assert liste.status_code == 200
    versions = liste.json()
    assert [v["version"] for v in versions] == [2, 1]
    assert all("contenu" not in v for v in versions)

    detail = client.get(
        f"/api/v1/missions/{mid}/notes-synthese/1", headers=h
    )
    assert detail.status_code == 200
    assert detail.json()["version"] == 1
    assert detail.json()["contenu"]["constats"] == []


def test_anti_rafale_409_si_generation_en_cours(session, monkeypatch):
    from backend.plateforme.contexte import contexte_tenant

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    tenant_id = int(login.json()["tenant_id"])
    mid = _mission(client, h)

    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO note_synthese_mission "
                "(tenant_id, mission_id, version, statut) "
                "VALUES (:t, :m, 1, 'en_cours')"
            ),
            {"t": tenant_id, "m": mid},
        )
    session.commit()

    _mock_llm(monkeypatch, {"contexte": "x"})
    r = client.post(f"/api/v1/missions/{mid}/note-synthese", headers=h)
    assert r.status_code == 409, r.text
    assert "en cours" in r.json()["detail"]
