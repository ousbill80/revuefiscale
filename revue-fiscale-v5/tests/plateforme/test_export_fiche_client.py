"""Export texte de la fiche client — préparation du rendez-vous."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.plateforme.export_fiche_client import (
    MENTION_DEPASSEE,
    MENTION_EVOLUTION_INDISPONIBLE,
    NOTE_EXPORT_FICHE,
    rendre_fiche_texte,
)
from backend.plateforme.fiche_client import MENTION_NOTE

# ── Tests purs (sans DB) ───────────────────────────────────────────


def _fiche(**surcharge) -> dict:
    base = {
        "aujourd_hui": "2026-07-28",
        "contribuable_id": 5,
        "denomination": "SA FICTIVE",
        "forme": "pm",
        "missions": [
            {"mission_id": 9, "exercice": 2025, "statut": "en_cours"},
            {"mission_id": 4, "exercice": 2024, "statut": "cloturee"},
        ],
        "points_ouverts": [
            {
                "point_id": 1,
                "mission_id": 9,
                "exercice": 2025,
                "libelle": "Rassembler les quittances d'acomptes",
                "date_cible": "2026-07-01",
                "depassee": True,
            },
            {
                "point_id": 2,
                "mission_id": 9,
                "exercice": 2025,
                "libelle": "Transmettre la balance définitive",
                "date_cible": None,
                "depassee": False,
            },
        ],
        "evolution_charge_fiscale": {
            "disponible": True,
            "variations": [
                {
                    "exercice_precedent": 2024,
                    "exercice": 2025,
                    "total": {
                        "variation_absolue": "125000",
                        "variation_relative_pct": "12.5",
                        "sens": "hausse",
                    },
                }
            ],
        },
        "alertes": [
            {
                "type": "point_convenu",
                "gravite": "vigilance",
                "client": "SA FICTIVE",
                "mission_id": 9,
                "libelle": "Un point convenu a dépassé sa date cible",
                "echeance": "2026-07-01",
            }
        ],
        "volets_en_echec": [],
        "note": MENTION_NOTE,
    }
    base.update(surcharge)
    return base


def test_texte_en_tete_denomination_forme_et_date_francaise():
    texte = rendre_fiche_texte(_fiche())
    assert "FICHE CLIENT — SA FICTIVE" in texte
    assert "Forme : Personne morale" in texte
    assert "Date d'édition : 28/07/2026" in texte


def test_texte_sections_missions_statuts_francais_et_ordre():
    texte = rendre_fiche_texte(_fiche())
    assert "── Missions par exercice (2)" in texte
    assert "Exercice 2025 — mission #9 — En cours" in texte
    assert "Exercice 2024 — mission #4 — Clôturée" in texte
    # Exercice décroissant : 2025 avant 2024 (ordre de la fiche).
    assert texte.index("Exercice 2025 — mission #9") < texte.index(
        "Exercice 2024 — mission #4"
    )


def test_texte_points_ouverts_dates_fr_et_mention_douce():
    texte = rendre_fiche_texte(_fiche())
    assert "── Points convenus encore ouverts (2)" in texte
    # Date cible au format français, mention DOUCE si dépassée.
    assert (
        "Rassembler les quittances d'acomptes (exercice 2025) — "
        f"date cible 01/07/2026 ({MENTION_DEPASSEE})"
    ) in texte
    # Sans date cible : mention neutre, jamais de mention « passée ».
    assert (
        "Transmettre la balance définitive (exercice 2025) — "
        "sans date cible"
    ) in texte
    assert texte.count(MENTION_DEPASSEE) == 1


def test_texte_alertes_gravite_francaise_et_echeance():
    texte = rendre_fiche_texte(_fiche())
    assert "── Signaux du centre d'alertes (1)" in texte
    assert (
        "[Vigilance] Un point convenu a dépassé sa date cible "
        "(échéance 01/07/2026)"
    ) in texte


def test_texte_evolution_virgule_francaise_et_sens_en_lettres():
    texte = rendre_fiche_texte(_fiche())
    assert "── Évolution de la charge fiscale estimée" in texte
    assert (
        "De l'exercice 2024 à l'exercice 2025 : charge fiscale "
        "propre estimée en hausse de 12,5 %"
    ) in texte
    # Contrat machine à point décimal JAMAIS restitué tel quel.
    assert "12.5" not in texte
    # Une variation s'explique — formulation jamais accusatoire.
    assert "Chaque variation s'explique" in texte


def test_texte_evolution_baisse_et_stable():
    fiche = _fiche(evolution_charge_fiscale={
        "disponible": True,
        "variations": [
            {
                "exercice_precedent": 2023,
                "exercice": 2024,
                "total": {
                    "variation_absolue": "-50000",
                    "variation_relative_pct": "-4.2",
                    "sens": "baisse",
                },
            },
            {
                "exercice_precedent": 2024,
                "exercice": 2025,
                "total": {
                    "variation_absolue": "0",
                    "variation_relative_pct": "0.0",
                    "sens": "stable",
                },
            },
        ],
    })
    texte = rendre_fiche_texte(fiche)
    # Baisse : pourcentage SANS signe, le sens porte la direction.
    assert "estimée en baisse de 4,2 %" in texte
    assert "-4,2" not in texte
    # Stable : sens seul, aucun pourcentage inutile.
    assert (
        "De l'exercice 2024 à l'exercice 2025 : charge fiscale "
        "propre estimée stable"
    ) in texte


def test_texte_evolution_indisponible_mention_douce():
    # Évolution absente OU non disponible : même mention douce.
    for evolution in (None, {"disponible": False, "variations": []}):
        texte = rendre_fiche_texte(
            _fiche(evolution_charge_fiscale=evolution)
        )
        assert MENTION_EVOLUTION_INDISPONIBLE in texte


def test_texte_volets_en_echec_signales():
    texte = rendre_fiche_texte(
        _fiche(volets_en_echec=["alertes", "evolution_charge_fiscale"])
    )
    assert (
        "Volets momentanément indisponibles : alertes, "
        "evolution_charge_fiscale — le reste de la fiche reste "
        "présenté."
    ) in texte
    # Sans échec : aucune mention.
    assert "momentanément indisponibles" not in rendre_fiche_texte(_fiche())


def test_texte_fiche_minimale_tolerante():
    # Fiche entièrement vide (défensif) : document valide quand même.
    texte = rendre_fiche_texte({})
    assert texte.startswith("FICHE CLIENT")
    assert "Aucune mission pour ce client." in texte
    assert "Aucun point convenu en attente pour ce client." in texte
    assert (
        "Aucun signal du centre d'alertes ne concerne ce client."
    ) in texte
    assert MENTION_EVOLUTION_INDISPONIBLE in texte
    assert NOTE_EXPORT_FICHE in texte


def test_texte_note_consultative_en_pied():
    texte = rendre_fiche_texte(_fiche())
    # Note de la fiche reprise, puis note d'export en fermeture.
    assert MENTION_NOTE in texte
    assert texte.rstrip().endswith(NOTE_EXPORT_FICHE)
    # Document préparatoire : l'expert décide, jamais l'outil.
    assert "préparatoire" in NOTE_EXPORT_FICHE
    assert "décide" in NOTE_EXPORT_FICHE


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
    return f"/api/v1/contribuables/{contribuable_id}/fiche.txt"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-expfc-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="export fiche client")
    publier_version(session, lib, "expfc@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"expfc.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Export Fiche {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _client_avec_mission(
    session, tenant_id: int, nom: str
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
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        session.execute(
            text("UPDATE mission SET statut = 'en_cours' WHERE id = :m"),
            {"m": int(mid)},
        )
    return int(cid), int(mid)


def _point_ouvert(
    session, tenant_id: int, mission_id: int, date_cible: str | None
) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO point_convenu (tenant_id, mission_id, "
                "libelle, date_cible) "
                "VALUES (:t, :m, :lib, CAST(:dc AS DATE))"
            ),
            {"t": tenant_id, "m": mission_id,
             "lib": "Rassembler les quittances d'acomptes",
             "dc": date_cible},
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


def test_api_txt_200_entetes_et_contenu(session):
    tid, email = _cabinet(session)
    cid, mid = _client_avec_mission(session, tid, "PM Export Fiche FICTIVE")
    hier = (date.today() - timedelta(days=1)).isoformat()
    _point_ouvert(session, tid, mid, hier)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(cid), headers=h)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    jour = date.today().isoformat()
    assert r.headers["content-disposition"] == (
        f'attachment; filename="fiche-client-{cid}-{jour}.txt"'
    )
    # Même assemblage que la fiche JSON : dénomination et mission.
    assert "FICHE CLIENT — PM Export Fiche FICTIVE" in r.text
    assert f"Exercice 2025 — mission #{mid} — En cours" in r.text
    assert "Rassembler les quittances d'acomptes" in r.text
    assert MENTION_DEPASSEE in r.text
    assert NOTE_EXPORT_FICHE in r.text


def test_api_404_contribuable_hors_tenant(session):
    tid_a, email_a = _cabinet(session)
    tid_b, _ = _cabinet(session)
    cid_b, _mid = _client_avec_mission(
        session, tid_b, "PM Autre Tenant Export FICTIVE"
    )
    session.commit()

    client, h = _client_connecte(email_a)
    # Le contribuable du tenant B est invisible pour A : 404, pas de fuite.
    assert client.get(_url(cid_b), headers=h).status_code == 404


def test_api_journalisation_export(session):
    tid, email = _cabinet(session)
    cid, _mid = _client_avec_mission(session, tid, "PM Journal Export FICHE")
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(_url(cid), headers=h).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'export_fiche_client'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    charge = lignes[0]["charge_utile"]
    assert charge["contribuable_id"] == cid
    assert charge["format"] == "txt"
    assert charge["volets_en_echec"] == []


def test_api_sans_jeton_401(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
