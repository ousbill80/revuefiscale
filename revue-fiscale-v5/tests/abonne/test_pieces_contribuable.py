"""Pièces contribuable + extraction identité (brouillon, sans LLM inventé)."""
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.abonne.extraction_identite import (
    MESSAGE_INDISPONIBLE,
    proposer_identite,
    verifier_conformite,
)
from backend.abonne.pieces_contribuable_service import (
    deposer_piece,
    lire_contenu_piece,
    lister_pieces,
    rattacher_session,
    retirer_piece,
)
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant

pytestmark = pytest.mark.db


@pytest.fixture
def tenant_pieces(session, tmp_path, monkeypatch):
    monkeypatch.setenv("PIECES_DIR", str(tmp_path / "pieces"))
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))
    # Pas de clé LLM — chemin indisponible explicite
    monkeypatch.setattr(
        "backend.socle.llm_providers.config.moonshot_api_key", ""
    )
    monkeypatch.setattr(
        "backend.socle.llm_providers.config.deepseek_api_key", ""
    )
    monkeypatch.setattr(
        "backend.socle.llm_providers.config.modele_cle_api", ""
    )

    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab Pieces Contrib', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    session.flush()
    return tid


def _table_ok(session) -> bool:
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'piece_contribuable'"
        )
    ).scalar_one()
    return int(n) > 0


def test_table_piece_contribuable_existe(session):
    if not _table_ok(session):
        pytest.skip("migration 014 non appliquée — lancez make migrate")


def test_upload_session_puis_rattachement(session, tenant_pieces):
    test_table_piece_contribuable_existe(session)
    tid = tenant_pieces
    sid = "11111111-2222-3333-4444-555555555555"

    with contexte_tenant(session, tid):
        piece = deposer_piece(
            session,
            tid,
            type_piece="dfe",
            nom_fichier="dfe.txt",
            contenu=b"NCC 1234567A\nRaison sociale DEMO SA",
            content_type="text/plain",
            session_upload=sid,
        )
        assert piece["contribuable_id"] is None
        assert piece["session_upload"] == sid
        assert piece["type_piece"] == "dfe"

        liste = lister_pieces(session, session_upload=sid)
        assert len(liste) == 1

        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Demo SA') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()

        rattachees = rattacher_session(
            session, session_upload=sid, contribuable_id=int(cid)
        )
        assert len(rattachees) == 1
        assert rattachees[0]["contribuable_id"] == cid

        retirer_piece(session, int(piece["id"]))
        assert lister_pieces(session, contribuable_id=int(cid)) == []

    effacer_contexte_tenant(session)


def test_lire_contenu_piece_session(session, tenant_pieces):
    """Contenu lisible dès l'upload session (aperçu avant création fiche)."""
    test_table_piece_contribuable_existe(session)
    tid = tenant_pieces
    sid = "contenu-preview-1111-2222-3333-444444"

    with contexte_tenant(session, tid):
        piece = deposer_piece(
            session,
            tid,
            type_piece="dfe",
            nom_fichier="DFE ZenAPI SAS-2023 (4).pdf",
            contenu=b"%PDF-1.4 fake",
            content_type="application/pdf",
            session_upload=sid,
            auto_detecter_type=False,
            autoriser_vision_classif=False,
        )
        meta, brut = lire_contenu_piece(session, int(piece["id"]))
        assert meta["id"] == piece["id"]
        assert meta["nom_fichier"] == "DFE ZenAPI SAS-2023 (4).pdf"
        assert brut == b"%PDF-1.4 fake"

    effacer_contexte_tenant(session)


def test_proposer_identite_sans_cle_llm(session, tenant_pieces):
    test_table_piece_contribuable_existe(session)
    tid = tenant_pieces
    sid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    with contexte_tenant(session, tid):
        deposer_piece(
            session,
            tid,
            type_piece="rccm",
            nom_fichier="rccm.txt",
            contenu=b"RCCM CI-ABJ-2020-B-12345",
            content_type="text/plain",
            session_upload=sid,
        )
        prop = proposer_identite(
            session, tid, session_upload=sid
        )
        assert prop["disponible"] is False
        assert prop["statut"] == "indisponible"
        assert MESSAGE_INDISPONIBLE.split(":")[0] in prop["message"]
        assert prop["proposition_id"]
        # Aucun champ inventé
        assert all(v is None for v in prop["champs"].values())

        conf = verifier_conformite(
            session,
            tid,
            champs_saisis={"denomination": "X", "ncc": "1"},
            session_upload=sid,
        )
        assert conf["disponible"] is False
        assert conf["ok"] is None
        assert conf["ecarts"] == []

    effacer_contexte_tenant(session)


def test_purge_session_orpheline_ttl(session, tenant_pieces, monkeypatch):
    test_table_piece_contribuable_existe(session)
    tid = tenant_pieces
    sid = "purge-session-aaaa-bbbb-cccc-dddddd"

    from backend.abonne.pieces_contribuable_service import (
        abandonner_session,
        purger_orphelines,
    )

    with contexte_tenant(session, tid):
        piece = deposer_piece(
            session,
            tid,
            type_piece="dfe",
            nom_fichier="orphan.txt",
            contenu=b"NCC ORPHELIN",
            session_upload=sid,
        )
        # dry-run immédiat : trop récent pour TTL 72h
        dry = purger_orphelines(session, dry_run=True)
        assert dry["dry_run"] is True
        assert dry["pieces_supprimees"] == 0

        # TTL 0h → éligible (plus_vieux_que=0)
        from datetime import timedelta

        dry0 = purger_orphelines(
            session, plus_vieux_que=timedelta(hours=0), dry_run=True
        )
        assert any(s["session_upload"] == sid for s in dry0["sessions"])

        res = abandonner_session(session, session_upload=sid)
        assert res["pieces_supprimees"] == 1
        assert lister_pieces(session, session_upload=sid) == []

        # pièce déjà retirée — id ne doit plus exister
        assert piece["id"]

    effacer_contexte_tenant(session)


def test_isolation_tenant_pieces(session, tenant_pieces, tmp_path, monkeypatch):
    test_table_piece_contribuable_existe(session)
    tid_a = tenant_pieces
    monkeypatch.setenv("PIECES_DIR", str(tmp_path / "pieces"))
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))

    tid_b = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Autre Cab', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    session.flush()

    sid = "isolation-session-0001"
    with contexte_tenant(session, tid_a):
        deposer_piece(
            session,
            tid_a,
            type_piece="bail",
            nom_fichier="bail.txt",
            contenu=b"siege Cocody",
            session_upload=sid,
        )
    effacer_contexte_tenant(session)

    with contexte_tenant(session, tid_b):
        liste = lister_pieces(session, session_upload=sid)
        assert liste == []
    effacer_contexte_tenant(session)
