"""Routes API corpus editorial."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.corpus.ingestion import ingerer_document, seed_corpus_demo
from backend.corpus.recherche import recherche_hybride
from backend.editorial.dependances import StaffEditorialDep
from backend.plateforme.dependances import SessionDep

router = APIRouter(prefix="/api/v1/editorial/corpus", tags=["corpus"])


class IngestionIn(BaseModel):
    titre: str = Field(min_length=1, max_length=500)
    type: str = Field(min_length=1, max_length=80)
    millesime: int | None = None
    texte_brut: str = Field(min_length=1)


@router.post("/ingerer")
def api_ingerer(
    corps: IngestionIn,
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    resultat = ingerer_document(
        session,
        titre=corps.titre,
        type=corps.type,
        millesime=corps.millesime,
        texte_brut=corps.texte_brut,
    )
    return {
        "source_document_id": resultat.source_document_id,
        "articles": resultat.articles,
        "fragments": resultat.fragments,
    }


@router.get("/rechercher")
def api_rechercher(
    _staff: StaffEditorialDep,
    session: SessionDep,
    q: str = Query(min_length=1, description="Requete de recherche"),
    limite: int = Query(default=10, ge=1, le=50),
    type: str | None = Query(
        default=None,
        description="Filtre source_document.type (ex. cgi, annexe, demo)",
    ),
    millesime: int | None = Query(
        default=None,
        description="Filtre strict millésime (ex. 2026)",
    ),
) -> list[dict[str, object]]:
    types = [type] if type else None
    return recherche_hybride(
        session,
        q,
        limite=limite,
        types=types,
        millesime=millesime,
        millesime_prioritaire=millesime if millesime is not None else 2026,
    )


@router.post("/seed-demo")
def api_seed_demo(_staff: StaffEditorialDep, session: SessionDep) -> dict[str, object]:
    resultat = seed_corpus_demo(session)
    if resultat is None:
        return {"deja_present": True}
    return {
        "source_document_id": resultat.source_document_id,
        "articles": resultat.articles,
        "fragments": resultat.fragments,
        "deja_present": False,
    }
