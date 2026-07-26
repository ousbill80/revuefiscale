"""Preuve de résolution d'un risque — verdict IA consultatif, l'humain décide.

Le passage d'un risque à « resolu » exige un justificatif déposé dans le
registre. L'IA rend un verdict (probante / insuffisante / sans_rapport /
indisponible) ; la résolution est ``acceptee`` si probante, sinon ``forcee``
avec un motif obligatoire. Aucun calcul fiscal.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

logger = logging.getLogger(__name__)

VERDICTS: Final[frozenset[str]] = frozenset(
    {"probante", "insuffisante", "sans_rapport", "indisponible"}
)
VERDICTS_IA: Final[frozenset[str]] = frozenset(
    {"probante", "insuffisante", "sans_rapport"}
)
JUSTIFICATION_MAX: Final[int] = 2000

MESSAGE_PREUVE_REQUISE: Final[str] = (
    "Le statut \"Résolu\" exige une preuve de résolution. "
    "Joignez le justificatif via le registre."
)
MESSAGE_MOTIF_FORCAGE_REQUIS: Final[str] = (
    "Le verdict IA n'est pas « probante » : un motif de résolution "
    "malgré le verdict est obligatoire."
)
MESSAGE_ANALYSE_INDISPONIBLE: Final[str] = (
    "Analyse de la preuve indisponible pour le moment. "
    "Le verdict IA est consultatif — vous pouvez forcer la résolution "
    "en motivant votre décision."
)
MESSAGE_DOCUMENT_INEXPLOITABLE: Final[str] = (
    "Document inexploitable (ni texte ni image analysable). "
    "Le verdict IA est consultatif — vous pouvez forcer la résolution "
    "en motivant votre décision."
)

_PROMPT_PREUVE = """Tu es un assistant de revue fiscale en Côte d'Ivoire.
On te fournit le contexte d'un risque fiscal identifié chez un contribuable
et un document déposé comme preuve de résolution de ce risque (quittance,
déclaration rectificative, attestation, courrier DGI, écriture comptable…).

Ta mission : dire si le document constitue une preuve de résolution du
risque décrit. Verdict :
- "probante" : le document démontre clairement que le risque est traité
  (paiement, régularisation, décharge…) et se rapporte bien à ce risque.
- "insuffisante" : le document se rapporte au risque mais ne suffit pas à
  démontrer sa résolution (partiel, non daté, non signé, montant incohérent…).
- "sans_rapport" : le document n'a pas de lien identifiable avec ce risque.

Règles strictes :
- Ne calcule aucun montant fiscal, taxe, pénalité ou plafonnement.
- N'invente rien : appuie-toi uniquement sur le contenu lisible du document.
- Si une zone est floue ou illisible, dis-le dans la justification.
- Français professionnel, concis. Pas de nom de fournisseur technique.

Réponds UNIQUEMENT en JSON valide :
{
  "verdict": "probante" | "insuffisante" | "sans_rapport",
  "justification": "…",
  "elements_retrouves": ["…"]
}
"""


class ErreurPreuveResolution(Exception):
    """Échec métier preuve de résolution."""


def valider_verdict_ia(brut: Any) -> dict[str, Any]:
    """Coercition tolérante du JSON LLM — pure, testable.

    Verdict hors référentiel → ``indisponible`` ; justification coercée str.
    """
    src = brut if isinstance(brut, dict) else {}
    verdict = str(src.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS_IA:
        verdict = "indisponible"
    justification = str(src.get("justification") or "").strip()
    if not justification:
        justification = (
            MESSAGE_ANALYSE_INDISPONIBLE
            if verdict == "indisponible"
            else "Verdict rendu sans justification détaillée."
        )
    elements: list[str] = []
    brut_elements = src.get("elements_retrouves")
    for e in brut_elements if isinstance(brut_elements, list) else []:
        v = str(e or "").strip()
        if v:
            elements.append(v[:300])
    return {
        "verdict": verdict,
        "justification": justification[:JUSTIFICATION_MAX],
        "elements_retrouves": elements[:20],
    }


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    cree = row.get("cree_le")
    return {
        "id": int(row["id"]),
        "risque_id": int(row["risque_id"]),
        "nom_fichier": str(row["nom_fichier"]),
        "format": str(row["format"]),
        "taille_octets": (
            int(row["taille_octets"])
            if row.get("taille_octets") is not None
            else None
        ),
        "verdict_ia": row.get("verdict_ia"),
        "justification_ia": row.get("justification_ia"),
        "modele": row.get("modele"),
        "decision": row.get("decision"),
        "motif_forcage": row.get("motif_forcage"),
        "auteur": row.get("auteur"),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
    }


_COLONNES = (
    "id, risque_id, nom_fichier, format, chemin_stockage, taille_octets, "
    "verdict_ia, justification_ia, modele, decision, motif_forcage, "
    "auteur, cree_le"
)


def _verifier_fichier(
    nom_fichier: str, content_type: str | None, brut: bytes
) -> str:
    """Garde-fous upload (mêmes règles que backend/abonne/routes.py)."""
    from backend.abonne.routes import (
        _FORMATS_PAR_CONTENT_TYPE,
        _FORMATS_PAR_EXTENSION,
        MESSAGE_FORMAT_NON_SUPPORTE,
        MESSAGE_PREUVE_TROP_VOLUMINEUSE,
        TAILLE_MAX_PREUVE_OCTETS,
        _format_reel_piece,
    )

    if not brut:
        raise ErreurPreuveResolution("fichier vide")
    if len(brut) > TAILLE_MAX_PREUVE_OCTETS:
        raise ErreurPreuveResolution(MESSAGE_PREUVE_TROP_VOLUMINEUSE)
    fmt = _format_reel_piece(brut)
    if fmt is None:
        raise ErreurPreuveResolution(MESSAGE_FORMAT_NON_SUPPORTE)
    ext = Path(nom_fichier or "").suffix.lower()
    if ext and _FORMATS_PAR_EXTENSION.get(ext) != fmt:
        raise ErreurPreuveResolution(MESSAGE_FORMAT_NON_SUPPORTE)
    ct = (content_type or "").split(";")[0].strip().lower()
    if (
        ct
        and ct != "application/octet-stream"
        and _FORMATS_PAR_CONTENT_TYPE.get(ct) != fmt
    ):
        raise ErreurPreuveResolution(MESSAGE_FORMAT_NON_SUPPORTE)
    return fmt


def enregistrer_preuve(
    session: Session,
    tenant_id: int,
    risque_id: int,
    *,
    nom_fichier: str,
    content_type: str | None,
    brut: bytes,
    auteur: str | None = None,
) -> dict[str, Any]:
    from backend.socle.stockage_pieces import ecrire_piece_contribuable

    nom = (nom_fichier or "").strip() or "preuve"
    fmt = _verifier_fichier(nom, content_type, brut)
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT id FROM risque WHERE id = :id"),
            {"id": risque_id},
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurPreuveResolution(f"risque {risque_id} introuvable")
        chemin = ecrire_piece_contribuable(
            tenant_id, f"risque_{risque_id}", nom, brut
        )
        row = session.execute(
            text(
                "INSERT INTO preuve_resolution_risque "  # noqa: S608
                "(tenant_id, risque_id, nom_fichier, format, "
                "chemin_stockage, taille_octets, auteur) "
                "VALUES (:t, :r, :nom, :fmt, :chemin, :taille, :aut) "
                f"RETURNING {_COLONNES}"
            ),
            {
                "t": tenant_id,
                "r": risque_id,
                "nom": nom,
                "fmt": fmt,
                "chemin": chemin,
                "taille": len(brut),
                "aut": (auteur or "").strip() or None,
            },
        ).mappings().one()
        session.flush()
        return _serialiser(dict(row))


def lister_preuves(
    session: Session, tenant_id: int, risque_id: int
) -> list[dict[str, Any]]:
    with contexte_tenant(session, tenant_id):
        existe = session.execute(
            text("SELECT id FROM risque WHERE id = :id"),
            {"id": risque_id},
        ).scalar_one_or_none()
        if existe is None:
            raise ErreurPreuveResolution(f"risque {risque_id} introuvable")
        rows = session.execute(
            text(
                f"SELECT {_COLONNES} FROM preuve_resolution_risque "  # noqa: S608
                "WHERE risque_id = :r ORDER BY cree_le DESC, id DESC"
            ),
            {"r": risque_id},
        ).mappings().all()
        return [_serialiser(dict(r)) for r in rows]


def _lire_preuve(
    session: Session, preuve_id: int
) -> dict[str, Any]:
    row = session.execute(
        text(
            f"SELECT {_COLONNES} FROM preuve_resolution_risque "  # noqa: S608
            "WHERE id = :id"
        ),
        {"id": preuve_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurPreuveResolution(f"preuve {preuve_id} introuvable")
    return dict(row)


def _contexte_risque(session: Session, risque_id: int) -> dict[str, Any]:
    row = session.execute(
        text(
            "SELECT r.libelle, r.impot, r.reference_legale, "
            "r.exercice_origine, r.montant_estime, r.penalites_estimees, "
            "r.probabilite, c.denomination "
            "FROM risque r JOIN contribuable c ON c.id = r.contribuable_id "
            "WHERE r.id = :id"
        ),
        {"id": risque_id},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurPreuveResolution(f"risque {risque_id} introuvable")
    d = dict(row)
    return {
        "intitule": d.get("libelle"),
        "impot": d.get("impot"),
        "reference_legale": d.get("reference_legale"),
        "exercice_origine": d.get("exercice_origine"),
        "exposition_estimee_fcfa": (
            str(d["montant_estime"])
            if d.get("montant_estime") is not None
            else None
        ),
        "penalites_estimees_fcfa": (
            str(d["penalites_estimees"])
            if d.get("penalites_estimees") is not None
            else None
        ),
        "probabilite": d.get("probabilite"),
        "contribuable": d.get("denomination"),
    }


def _preparer_document(
    nom: str, brut: bytes
) -> tuple[str, list[tuple[str, bytes]], bool, bool]:
    """Retourne (texte, images, besoin_vision, exploitable)."""
    from backend.abonne.extraction_identite import (
        _EXT_IMAGES,
        MAX_OCTETS_IMAGE_VISION,
        _extraire_texte_fichier,
        _pdf_vers_images,
        _texte_insuffisant,
    )
    from backend.socle import llm_providers

    suffixe = Path(nom).suffix.lower()
    texte = _extraire_texte_fichier(nom, brut)
    images: list[tuple[str, bytes]] = []
    besoin_vision = False
    exploitable = False
    if suffixe in _EXT_IMAGES:
        besoin_vision = True
        if len(brut) <= MAX_OCTETS_IMAGE_VISION:
            images.append((llm_providers.mime_depuis_nom(nom), brut))
            exploitable = True
            texte = "[Image : lecture via l'image jointe.]"
    elif suffixe == ".pdf":
        if _texte_insuffisant(texte):
            besoin_vision = True
            pages, _ = _pdf_vers_images(brut)
            images.extend(pages)
            if pages:
                exploitable = True
                texte = "[PDF scanné : lecture via les images jointes.]"
        else:
            exploitable = True
    elif not _texte_insuffisant(texte):
        exploitable = True
    return texte[:12000], images, besoin_vision, exploitable


def _mettre_a_jour_verdict(
    session: Session,
    tenant_id: int,
    preuve_id: int,
    *,
    verdict: str,
    justification: str,
    modele: str | None,
) -> dict[str, Any]:
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "UPDATE preuve_resolution_risque "  # noqa: S608
                "SET verdict_ia = :v, justification_ia = :j, modele = :m "
                f"WHERE id = :id RETURNING {_COLONNES}"
            ),
            {
                "v": verdict,
                "j": justification[:JUSTIFICATION_MAX],
                "m": modele,
                "id": preuve_id,
            },
        ).mappings().one()
        session.flush()
        return _serialiser(dict(row))


def analyser_preuve(
    session: Session, tenant_id: int, preuve_id: int
) -> dict[str, Any]:
    """Analyse IA du justificatif — verdict consultatif, jamais bloquant."""
    from backend.abonne.extraction_identite import (
        ErreurExtractionIdentite,
        _appeler_llm,
        llm_configure,
    )
    from backend.socle.stockage_pieces import lire_piece

    with contexte_tenant(session, tenant_id):
        preuve = _lire_preuve(session, preuve_id)
        contexte = _contexte_risque(session, int(preuve["risque_id"]))

    if not llm_configure():
        return _mettre_a_jour_verdict(
            session,
            tenant_id,
            preuve_id,
            verdict="indisponible",
            justification=MESSAGE_ANALYSE_INDISPONIBLE,
            modele=None,
        )

    try:
        brut = lire_piece(str(preuve["chemin_stockage"]))
    except OSError:
        return _mettre_a_jour_verdict(
            session,
            tenant_id,
            preuve_id,
            verdict="indisponible",
            justification=MESSAGE_DOCUMENT_INEXPLOITABLE,
            modele=None,
        )

    texte, images, besoin_vision, exploitable = _preparer_document(
        str(preuve["nom_fichier"]), brut
    )
    if not exploitable:
        return _mettre_a_jour_verdict(
            session,
            tenant_id,
            preuve_id,
            verdict="indisponible",
            justification=MESSAGE_DOCUMENT_INEXPLOITABLE,
            modele=None,
        )

    user = (
        "Contexte du risque (JSON) :\n"
        + json.dumps(contexte, ensure_ascii=False)
        + f"\n\nDocument déposé ({preuve['nom_fichier']}) :\n{texte}"
    )
    if images:
        user += (
            f"\n\n{len(images)} image(s) jointe(s) (scan / photo) — "
            "lis le contenu visuel."
        )
    try:
        brut_json, provider_id, _ = _appeler_llm(
            _PROMPT_PREUVE,
            user,
            images=images,
            besoin_vision=besoin_vision,
        )
    except ErreurExtractionIdentite as e:
        return _mettre_a_jour_verdict(
            session,
            tenant_id,
            preuve_id,
            verdict="indisponible",
            justification=str(e),
            modele=None,
        )

    resultat = valider_verdict_ia(brut_json)
    justification = resultat["justification"]
    if resultat["elements_retrouves"]:
        justification = (
            f"{justification} Éléments retrouvés : "
            + " ; ".join(resultat["elements_retrouves"])
        )
    return _mettre_a_jour_verdict(
        session,
        tenant_id,
        preuve_id,
        verdict=resultat["verdict"],
        justification=justification,
        modele=provider_id,
    )


def verifier_motif_forcage(
    verdict_ia: str | None, motif_forcage: str | None
) -> tuple[str, str | None]:
    """Décision selon verdict — pure. Retourne (decision, motif normalisé)."""
    verdict = (verdict_ia or "").strip().lower()
    if not verdict:
        raise ErreurPreuveResolution(
            "Analysez la preuve avant de résoudre le risque."
        )
    if verdict == "probante":
        return "acceptee", None
    motif = (motif_forcage or "").strip()
    if not motif:
        raise ErreurPreuveResolution(MESSAGE_MOTIF_FORCAGE_REQUIS)
    return "forcee", motif


def resoudre_risque_avec_preuve(
    session: Session,
    tenant_id: int,
    risque_id: int,
    *,
    preuve_id: int,
    acteur: str,
    motif_forcage: str | None = None,
) -> dict[str, Any]:
    from backend.plateforme.risques import patcher_risque

    with contexte_tenant(session, tenant_id):
        preuve = _lire_preuve(session, preuve_id)
        if int(preuve["risque_id"]) != int(risque_id):
            raise ErreurPreuveResolution(
                f"la preuve {preuve_id} ne concerne pas le risque {risque_id}"
            )
    decision, motif = verifier_motif_forcage(
        preuve.get("verdict_ia"), motif_forcage
    )
    with contexte_tenant(session, tenant_id):
        session.execute(
            text(
                "UPDATE preuve_resolution_risque "
                "SET decision = :d, motif_forcage = :m WHERE id = :id"
            ),
            {"d": decision, "m": motif, "id": preuve_id},
        )
        session.flush()

    risque = patcher_risque(
        session,
        tenant_id,
        risque_id,
        acteur=acteur,
        statut="resolu",
        avec_preuve=True,
    )

    from backend.plateforme.memoire_client import alimenter_memoire

    verdict = str(preuve.get("verdict_ia") or "indisponible")
    contenu = (
        f"Risque résolu : {risque['libelle']} — preuve "
        f"« {preuve['nom_fichier']} », verdict IA {verdict}, "
        f"décision {decision}"
        + (f" (motif : {motif})" if motif else "")
        + "."
    )[:4000]
    alimenter_memoire(
        session,
        tenant_id,
        int(risque["contribuable_id"]),
        type_entree="contexte",
        contenu=contenu,
        source_type="risque",
        source_ref=f"risque:{risque_id}",
    )
    preuve_maj = None
    with contexte_tenant(session, tenant_id):
        preuve_maj = _serialiser(_lire_preuve(session, preuve_id))
    return {"risque": risque, "preuve": preuve_maj}


def compter_preuves(session: Session, risque_id: int) -> int:
    """Nombre de preuves d'un risque — contexte tenant requis par l'appelant."""
    return int(
        session.execute(
            text(
                "SELECT count(*) FROM preuve_resolution_risque "
                "WHERE risque_id = :r"
            ),
            {"r": risque_id},
        ).scalar_one()
    )
