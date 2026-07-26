"""Routes admin editorial — versions du referentiel + file propositions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.editorial import pistes_annexe, pistes_cgi
from backend.editorial.acceptation_proposition import (
    ErreurAcceptation,
    traiter_acceptation,
)
from backend.editorial.contexte_cgi import construire_contexte_cgi
from backend.editorial.croisement_cgi import (
    charger_catalogue_croisement,
    enrichir_entrees_croisement,
    index_classes_croisement,
)
from backend.editorial.dependances import StaffEditorialDep
from backend.editorial.inventaire_a_confirmer import (
    construire_file_validation,
    construire_inventaire,
    marquer_en_revue,
    remettre_en_attente,
    rendre_csv,
)
from backend.editorial.publication import (
    ErreurEditorial,
    charger_regle_yaml,
    creer_version_brouillon,
    publier_version,
)
from backend.plateforme.dependances import SessionDep

router = APIRouter(prefix="/api/v1/editorial", tags=["editorial"])

RACINE_REFERENTIEL = Path(__file__).resolve().parents[2] / "referentiel"


class VersionIn(BaseModel):
    libelle: str = Field(min_length=1, max_length=100)
    note: str | None = None


class PublierIn(BaseModel):
    libelle: str
    par: str = Field(min_length=1, max_length=200)


class ChargerYamlIn(BaseModel):
    version_id: int
    fichier: str = Field(description="Nom relatif sous referentiel/, ex. BIC-CHG-18G-DONS.yaml")


class PropositionStatutIn(BaseModel):
    statut: Literal["acceptee", "corrigee", "rejetee"]
    commentaire: str | None = None
    # Acceptation YAML contrôlée (domaine éditorial) — défaut = statut seul.
    mode: Literal["statut_seul", "preparer_patch", "appliquer"] = "statut_seul"
    retirer_mention_a_confirmer: bool = False


class EnRevueIn(BaseModel):
    """Workflow éditeur — ne purge aucun ``a_confirmer`` YAML."""

    entree_id: str = Field(
        min_length=3,
        max_length=200,
        description="Identifiant file, ex. BIC-CHG-18G-DONS#0",
    )
    note_editeur: str | None = Field(default=None, max_length=2000)


class RemettreAttenteIn(BaseModel):
    entree_id: str = Field(min_length=3, max_length=200)


@router.get("/versions")
def api_lister_versions(
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> list[dict[str, object]]:
    rows = session.execute(
        text(
            "SELECT id, libelle, publiee_le, publiee_par, note "
            "FROM version_referentiel ORDER BY id"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/a-confirmer")
def api_lister_a_confirmer(
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    """Liste des mentions ``a_confirmer`` + workflow ``en_revue`` (éditeur 2AàZ).

    Ne modifie aucun YAML. Le statut ``en_revue`` est un overlay workflow
    (note éditeur) — **pas** une validation du fond fiscal.
    Enrichit les pistes Annexe (~8) et CGI (~7) 2026 (badges + liens propositions).
    """
    inventaire = construire_inventaire(RACINE_REFERENTIEL)
    file_val = construire_file_validation(inventaire)
    cat_annexe = pistes_annexe.charger_catalogue_pistes()
    cat_cgi = pistes_cgi.charger_catalogue_pistes()
    liens_annexe = pistes_annexe.lier_propositions_ouvertes(session, cat_annexe)
    liens_cgi = pistes_cgi.lier_propositions_ouvertes(session, cat_cgi)
    ids_annexe = pistes_annexe.ids_entrees_pistes(cat_annexe)
    ids_cgi = pistes_cgi.ids_entrees_pistes(cat_cgi)
    entrees_brutes = [e for e in (file_val.get("entrees") or []) if isinstance(e, dict)]
    entrees_enrichies = pistes_annexe.enrichir_entrees_file(entrees_brutes, liens_annexe)
    entrees_enrichies = pistes_cgi.enrichir_entrees_file(entrees_enrichies, liens_cgi)
    cat_croisement = charger_catalogue_croisement()
    idx_croisement = index_classes_croisement(cat_croisement)
    entrees_enrichies = enrichir_entrees_croisement(entrees_enrichies, idx_croisement)
    file_val = {**file_val, "entrees": entrees_enrichies}
    par_regle_file: dict[str, list[dict[str, object]]] = {}
    for entree in entrees_enrichies:
        rid = str(entree.get("identifiant") or "")
        par_regle_file.setdefault(rid, []).append(
            {
                "id": entree.get("id"),
                "index": entree.get("index"),
                "champ_a_valider": entree.get("texte"),
                "categorie": entree.get("categorie"),
                "priorite": entree.get("priorite"),
                "statut": entree.get("statut"),
                "fichier": entree.get("fichier"),
                "impot": entree.get("impot"),
                "reference_legale": entree.get("reference_legale"),
                "note_editeur": entree.get("note_editeur"),
                "revue_par": entree.get("revue_par"),
                "revue_le": entree.get("revue_le"),
                "piste_annexe": entree.get("piste_annexe"),
                "piste_cgi": entree.get("piste_cgi"),
                "piste_sourcee": entree.get("piste_sourcee"),
                "proposition_id": entree.get("proposition_id"),
                "proposition_id_annexe": entree.get("proposition_id_annexe"),
                "proposition_id_cgi": entree.get("proposition_id_cgi"),
                "piste_annexe_meta": entree.get("piste_annexe_meta"),
                "piste_cgi_meta": entree.get("piste_cgi_meta"),
                "peut_preparer_patch": entree.get("peut_preparer_patch"),
                "peut_appliquer": entree.get("peut_appliquer"),
                "retirer_a_confirmer_autorise": entree.get(
                    "retirer_a_confirmer_autorise"
                ),
                "classe_croisement": entree.get("classe_croisement"),
                "croisement_cgi_meta": entree.get("croisement_cgi_meta"),
            }
        )
    n_sourcees = len(ids_annexe | ids_cgi)
    comptes_croisement = (cat_croisement or {}).get("comptes") or {}
    return {
        "total_mentions": inventaire["total_mentions"],
        "total_regles_concernees": inventaire["total_regles_concernees"],
        "comptes_par_categorie": inventaire["comptes_par_categorie"],
        "comptes_par_priorite": inventaire["comptes_par_priorite"],
        "comptes_par_statut": file_val.get("comptes_par_statut") or {},
        "libelles_priorite": inventaire["libelles_priorite"],
        "empreinte": inventaire["empreinte"],
        "avertissement": inventaire["avertissement"],
        "note_sources": inventaire.get("note_sources"),
        "note_workflow": (
            "Action « Marquer en revue » = statut workflow + note éditeur. "
            "Ne retire aucun a_confirmer du YAML. "
            "Badges « Piste Annexe / CGI » = propositions sourcées "
            "(a_valider_humain), pas un visa. "
            "Vue Faibles = matches croisement faibles (pas promus en claire)."
        ),
        "pistes_annexe": {
            "lot": cat_annexe.get("lot"),
            "n": len(ids_annexe),
            "entree_ids": sorted(ids_annexe),
            "liens": liens_annexe,
            "checklist": cat_annexe.get("checklist"),
            "rapport": cat_annexe.get("rapport"),
            "avertissement": cat_annexe.get("avertissement"),
        },
        "pistes_cgi": {
            "lot": cat_cgi.get("lot"),
            "n": len(ids_cgi),
            "entree_ids": sorted(ids_cgi),
            "liens": liens_cgi,
            "checklist": cat_cgi.get("checklist"),
            "rapport": cat_cgi.get("rapport"),
            "avertissement": cat_cgi.get("avertissement"),
        },
        "pistes_sourcees": {
            "n": n_sourcees,
            "n_annexe": len(ids_annexe),
            "n_cgi": len(ids_cgi),
            "entree_ids": sorted(ids_annexe | ids_cgi),
        },
        "croisement_cgi": {
            "genere_le": (cat_croisement or {}).get("genere_le"),
            "comptes": comptes_croisement,
            "n_faibles": int(comptes_croisement.get("faible") or 0),
            "n_bloques": int(comptes_croisement.get("bloque") or 0),
            "n_claires": int(comptes_croisement.get("claire") or 0),
            "n_contrastes": int(comptes_croisement.get("contraste") or 0),
            "rapport": (cat_croisement or {}).get("rapport_md")
            or "docs/21-cgi-vs-a-confirmer-v2.md",
            "avertissement": (cat_croisement or {}).get("avertissement")
            or (
                "Lancer make croiser-cgi pour générer "
                "referentiel/croisement_cgi_2026.json"
            ),
            "faibles_ne_sont_pas_promues": True,
        },
        "file": file_val,
        "par_regle": inventaire.get("par_regle") or {},
        "par_regle_file": dict(sorted(par_regle_file.items())),
        "par_theme": inventaire["par_theme"],
        "par_priorite": inventaire["par_priorite"],
        "mentions": inventaire["mentions"],
    }


@router.get("/a-confirmer/contexte-cgi")
def api_contexte_cgi_a_confirmer(
    _staff: StaffEditorialDep,
    session: SessionDep,
    entree_id: str = Query(
        min_length=3,
        max_length=200,
        description="Identifiant file, ex. BIC-CHG-18G-DONS#0",
    ),
    millesime: int = Query(default=2026, ge=1990, le=2100),
    limite: int = Query(default=3, ge=1, le=10),
) -> dict[str, object]:
    """Extraits CGI (type=cgi, millésime) pour accélérer la revue — pas un visa."""
    if "#" not in entree_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="entree_id invalide (attendu IDENTIFIANT#index)",
        )
    return construire_contexte_cgi(
        session,
        entree_id=entree_id,
        millesime=millesime,
        limite=limite,
    )


@router.get("/propositions/{proposition_id}/contexte-cgi")
def api_contexte_cgi_proposition(
    proposition_id: int,
    _staff: StaffEditorialDep,
    session: SessionDep,
    millesime: int = Query(default=2026, ge=1990, le=2100),
    limite: int = Query(default=3, ge=1, le=10),
) -> dict[str, object]:
    """Contexte CGI depuis la charge utile d'une proposition éditoriale."""
    row = session.execute(
        text(
            "SELECT id, charge_utile, sources FROM proposition_editoriale "
            "WHERE id = :id"
        ),
        {"id": proposition_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="proposition introuvable"
        )
    charge = row["charge_utile"] or {}
    if isinstance(charge, str):
        charge = json.loads(charge)
    sources = row["sources"] or []
    if isinstance(sources, str):
        sources = json.loads(sources)
    article = charge.get("article_corpus")
    if not article and isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict) and s.get("article_corpus"):
                article = s.get("article_corpus")
                break
    return construire_contexte_cgi(
        session,
        entree_id=str(charge.get("entree_id") or "") or None,
        rule_id=str(charge.get("rule_id") or "") or None,
        article_corpus=str(article) if article else None,
        millesime=millesime,
        limite=limite,
    )


@router.get("/a-confirmer/export.csv")
def api_export_a_confirmer_csv(
    _staff: StaffEditorialDep,
) -> PlainTextResponse:
    """Export CSV checklist fiscaliste — lecture seule, aucune purge YAML."""
    inventaire = construire_inventaire(RACINE_REFERENTIEL)
    return PlainTextResponse(
        content=rendre_csv(inventaire),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="a-confirmer.csv"'
        },
    )


@router.post("/a-confirmer/en-revue")
def api_marquer_en_revue(
    corps: EnRevueIn,
    staff: StaffEditorialDep,
) -> dict[str, object]:
    """Passe une entrée en ``en_revue`` (workflow) — sans purge YAML."""
    try:
        resultat = marquer_en_revue(
            corps.entree_id,
            note_editeur=corps.note_editeur,
            revue_par=staff.email,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    return {
        **resultat,
        "avertissement": (
            "Workflow uniquement — a_confirmer reste dans le YAML. "
            "Aucune validation fiscale implicite."
        ),
    }


@router.post("/a-confirmer/remettre-attente")
def api_remettre_attente(
    corps: RemettreAttenteIn,
    _staff: StaffEditorialDep,
) -> dict[str, object]:
    """Retire l'overlay ``en_revue`` — retour ``en_attente``."""
    try:
        return remettre_en_attente(corps.entree_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e


@router.post("/versions")
def api_creer_version(
    corps: VersionIn,
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    try:
        vid = creer_version_brouillon(session, corps.libelle, note=corps.note)
    except ErreurEditorial as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {"id": vid, "libelle": corps.libelle}


@router.post("/versions/publier")
def api_publier(
    corps: PublierIn,
    staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    par = corps.par or staff.email
    try:
        vid = publier_version(session, corps.libelle, par)
    except ErreurEditorial as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {"id": vid, "libelle": corps.libelle, "publiee": True}


@router.post("/regles/charger")
def api_charger_yaml(
    corps: ChargerYamlIn,
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    chemin = (RACINE_REFERENTIEL / corps.fichier).resolve()
    if not str(chemin).startswith(str(RACINE_REFERENTIEL.resolve())):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="chemin refuse")
    try:
        rv_id = charger_regle_yaml(session, corps.version_id, chemin)
    except ErreurEditorial as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return {"regle_version_id": rv_id, "version_id": corps.version_id}


@router.get("/propositions")
def api_lister_propositions(
    _staff: StaffEditorialDep,
    session: SessionDep,
    statut: str | None = None,
) -> list[dict[str, object]]:
    """File propositions — acceptation contrôlée (statut / patch / appliquer)."""
    if statut:
        rows = session.execute(
            text(
                "SELECT id, deposee_le, source, statut, charge_utile, sources, "
                "traitee_par, traitee_le "
                "FROM proposition_editoriale WHERE statut = :s ORDER BY id DESC"
            ),
            {"s": statut},
        ).mappings().all()
    else:
        rows = session.execute(
            text(
                "SELECT id, deposee_le, source, statut, charge_utile, sources, "
                "traitee_par, traitee_le "
                "FROM proposition_editoriale ORDER BY id DESC LIMIT 200"
            )
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/propositions/{proposition_id}/statut")
def api_statut_proposition(
    proposition_id: int,
    corps: PropositionStatutIn,
    staff: StaffEditorialDep,
    session: SessionDep,
) -> dict[str, object]:
    """Accepter / corriger / rejeter.

    - ``rejetee`` / ``corrigee`` : statut seul, YAML intact.
    - ``acceptee`` + ``mode=statut_seul`` (défaut) : statut seul ; aperçu patch si structuré.
    - ``acceptee`` + ``mode=preparer_patch`` : patch YAML téléchargeable, pas d'écriture.
    - ``acceptee`` + ``mode=appliquer`` : écriture contrôlée (1 champ / 1 mention) + backup
      + journal — retrait ``a_confirmer`` seulement si autorisé par la suggestion
      **et** ``retirer_mention_a_confirmer=true``.
    """
    row = session.execute(
        text(
            "SELECT id, statut, charge_utile, sources FROM proposition_editoriale "
            "WHERE id = :id"
        ),
        {"id": proposition_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="proposition introuvable")
    if row["statut"] != "ouverte":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"proposition deja {row['statut']}",
        )

    charge = row["charge_utile"] or {}
    if isinstance(charge, str):
        charge = json.loads(charge)
    sources = row["sources"] or []
    if isinstance(sources, str):
        sources = json.loads(sources)

    acceptation: dict[str, object] | None = None
    if corps.statut == "acceptee" and corps.mode != "statut_seul":
        try:
            acceptation = traiter_acceptation(
                charge,
                par=staff.email,
                mode=corps.mode,
                retirer_mention_a_confirmer=corps.retirer_mention_a_confirmer,
                proposition_id=proposition_id,
                sources=sources if isinstance(sources, list) else [],
            )
        except ErreurAcceptation as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
            ) from e
    elif corps.statut == "acceptee":
        acceptation = traiter_acceptation(
            charge,
            par=staff.email,
            mode="statut_seul",
            retirer_mention_a_confirmer=corps.retirer_mention_a_confirmer,
            proposition_id=proposition_id,
            sources=sources if isinstance(sources, list) else [],
        )

    # preparer_patch : ne change pas le statut (humain télécharge puis décide)
    if corps.statut == "acceptee" and corps.mode == "preparer_patch":
        return {
            "id": proposition_id,
            "statut": "ouverte",
            "traitee_par": None,
            "commentaire": corps.commentaire,
            "acceptation": acceptation,
            "note": "Patch préparatoire — proposition reste ouverte, YAML non modifié",
        }

    session.execute(
        text(
            "UPDATE proposition_editoriale "
            "SET statut = :s, traitee_par = :p, traitee_le = now() "
            "WHERE id = :id"
        ),
        {"s": corps.statut, "p": staff.email, "id": proposition_id},
    )
    return {
        "id": proposition_id,
        "statut": corps.statut,
        "traitee_par": staff.email,
        "commentaire": corps.commentaire,
        "acceptation": acceptation,
        "note": (
            "Workflow statut — YAML intact"
            if corps.statut != "acceptee" or corps.mode == "statut_seul"
            else "Acceptation traitée (voir acceptation.yaml_modifie)"
        ),
    }


@router.get("/contestations")
def api_lister_contestations(
    _staff: StaffEditorialDep,
    session: SessionDep,
) -> list[dict[str, object]]:
    """Contestations abonnes — lecture via SECURITY DEFINER (pas de balances)."""
    rows = session.execute(
        text("SELECT * FROM editorial_lister_contestations()")
    ).mappings().all()
    return [dict(r) for r in rows]
