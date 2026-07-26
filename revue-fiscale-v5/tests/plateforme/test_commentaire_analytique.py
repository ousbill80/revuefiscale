"""Commentaire IA de revue analytique : coercition pure + endpoints."""
from __future__ import annotations

import json
import uuid

import pytest

from backend.plateforme.commentaire_analytique import (
    ELEMENTS_MAX,
    GRAVITE_DEFAUT,
    ErreurCommentaireAnalytique,
    _parser_json_llm,
    normaliser_contenu_commentaire,
    postes_du_contexte,
)

POSTES = {"601", "701", "411"}


# ── Normalisation pure ─────────────────────────────────────────────


def test_contenu_complet_valide():
    brut = {
        "resume": "  Charges en forte hausse, produits stables.  ",
        "explications": [
            {
                "poste": "601",
                "hypothese_explicative": "Hausse des achats liée au stock.",
                "question_a_poser_au_client": "Le volume d'achats a-t-il augmenté ?",
                "gravite": "haute",
            }
        ],
        "alertes_coherence": ["Charges +400 % sans hausse du CA."],
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert out["resume"] == "Charges en forte hausse, produits stables."
    assert out["explications"] == [
        {
            "poste": "601",
            "hypothese_explicative": "Hausse des achats liée au stock.",
            "question_a_poser_au_client": "Le volume d'achats a-t-il augmenté ?",
            "gravite": "haute",
        }
    ]
    assert out["alertes_coherence"] == ["Charges +400 % sans hausse du CA."]


def test_explication_poste_inconnu_retiree():
    brut = {
        "explications": [
            {"poste": "999999", "hypothese_explicative": "Poste inventé."},
            {"poste": "", "hypothese_explicative": "Sans poste."},
            {"poste": "701", "hypothese_explicative": "Poste sourcé."},
        ]
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert [e["poste"] for e in out["explications"]] == ["701"]


@pytest.mark.parametrize("gravite", ["critique", "", None, 3, "URGENT"])
def test_gravite_invalide_devient_moyenne(gravite):
    brut = {
        "explications": [
            {
                "poste": "601",
                "hypothese_explicative": "Écart.",
                "gravite": gravite,
            }
        ]
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert out["explications"][0]["gravite"] == GRAVITE_DEFAUT == "moyenne"


def test_gravite_normalisee_casse():
    brut = {
        "explications": [
            {
                "poste": "601",
                "hypothese_explicative": "d",
                "gravite": " Haute ",
            }
        ]
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert out["explications"][0]["gravite"] == "haute"


def test_explication_sans_hypothese_ignoree_et_question_optionnelle():
    brut = {
        "explications": [
            {"poste": "601", "hypothese_explicative": "  "},
            {"poste": "601"},
            "chaîne brute",
            None,
            {"poste": "701", "hypothese_explicative": "ok"},
            {
                "poste": "411",
                "hypothese_explicative": "ok2",
                "question_a_poser_au_client": "Pourquoi ?",
            },
        ]
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert [
        (e["poste"], e["question_a_poser_au_client"])
        for e in out["explications"]
    ] == [("701", ""), ("411", "Pourquoi ?")]


def test_alertes_coherence_nettoyees():
    brut = {
        "alertes_coherence": ["  a  ", "", None, {"objet": "x"}, ["liste"], 1],
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert out["alertes_coherence"] == ["a", "1"]


def test_structures_invalides_tolerees():
    for brut in (None, [], "texte", 42, {"explications": "pas une liste"}):
        out = normaliser_contenu_commentaire(brut, POSTES)
        assert out == {
            "resume": "",
            "explications": [],
            "alertes_coherence": [],
        }


def test_explications_plafonnees():
    brut = {
        "explications": [
            {"poste": "601", "hypothese_explicative": f"h{i}"}
            for i in range(ELEMENTS_MAX + 10)
        ]
    }
    out = normaliser_contenu_commentaire(brut, POSTES)
    assert len(out["explications"]) == ELEMENTS_MAX


def test_postes_du_contexte():
    contexte = {
        "variations": [
            {"poste": "601"},
            {"poste": " "},
            {"poste": "701"},
        ]
    }
    assert postes_du_contexte(contexte) == {"601", "701"}
    assert postes_du_contexte({}) == set()


def test_parser_json_tolerant():
    assert _parser_json_llm('{"resume": "ok"}') == {"resume": "ok"}
    assert _parser_json_llm('Voici :\n```json\n{"resume": "ok"}\n```') == {
        "resume": "ok"
    }
    with pytest.raises(ErreurCommentaireAnalytique):
        _parser_json_llm("aucun json ici")
    with pytest.raises(ErreurCommentaireAnalytique):
        _parser_json_llm('["liste", "pas objet"]')


# ── Endpoints (base + LLM mocké) ───────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-cra-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="commentaire-analytique")
    publier_version(session, lib, "cra@test.ci")


def _cabinet(session):
    email = f"cra.{uuid.uuid4().hex[:8]}@demo.local"
    provisionner_cabinet(
        session,
        denomination=f"Cab CRA {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    session.commit()
    return email


def _connexion(client: TestClient, email: str) -> tuple[dict[str, str], int]:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    corps = login.json()
    return (
        {"Authorization": f"Bearer {corps['jeton']}"},
        int(corps["tenant_id"]),
    )


def _mission_avec_revue(
    client: TestClient, session, h: dict[str, str], tenant_id: int
) -> int:
    """Mission N (2025) + mission N-1 (2024) avec soldes comparables."""
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM CRA FICTIF",
            "ncc": f"CI-CRA-{uuid.uuid4().hex[:6].upper()}",
            "forme": "pm",
            "rccm": "CI-RCCM-CRA",
            "regime_fiscal": "reel",
            "forme_juridique": "SA",
            "siege_social": "Abidjan Plateau",
        },
    )
    assert c.status_code == 200, c.text
    cid = int(c.json()["id"])
    ids: dict[int, int] = {}
    for exercice in (2024, 2025):
        m = client.post(
            "/api/v1/missions",
            headers=h,
            json={
                "contribuable_id": cid,
                "type_engagement": "preventive",
                "exercice": exercice,
                "profil": {"regime": "reel", "forme_juridique": "SA"},
            },
        )
        assert m.status_code == 200, m.text
        ids[exercice] = int(m.json()["id"])
    # Variation forte sur 601 (1 M → 5 M) ; 701 stable.
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO solde_compte "
                "(tenant_id, mission_id, compte, libelle, debit, credit) "
                "VALUES "
                "(:t, :m1, '601', 'Achats', 1000000, 0), "
                "(:t, :m1, '701', 'Ventes', 0, 9000000), "
                "(:t, :m, '601', 'Achats', 5000000, 0), "
                "(:t, :m, '701', 'Ventes', 0, 9000000)"
            ),
            {"t": tenant_id, "m": ids[2025], "m1": ids[2024]},
        )
    session.commit()
    return ids[2025]


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
    h_a, tid_a = _connexion(client, email_a)
    mid = _mission_avec_revue(client, session, h_a, tid_a)

    vide = client.get(
        f"/api/v1/missions/{mid}/commentaires-analytiques", headers=h_a
    )
    assert vide.status_code == 200, vide.text
    assert vide.json() == []

    h_b, _ = _connexion(client, email_b)
    assert (
        client.get(
            f"/api/v1/missions/{mid}/commentaires-analytiques", headers=h_b
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/missions/{mid}/commentaire-analytique", headers=h_b
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/missions/{mid}/commentaires-analytiques/1", headers=h_a
        ).status_code
        == 404
    )


def test_generation_llm_mocke_v1_puis_v2(session, monkeypatch):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission_avec_revue(client, session, h, tid)

    _mock_llm(
        monkeypatch,
        {
            "resume": "Achats en forte hausse à activité constante.",
            "explications": [
                {
                    "poste": "999999",
                    "hypothese_explicative": "Poste non fourni — retiré.",
                    "question_a_poser_au_client": "?",
                    "gravite": "haute",
                },
                {
                    "poste": "601",
                    "hypothese_explicative": "Constitution de stock possible.",
                    "question_a_poser_au_client": (
                        "Pouvez-vous justifier la hausse des achats "
                        "de 4 000 000 FCFA ?"
                    ),
                    "gravite": "critique",
                },
            ],
            "alertes_coherence": ["Achats +400 % sans variation du CA."],
        },
    )

    r1 = client.post(
        f"/api/v1/missions/{mid}/commentaire-analytique", headers=h
    )
    assert r1.status_code == 201, r1.text
    c1 = r1.json()
    assert c1["statut"] == "disponible"
    assert c1["version"] == 1
    assert c1["mission_id"] == mid
    # Traçabilité stricte : poste inconnu des variations → RETIRÉ.
    assert [e["poste"] for e in c1["contenu"]["explications"]] == ["601"]
    # Gravité invalide → moyenne.
    assert c1["contenu"]["explications"][0]["gravite"] == "moyenne"
    assert c1["contenu"]["resume"].startswith("Achats en forte hausse")
    assert c1["contenu"]["alertes_coherence"] == [
        "Achats +400 % sans variation du CA."
    ]

    r2 = client.post(
        f"/api/v1/missions/{mid}/commentaire-analytique", headers=h
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["version"] == 2
    assert r2.json()["statut"] == "disponible"

    liste = client.get(
        f"/api/v1/missions/{mid}/commentaires-analytiques", headers=h
    )
    assert liste.status_code == 200
    versions = liste.json()
    assert [v["version"] for v in versions] == [2, 1]
    assert all("contenu" not in v for v in versions)

    detail = client.get(
        f"/api/v1/missions/{mid}/commentaires-analytiques/1", headers=h
    )
    assert detail.status_code == 200
    assert detail.json()["version"] == 1
    assert [
        e["poste"] for e in detail.json()["contenu"]["explications"]
    ] == ["601"]


def test_revue_indisponible_400(session, monkeypatch):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    c = client.post(
        "/api/v1/contribuables",
        headers=h,
        json={
            "denomination": "PM CRA SANS N-1",
            "ncc": f"CI-CRA-{uuid.uuid4().hex[:6].upper()}",
            "forme": "pm",
            "rccm": "CI-RCCM-CRA2",
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
    mid = int(m.json()["id"])

    _mock_llm(monkeypatch, {"resume": "x"})
    r = client.post(
        f"/api/v1/missions/{mid}/commentaire-analytique", headers=h
    )
    assert r.status_code == 400, r.text
    assert "indisponible" in r.json()["detail"]


def test_anti_rafale_409_si_generation_en_cours(session, monkeypatch):
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tenant_id = _connexion(client, email)
    mid = _mission_avec_revue(client, session, h, tenant_id)

    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO commentaire_revue_analytique "
                "(tenant_id, mission_id, version, statut) "
                "VALUES (:t, :m, 1, 'en_cours')"
            ),
            {"t": tenant_id, "m": mid},
        )
    session.commit()

    _mock_llm(monkeypatch, {"resume": "x"})
    r = client.post(
        f"/api/v1/missions/{mid}/commentaire-analytique", headers=h
    )
    assert r.status_code == 409, r.text
    assert "en cours" in r.json()["detail"]
