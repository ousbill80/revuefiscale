"""Note de synthèse de mission : coercition pure + endpoints versionnés."""
from __future__ import annotations

import json
import uuid

import pytest

from backend.plateforme.note_synthese import (
    ACTIONS_NOTE_MAX,
    ECHEANCES_MANQUANTES_MAX,
    ELEMENTS_MAX,
    GRAVITE_DEFAUT,
    ErreurNoteSynthese,
    _parser_json_llm,
    normaliser_contenu_note,
    regles_du_contexte,
    section_civisme,
    section_plan_actions,
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


# ── Sections déterministes (civisme / plan d'actions) ──────────────


def _analyse_civisme(nb_manquantes: int = 2) -> dict:
    """Analyse de civisme réaliste, via les fonctions pures du module."""
    from datetime import date

    from backend.plateforme.civisme_fiscal import (
        rapprocher,
        synthese_rapprochement,
    )

    echeances = [
        {
            "impot": "TVA",
            "obligation": "Déclaration et paiement de la TVA du mois",
            "periode": f"mois {i} 2025",
            "date_limite": f"2025-{(i % 12) + 1:02d}-15",
        }
        for i in range(nb_manquantes)
    ] + [
        {
            "impot": "Patente",
            "obligation": "Contribution des patentes",
            "periode": "exercice 2025",
            "date_limite": "2025-03-15",
        },
        {
            "impot": "États financiers",
            "obligation": "Dépôt des états financiers",
            "periode": "exercice 2025",
            "date_limite": "2099-04-30",
        },
    ]
    elements = [
        {"impot": "Patente", "periode": None, "source": "data room : p.pdf"}
    ]
    rapprochement = rapprocher(echeances, elements, date(2026, 1, 15))
    return {
        "mission_id": 1,
        "exercice": 2025,
        "regime": "reel",
        "aujourd_hui": "2026-01-15",
        "elements_collectes": elements,
        "rapprochement": rapprochement,
        "synthese": synthese_rapprochement(rapprochement),
        "note": "Rapprochement consultatif — pièces de data room.",
    }


def test_section_civisme_indisponible():
    """Analyse absente/inattendue → section non bloquante, jamais d'erreur."""
    assert section_civisme(None) == {"disponible": False}
    assert section_civisme("pas un dict") == {"disponible": False}
    assert section_civisme({"synthese": "pas un dict"}) == {
        "disponible": False
    }


def test_section_civisme_synthese_et_manquantes():
    analyse = _analyse_civisme(nb_manquantes=2)
    out = section_civisme(analyse)
    assert out["disponible"] is True
    assert out["exercice"] == 2025
    assert out["regime"] == "reel"
    # Compteurs recopiés de la synthèse réelle : 1 couverte (patente),
    # 1 en attente (EF 2099), 2 manquantes (TVA passées).
    assert out["couvertes"] == 1
    assert out["en_attente"] == 1
    assert out["manquantes"] == 2
    assert out["taux_civisme"] == "33.33"
    assert len(out["echeances_manquantes"]) == 2
    premiere = out["echeances_manquantes"][0]
    assert premiere["impot"] == "TVA"
    assert premiere["obligation"].startswith("Déclaration")
    assert premiere["date_limite"].startswith("2025-")
    # Réserve consultative recopiée telle quelle.
    assert out["reserve"] == analyse["note"]


def test_section_civisme_manquantes_plafonnees():
    out = section_civisme(_analyse_civisme(nb_manquantes=ECHEANCES_MANQUANTES_MAX + 5))
    assert out["manquantes"] == ECHEANCES_MANQUANTES_MAX + 5
    assert len(out["echeances_manquantes"]) == ECHEANCES_MANQUANTES_MAX


def _analyse_plan(risques: list[dict]) -> dict:
    """Analyse de plan d'actions réaliste, via les fonctions pures."""
    from datetime import date

    from backend.plateforme.plan_actions import (
        MENTION_NOTE,
        deriver_plan,
        synthese_plan,
    )

    plan = deriver_plan(risques, date(2026, 1, 15))
    return {
        "mission_id": 1,
        "contribuable_id": 1,
        "date_analyse": "2026-01-15",
        "plan": plan,
        "synthese": synthese_plan(plan),
        "note": MENTION_NOTE,
    }


def _risque(rid: int, probabilite: str, montant: str | None) -> dict:
    return {
        "id": rid,
        "libelle": f"Risque {rid}",
        "impot": "tva",
        "exercice_origine": 2025,
        "statut": "ouvert",
        "probabilite": probabilite,
        "montant_estime": montant,
        "penalites_estimees": None,
    }


def test_section_plan_actions_indisponible():
    assert section_plan_actions(None) == {"disponible": False}
    assert section_plan_actions([]) == {"disponible": False}
    assert section_plan_actions({"synthese": None}) == {"disponible": False}


def test_section_plan_actions_hautes_puis_moyennes():
    analyse = _analyse_plan(
        [
            _risque(1, "probable", "6000000"),  # haute (exposition ≥ seuil)
            _risque(2, "possible", "1000000"),  # moyenne (exposition chiffrée)
            _risque(3, "faible", None),  # basse — exclue de la note
        ]
    )
    out = section_plan_actions(analyse)
    assert out["disponible"] is True
    assert out["total_actions"] == 3
    assert out["par_priorite"] == {"haute": 1, "moyenne": 1, "basse": 1}
    assert out["exposition_totale"] == "7000000"
    # Hautes d'abord, complétées par les moyennes ; les basses omises.
    assert [(a["risque_id"], a["priorite"]) for a in out["actions"]] == [
        (1, "haute"),
        (2, "moyenne"),
    ]
    assert out["actions"][0]["type_action"] == "declaration_rectificative"
    assert out["actions"][0]["exposition"] == "6000000"
    assert out["actions"][0]["impot"] == "TVA"
    assert out["actions"][0]["action"]
    assert out["actions"][0]["date_prescription"]
    assert out["reserve"] == analyse["note"]


def test_section_plan_actions_plafonnee_aux_hautes():
    analyse = _analyse_plan(
        [
            _risque(i, "probable", "9000000")
            for i in range(1, ACTIONS_NOTE_MAX + 4)
        ]
        + [_risque(99, "possible", "1000")]
    )
    out = section_plan_actions(analyse)
    assert len(out["actions"]) == ACTIONS_NOTE_MAX
    # Plafond atteint par les hautes : aucune moyenne ajoutée.
    assert all(a["priorite"] == "haute" for a in out["actions"])
    assert out["total_actions"] == ACTIONS_NOTE_MAX + 4


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
    # Sections déterministes — jamais rédigées par le LLM (absentes de
    # sa réponse mockée) mais toujours présentes dans le contenu stocké.
    civisme = n1["contenu"]["civisme_declaratif"]
    assert civisme["disponible"] is True
    assert civisme["exercice"] == 2025
    assert civisme["couvertes"] == 0  # aucune pièce en data room
    assert civisme["manquantes"] >= 1  # échéances 2025 passées
    assert civisme["couvertes"] + civisme["manquantes"] > 0
    assert 0 <= float(civisme["taux_civisme"]) <= 100
    assert 1 <= len(civisme["echeances_manquantes"]) <= 10
    assert "data room" in civisme["reserve"]
    plan = n1["contenu"]["plan_actions"]
    assert plan["disponible"] is True
    assert plan["total_actions"] == 0  # aucun risque au registre
    assert plan["par_priorite"] == {"haute": 0, "moyenne": 0, "basse": 0}
    assert plan["exposition_totale"] == "0"
    assert plan["actions"] == []
    assert "consultatif" in plan["reserve"]

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


def _tenant_id(client: TestClient, email: str) -> int:
    login = client.post(
        "/api/v1/auth/connexion",
        json={"email": email, "mot_de_passe": "admin-admin1"},
    )
    assert login.status_code == 200, login.text
    return int(login.json()["tenant_id"])


def test_sections_civisme_et_plan_avec_donnees(session, monkeypatch):
    """Pièces en data room + risques au registre → sections alimentées."""
    from backend.plateforme.contexte import contexte_tenant

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    tenant_id = _tenant_id(client, email)
    mid = _mission(client, h)

    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text("SELECT contribuable_id FROM mission WHERE id = :m"),
            {"m": mid},
        ).scalar_one()
        # Pièce « autre » couvrant la Patente 2025 (nom de fichier).
        session.execute(
            text(
                "INSERT INTO piece_mission (tenant_id, mission_id, "
                "type_piece, role, nom_fichier, chemin_stockage) "
                "VALUES (:t, :m, 'autre', 'annexe', "
                "'declaration_patente_2025.pdf', :c)"
            ),
            {"t": tenant_id, "m": mid, "c": f"tests/note/{uuid.uuid4().hex}"},
        )
        # Risque probable et chiffré ≥ 5 000 000 → action haute priorité.
        session.execute(
            text(
                "INSERT INTO risque (tenant_id, contribuable_id, impot, "
                "libelle, montant_estime, statut, probabilite, "
                "exercice_origine) "
                "VALUES (:t, :c, 'TVA', 'TVA collectée non déclarée', "
                "6000000, 'ouvert', 'probable', 2025)"
            ),
            {"t": tenant_id, "c": int(cid)},
        )
    session.commit()

    _mock_llm(monkeypatch, {"contexte": "Revue 2025."})
    r = client.post(f"/api/v1/missions/{mid}/note-synthese", headers=h)
    assert r.status_code == 201, r.text
    contenu = r.json()["contenu"]

    civisme = contenu["civisme_declaratif"]
    assert civisme["disponible"] is True
    assert civisme["couvertes"] >= 1  # Patente couverte par la pièce
    assert civisme["manquantes"] >= 1  # TVA/ITS 2025 sans pièce
    assert len(civisme["echeances_manquantes"]) == 10  # borné (régime réel)
    assert all(
        e["impot"] and e["date_limite"]
        for e in civisme["echeances_manquantes"]
    )

    plan = contenu["plan_actions"]
    assert plan["disponible"] is True
    assert plan["total_actions"] == 1
    assert plan["par_priorite"]["haute"] == 1
    from decimal import Decimal

    assert Decimal(plan["exposition_totale"]) == Decimal("6000000")
    assert len(plan["actions"]) == 1
    action = plan["actions"][0]
    assert action["priorite"] == "haute"
    assert action["type_action"] == "declaration_rectificative"
    assert action["impot"] == "TVA"
    assert action["libelle_risque"] == "TVA collectée non déclarée"
    assert Decimal(action["exposition"]) == Decimal("6000000")


def test_note_survit_a_l_echec_des_analyses(session, monkeypatch):
    """Analyse annexe en échec → note générée, section indisponible."""
    import backend.plateforme.civisme_fiscal as civisme_mod
    import backend.plateforme.plan_actions as plan_mod

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    mid = _mission(client, h)

    def _echec_civisme(*a, **k):
        raise civisme_mod.ErreurCivismeFiscal("échéancier indisponible")

    def _echec_plan(*a, **k):
        raise plan_mod.ErreurPlanActions("registre indisponible")

    monkeypatch.setattr(civisme_mod, "analyse_mission", _echec_civisme)
    monkeypatch.setattr(plan_mod, "analyse_mission", _echec_plan)
    _mock_llm(monkeypatch, {"contexte": "Revue 2025 sans annexes."})

    r = client.post(f"/api/v1/missions/{mid}/note-synthese", headers=h)
    assert r.status_code == 201, r.text
    contenu = r.json()["contenu"]
    assert r.json()["statut"] == "disponible"
    assert contenu["civisme_declaratif"] == {"disponible": False}
    assert contenu["plan_actions"] == {"disponible": False}
    # L'analyse civisme alimente aussi les prochaines obligations.
    assert contenu["prochaines_obligations"] == {"disponible": False}


# ── Section « Prochaines obligations déclaratives » ────────────────


def test_section_prochaines_obligations_fenetre_tri_statuts(session):
    """Cas nominal : fenêtre, tri par date, statuts, plafond à 10."""
    from datetime import date

    from backend.plateforme.contexte import contexte_tenant
    from backend.plateforme.note_synthese import (
        OBLIGATIONS_NOTE_MAX,
        section_prochaines_obligations,
    )

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    tenant_id = _tenant_id(client, email)
    mid = _mission(client, h)

    with contexte_tenant(session, tenant_id):
        # Pièce « autre » couvrant la TVA de mai 2025 (nom de fichier).
        session.execute(
            text(
                "INSERT INTO piece_mission (tenant_id, mission_id, "
                "type_piece, role, nom_fichier, chemin_stockage) "
                "VALUES (:t, :m, 'autre', 'annexe', "
                "'declaration_tva_mai_2025.pdf', :c)"
            ),
            {"t": tenant_id, "m": mid, "c": f"tests/note/{uuid.uuid4().hex}"},
        )
    session.commit()

    out = section_prochaines_obligations(
        session, tenant_id, mid, aujourd_hui=date(2025, 6, 1), jours=90
    )
    assert out["disponible"] is True
    assert out["fenetre_jours"] == 90
    assert out["aujourd_hui"] == "2025-06-01"
    obligations = out["obligations"]
    # Fenêtre [01/06, 30/08/2025] (régime réel, hors DGE) : TVA + ITS
    # de mai/juin/juillet (limites 15/06, 15/07, 15/08) + IRC/IRCM T2
    # (15/07) = 7 échéances.
    assert len(obligations) == 7
    dates = [o["date_limite"] for o in obligations]
    assert dates == sorted(dates)  # tri par date limite croissante
    assert obligations[0] == {
        "date_limite": "2025-06-15",
        "impot": "ITS",
        "obligation": "Déclaration et reversement des ITS du mois",
        "periode": "mai 2025",
        "statut": "en_attente",
    }
    # La pièce « declaration_tva_mai_2025.pdf » couvre la TVA de mai.
    tva_mai = next(
        o
        for o in obligations
        if o["impot"] == "TVA" and o["periode"] == "mai 2025"
    )
    assert tva_mai["statut"] == "couverte"
    assert tva_mai["date_limite"] == "2025-06-15"
    autres = [o for o in obligations if o is not tva_mai]
    assert all(o["statut"] == "en_attente" for o in autres)
    assert "consultatif" in out["reserve"]

    # Fenêtre large : plus d'échéances que le plafond → borné à 10,
    # toujours triées par date.
    large = section_prochaines_obligations(
        session, tenant_id, mid, aujourd_hui=date(2025, 6, 1), jours=200
    )
    assert large["disponible"] is True
    assert large["fenetre_jours"] == 200
    assert len(large["obligations"]) == OBLIGATIONS_NOTE_MAX
    dates_larges = [o["date_limite"] for o in large["obligations"]]
    assert dates_larges == sorted(dates_larges)


def test_section_prochaines_obligations_mission_introuvable(session):
    """Mission hors périmètre → section non bloquante, jamais d'erreur."""
    from backend.plateforme.note_synthese import (
        section_prochaines_obligations,
    )

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    _connexion(client, email)
    tenant_id = _tenant_id(client, email)

    out = section_prochaines_obligations(session, tenant_id, 99999999)
    assert out == {"disponible": False}


def test_prochaines_obligations_dans_contexte_et_note(session, monkeypatch):
    """La clé figure dans le contexte ET dans le contenu de la note."""
    from backend.plateforme.note_synthese import construire_contexte

    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h = _connexion(client, email)
    tenant_id = _tenant_id(client, email)
    mid = _mission(client, h)

    ctx = construire_contexte(session, tenant_id, mid)
    po = ctx["prochaines_obligations"]
    assert po["disponible"] is True
    assert po["fenetre_jours"] == 90
    assert isinstance(po["obligations"], list)
    assert len(po["obligations"]) <= 10
    assert all(
        set(o)
        == {"date_limite", "impot", "obligation", "periode", "statut"}
        for o in po["obligations"]
    )
    assert "consultatif" in po["reserve"]

    _mock_llm(monkeypatch, {"contexte": "Revue 2025."})
    r = client.post(f"/api/v1/missions/{mid}/note-synthese", headers=h)
    assert r.status_code == 201, r.text
    contenu = r.json()["contenu"]
    # Section déterministe recopiée telle quelle dans le contenu stocké.
    assert contenu["prochaines_obligations"]["disponible"] is True
    assert contenu["prochaines_obligations"]["fenetre_jours"] == 90
    assert contenu["prochaines_obligations"]["reserve"] == po["reserve"]
