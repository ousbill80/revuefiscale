"""Calendrier fiscal du cabinet — consolidation mensuelle consultative."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from backend.plateforme.calendrier_cabinet import (
    HORIZON_DEFAUT,
    HORIZON_MAX,
    MENTION_NOTE,
    PLAFOND_ELEMENTS,
    assembler_calendrier,
    borner_horizon,
    compteurs_calendrier,
    fin_horizon,
    grouper_par_mois,
    libelle_mois,
    normaliser_element,
    plafonner_elements,
    trier_elements,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────

JOUR = date(2026, 7, 28)


def _element(**surcharge) -> dict:
    base = {
        "date": "2026-08-10",
        "type": "echeance_fiscale",
        "client": "SA FICTIVE",
        "mission_id": 7,
        "libelle": "TVA — Déclaration (juillet 2026)",
    }
    base.update(surcharge)
    return base


def test_borner_horizon_bornes_et_defensif():
    assert borner_horizon(3) == 3
    assert borner_horizon(0) == 1
    assert borner_horizon(99) == HORIZON_MAX
    # Valeur illisible → défaut, jamais bloquant.
    assert borner_horizon("abc") == HORIZON_DEFAUT
    assert borner_horizon(None) == HORIZON_DEFAUT


def test_fin_horizon_mois_courant_inclus_et_bascule_annee():
    # 3 mois depuis juillet : juillet, août, septembre → fin le 30/09.
    assert fin_horizon(JOUR, 3) == date(2026, 9, 30)
    # 1 mois : fin du mois courant.
    assert fin_horizon(JOUR, 1) == date(2026, 7, 31)
    # Bascule d'année : 3 mois depuis novembre → fin le 31/01 suivant.
    assert fin_horizon(date(2026, 11, 15), 3) == date(2027, 1, 31)
    # Février (année non bissextile).
    assert fin_horizon(date(2026, 12, 1), 3) == date(2027, 2, 28)


def test_libelle_mois_francais_et_defensif():
    assert libelle_mois("2026-08") == "Août 2026"
    assert libelle_mois("2026-12") == "Décembre 2026"
    assert libelle_mois("2027-02") == "Février 2027"
    # Valeur illisible → inchangée, jamais bloquant.
    assert libelle_mois("n-importe-quoi") == "n-importe-quoi"


def test_normaliser_element_cles_stables_et_depassee():
    e = normaliser_element(_element(), JOUR)
    assert e is not None
    assert set(e) == {
        "date", "type", "client", "mission_id", "libelle", "depassee",
    }
    assert e["depassee"] is False
    # Date antérieure au jour → dépassée (constat, pas un reproche).
    passe = normaliser_element(_element(date="2026-07-01"), JOUR)
    assert passe is not None and passe["depassee"] is True
    # Le jour même n'est PAS dépassé (encore actionnable).
    ce_jour = normaliser_element(_element(date="2026-07-28"), JOUR)
    assert ce_jour is not None and ce_jour["depassee"] is False


def test_normaliser_element_defensif_ecarte_l_illisible():
    # Date illisible ou type hors référentiel → écarté, jamais bloquant.
    assert normaliser_element(_element(date="pas-une-date"), JOUR) is None
    assert normaliser_element(_element(type="ovni"), JOUR) is None
    sans_mission = normaliser_element(
        _element(mission_id=None, client=None, libelle=None), JOUR
    )
    assert sans_mission is not None
    assert sans_mission["mission_id"] is None
    assert sans_mission["client"] == ""
    assert sans_mission["libelle"] == ""


def test_trier_elements_chronologique_puis_client():
    tri = trier_elements([
        _element(date="2026-09-01", client="B"),
        _element(date="2026-08-10", client="Z"),
        _element(date="2026-08-10", client="A"),
        _element(date="2026-07-02", client="C"),
    ])
    assert [(t["date"], t["client"]) for t in tri] == [
        ("2026-07-02", "C"),
        ("2026-08-10", "A"),
        ("2026-08-10", "Z"),
        ("2026-09-01", "B"),
    ]


def test_plafonner_elements_coupe_les_plus_lointaines():
    items = [_element(libelle=str(i)) for i in range(PLAFOND_ELEMENTS + 60)]
    assert len(plafonner_elements(items)) == PLAFOND_ELEMENTS


def test_grouper_par_mois_libelles_francais():
    elements = [
        _element(date="2026-07-30"),
        _element(date="2026-08-05"),
        _element(date="2026-08-20"),
        _element(date="2026-09-10"),
    ]
    groupes = grouper_par_mois(trier_elements(elements))
    assert [g["mois"] for g in groupes] == [
        "2026-07", "2026-08", "2026-09",
    ]
    assert [g["libelle_mois"] for g in groupes] == [
        "Juillet 2026", "Août 2026", "Septembre 2026",
    ]
    assert [len(g["elements"]) for g in groupes] == [1, 2, 1]


def test_compteurs_calendrier():
    items = [
        {"depassee": True},
        {"depassee": False},
        {"depassee": False},
    ]
    c = compteurs_calendrier(items)
    assert c == {"nb_total": 3, "nb_depassees": 1, "nb_a_venir": 2}


def test_assembler_calendrier_vide_cles_stables():
    vue = assembler_calendrier([], JOUR)
    assert set(vue) == {"aujourd_hui", "mois", "compteurs", "note"}
    assert vue["aujourd_hui"] == "2026-07-28"
    assert vue["mois"] == []
    assert vue["compteurs"] == {
        "nb_total": 0, "nb_depassees": 0, "nb_a_venir": 0,
    }
    assert vue["note"] == MENTION_NOTE


def test_assembler_calendrier_groupes_tries_et_depassees():
    vue = assembler_calendrier(
        [
            _element(date="2026-09-01"),
            _element(
                date="2026-07-10", type="point_convenu",
                libelle="point convenu — relancer les quittances",
            ),
            _element(date="2026-08-10"),
            _element(date="illisible"),  # écarté sans bloquer
        ],
        JOUR,
    )
    assert [g["mois"] for g in vue["mois"]] == [
        "2026-07", "2026-08", "2026-09",
    ]
    juillet = vue["mois"][0]["elements"][0]
    assert juillet["type"] == "point_convenu"
    assert juillet["depassee"] is True
    assert vue["compteurs"] == {
        "nb_total": 3, "nb_depassees": 1, "nb_a_venir": 2,
    }


def test_assembler_calendrier_plafond_500():
    elements = [
        _element(date="2026-08-10", libelle=str(i))
        for i in range(PLAFOND_ELEMENTS + 40)
    ]
    vue = assembler_calendrier(elements, JOUR)
    assert vue["compteurs"]["nb_total"] == PLAFOND_ELEMENTS


def test_note_consultative_planification_sans_email():
    assert "consultatif" in MENTION_NOTE
    assert "indicative" in MENTION_NOTE
    assert "arbitre" in MENTION_NOTE  # l'humain arbitre et décide
    assert "email" in MENTION_NOTE  # rappel : rien ne part par email


# ── Tests API (DB) ─────────────────────────────────────────────────

pytestmark = pytest.mark.db

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from backend.plateforme.provisionnement import (  # noqa: E402
    derniere_version_publiee,
    provisionner_cabinet,
)

URL = "/api/v1/cabinet/calendrier"


def _assurer_version(session) -> None:
    if derniere_version_publiee(session) is not None:
        return
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-calcab-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="calendrier cabinet")
    publier_version(session, lib, "calcab@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"calcab.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab Calendrier {email}",
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


def _point_date(
    session, tenant_id: int, mission_id: int, date_cible: str
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


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(URL).status_code == 401


def test_api_structure_stable_et_point_convenu_date(session):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Calendrier FICTIVE")
    demain = (date.today() + timedelta(days=1)).isoformat()
    _point_date(session, tid, mid, demain)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert set(corps) == {
        "aujourd_hui", "horizon_mois", "fin_horizon", "mois",
        "compteurs", "sources_en_echec", "note",
    }
    assert corps["horizon_mois"] == 3
    assert corps["sources_en_echec"] == []
    assert "consultatif" in corps["note"]
    # Le point convenu daté de demain apparaît dans son mois.
    elements = [e for g in corps["mois"] for e in g["elements"]]
    points = [e for e in elements if e["type"] == "point_convenu"]
    assert len(points) == 1
    assert points[0]["date"] == demain
    assert points[0]["depassee"] is False
    assert points[0]["mission_id"] == mid
    # Contrat stable de chaque élément et de chaque groupe mensuel.
    for g in corps["mois"]:
        assert set(g) == {"mois", "libelle_mois", "elements"}
        for e in g["elements"]:
            assert set(e) == {
                "date", "type", "client", "mission_id", "libelle",
                "depassee",
            }
    # Compteurs cohérents avec les éléments restitués.
    assert corps["compteurs"]["nb_total"] == len(elements)
    assert corps["compteurs"]["nb_total"] == (
        corps["compteurs"]["nb_depassees"]
        + corps["compteurs"]["nb_a_venir"]
    )


def test_api_horizon_mois_pris_en_compte(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(URL, params={"horizon_mois": 6}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["horizon_mois"] == 6


def test_api_horizon_mois_invalide_422(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(
        URL, params={"horizon_mois": 0}, headers=h
    ).status_code == 422
    assert client.get(
        URL, params={"horizon_mois": 13}, headers=h
    ).status_code == 422


def test_api_journalisation_consultation(session):
    tid, email = _cabinet(session)
    session.commit()

    client, h = _client_connecte(email)
    assert client.get(URL, headers=h).status_code == 200
    with contexte_tenant(session, tid):
        lignes = session.execute(
            text(
                "SELECT charge_utile FROM journal_audit "
                "WHERE action = 'consultation_calendrier_cabinet'"
            ),
        ).mappings().all()
    assert len(lignes) == 1
    assert lignes[0]["charge_utile"]["horizon_mois"] == 3


def test_api_source_en_echec_jamais_bloquante(session, monkeypatch):
    tid, email = _cabinet(session)
    mid = _mission_en_cours(session, tid, "PM Tolerance Cal FICTIVE")
    demain = (date.today() + timedelta(days=1)).isoformat()
    _point_date(session, tid, mid, demain)
    session.commit()

    import backend.plateforme.echeances_cabinet as ec

    # La source échéances importe filtrer_fenetre du module réutilisé :
    # sa disparition fait échouer TOUTE la source (pas une seule
    # mission) — le calendrier doit rester servi malgré tout.
    monkeypatch.delattr(ec, "filtrer_fenetre")

    client, h = _client_connecte(email)
    r = client.get(URL, headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    # La source en échec est signalée… mais RIEN ne bloque : le point
    # convenu daté reste dans le calendrier.
    assert corps["sources_en_echec"] == ["echeances_fiscales"]
    elements = [e for g in corps["mois"] for e in g["elements"]]
    assert any(e["type"] == "point_convenu" for e in elements)
    assert corps["note"]
