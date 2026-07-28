"""Panorama consultatif de conformité de la mission — statuts agrégés."""
from __future__ import annotations

import uuid

import pytest

from backend.plateforme.panorama_conformite import (
    NIVEAU_A_EXAMINER,
    NIVEAU_A_QUALIFIER,
    NIVEAU_A_SUIVRE,
    NIVEAU_INDISPONIBLE,
    NIVEAU_SANS_SIGNAL,
    NIVEAUX_ATTENTION,
    NOTE_PANORAMA_CONFORMITE,
    VOLETS_PANORAMA,
    assembler_panorama,
    classer_statut,
    volet_indisponible,
)

# ── Tests purs (sans DB) ───────────────────────────────────────────


def test_classement_statuts_a_examiner():
    assert classer_statut("ecart_a_expliquer") == NIVEAU_A_EXAMINER
    assert classer_statut("aucune_saisie") == NIVEAU_A_EXAMINER
    assert classer_statut("lacunaire") == NIVEAU_A_EXAMINER


def test_classement_statut_a_qualifier():
    assert classer_statut("a_qualifier") == NIVEAU_A_QUALIFIER


def test_classement_statuts_a_suivre():
    assert classer_statut("deficits_a_suivre") == NIVEAU_A_SUIVRE
    assert classer_statut("solde_a_payer_indicatif") == NIVEAU_A_SUIVRE
    assert classer_statut("excedent_indicatif") == NIVEAU_A_SUIVRE
    assert classer_statut("estimation_partielle") == NIVEAU_A_SUIVRE
    assert classer_statut("partiel") == NIVEAU_A_SUIVRE


def test_classement_statuts_sans_signal():
    assert classer_statut("coherent") == NIVEAU_SANS_SIGNAL
    assert classer_statut("complet") == NIVEAU_SANS_SIGNAL
    assert classer_statut("aucun_deficit") == NIVEAU_SANS_SIGNAL
    assert classer_statut("equilibre_indicatif") == NIVEAU_SANS_SIGNAL
    assert classer_statut("sans_periode_echue") == NIVEAU_SANS_SIGNAL


def test_classement_defensif_indisponible():
    # Statut explicitement indisponible, inconnu, vide ou absent :
    # jamais d'invention de signal.
    assert classer_statut("indisponible") == NIVEAU_INDISPONIBLE
    assert classer_statut("statut_inconnu") == NIVEAU_INDISPONIBLE
    assert classer_statut("") == NIVEAU_INDISPONIBLE
    assert classer_statut(None) == NIVEAU_INDISPONIBLE


def test_volet_indisponible_cles_stables():
    v = volet_indisponible("coherence_ca")
    assert v["volet"] == "coherence_ca"
    assert v["disponible"] is False
    assert v["statut_source"] is None
    assert v["niveau"] == NIVEAU_INDISPONIBLE
    assert v["libelle"]


def test_assembler_compteurs_sans_score():
    panorama = assembler_panorama(
        {
            "completude_declarative": {
                "disponible": True, "statut_source": "lacunaire",
            },
            "coherence_ca": {
                "disponible": True, "statut_source": "ecart_a_expliquer",
            },
            "retenue_loyers": {
                "disponible": True, "statut_source": "a_qualifier",
            },
            "retenue_honoraires": {
                "disponible": True, "statut_source": "a_qualifier",
            },
            "deficits_reportables": {
                "disponible": True, "statut_source": "deficits_a_suivre",
            },
            "rapprochement_acomptes": {
                "disponible": True,
                "statut_source": "equilibre_indicatif",
            },
            "patente": {
                "disponible": True,
                "statut_source": "estimation_partielle",
            },
            "charge_fiscale": {
                "disponible": True, "statut_source": "complet",
            },
        }
    )
    assert panorama["disponible"] is True
    c = panorama["compteurs"]
    assert c[NIVEAU_A_EXAMINER] == 2
    assert c[NIVEAU_A_QUALIFIER] == 2
    assert c[NIVEAU_A_SUIVRE] == 2
    assert c[NIVEAU_SANS_SIGNAL] == 2
    assert c[NIVEAU_INDISPONIBLE] == 0
    # AUCUN score chiffré, AUCUN cumul pondéré.
    assert "score" not in panorama
    assert "note_globale" not in panorama
    assert sum(c.values()) == panorama["nb_volets_suivis"]
    assert panorama["volets_en_echec"] == []
    assert panorama["note"] == NOTE_PANORAMA_CONFORMITE


def test_assembler_tolere_volet_en_echec():
    # Un module en échec (None ou non-dict) → volet indisponible listé
    # dans volets_en_echec, jamais bloquant.
    panorama = assembler_panorama(
        {
            "coherence_ca": {
                "disponible": True, "statut_source": "coherent",
            },
            "patente": None,
            "charge_fiscale": "n/a",
        }
    )
    assert panorama["disponible"] is True
    assert "patente" in panorama["volets_en_echec"]
    assert "charge_fiscale" in panorama["volets_en_echec"]
    par_volet = {v["volet"]: v for v in panorama["volets"]}
    assert par_volet["patente"]["niveau"] == NIVEAU_INDISPONIBLE
    assert par_volet["patente"]["disponible"] is False
    assert par_volet["coherence_ca"]["niveau"] == NIVEAU_SANS_SIGNAL


def test_assembler_cles_toujours_presentes():
    panorama = assembler_panorama({})
    assert panorama["disponible"] is False
    assert panorama["nb_volets_suivis"] == len(VOLETS_PANORAMA)
    assert panorama["nb_volets_disponibles"] == 0
    assert [v["volet"] for v in panorama["volets"]] == list(
        VOLETS_PANORAMA
    )
    for v in panorama["volets"]:
        for cle in (
            "volet", "libelle", "disponible", "statut_source", "niveau",
        ):
            assert cle in v
    for niveau in NIVEAUX_ATTENTION:
        assert niveau in panorama["compteurs"]
        assert niveau in panorama["libelles_niveaux"]
    assert panorama["note"] == NOTE_PANORAMA_CONFORMITE


def test_note_consultative_oriente_sans_conclure():
    assert "oriente la lecture" in NOTE_PANORAMA_CONFORMITE
    assert "ne conclut rien" in NOTE_PANORAMA_CONFORMITE
    assert "vue détaillée" in NOTE_PANORAMA_CONFORMITE
    assert "décide" in NOTE_PANORAMA_CONFORMITE
    assert "Aucun score" in NOTE_PANORAMA_CONFORMITE


def test_formulations_non_accusatoires():
    from backend.plateforme.panorama_conformite import LIBELLES_NIVEAUX

    interdits = ("fraude", "faute", "anomalie", "infraction", "grave")
    for libelle in LIBELLES_NIVEAUX.values():
        for mot in interdits:
            assert mot not in libelle.lower()


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
    from backend.editorial.publication import (
        creer_version_brouillon,
        publier_version,
    )

    lib = f"v-panoconf-{uuid.uuid4().hex[:8]}"
    creer_version_brouillon(session, lib, note="panorama-conformite")
    publier_version(session, lib, "panoconf@test.ci")


def _cabinet(session) -> tuple[int, str]:
    _assurer_version(session)
    email = f"pano.{uuid.uuid4().hex[:8]}@demo.local"
    r = provisionner_cabinet(
        session,
        denomination=f"Cab PanoConf {email}",
        type_tenant="cabinet",
        palier="standard",
        email_admin=email,
        mot_de_passe_admin="admin-admin1",
        creer_demo=False,
    )
    return r.tenant_id, email


def _mission(session, tenant_id: int, nom: str) -> int:
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
    return int(mid)


def _solde(session, tenant_id: int, mission_id: int, compte: str,
           libelle: str, debit: str, credit: str) -> None:
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "INSERT INTO solde_compte (tenant_id, mission_id, "
                "compte, libelle, debit, credit) "
                "VALUES (:t, :m, :c, :l, :d, :cr)"
            ),
            {"t": tenant_id, "m": mission_id, "c": compte, "l": libelle,
             "d": debit, "cr": credit},
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


def _url(mid: int) -> str:
    return f"/api/v1/missions/{mid}/panorama-conformite"


def test_api_statuts_agreges_sans_montants(session):
    tid, email = _cabinet(session)
    mid = _mission(session, tid, "PM PanoConf FICTIF")
    # Balance : CA 200M (patente estimable), loyers 622x (à qualifier).
    _solde(session, tid, mid, "701", "Ventes", "0", "200000000")
    _solde(session, tid, mid, "622", "Loyers", "12000000", "0")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["mission_id"] == mid
    assert corps["exercice"] == 2025
    assert corps["disponible"] is True
    assert [v["volet"] for v in corps["volets"]] == list(VOLETS_PANORAMA)
    par_volet = {v["volet"]: v for v in corps["volets"]}

    # Retenue loyers : statut source « a_qualifier » → à qualifier.
    assert par_volet["retenue_loyers"]["statut_source"] == "a_qualifier"
    assert par_volet["retenue_loyers"]["niveau"] == NIVEAU_A_QUALIFIER

    # Patente : estimation partielle disponible → à suivre.
    assert (
        par_volet["patente"]["statut_source"] == "estimation_partielle"
    )
    assert par_volet["patente"]["niveau"] == NIVEAU_A_SUIVRE

    # AUCUN montant dans le panorama — statuts seulement.
    for v in corps["volets"]:
        assert set(v) == {
            "volet", "libelle", "disponible", "statut_source", "niveau",
        }
    assert "score" not in corps
    assert corps["note"] == NOTE_PANORAMA_CONFORMITE

    # Compteurs cohérents avec les volets restitués.
    for niveau in NIVEAUX_ATTENTION:
        attendu = sum(
            1 for v in corps["volets"] if v["niveau"] == niveau
        )
        assert corps["compteurs"][niveau] == attendu

    # Consultation journalisée (append_journal).
    with contexte_tenant(session, tid):
        n = session.execute(
            text(
                "SELECT count(*) FROM journal_audit "
                "WHERE mission_id = :m "
                "AND action = 'consultation_panorama_conformite'"
            ),
            {"m": mid},
        ).scalar_one()
    assert int(n) >= 1


def test_api_tolerance_mission_vide(session):
    # Sans balance ni saisie : le panorama se sert quand même — les
    # volets sans données sont indisponibles ou sans signal, jamais
    # un signal inventé.
    tid, email = _cabinet(session)
    mid = _mission(session, tid, "PM PanoConf Vide FICTIF")
    session.commit()

    client, h = _client_connecte(email)
    r = client.get(_url(mid), headers=h)
    assert r.status_code == 200, r.text
    corps = r.json()
    assert [v["volet"] for v in corps["volets"]] == list(VOLETS_PANORAMA)
    par_volet = {v["volet"]: v for v in corps["volets"]}
    # Sans balance : cohérence CA et retenues indisponibles.
    assert par_volet["coherence_ca"]["niveau"] == NIVEAU_INDISPONIBLE
    assert par_volet["retenue_loyers"]["niveau"] == NIVEAU_INDISPONIBLE
    assert corps["note"] == NOTE_PANORAMA_CONFORMITE


def test_api_404_cross_tenant(session):
    tid_a, _email_a = _cabinet(session)
    mid_a = _mission(session, tid_a, "PM PanoConf Cross FICTIF")
    _tid_b, email_b = _cabinet(session)
    session.commit()

    client_b, h_b = _client_connecte(email_b)
    assert client_b.get(_url(mid_a), headers=h_b).status_code == 404


def test_api_401_sans_jeton(session):
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    assert client.get(_url(1)).status_code == 401
