"""Routes agent fiscal + propositions + usages editoriaux.

Tous ces endpoints sont des outils de production editeur (2AàZ) :
staff editorial | ops requis — jamais ouverts anonymement.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.agent.boucle import repondre
from backend.agent.outils import ErreurOutil, proposer_regle, simuler_regle
from backend.agent.usages import conversion_assistee_regle, differentiel_annexe
from backend.editorial.dependances import StaffEditorialDep
from backend.plateforme.dependances import SessionDep

router_agent = APIRouter(prefix="/api/v1/agent", tags=["agent"])
router_propositions = APIRouter(prefix="/api/v1/editorial", tags=["editorial"])
router_usages = APIRouter(prefix="/api/v1/editorial/usages", tags=["usages"])


class QuestionIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    tenant_id: int | None = None


class PropositionIn(BaseModel):
    charge_utile: dict[str, Any]
    sources: list[Any] = Field(default_factory=list)
    source: str = "copilote"


class SimulationIn(BaseModel):
    tenant_id: int
    mission_id: int
    regle_id: str
    reponses: dict[str, Any] = Field(default_factory=dict)


class DifferentielIn(BaseModel):
    texte_ancien: str
    texte_nouveau: str


class ConversionIn(BaseModel):
    texte_article: str = Field(min_length=1)


@router_agent.post("/question")
def api_question(
    corps: QuestionIn,
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    rep = repondre(session, corps.question, tenant_id=corps.tenant_id)
    return {
        "statut": rep.statut,
        "texte": rep.texte,
        "references": rep.references,
        "citations": rep.citations,
        "fragments": rep.fragments,
        "invention": rep.invention,
    }


@router_agent.post("/simuler")
def api_simuler(
    corps: SimulationIn,
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    try:
        c = simuler_regle(
            session,
            tenant_id=corps.tenant_id,
            mission_id=corps.mission_id,
            regle_id=corps.regle_id,
            reponses=corps.reponses,
        )
    except ErreurOutil as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {
        "regle_id": c.regle_id,
        "declenchee": c.declenchee,
        "montant": str(c.montant) if c.montant is not None else None,
        "sens": c.sens,
        "niveau_risque": c.niveau_risque,
        "detail": c.detail,
    }


@router_propositions.post("/propositions")
def api_proposition(
    corps: PropositionIn,
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    pid = proposer_regle(
        session,
        {
            "charge_utile": corps.charge_utile,
            "sources": corps.sources,
            "source": corps.source,
        },
    )
    return {"id": pid, "statut": "ouverte"}


@router_usages.post("/differentiel")
def api_differentiel(
    corps: DifferentielIn,
    _staff: StaffEditorialDep,
) -> dict[str, object]:
    diffs = differentiel_annexe(corps.texte_ancien, corps.texte_nouveau)
    return {"changements": diffs, "n": len(diffs)}


@router_usages.post("/conversion-assistee")
def api_conversion(
    corps: ConversionIn,
    _staff: StaffEditorialDep,
) -> dict[str, object]:
    return conversion_assistee_regle(corps.texte_article)
