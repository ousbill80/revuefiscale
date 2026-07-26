"""Smoke pièces contribuable — upload session, rattachement, extraction mockée.

Sans clés LLM réelles : mock du JSON d'extraction. Prérequis : DB + migrate 014.
Usage :
  cd revue-fiscale-v5 && .venv/bin/python -m backend.scripts.smoke_pieces_contribuable
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

from backend.abonne.extraction_identite import proposer_identite
from backend.abonne.pieces_contribuable_service import (
    deposer_piece,
    lister_pieces,
    rattacher_session,
)
from backend.db import Fabrique
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant


def main() -> int:
    session = Fabrique()
    try:
        ok_table = session.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = 'piece_contribuable'"
            )
        ).scalar_one()
        if int(ok_table) == 0:
            print("FAIL — table piece_contribuable absente. Lancez : make migrate")
            return 1

        tid = session.execute(
            text(
                "INSERT INTO tenant (denomination, type, palier) "
                "VALUES ('Smoke Pieces', 'cabinet', 'standard') RETURNING id"
            )
        ).scalar_one()
        session.flush()
        sid = str(uuid.uuid4())
        cid = 0

        with contexte_tenant(session, int(tid)):
            piece = deposer_piece(
                session,
                int(tid),
                type_piece="dfe",
                nom_fichier="dfe-smoke.txt",
                contenu=(
                    b"DFE\nRaison sociale : SMOKE DEMO SARL\n"
                    b"NCC : 1234567A\nRegime : RNI\nForme : SARL\n"
                ),
                content_type="text/plain",
                session_upload=sid,
            )
            assert piece["session_upload"] == sid

            fake_json = json.dumps(
                {
                    "champs": {
                        "denomination": "SMOKE DEMO SARL",
                        "ncc": "1234567A",
                        "regime_fiscal": "RNI",
                        "forme_juridique": "SARL",
                        "forme": "pm",
                    },
                    "citations": [
                        {
                            "champ": "ncc",
                            "piece_id": piece["id"],
                            "extrait": "NCC : 1234567A",
                            "confiance": 0.9,
                        }
                    ],
                    "notes": "smoke mock",
                }
            )

            with (
                patch(
                    "backend.abonne.extraction_identite.llm_configure",
                    return_value=True,
                ),
                patch(
                    "backend.socle.llm_providers.appeler_chat",
                    return_value=(fake_json, "deepseek", ("moonshot",)),
                ),
            ):
                prop = proposer_identite(session, int(tid), session_upload=sid)

            assert prop["disponible"] is True
            assert prop["provider"] == "deepseek"
            assert prop["failover_depuis"] == ["moonshot"]
            assert prop["champs"]["regime_fiscal"] == "reel"
            assert prop["champs"]["forme_juridique"] == "SARL"
            # Message métier : jamais de nom de fournisseur
            assert "DeepSeek" not in (prop["message"] or "")
            assert "Moonshot" not in (prop["message"] or "")
            assert "champs_manquants" in prop

            cid = int(
                session.execute(
                    text(
                        "INSERT INTO contribuable ("
                        "tenant_id, denomination, ncc, forme, regime_fiscal, "
                        "forme_juridique, commune, centre_impots, siege_social, "
                        "capital_social, mois_cloture, activite_principale"
                        ") VALUES ("
                        ":t, 'SMOKE DEMO SARL', '1234567A', 'pm', 'reel', 'SARL', "
                        "'Abidjan', 'Centre des Impôts de Cocody', "
                        "'Cocody Angré', 1000000, 12, 'Commerce'"
                        ") RETURNING id"
                    ),
                    {"t": tid},
                ).scalar_one()
            )

            rattachees = rattacher_session(
                session, session_upload=sid, contribuable_id=cid
            )
            assert len(rattachees) == 1
            assert rattachees[0]["contribuable_id"] == cid
            assert lister_pieces(session, contribuable_id=cid)

        session.commit()
        print(
            "OK — smoke pièces : upload session → extraction mock "
            "(failover loggé, message sans provider, mapping RNI/SARL) → "
            f"rattachement contribuable #{cid} tenant #{tid}"
        )
        return 0
    except Exception as e:
        session.rollback()
        print(f"FAIL — {e}", file=sys.stderr)
        return 1
    finally:
        try:
            effacer_contexte_tenant(session)
        except Exception:
            pass
        session.close()


if __name__ == "__main__":
    racine = Path(__file__).resolve().parents[2]
    if str(racine) not in sys.path:
        sys.path.insert(0, str(racine))
    raise SystemExit(main())
