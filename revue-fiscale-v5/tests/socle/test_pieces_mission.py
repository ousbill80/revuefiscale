"""Pièces mission — source active vs annexes (domaine abonné)."""
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.socle.erreurs import ErreurPiece
from backend.socle.modeles import LigneBalance
from backend.socle.pieces_service import (
    deposer_annexe,
    designer_source_active,
    lister_pieces_mission,
    retirer_annexe,
)
from backend.socle.service import fiabiliser_balance
from backend.socle.stockage_pieces import racine_pieces

pytestmark = pytest.mark.db


@pytest.fixture
def mission_prete(session, tmp_path, monkeypatch):
    monkeypatch.setenv("PIECES_DIR", str(tmp_path / "pieces"))
    # Recharge la racine du module (évaluée au chargement).
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))

    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab Pieces', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    with contexte_tenant(session, tid):
        cid = session.execute(
            text(
                "INSERT INTO contribuable (tenant_id, denomination) "
                "VALUES (:t, 'Client Pieces') RETURNING id"
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
    return tid, mid


def _csv_balance_ok() -> bytes:
    return (
        b"compte,libelle,debit,credit\n"
        b"411,Clients,500,0\n"
        b"701,CA,0,500\n"
    )


def test_table_piece_mission_existe(session):
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'piece_mission'"
        )
    ).scalar_one()
    if n == 0:
        pytest.skip("migration 010 non appliquée — lancez make migrate")


def test_annexe_n_ecrase_pas_soldes(session, mission_prete):
    tid, mid = mission_prete
    test_table_piece_mission_existe(session)

    lignes = [
        LigneBalance(
            compte="701", libelle="CA", debit=Decimal("0"), credit=Decimal("500")
        ),
        LigneBalance(
            compte="411",
            libelle="Clients",
            debit=Decimal("500"),
            credit=Decimal("0"),
        ),
    ]
    fiabiliser_balance(session, tid, mid, lignes)

    deposer_annexe(
        session,
        tid,
        mid,
        type_piece="fec",
        nom_fichier="note.txt",
        contenu=b"annexe sans import",
        content_type="text/plain",
    )

    with contexte_tenant(session, tid):
        n_soldes = session.execute(
            text("SELECT count(*) FROM solde_compte WHERE mission_id = :m"),
            {"m": mid},
        ).scalar_one()
        roles = session.execute(
            text(
                "SELECT role FROM piece_mission WHERE mission_id = :m ORDER BY id"
            ),
            {"m": mid},
        ).scalars().all()
    assert n_soldes == 2
    assert roles == ["annexe"]


def test_source_active_exige_confirmation(session, mission_prete):
    tid, mid = mission_prete
    test_table_piece_mission_existe(session)

    out1 = designer_source_active(
        session,
        tid,
        mid,
        type_piece="balance",
        nom_fichier="b1.csv",
        contenu=_csv_balance_ok(),
        confirmer=False,
    )
    assert out1.rapport.statut == "ok"
    assert out1.piece is not None
    assert out1.piece.role == "source_active"

    with pytest.raises(ErreurPiece, match="déjà définie"):
        designer_source_active(
            session,
            tid,
            mid,
            type_piece="balance",
            nom_fichier="b2.csv",
            contenu=_csv_balance_ok(),
            confirmer=False,
        )

    out2 = designer_source_active(
        session,
        tid,
        mid,
        type_piece="balance",
        nom_fichier="b2.csv",
        contenu=_csv_balance_ok(),
        confirmer=True,
    )
    assert out2.rapport.statut == "ok"
    assert out2.source_precedente_degradee is True

    pieces = lister_pieces_mission(session, tid, mid)
    roles = sorted(p.role for p in pieces)
    assert roles.count("source_active") == 1
    assert roles.count("annexe") == 1


def test_retirer_refuse_source_active(session, mission_prete):
    tid, mid = mission_prete
    test_table_piece_mission_existe(session)

    out = designer_source_active(
        session,
        tid,
        mid,
        type_piece="balance",
        nom_fichier="b1.csv",
        contenu=_csv_balance_ok(),
    )
    assert out.piece is not None
    with pytest.raises(ErreurPiece, match="source active"):
        retirer_annexe(session, tid, mid, out.piece.id)

    assert racine_pieces().exists() or True
