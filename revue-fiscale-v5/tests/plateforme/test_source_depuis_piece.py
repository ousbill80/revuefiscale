"""Pont Data Room → mission : pièce tabulaire vers source active."""
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.abonne.pieces_contribuable_service import deposer_piece
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.source_depuis_piece import (
    ErreurSourceDepuisPiece,
    importer_source_depuis_piece,
    lister_pieces_tabulaires,
)

pytestmark = pytest.mark.db

_FEC_OK = (
    b"JournalCode|JournalLib|EcritureNum|EcritureDate|CompteNum|CompteLib|Debit|Credit\n"
    b"VE|Ventes|1|20250131|411|Clients|500|0\n"
    b"VE|Ventes|1|20250131|701|CA|0|500\n"
)


@pytest.fixture
def contexte_pont(session, tmp_path, monkeypatch):
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))

    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab Pont', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    with contexte_tenant(session, tid):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Pont') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()
        cid_autre = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Autre Client') RETURNING id"
            ),
            {"t": tid},
        ).scalar_one()
        mid = session.execute(
            text(
                "INSERT INTO mission (tenant_id, contribuable_id, exercice, profil) "
                "VALUES (:t, :c, 2025, '{}') RETURNING id"
            ),
            {"t": tid, "c": cid},
        ).scalar_one()
    effacer_contexte_tenant(session)
    session.flush()
    return tid, cid, cid_autre, mid


def _deposer(session, tid, cid, nom, contenu):
    with contexte_tenant(session, tid):
        piece = deposer_piece(
            session,
            tid,
            type_piece="autre",
            nom_fichier=nom,
            contenu=contenu,
            contribuable_id=cid,
            auto_detecter_type=False,
        )
    effacer_contexte_tenant(session)
    return piece


def test_liste_pieces_tabulaires_filtre_les_formats(session, contexte_pont):
    tid, cid, _, _ = contexte_pont
    _deposer(session, tid, cid, "fec_2025.csv", _FEC_OK)
    _deposer(session, tid, cid, "dfe.pdf", b"%PDF-1.4 fake")
    _deposer(session, tid, cid, "notes.txt", b"texte libre sans en-tete")

    pieces = lister_pieces_tabulaires(session, tid, cid)
    assert len(pieces) == 1
    assert pieces[0]["nom_fichier"] == "fec_2025.csv"
    assert pieces[0]["format"] == "fec"
    assert pieces[0]["taille_octets"] == len(_FEC_OK)


def test_import_fec_valide_cree_les_soldes(session, contexte_pont):
    tid, cid, _, mid = contexte_pont
    piece = _deposer(session, tid, cid, "fec_2025.csv", _FEC_OK)

    p, out = importer_source_depuis_piece(
        session, tid, mid, piece_id=int(piece["id"])
    )
    assert p["id"] == piece["id"]
    assert out.rapport.statut == "ok"
    assert out.piece is not None
    assert out.piece.type_piece == "fec"
    assert out.piece.role == "source_active"

    with contexte_tenant(session, tid):
        comptes = session.execute(
            text(
                "SELECT compte FROM solde_compte WHERE mission_id = :m "
                "ORDER BY compte"
            ),
            {"m": mid},
        ).scalars().all()
    assert comptes == ["411", "701"]


def test_piece_non_tabulaire_refusee(session, contexte_pont):
    tid, cid, _, mid = contexte_pont
    piece = _deposer(session, tid, cid, "dfe.pdf", b"%PDF-1.4 fake")

    with pytest.raises(ErreurSourceDepuisPiece, match="tabulaire"):
        importer_source_depuis_piece(
            session, tid, mid, piece_id=int(piece["id"])
        )


def test_piece_autre_contribuable_refusee(session, contexte_pont):
    tid, _, cid_autre, mid = contexte_pont
    piece = _deposer(session, tid, cid_autre, "fec_2025.csv", _FEC_OK)

    with pytest.raises(ErreurSourceDepuisPiece, match="autre client"):
        importer_source_depuis_piece(
            session, tid, mid, piece_id=int(piece["id"])
        )


def test_piece_inconnue_introuvable(session, contexte_pont):
    tid, _, _, mid = contexte_pont
    with pytest.raises(ErreurSourceDepuisPiece, match="introuvable"):
        importer_source_depuis_piece(session, tid, mid, piece_id=999999)
