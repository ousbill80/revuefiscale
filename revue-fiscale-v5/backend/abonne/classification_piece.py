"""Classification du type de pièce contribuable — IA propose, humain corrige.

Heuristiques nom + texte d'abord ; vision multimodale seulement si scan / ambigu.
Aucun montant fiscal, aucun article inventé.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from backend.config import config
from backend.socle import llm_providers
from backend.socle import poppler_outils

logger = logging.getLogger(__name__)

TYPES_PIECE = frozenset({"dfe", "rccm", "bail", "cie", "sodeci", "autre"})

# Seuil : au-delà, on saute la vision (évite double round-trip avant extraction).
_CONF_SKIP_VISION = 0.7

# Indices nom de fichier (ordre = priorité relative si scores proches).
_INDICES_NOM: list[tuple[str, tuple[str, ...]]] = [
    ("dfe", ("dfe", "declaration fiscale", "déclaration fiscale", "d1020")),
    ("rccm", ("rccm", "registre du commerce", "registre_commerce", "cepici")),
    ("bail", ("bail", "contrat de location", "location commerciale")),
    ("cie", ("cie", "facture cie", "electricite", "électricité")),
    ("sodeci", ("sodeci", "facture eau", "facture sodeci")),
]

# Indices contenu texte / OCR (libellés DFE CI, RCCM, factures).
_INDICES_TEXTE: list[tuple[str, tuple[str, ...]]] = [
    (
        "dfe",
        (
            "declaration fiscale d'existence",
            "déclaration fiscale d'existence",
            "personnes morales",
            "modele d 1020",
            "modèle d 1020",
            "n de compte contribuable",
            "n° de compte contribuable",
            "regime d'imposition",
            "régime d'imposition",
            "identification du contribuable",
            "direction generale des impots",
            "direction générale des impôts",
        ),
    ),
    (
        "rccm",
        (
            "registre du commerce et du credit mobilier",
            "registre du commerce et du crédit mobilier",
            "extrait rccm",
            "greffe du tribunal",
            "numero rccm",
            "n° rccm",
            "ohada",
            "matricule au rccm",
        ),
    ),
    (
        "bail",
        (
            "contrat de bail",
            "bailleur",
            "preneur",
            "loyer mensuel",
            "duree du bail",
            "durée du bail",
            "local a usage",
            "local à usage",
        ),
    ),
    (
        "cie",
        (
            "compagnie ivoirienne d'electricite",
            "compagnie ivoirienne d'électricité",
            "cie ci",
            "facture d'electricite",
            "facture d'électricité",
            "index ancien",
            "index nouveau",
        ),
    ),
    (
        "sodeci",
        (
            "sodeci",
            "societe de distribution d'eau",
            "société de distribution d'eau",
            "facture d'eau",
            "consommation m3",
        ),
    ),
]

_PROMPT_CLASSIF = """Tu classifies UNE pièce d'identité ivoirienne à partir
du contenu visible (image et/ou texte), pas seulement du nom de fichier.
Types autorisés UNIQUEMENT : dfe | rccm | bail | cie | sodeci | autre

Repères (sans inventer de taux ni d'article) :
- dfe : Déclaration Fiscale d'Existence DGI (Modèle D 1020, NCC, régime,
  cases cochées, cachet centre des impôts…)
- rccm : extrait / certificat Registre du Commerce (RCCM, greffe, OHADA)
- bail : contrat de bail / location
- cie : facture CIE (électricité)
- sodeci : facture SODECI (eau)
- autre : si doute ou autre document

Règles :
- Ne calcule aucun montant fiscal.
- Ne te fie pas au seul nom de fichier s'il contredit le contenu visible.
- Lis titres, tableaux, cachets ; si illisible : type=autre.
- Dans « motif » : justification courte, sans nom de fournisseur technique.

Réponds UNIQUEMENT en JSON :
{"type_piece":"dfe|rccm|bail|cie|sodeci|autre","confiance":0.0,"motif":"..."}
"""


def _pli(s: str) -> str:
    t = (s or "").casefold()
    for a, b in (
        ("é", "e"),
        ("è", "e"),
        ("ê", "e"),
        ("à", "a"),
        ("â", "a"),
        ("ô", "o"),
        ("ù", "u"),
        ("û", "u"),
        ("î", "i"),
        ("ï", "i"),
        ("ç", "c"),
        ("’", "'"),
    ):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def _score_indices(texte: str, indices: list[tuple[str, tuple[str, ...]]]) -> dict[str, int]:
    scores: dict[str, int] = {t: 0 for t in TYPES_PIECE if t != "autre"}
    for typ, mots in indices:
        for m in mots:
            if m in texte:
                scores[typ] = scores.get(typ, 0) + 1
    return scores


def classer_par_nom(nom_fichier: str) -> tuple[str | None, float]:
    """Score depuis le nom de fichier seul."""
    base = _pli(Path(nom_fichier or "").name)
    if not base:
        return None, 0.0
    scores = _score_indices(base, _INDICES_NOM)
    # Match token exact (ex. « dfe » dans « dfe.pdf »)
    stem = Path(base).stem.replace("_", " ").replace("-", " ")
    for typ, mots in _INDICES_NOM:
        for m in mots:
            if re.search(rf"(^|[^a-z0-9]){re.escape(m)}([^a-z0-9]|$)", stem):
                scores[typ] = scores.get(typ, 0) + 2
    meilleur = max(scores, key=lambda k: scores[k])
    if scores[meilleur] <= 0:
        return None, 0.0
    # Confiance : 0.55–0.85 selon force
    conf = min(0.85, 0.5 + 0.1 * scores[meilleur])
    return meilleur, conf


def classer_par_texte(texte: str) -> tuple[str | None, float]:
    t = _pli(texte or "")
    if len(t) < 20:
        return None, 0.0
    scores = _score_indices(t, _INDICES_TEXTE)
    meilleur = max(scores, key=lambda k: scores[k])
    if scores[meilleur] <= 0:
        return None, 0.0
    conf = min(0.95, 0.6 + 0.08 * scores[meilleur])
    return meilleur, conf


def _extraire_texte_rapide(nom: str, contenu: bytes) -> str:
    """Texte extractible sans OCR local (pdftotext / utf-8)."""
    suffixe = Path(nom).suffix.lower()
    if suffixe in {".txt", ".text", ".md", ".markdown", ".csv"}:
        return contenu.decode("utf-8", errors="replace")
    if suffixe == ".pdf":
        binaire = poppler_outils.chemin_pdftotext()
        if not binaire:
            return ""
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(contenu)
            chemin = Path(tmp.name)
        try:
            r = subprocess.run(  # noqa: S603
                [binaire, "-layout", str(chemin), "-"],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return (r.stdout or "").strip()
        except (subprocess.TimeoutExpired, OSError):
            return ""
        finally:
            chemin.unlink(missing_ok=True)
    if suffixe in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif"}:
        return ""
    try:
        return contenu.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _pdf_premiere_page(contenu: bytes) -> list[tuple[str, bytes]]:
    """Une seule page JPEG basse résolution — classif légère."""
    images, _ = poppler_outils.pdf_vers_images_vision(
        contenu,
        max_pages=1,
        dpi=min(120, int(config.llm_vision_pdf_dpi or 140)),
        jpeg_quality=min(75, int(config.llm_vision_jpeg_quality or 82)),
        plafond_pages=1,
    )
    return images


def _classer_par_vision(
    nom: str, contenu: bytes, *, texte_extrait: str
) -> tuple[str | None, float, str | None]:
    """Appel LLM vision court — brouillon, jamais montant fiscal."""
    if not llm_providers.providers_configures():
        return None, 0.0, None
    ordre = llm_providers.ordre_providers(capacite="vision")
    vision_ok = [p for p in ordre if p.supports_vision]
    if not vision_ok:
        return None, 0.0, None

    suffixe = Path(nom).suffix.lower()
    images: list[tuple[str, bytes]] = []
    if suffixe in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif"}:
        if len(contenu) <= 2_000_000:
            images.append((llm_providers.mime_depuis_nom(nom), contenu))
    elif suffixe == ".pdf":
        images = _pdf_premiere_page(contenu)
    if not images:
        return None, 0.0, None

    user = (
        f"Nom fichier (indice seulement, peut être trompeur) : {nom}\n"
        f"Extrait texte local (peut être vide) :\n{(texte_extrait or '')[:1500]}\n"
        "Lis l'image et classifie le type_piece."
    )
    messages = [
        {"role": "system", "content": _PROMPT_CLASSIF},
        llm_providers.message_user_avec_images(user, images),
    ]
    t0 = time.perf_counter()
    try:
        # Classif courte : timeout plus bas que l'extraction complète,
        # mais suffisant pour la vision multi-page (scans lourds).
        timeout_classif = min(
            90.0, float(config.llm_vision_timeout_seconds or 180.0)
        )
        contenu_llm, provider_id, _ = llm_providers.appeler_chat(
            messages,
            capacite="vision",
            temperature=0,
            json_object=True,
            timeout=timeout_classif,
            vision_stricte=True,
        )
    except llm_providers.ErreurLlm as e:
        logger.info(
            "classif_vision_echec raison=%s duree_ms=%s",
            str(e)[:160],
            int((time.perf_counter() - t0) * 1000),
        )
        return None, 0.0, None

    try:
        data = json.loads(contenu_llm)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", contenu_llm or "")
        if not m:
            return None, 0.0, None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None, 0.0, None

    typ = str(data.get("type_piece") or "").strip().lower()
    type_invalide = typ not in TYPES_PIECE
    if type_invalide:
        # Type hors référentiel : ne pas avaler silencieusement — repli « autre »
        logger.warning(
            "classif_vision_type_invalide type=%r nom=%s — repli sur « autre »",
            typ,
            nom,
        )
        typ = "autre"
    try:
        conf = float(data.get("confiance") or 0.7)
    except (TypeError, ValueError):
        conf = 0.7
    conf = max(0.0, min(conf, 0.95))
    if type_invalide:
        # Repli : confiance basse pour ne pas écraser les heuristiques nom/texte
        conf = min(conf, 0.3)
    logger.info(
        "classif_vision ok type=%s conf=%.2f provider=%s duree_ms=%s",
        typ,
        conf,
        provider_id,
        int((time.perf_counter() - t0) * 1000),
    )
    return typ, conf, str(data.get("motif") or "")[:200] or None


def classer_piece(
    nom_fichier: str,
    contenu: bytes,
    *,
    type_impose: str | None = None,
    autoriser_vision: bool = True,
) -> dict[str, Any]:
    """Détermine type_piece + métadonnées (proposition, corrigible).

    ``type_impose`` : si fourni et ∈ TYPES (hors auto/autre), conservé comme
    saisie manuelle — sauf si ``type_impose`` vaut ``auto`` / vide / ``autre``
    auquel cas on détecte.
    """
    t0 = time.perf_counter()
    impose = (type_impose or "").strip().lower()
    forcer_manuel = impose in TYPES_PIECE and impose != "autre"

    from backend.abonne.formats_piece import detecter_format_tabulaire

    fmt_tab = detecter_format_tabulaire(nom_fichier, contenu)
    if fmt_tab is not None and not forcer_manuel:
        # Formats tabulaires (fec/csv/xlsx) : jamais de vision ni de LLM.
        logger.info(
            "classif_piece_tabulaire format=%s nom=%s", fmt_tab, nom_fichier
        )
        return {
            "type_piece": "autre",
            "type_detecte": "autre",
            "type_source": f"format_{fmt_tab}",
            "type_confiance": 1.0,
            "type_detecte_auto": True,
            "motif": (
                f"document {fmt_tab.upper()} — classification déterministe, "
                "sans analyse visuelle"
            ),
        }

    texte = _extraire_texte_rapide(nom_fichier, contenu)
    typ_nom, conf_nom = classer_par_nom(nom_fichier)
    typ_txt, conf_txt = classer_par_texte(texte)

    typ: str | None = None
    conf = 0.0
    source = "indetermine"
    motif: str | None = None

    if typ_txt and conf_txt >= 0.65:
        typ, conf, source = typ_txt, conf_txt, "texte"
    elif typ_nom and conf_nom >= 0.6:
        typ, conf, source = typ_nom, conf_nom, "nom_fichier"
        # Texte contredit fortement le nom → préférer texte
        if typ_txt and conf_txt >= 0.55 and typ_txt != typ_nom:
            typ, conf, source = typ_txt, conf_txt, "texte"
    elif typ_txt:
        typ, conf, source = typ_txt, conf_txt, "texte"
    elif typ_nom:
        typ, conf, source = typ_nom, conf_nom, "nom_fichier"

    # Skip vision si heuristique déjà fiable (évite 2e appel vision avant extract).
    # Ancien comportement : tout PDF scan sans texte déclenchait la vision même
    # si le nom disait clairement « DFE ».
    heuristique_fiable = typ is not None and conf >= _CONF_SKIP_VISION
    besoin_vision = (
        autoriser_vision
        and not forcer_manuel
        and not heuristique_fiable
        and (typ is None or conf < 0.55)
    )
    if besoin_vision:
        typ_v, conf_v, motif_v = _classer_par_vision(
            nom_fichier, contenu, texte_extrait=texte
        )
        if typ_v and conf_v >= conf:
            typ, conf, source, motif = typ_v, conf_v, "vision", motif_v
    elif autoriser_vision and heuristique_fiable:
        logger.info(
            "classif_skip_vision type=%s conf=%.2f source=%s duree_ms=%s",
            typ,
            conf,
            source,
            int((time.perf_counter() - t0) * 1000),
        )

    if forcer_manuel:
        return {
            "type_piece": impose,
            "type_detecte": typ or impose,
            "type_source": "manuel",
            "type_confiance": 1.0,
            "type_detecte_auto": False,
            "motif": "saisie manuelle à l'upload",
        }

    final = typ if typ in TYPES_PIECE else "autre"
    if final == "autre":
        conf = min(conf, 0.4)
        source = source if typ else "indetermine"

    logger.info(
        "classif_piece type=%s conf=%.2f source=%s vision=%s duree_ms=%s",
        final,
        conf,
        source,
        besoin_vision,
        int((time.perf_counter() - t0) * 1000),
    )
    return {
        "type_piece": final,
        "type_detecte": final,
        "type_source": source,
        "type_confiance": round(conf, 3),
        "type_detecte_auto": True,
        "motif": motif,
    }
