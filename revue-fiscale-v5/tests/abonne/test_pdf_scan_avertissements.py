"""PDF scan → avertissement explicite si pdftoppm absent."""
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import text

from backend.abonne.extraction_identite import (
    ErreurExtractionIdentite,
    proposer_identite,
)
from backend.abonne.pieces_contribuable_service import deposer_piece
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.socle import poppler_outils

pytestmark = pytest.mark.db


@pytest.fixture
def tenant_pdf(session, tmp_path, monkeypatch):
    monkeypatch.setenv("PIECES_DIR", str(tmp_path / "pieces"))
    import backend.socle.stockage_pieces as stock

    monkeypatch.setattr(stock, "_RACINE", Path(tmp_path / "pieces"))
    tid = session.execute(
        text(
            "INSERT INTO tenant (denomination, type, palier) "
            "VALUES ('Cab PDF Scan', 'cabinet', 'standard') RETURNING id"
        )
    ).scalar_one()
    session.flush()
    return tid


def test_pdf_vers_images_sans_pdftoppm():
    from backend.abonne.extraction_identite import _pdf_vers_images

    with patch(
        "backend.socle.poppler_outils.chemin_pdftoppm", return_value=None
    ):
        images, avis = _pdf_vers_images(b"%PDF-1.4\n%%EOF\n")
    assert images == []
    assert avis is not None
    assert "pdftoppm" in avis.casefold()
    assert "poppler" in poppler_outils.MESSAGE_PDFTOPPM_ABSENT.casefold()


def test_proposer_propage_avertissement_pdftoppm(session, tenant_pdf):
    n = session.execute(
        text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'piece_contribuable'"
        )
    ).scalar_one()
    if int(n) == 0:
        pytest.skip("migration 014 non appliquée")

    tid = tenant_pdf
    sid = "pdf-scan-session-aaaa-bbbb-cccc-dddd"
    pdf_brut = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

    with contexte_tenant(session, tid):
        deposer_piece(
            session,
            tid,
            type_piece="dfe",
            nom_fichier="dfe-scan.pdf",
            contenu=pdf_brut,
            content_type="application/pdf",
            session_upload=sid,
        )
        with (
            patch(
                "backend.abonne.extraction_identite.llm_configure",
                return_value=True,
            ),
            patch(
                "backend.socle.poppler_outils.chemin_pdftotext",
                return_value="/usr/bin/pdftotext",
            ),
            patch(
                "backend.socle.poppler_outils.pdftoppm_disponible",
                return_value=False,
            ),
            patch(
                "backend.socle.poppler_outils.chemin_pdftoppm",
                return_value=None,
            ),
            patch(
                "backend.abonne.extraction_identite.subprocess.run"
            ) as run_mock,
            patch(
                "backend.abonne.extraction_identite._appeler_llm",
                side_effect=ErreurExtractionIdentite("mock LLM"),
            ),
        ):
            run_mock.return_value.stdout = ""
            run_mock.return_value.returncode = 0
            prop = proposer_identite(session, tid, session_upload=sid)

        assert prop["disponible"] is False
        avis = " ".join(prop.get("avertissements") or [])
        msg = (prop.get("message") or "").casefold()
        assert "pdftoppm" in avis.casefold() or "pdftoppm" in msg

    effacer_contexte_tenant(session)
