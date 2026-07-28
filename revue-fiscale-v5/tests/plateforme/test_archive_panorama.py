"""Pièce d'archive « panorama de conformité » : rendu pur, clôture, tolérance."""
from __future__ import annotations

import io
import uuid
import zipfile

import pytest

pytestmark = pytest.mark.db

from backend.plateforme import archive_mission  # noqa: E402
from backend.plateforme.archive_mission import (  # noqa: E402
    rendre_panorama_texte,
)
from backend.plateforme.panorama_conformite import (  # noqa: E402
    LIBELLES_VOLETS,
    NOTE_PANORAMA_CONFORMITE,
    assembler_panorama,
)

# ── Rendu texte pur (sans DB) ────────────────────────────────────────


def _panorama_complet() -> dict:
    """Panorama assemblé (fonction pure du module source) — 8 volets."""
    p = assembler_panorama(
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
    p["mission_id"] = 314
    p["exercice"] = 2025
    p["client"] = "SARL Ivoire FICTIVE"
    return p


def test_rendu_texte_volets_et_niveaux():
    """PUR — en-tête, libellés français des 8 volets, niveaux, compteurs."""
    texte = rendre_panorama_texte(_panorama_complet())
    lignes = texte.splitlines()
    assert lignes[0] == (
        "PANORAMA DE CONFORMITÉ — agrégat consultatif de statuts"
    )
    assert lignes[1] == (
        "Mission #314 — client : SARL Ivoire FICTIVE — exercice 2025"
    )
    # Chaque volet apparaît avec son libellé français.
    assert "VOLETS SUIVIS (8)" in texte
    for libelle in LIBELLES_VOLETS.values():
        assert libelle in texte
    # Niveaux d'attention en libellés français (jamais de score).
    assert "[À EXAMINER] Cohérence CA / TVA" in texte
    assert "statut de la vue : ecart_a_expliquer" in texte
    assert "[À QUALIFIER] Retenue sur loyers" in texte
    assert "[À QUALIFIER] Retenue sur honoraires" in texte
    assert "[À SUIVRE] Déficits reportables" in texte
    assert "[SANS SIGNAL] Charge fiscale estimée (panorama)" in texte
    # Compteurs par niveau — simples décomptes, aucun score.
    assert "COMPTEURS PAR NIVEAU D'ATTENTION" in texte
    assert (
        "À examiner — un signal appelle une lecture de la vue détaillée : 2"
        in texte
    )
    assert "À qualifier — une appréciation humaine est requise : 2" in texte
    assert "À suivre — point de suivi indicatif : 2" in texte
    assert (
        "Sans signal particulier — la vue ne relève aucun point : 2" in texte
    )
    assert "Indisponible — la vue n'a pas pu être servie : 0" in texte
    assert "VOLETS EN ÉCHEC (0)" in texte
    assert "score" not in texte.lower().replace("aucun score", "")
    # Note consultative en pied — l'humain décide.
    assert texte.splitlines()[-1] == f"* {NOTE_PANORAMA_CONFORMITE}"
    assert "L'humain décide." in texte


def test_rendu_texte_volets_en_echec_affiches():
    """PUR — volets en échec : niveau indisponible + section dédiée."""
    p = assembler_panorama(
        {
            "coherence_ca": {
                "disponible": True, "statut_source": "coherent",
            },
            # Les 7 autres volets ont échoué (None / absents).
            "patente": None,
        }
    )
    p["mission_id"] = 7
    p["exercice"] = 2024
    texte = rendre_panorama_texte(p)
    assert "client : [non renseigné]" in texte
    assert "[SANS SIGNAL] Cohérence CA / TVA" in texte
    assert "[INDISPONIBLE] Contribution des patentes" in texte
    assert "VOLETS EN ÉCHEC (7)" in texte
    assert (
        "  - Contribution des patentes (estimation partielle) : vue non "
        "servie (module en échec ou données absentes)" in texte
    )
    assert (
        "  - Complétude déclarative (TVA / salaires) : vue non servie "
        "(module en échec ou données absentes)" in texte
    )
    assert "Indisponible — la vue n'a pas pu être servie : 7" in texte
    assert NOTE_PANORAMA_CONFORMITE in texte


def test_rendu_texte_defensif_charge_vide():
    """PUR — charge vide ou lacunaire : jamais d'exception, note présente."""
    texte = rendre_panorama_texte({})
    assert "PANORAMA DE CONFORMITÉ" in texte
    assert "exercice [non renseigné]" in texte
    assert "VOLETS SUIVIS (0)" in texte
    assert "  (aucun)" in texte
    assert NOTE_PANORAMA_CONFORMITE in texte


# ── Intégration à l'archive (DB) ─────────────────────────────────────

sa = pytest.importorskip("sqlalchemy")
text = sa.text

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402
from backend.plateforme.contexte import contexte_tenant  # noqa: E402
from tests.plateforme.test_demande_renseignements import (  # noqa: E402
    _assurer_version,
    _cabinet,
    _connexion,
    _mission,
)


def _cloturer(session, tid, mid):
    """Clôture directe du dossier (photographie d'état, comme les autres
    suites : test_compte_rendu, test_bilan_cloture)."""
    with contexte_tenant(session, tid):
        session.execute(
            text("UPDATE mission SET statut = 'cloturee' WHERE id = :m"),
            {"m": mid},
        )
    session.commit()


def _telecharger_zip(client, h, mid):
    resp = client.get(f"/api/v1/missions/{mid}/dossier-travail.zip", headers=h)
    assert resp.status_code == 200, resp.text
    return resp


def test_piece_presente_dans_archive_mission_cloturee(session):
    """Mission clôturée → pièce 25 incluse, lisible, listée au sommaire."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    _cloturer(session, tid, mid)

    resp = _telecharger_zip(client, h, mid)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "25_panorama_conformite.txt" in noms
        texte = z.read("25_panorama_conformite.txt").decode("utf-8")
        assert "PANORAMA DE CONFORMITÉ" in texte
        assert f"Mission #{mid}" in texte
        assert "client : PM Demande FICTIF" in texte
        assert "exercice 2025" in texte
        assert "VOLETS SUIVIS (8)" in texte
        for libelle in LIBELLES_VOLETS.values():
            assert libelle in texte
        assert "COMPTEURS PAR NIVEAU D'ATTENTION" in texte
        assert NOTE_PANORAMA_CONFORMITE in texte
        # La pièce apparaît naturellement au sommaire du dossier.
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert (
            "25_panorama_conformite.txt : Panorama de conformité "
            "(niveaux d'attention par volet, consultatif)" in sommaire
        )


def test_piece_absente_hors_cloture(session):
    """Mission non clôturée : dossier intermédiaire strictement inchangé
    (ni pièce 25, ni mention au sommaire)."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, _tid = _connexion(client, email)
    mid = _mission(client, h)

    resp = _telecharger_zip(client, h, mid)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        assert "25_panorama_conformite.txt" not in set(z.namelist())
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert "25_panorama_conformite.txt" not in sommaire


def test_panorama_en_echec_archive_produite_et_signalee(session, monkeypatch):
    """Tolérance : panorama en panne → archive produite, pièce omise
    avec motif au sommaire (jamais bloquant)."""
    _assurer_version(session)
    email = _cabinet(session)
    client = TestClient(app)
    h, tid = _connexion(client, email)
    mid = _mission(client, h)
    _cloturer(session, tid, mid)

    def _boom(*_a, **_k):
        raise RuntimeError("panne simulée du panorama de conformité")

    monkeypatch.setattr(
        archive_mission, "panorama_conformite_mission", _boom
    )
    resp = _telecharger_zip(client, h, mid)
    assert resp.content[:4] == b"PK\x03\x04"
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        noms = set(z.namelist())
        assert "25_panorama_conformite.txt" not in noms
        # Les autres pièces restent produites (indépendance des pièces).
        assert "23_ordre_du_jour.txt" in noms
        assert "15_echeancier_fiscal.txt" in noms
        sommaire = z.read("00_sommaire.txt").decode("utf-8")
        assert (
            "25_panorama_conformite.txt : OMISE — panne simulée du "
            "panorama de conformité" in sommaire
        )
