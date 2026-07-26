"""Extraction / conformité identité depuis pièces — IA propose, humain valide.

Aucun montant fiscal produit pour le moteur. Sans clé LLM : statut
``indisponible`` (pas de données inventées).

Routage multi-provider (``backend.socle.llm_providers``) :
- Image / PDF sans texte extractible → Moonshot vision d'abord
- Texte PDF (pdftotext) OK → DeepSeek puis Moonshot (ordre configurable)
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from backend.abonne.pieces_contribuable_service import (
    ErreurPieceContribuable,
    lire_contenu_piece,
    lister_pieces,
    pieces_par_ids,
)
from backend.socle import llm_providers
from backend.socle import poppler_outils

CHAMPS_IDENTITE = (
    "denomination",
    "ncc",
    "rccm",
    "forme",
    "dfe",
    "regime_fiscal",
    "forme_juridique",
    "siege_social",
    "commune",
    "centre_impots",
    "capital_social",
    "mois_cloture",
    "activite_principale",
    "date_immatriculation",
)

MESSAGE_INDISPONIBLE = (
    "Analyse documentaire indisponible pour le moment. "
    "Saisissez manuellement les champs, ou réessayez plus tard."
)

_PROMPT_EXTRACTION = """Tu es un assistant de lecture documentaire pour l'identité
légale d'entreprises en Côte d'Ivoire. Tu analyses TOUTES les pièces jointes
(texte et/ou images scannées) : DFE, RCCM, bail, CIE, SODECI…. Combine-les :
un champ lu sur le DFE et un autre sur le RCCM → les deux dans la réponse.

Compréhension visuelle (scans / photos / PDF image) — pas un simple OCR brut :
- Relis chaque page : titres, tableaux, colonnes, cases cochées, marges.
- Lis les cachets, tamponnements, annotations manuscrites et zones « réserve
  administration » (souvent à droite sur une DFE).
- Si une zone est floue / coupée : null pour ce champ (n'invente pas).

Structure typique d'une DFE Côte d'Ivoire (Modèle D 1020, DGI) — repères
de lecture uniquement, pas de règles de calcul :
- Page couverture : « DECLARATION FISCALE D'EXISTENCE », PERSONNES MORALES.
- Identification : Raison sociale, Forme juridique, RCCM, date délivrance.
- Localisation siège : Ville, Commune, Quartier, Lot / Îlot, réf. cadastrale.
- Activités : activité principale (nature exacte), date de début.
- Capital social (montant).
- Réserve administration : N° de compte contribuable (NCC), Code CDI / centre,
  Régime d'imposition coché (RNI, RSI, IM/IME, TEE…).
- RCCM (autre pièce) : n° RCCM, dénomination, forme, date d'immatriculation.
Le type_piece déclaré peut être faux — fie-toi au CONTENU visible.

Règles strictes :
- Ne calcule aucun montant fiscal, taxe, pénalité ou plafonnement.
- N'invente AUCUN champ. Si non lisible : null.
- N'utilise PAS le nom de fichier comme source.
- forme = "pm" ou "pp" uniquement si clairement déductible, sinon null.
- regime_fiscal parmi UNIQUEMENT :
  reel | reel_simplifie | ime | tee | tce | autre
  (alias : RNI→reel, RSI→reel_simplifie, IM/IME/RME/micro→ime,
   TEE→tee, TCE→tce — case cochée sur DFE ; sinon null).
- forme_juridique : sigle OHADA / pratique CI (SA, SARL, SAS, SASU, SUARL,
  SNC, SCS, SCA, SEP, SCI, SCP, SCPA, GIE, SCOOPS, COOP-CA, Association,
  ONG, Fondation, Succursale, Autre, EI pour pp) — sinon null.
- dfe : n° DFE / référence administrative si présente, sinon null.
- siege_social : adresse complète du siège si lue (quartier, lot, îlot…).
- commune : commune / ville du siège.
- centre_impots : libellé du centre / service DGI si lu (cachet ou marge).
- mois_cloture = entier 1–12 si trouvé, sinon null.
- capital_social = nombre (pas de devise) si trouvé, sinon null.
- date_immatriculation = YYYY-MM-DD si date RCCM / création lisible, sinon null.
- activite_principale = libellé activité lu (texte libre), pas un code inventé.
- Pour chaque champ non null : citation courte + piece_id source.
- Liste aussi champs_non_lus : clés attendues restées null faute de lecture.
- Dans « notes » : réserves de lecture seulement (scan partiel, page manquante).
  Jamais de nom de fournisseur technique.

Réponds UNIQUEMENT en JSON valide :
{
  "champs": {
    "denomination": null, "ncc": null, "rccm": null, "forme": null,
    "dfe": null, "regime_fiscal": null, "forme_juridique": null,
    "siege_social": null, "commune": null, "centre_impots": null,
    "capital_social": null, "mois_cloture": null,
    "activite_principale": null, "date_immatriculation": null
  },
  "citations": [
    {"champ": "...", "piece_id": 123, "extrait": "...", "confiance": 0.0}
  ],
  "champs_non_lus": ["..."],
  "notes": "éventuelles réserves (scan partiel, etc.)"
}
"""

# Valeurs alignées sur frontend/mission/src/legalite.ts (saisie, pas calcul).
_REGIMES_CANONIQUES = frozenset(
    {"reel", "reel_simplifie", "ime", "tee", "tce", "autre"}
)
_FORMES_JURIDIQUES_CANONIQUES = frozenset(
    {
        "SA",
        "SARL",
        "SAS",
        "SASU",
        "SUARL",
        "SNC",
        "SCS",
        "SCA",
        "SEP",
        "SCI",
        "SCP",
        "SCPA",
        "GIE",
        "SCOOPS",
        "COOP-CA",
        "Association",
        "ONG",
        "Fondation",
        "Succursale",
        "Autre",
        "EI",
    }
)

# Alias CI / DGI → valeur formulaire (pas de seuil ni article inventé).
_ALIAS_REGIME: dict[str, str] = {
    "reel": "reel",
    "rni": "reel",
    "reel normal": "reel",
    "regime reel": "reel",
    "régime réel": "reel",
    "regime du reel": "reel",
    "réel normal": "reel",
    "reel_simplifie": "reel_simplifie",
    "reel simplifie": "reel_simplifie",
    "réel simplifié": "reel_simplifie",
    "rsi": "reel_simplifie",
    "simplifie": "reel_simplifie",
    "simplifié": "reel_simplifie",
    "ime": "ime",
    "im": "ime",
    "impot minimum": "ime",
    "impôt minimum": "ime",
    "rme": "ime",
    "micro": "ime",
    "microentreprise": "ime",
    "micro-entreprise": "ime",
    "impôt des microentreprises": "ime",
    "impot des microentreprises": "ime",
    "tee": "tee",
    "taxe d'etat de l'entreprenant": "tee",
    "taxe d'état de l'entreprenant": "tee",
    "tce": "tce",
    "taxe communale de l'entreprenant": "tce",
    "autre": "autre",
    "liberatoire": "autre",
    "libératoire": "autre",
}

_ALIAS_FORME_JURIDIQUE: dict[str, str] = {
    "sa": "SA",
    "s.a.": "SA",
    "s.a": "SA",
    "societe anonyme": "SA",
    "société anonyme": "SA",
    "sarl": "SARL",
    "s.a.r.l.": "SARL",
    "s.a.r.l": "SARL",
    "societe a responsabilite limitee": "SARL",
    "société à responsabilité limitée": "SARL",
    "sas": "SAS",
    "s.a.s.": "SAS",
    "societe par actions simplifiee": "SAS",
    "société par actions simplifiée": "SAS",
    "sasu": "SASU",
    "suarl": "SUARL",
    "eurl": "SUARL",
    "snc": "SNC",
    "scs": "SCS",
    "sca": "SCA",
    "sep": "SEP",
    "sci": "SCI",
    "scp": "SCP",
    "scpa": "SCPA",
    "gie": "GIE",
    "scoops": "SCOOPS",
    "coop-ca": "COOP-CA",
    "coop ca": "COOP-CA",
    "coopca": "COOP-CA",
    "association": "Association",
    "ong": "ONG",
    "fondation": "Fondation",
    "succursale": "Succursale",
    "etablissement": "Succursale",
    "établissement": "Succursale",
    "autre": "Autre",
    "ei": "EI",
    "entrepreneur individuel": "EI",
    "entreprise individuelle": "EI",
}

_LIBELLES_PROVIDER = {
    "moonshot": "Moonshot",
    "deepseek": "DeepSeek",
    "legacy": "fournisseur OpenAI-compatible",
}

_PROMPT_CONFORMITE = """Tu compares les champs saisis d'une fiche contribuable
avec le texte des pièces jointes (DFE, RCCM, bail, CIE, SODECI…).

Règles :
- Ne calcule aucun montant fiscal.
- Signale uniquement les écarts factuels (NCC différent, adresse siège ≠ bail, etc.).
- Si un champ saisi n'a pas de source dans les pièces : severity "info".
- Si contradiction claire : severity "ecart".
- Si cohérent : ne pas lister le champ.

Réponds UNIQUEMENT en JSON valide :
{
  "ok": true/false,
  "ecarts": [
    {
      "champ": "...",
      "saisi": "...",
      "lu_dans_piece": "...",
      "piece_id": 123,
      "severity": "ecart|info",
      "message": "..."
    }
  ],
  "notes": "..."
}
"""

_MARQUEURS_SANS_TEXTE = (
    "sans texte extractible",
    "OCR non disponible",
    "OCR local non disponible",
    "pdftotext indisponible",
    "pdftoppm indisponible",
    "rasterisation PDF scan impossible",
    "Fichier binaire non lisible",
)

_EXT_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".gif"}

# Plafond d'une image envoyée telle quelle à la vision (octets).
# Pillow absent des dépendances → pas de redimensionnement serveur :
# au-delà, avertissement explicite remonté jusqu'à l'UI.
MAX_OCTETS_IMAGE_VISION = 4_000_000

# Garde-fou coût / latence : nombre maximal de pièces par analyse IA.
MAX_PIECES_PAR_ANALYSE = 10

MESSAGE_AUCUN_CONTENU_EXPLOITABLE = (
    "Aucun contenu exploitable dans les pièces (ni texte ni image analysable). "
    "Saisissez manuellement les champs."
)


class ErreurExtractionIdentite(Exception):
    """Échec extraction / conformité."""


def llm_configure() -> bool:
    return llm_providers.providers_configures()


def _pli(s: str) -> str:
    """Normalise pour matching alias (casse, accents usuels, ponctuation)."""
    t = (s or "").strip().casefold()
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
        ("`", "'"),
    ):
        t = t.replace(a, b)
    t = re.sub(r"[.\-/_,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _variantes_alias(s: str) -> list[str]:
    """Variantes de matching : avec espaces et compact (S.A.R.L. → sarl)."""
    base = _pli(s)
    if not base:
        return []
    compact = base.replace(" ", "")
    out = [base]
    if compact and compact != base:
        out.append(compact)
    return out


def mapper_regime_fiscal(brut: str | None) -> str | None:
    """Mappe un libellé extrait → valeur `legalite.ts` (ou null)."""
    if brut is None or str(brut).strip() == "":
        return None
    raw = str(brut).strip()
    if raw in _REGIMES_CANONIQUES:
        return raw
    for cle in _variantes_alias(raw):
        if cle in _ALIAS_REGIME:
            return _ALIAS_REGIME[cle]
    cle = _pli(raw)
    # Contient un sigle connu
    for alias, canon in (
        ("reel simplifie", "reel_simplifie"),
        ("reel_simplifie", "reel_simplifie"),
        ("rni", "reel"),
        ("rsi", "reel_simplifie"),
        ("rme", "ime"),
        ("ime", "ime"),
        ("tee", "tee"),
        ("tce", "tce"),
    ):
        if alias in cle or alias.replace(" ", "") in cle.replace(" ", ""):
            return canon
    if "micro" in cle:
        return "ime"
    if "entreprenant" in cle and "communal" in cle:
        return "tce"
    if "entreprenant" in cle:
        return "tee"
    if "reel" in cle:
        if "simplif" in cle:
            return "reel_simplifie"
        return "reel"
    return None


def mapper_forme_juridique(brut: str | None) -> str | None:
    """Mappe un libellé extrait → sigle formulaire (ou null)."""
    if brut is None or str(brut).strip() == "":
        return None
    raw = str(brut).strip()
    if raw in _FORMES_JURIDIQUES_CANONIQUES:
        return raw
    for v in _FORMES_JURIDIQUES_CANONIQUES:
        if raw.casefold() == v.casefold():
            return v
    for cle in _variantes_alias(raw):
        if cle in _ALIAS_FORME_JURIDIQUE:
            return _ALIAS_FORME_JURIDIQUE[cle]
    cle = _pli(raw)
    premier = cle.split(" ", 1)[0]
    if premier in _ALIAS_FORME_JURIDIQUE:
        return _ALIAS_FORME_JURIDIQUE[premier]
    compact = cle.replace(" ", "")
    if compact in _ALIAS_FORME_JURIDIQUE:
        return _ALIAS_FORME_JURIDIQUE[compact]
    return None


def libelle_provider(
    provider_id: str | None,
    failover_depuis: tuple[str, ...] | list[str] | None = None,
) -> str | None:
    """Libellé FR sans clé — pour logs ops uniquement (pas d'affichage métier)."""
    if not provider_id:
        return None
    nom = _LIBELLES_PROVIDER.get(provider_id, provider_id)
    fails = tuple(failover_depuis or ())
    if not fails:
        return f"via {nom}"
    skips = ", ".join(_LIBELLES_PROVIDER.get(p, p) for p in fails)
    return f"via {nom} (bascule après {skips})"


def message_erreur_llm_fr(exc: BaseException) -> str:
    """Reformule une erreur LLM pour l'UI métier (FR neutre, sans fournisseurs).

    Les détails techniques (provider, HTTP, variables d'env) restent dans les logs.
    """
    msg = str(exc)
    bas = msg.casefold()
    kind = getattr(exc, "kind", None)
    status = getattr(exc, "status", None)
    provider = getattr(exc, "provider", None)

    # Inférence si l'exception n'est pas une ErreurLlm typée
    if kind in (None, "inconnu"):
        if status in (401, 403) or "http 401" in bas or "http 403" in bas:
            kind = "auth"
        elif status == 429 or "http 429" in bas or "rate limit" in bas:
            kind = "quota"
        elif "timeout" in bas:
            kind = "timeout"
        elif "http 404" in bas or (
            "model" in bas
            and ("not found" in bas or "does not exist" in bas or "unknown" in bas)
        ):
            kind = "modele"
        elif "aucun fournisseur" in bas or "configuré" in bas:
            kind = "config"

    logger.warning(
        "llm_erreur_ui kind=%s status=%s provider=%s detail=%s",
        kind,
        status,
        provider,
        msg[:300],
    )

    if kind == "config" or "aucun fournisseur" in bas or (
        "indisponible" in bas and "clé" in bas
    ):
        if "vision" in bas or "scan" in bas:
            return (
                "Analyse du document scanné indisponible pour le moment. "
                "Saisissez manuellement."
            )
        return MESSAGE_INDISPONIBLE

    if kind == "auth":
        return (
            "Authentification du service d'analyse refusée. "
            "Réessayez plus tard ou saisissez manuellement."
        )
    if kind == "quota":
        return (
            "Service d'analyse saturé. Réessayez dans un moment "
            "ou saisissez manuellement."
        )
    if kind == "timeout":
        return (
            "Délai dépassé lors de l'analyse du document. "
            "Réessayez ou saisissez manuellement."
        )
    if kind == "modele":
        return (
            "Service d'analyse temporairement indisponible. "
            "Réessayez plus tard ou saisissez manuellement."
        )
    if kind == "transport":
        return (
            "Service d'analyse injoignable pour le moment. "
            "Réessayez ou saisissez manuellement."
        )
    if "tous les fournisseurs" in bas:
        return (
            "Analyse documentaire indisponible pour le moment. "
            "Réessayez plus tard ou saisissez manuellement."
        )
    return (
        "Analyse documentaire échouée. "
        "Réessayez ou saisissez manuellement."
    )


def _pdf_vers_images(
    contenu: bytes,
    *,
    max_pages: int | None = None,
    dpi: int | None = None,
) -> tuple[list[tuple[str, bytes]], str | None]:
    """Rasterise les premières pages PDF (JPEG) pour vision — délégué Poppler."""
    return poppler_outils.pdf_vers_images_vision(
        contenu, max_pages=max_pages, dpi=dpi
    )


def _extraire_texte_fichier(nom: str, contenu: bytes) -> str:
    """Texte extractible — PDF via pdftotext, sinon UTF-8. Pas d'OCR local."""
    suffixe = Path(nom).suffix.lower()
    if suffixe in {".txt", ".text", ".md", ".markdown", ".csv"}:
        return contenu.decode("utf-8", errors="replace")
    if suffixe == ".pdf":
        binaire = poppler_outils.chemin_pdftotext()
        if not binaire:
            return f"[PDF : {poppler_outils.MESSAGE_PDFTOTEXT_ABSENT}]"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(contenu)
            chemin = Path(tmp.name)
        try:
            resultat = subprocess.run(  # noqa: S603
                [binaire, "-layout", str(chemin), "-"],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            texte = (resultat.stdout or "").strip()
            if not texte:
                avis_ppm = (
                    ""
                    if poppler_outils.pdftoppm_disponible()
                    else f" {poppler_outils.MESSAGE_PDFTOPPM_ABSENT}"
                )
                return (
                    "[PDF sans texte extractible (scan image ?). "
                    "Routage vision AI si fournisseur OCR disponible.]"
                    + avis_ppm
                )
            return texte
        except (subprocess.TimeoutExpired, OSError) as e:
            return f"[Échec extraction PDF : {e}]"
        finally:
            chemin.unlink(missing_ok=True)
    if suffixe in _EXT_IMAGES:
        return (
            "[Image : pas de texte local — "
            "envoi au service d'analyse visuelle.]"
        )
    try:
        return contenu.decode("utf-8", errors="replace")
    except Exception:
        return "[Fichier binaire non lisible en texte.]"


def _texte_insuffisant(texte: str) -> bool:
    t = (texte or "").strip()
    if len(t) < 40:
        return True
    if any(m.casefold() in t.casefold() for m in _MARQUEURS_SANS_TEXTE):
        return True
    return False


def _texte_partiel_identite(texte: str) -> bool:
    """Texte extractible mais trop pauvre pour une identité complète → vision aussi."""
    t = (texte or "").strip()
    if _texte_insuffisant(t):
        return True
    bas = t.casefold()
    # Indices d'identité typiques DFE / RCCM CI
    indices = (
        "ncc",
        "compte contribuable",
        "raison sociale",
        "rccm",
        "siege",
        "siège",
        "commune",
        "forme juridique",
        "regime",
        "régime",
    )
    hits = sum(1 for i in indices if i in bas)
    return hits < 2


def _preparer_corpus_pieces(
    session: Session, piece_ids: list[int]
) -> tuple[
    list[dict[str, Any]],
    str,
    list[tuple[str, bytes]],
    bool,
    list[str],
    bool,
]:
    """Retourne pieces, corpus, images, besoin_vision, avertissements, exploitable.

    Toutes les pièces sont lues ensemble. PDF scan / texte partiel → rasterisation
    + vision stricte. Texte riche OK sans image. ``exploitable`` = au moins un
    texte réel ou une image analysable (sinon : ne pas appeler le LLM texte avec
    des marqueurs d'erreur comme corpus).
    """
    pieces = pieces_par_ids(session, piece_ids)
    if not pieces:
        raise ErreurExtractionIdentite("aucune pièce trouvée")
    blocs: list[str] = []
    images: list[tuple[str, bytes]] = []
    besoin_vision = False
    avertissements: list[str] = []
    contenu_exploitable = False

    for p in pieces:
        _, brut = lire_contenu_piece(session, int(p["id"]))
        nom = str(p["nom_fichier"])
        suffixe = Path(nom).suffix.lower()
        texte = _extraire_texte_fichier(nom, brut)
        extrait = texte[:12000]

        if suffixe in _EXT_IMAGES:
            besoin_vision = True
            if len(brut) <= MAX_OCTETS_IMAGE_VISION:
                images.append((llm_providers.mime_depuis_nom(nom), brut))
                contenu_exploitable = True
            else:
                avertissements.append(
                    f"Image {nom} trop lourde "
                    f"({len(brut) / 1_000_000:.1f} Mo) — "
                    "non analysée par la vision."
                )
                extrait = "[Image trop lourde — non analysée.]"
        elif suffixe == ".pdf":
            sans_texte = _texte_insuffisant(texte)
            if sans_texte or _texte_partiel_identite(texte):
                besoin_vision = True
                # DFE CI multi-pages (couverture + identification + annexes)
                pages, avis = _pdf_vers_images(brut)
                images.extend(pages)
                if avis and avis not in avertissements:
                    avertissements.append(avis)
                if pages:
                    contenu_exploitable = True
                if sans_texte:
                    # Jamais le marqueur d'erreur comme corpus LLM texte
                    # (risque d'hallucination depuis le nom du fichier).
                    if pages:
                        extrait = (
                            "[PDF scanné : lecture via les images jointes.]"
                        )
                    else:
                        extrait = (
                            "[PDF scanné non analysable "
                            "(conversion en image indisponible).]"
                        )
                        avertissements.append(
                            f"PDF scanné {nom} sans texte extractible et "
                            "sans conversion en image — pièce non analysée."
                        )
                elif pages:
                    avertissements.append(
                        "Texte PDF partiel : lecture combinée texte + images."
                    )
            if not sans_texte:
                contenu_exploitable = True
        elif not _texte_insuffisant(texte):
            contenu_exploitable = True

        # Le type déclaré peut être faux — on le signale comme indice seulement
        blocs.append(
            f"--- piece_id={p['id']} type_declare={p['type_piece']} "
            f"(peut être incorrect) fichier={nom} ---\n{extrait}"
        )

    if besoin_vision and not images:
        msg = poppler_outils.MESSAGE_VISION_SANS_IMAGE
        if msg not in avertissements:
            avertissements.append(msg)

    return (
        pieces,
        "\n\n".join(blocs),
        images,
        besoin_vision,
        avertissements,
        contenu_exploitable,
    )


def _parser_json_llm(contenu: str) -> dict[str, Any]:
    try:
        return json.loads(contenu)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", contenu)
        if not m:
            raise ErreurExtractionIdentite("réponse LLM non JSON") from None
        return json.loads(m.group(0))


def _appeler_llm(
    systeme: str,
    user: str,
    *,
    images: list[tuple[str, bytes]] | None = None,
    besoin_vision: bool = False,
) -> tuple[dict[str, Any], str, tuple[str, ...]]:
    if not llm_configure():
        raise ErreurExtractionIdentite(MESSAGE_INDISPONIBLE)

    capacite: llm_providers.Capacite = (
        "vision" if (besoin_vision or images) else "chat"
    )
    msg_user = llm_providers.message_user_avec_images(user, images or [])
    # Si vision demandée mais aucune image rasterisée : rester en chat
    # (le corpus décrit déjà le manque de texte).
    if capacite == "vision" and not images:
        capacite = "chat"

    messages = [
        {"role": "system", "content": systeme},
        msg_user,
    ]
    timeout: float | None = None
    if capacite == "vision":
        from backend.config import config as cfg

        timeout = float(cfg.llm_vision_timeout_seconds or 180.0)
    t0 = time.perf_counter()
    try:
        contenu, provider_id, failover = llm_providers.appeler_chat(
            messages,
            capacite=capacite,
            temperature=0,
            json_object=True,
            timeout=timeout,
            vision_stricte=(capacite == "vision" and bool(images)),
        )
    except llm_providers.ErreurLlm as e:
        logger.info(
            "extraction_llm_echec capacite=%s images=%s duree_ms=%s",
            capacite,
            len(images or []),
            int((time.perf_counter() - t0) * 1000),
        )
        raise ErreurExtractionIdentite(message_erreur_llm_fr(e)) from e

    logger.info(
        "extraction_llm_ok capacite=%s images=%s provider=%s duree_ms=%s",
        capacite,
        len(images or []),
        provider_id,
        int((time.perf_counter() - t0) * 1000),
    )
    return _parser_json_llm(contenu), provider_id, failover


def _champs_manquants(champs: dict[str, Any]) -> list[str]:
    return [c for c in CHAMPS_IDENTITE if champs.get(c) in (None, "")]


def _message_sans_provider(notes: str | None) -> str:
    """Message métier : jamais de nom de fournisseur ni variable d'env."""
    base = (notes or "").strip() or (
        "Brouillon sourcé — vérifiez puis appliquez manuellement."
    )
    base = re.sub(
        r"\s*\(?\s*via\s+(?:Moonshot|DeepSeek|Kimi|legacy|OpenAI)[^)]*\)?",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(
        r"\b(?:Moonshot|DeepSeek|Kimi|OpenAI)\b(?:\s*\([^)]*\))?",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = re.sub(
        r"\b(?:MOONSHOT|DEEPSEEK|MODELE)_[A-Z0-9_]+\b",
        "",
        base,
    )
    base = re.sub(
        r"\b(?:api\.moonshot\.(?:ai|cn)|platform\.kimi\.ai|console\s*/?\s*Kimi)\b",
        "",
        base,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", base).strip() or (
        "Brouillon sourcé — vérifiez puis appliquez manuellement."
    )


def _normaliser_champs(brut: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    src = brut or {}
    for cle in CHAMPS_IDENTITE:
        val = src.get(cle)
        if val is None or val == "":
            out[cle] = None
            continue
        if cle == "forme":
            f = str(val).strip().lower()
            out[cle] = f if f in {"pm", "pp"} else None
        elif cle == "regime_fiscal":
            out[cle] = mapper_regime_fiscal(str(val))
        elif cle == "forme_juridique":
            out[cle] = mapper_forme_juridique(str(val))
        elif cle == "mois_cloture":
            try:
                m = int(val)
                out[cle] = m if 1 <= m <= 12 else None
            except (TypeError, ValueError):
                out[cle] = None
        elif cle == "capital_social":
            try:
                out[cle] = float(
                    str(val).replace(" ", "").replace(",", ".")
                )
            except (TypeError, ValueError):
                out[cle] = None
        else:
            out[cle] = str(val).strip() or None
    return out


def _normaliser_citations(
    brut: list[Any] | None, piece_ids: set[int]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in brut or []:
        if not isinstance(item, dict):
            continue
        champ = str(item.get("champ") or "").strip()
        if champ not in CHAMPS_IDENTITE:
            continue
        try:
            pid = int(item.get("piece_id"))
        except (TypeError, ValueError):
            continue
        if pid not in piece_ids:
            continue
        conf = item.get("confiance")
        try:
            confiance = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            confiance = None
        if confiance is not None:
            # Borne [0, 1] ; NaN → None (comparaison NaN != NaN)
            if confiance != confiance:
                confiance = None
            else:
                confiance = max(0.0, min(1.0, confiance))
        out.append(
            {
                "champ": champ,
                "piece_id": pid,
                "extrait": str(item.get("extrait") or "")[:500],
                "confiance": confiance,
            }
        )
    return out


def _enregistrer_proposition(
    session: Session,
    tenant_id: int,
    *,
    piece_ids: list[int],
    champs: dict[str, Any],
    citations: list[dict[str, Any]],
    statut: str,
    message: str | None,
    contribuable_id: int | None = None,
    session_upload: str | None = None,
) -> int:
    pid = session.execute(
        text(
            "INSERT INTO proposition_identite ("
            "tenant_id, contribuable_id, session_upload, piece_ids, "
            "champs_proposes, citations, statut, message"
            ") VALUES ("
            ":t, :c, :s, :pids, CAST(:champs AS jsonb), "
            "CAST(:cit AS jsonb), :st, :msg"
            ") RETURNING id"
        ),
        {
            "t": tenant_id,
            "c": contribuable_id,
            "s": session_upload,
            "pids": piece_ids,
            "champs": json.dumps(champs, ensure_ascii=False),
            "cit": json.dumps(citations, ensure_ascii=False),
            "st": statut,
            "msg": message,
        },
    ).scalar_one()
    session.flush()
    return int(pid)


def resoudre_piece_ids(
    session: Session,
    *,
    piece_ids: list[int] | None = None,
    session_upload: str | None = None,
    contribuable_id: int | None = None,
) -> list[int]:
    if piece_ids:
        return [int(x) for x in piece_ids]
    if contribuable_id is not None:
        return [
            int(p["id"])
            for p in lister_pieces(session, contribuable_id=contribuable_id)
        ]
    if session_upload:
        return [
            int(p["id"])
            for p in lister_pieces(session, session_upload=session_upload)
        ]
    raise ErreurExtractionIdentite(
        "fournir piece_ids, session_upload ou contribuable_id"
    )


def proposer_identite(
    session: Session,
    tenant_id: int,
    *,
    piece_ids: list[int] | None = None,
    session_upload: str | None = None,
    contribuable_id: int | None = None,
) -> dict[str, Any]:
    """Extrait un brouillon d'identité. N'écrit jamais dans contribuable."""
    ids = resoudre_piece_ids(
        session,
        piece_ids=piece_ids,
        session_upload=session_upload,
        contribuable_id=contribuable_id,
    )
    if not ids:
        raise ErreurExtractionIdentite("aucune pièce à analyser")
    if len(ids) > MAX_PIECES_PAR_ANALYSE:
        raise ErreurExtractionIdentite("Maximum 10 pièces par analyse.")

    if not llm_configure():
        prop_id = _enregistrer_proposition(
            session,
            tenant_id,
            piece_ids=ids,
            champs={},
            citations=[],
            statut="indisponible",
            message=MESSAGE_INDISPONIBLE,
            contribuable_id=contribuable_id,
            session_upload=session_upload,
        )
        return {
            "disponible": False,
            "statut": "indisponible",
            "proposition_id": prop_id,
            "champs": {c: None for c in CHAMPS_IDENTITE},
            "champs_manquants": list(CHAMPS_IDENTITE),
            "citations": [],
            "message": MESSAGE_INDISPONIBLE,
            "piece_ids": ids,
            "provider": None,
            "failover_depuis": [],
            "avertissements": [],
            "poppler": poppler_outils.etat_poppler(),
        }

    t0 = time.perf_counter()
    (
        pieces,
        corpus,
        images,
        besoin_vision,
        avertissements,
        contenu_exploitable,
    ) = _preparer_corpus_pieces(session, ids)
    logger.info(
        "proposer_identite_prep pieces=%s images=%s vision=%s duree_ms=%s",
        len(pieces),
        len(images),
        besoin_vision,
        int((time.perf_counter() - t0) * 1000),
    )
    if not contenu_exploitable:
        msg = MESSAGE_AUCUN_CONTENU_EXPLOITABLE
        if avertissements:
            msg = f"{msg} {' ; '.join(avertissements)}"
        prop_id = _enregistrer_proposition(
            session,
            tenant_id,
            piece_ids=ids,
            champs={},
            citations=[],
            statut="indisponible",
            message=msg,
            contribuable_id=contribuable_id,
            session_upload=session_upload,
        )
        return {
            "disponible": False,
            "statut": "indisponible",
            "proposition_id": prop_id,
            "champs": {c: None for c in CHAMPS_IDENTITE},
            "champs_manquants": list(CHAMPS_IDENTITE),
            "citations": [],
            "message": _message_sans_provider(msg),
            "piece_ids": ids,
            "provider": None,
            "failover_depuis": [],
            "avertissements": avertissements,
            "poppler": poppler_outils.etat_poppler(),
        }
    user = (
        f"Pièces ({len(pieces)}) :\n\n{corpus}\n\n"
        f"Champs attendus : {', '.join(CHAMPS_IDENTITE)}"
    )
    if images:
        user += (
            f"\n\n{len(images)} image(s) jointe(s) "
            "(scan / photo) — lis le contenu visuel."
        )
    if avertissements:
        user += "\n\nAvertissements techniques :\n- " + "\n- ".join(avertissements)
    try:
        brut, provider_id, failover = _appeler_llm(
            _PROMPT_EXTRACTION,
            user,
            images=images,
            besoin_vision=besoin_vision,
        )
    except ErreurExtractionIdentite as e:
        msg = str(e)
        if avertissements:
            msg = f"{msg} — {' ; '.join(avertissements)}"
        prop_id = _enregistrer_proposition(
            session,
            tenant_id,
            piece_ids=ids,
            champs={},
            citations=[],
            statut="indisponible",
            message=msg,
            contribuable_id=contribuable_id,
            session_upload=session_upload,
        )
        return {
            "disponible": False,
            "statut": "indisponible",
            "proposition_id": prop_id,
            "champs": {c: None for c in CHAMPS_IDENTITE},
            "champs_manquants": list(CHAMPS_IDENTITE),
            "citations": [],
            "message": _message_sans_provider(msg),
            "piece_ids": ids,
            "provider": None,
            "failover_depuis": [],
            "avertissements": avertissements,
            "poppler": poppler_outils.etat_poppler(),
        }

    champs = _normaliser_champs(
        brut.get("champs") if isinstance(brut.get("champs"), dict) else brut
    )
    citations = _normaliser_citations(
        brut.get("citations") if isinstance(brut.get("citations"), list) else [],
        set(ids),
    )
    notes = str(brut.get("notes") or "").strip() or None
    via = libelle_provider(provider_id, failover)
    if via:
        logger.info(
            "proposer_identite %s provider=%s failover_depuis=%s total_ms=%s",
            via,
            provider_id,
            list(failover),
            int((time.perf_counter() - t0) * 1000),
        )
    manquants = _champs_manquants(champs)
    message = _message_sans_provider(notes)
    if manquants:
        n_ok = len(CHAMPS_IDENTITE) - len(manquants)
        message = (
            f"{message} {n_ok}/{len(CHAMPS_IDENTITE)} champs lus — "
            f"{len(manquants)} non lus sur les pièces (à saisir ou joindre)."
        )
    if avertissements:
        message = f"{message} Attention : {' ; '.join(avertissements)}"
    prop_id = _enregistrer_proposition(
        session,
        tenant_id,
        piece_ids=ids,
        champs=champs,
        citations=citations,
        statut="brouillon",
        message=message,
        contribuable_id=contribuable_id,
        session_upload=session_upload,
    )
    return {
        "disponible": True,
        "statut": "brouillon",
        "proposition_id": prop_id,
        "champs": champs,
        "champs_manquants": manquants,
        "citations": citations,
        "message": message,
        "piece_ids": ids,
        "provider": provider_id,
        "failover_depuis": list(failover),
        "avertissements": avertissements,
        "poppler": poppler_outils.etat_poppler(),
    }


def verifier_conformite(
    session: Session,
    tenant_id: int,
    *,
    champs_saisis: dict[str, Any],
    piece_ids: list[int] | None = None,
    session_upload: str | None = None,
    contribuable_id: int | None = None,
) -> dict[str, Any]:
    """Compare saisie ↔ pièces. Non bloquant pour le moteur fiscal."""
    ids = resoudre_piece_ids(
        session,
        piece_ids=piece_ids,
        session_upload=session_upload,
        contribuable_id=contribuable_id,
    )
    if not ids:
        raise ErreurExtractionIdentite("aucune pièce à comparer")

    if not llm_configure():
        return {
            "disponible": False,
            "statut": "indisponible",
            "ok": None,
            "ecarts": [],
            "message": MESSAGE_INDISPONIBLE,
            "piece_ids": ids,
            "provider": None,
            "failover_depuis": [],
            "avertissements": [],
            "poppler": poppler_outils.etat_poppler(),
        }

    (
        _,
        corpus,
        images,
        besoin_vision,
        avertissements,
        contenu_exploitable,
    ) = _preparer_corpus_pieces(session, ids)
    if not contenu_exploitable:
        msg = MESSAGE_AUCUN_CONTENU_EXPLOITABLE
        if avertissements:
            msg = f"{msg} {' ; '.join(avertissements)}"
        return {
            "disponible": False,
            "statut": "indisponible",
            "ok": None,
            "ecarts": [],
            "message": _message_sans_provider(msg),
            "piece_ids": ids,
            "provider": None,
            "failover_depuis": [],
            "avertissements": avertissements,
            "poppler": poppler_outils.etat_poppler(),
        }
    saisis = {
        k: champs_saisis.get(k)
        for k in CHAMPS_IDENTITE
        if champs_saisis.get(k) not in (None, "")
    }
    user = (
        f"Champs saisis (JSON) :\n{json.dumps(saisis, ensure_ascii=False)}\n\n"
        f"Pièces :\n{corpus}"
    )
    if images:
        user += f"\n\n{len(images)} image(s) jointe(s) pour contrôle visuel."
    try:
        brut, provider_id, failover = _appeler_llm(
            _PROMPT_CONFORMITE,
            user,
            images=images,
            besoin_vision=besoin_vision,
        )
    except ErreurExtractionIdentite as e:
        msg = str(e)
        if avertissements:
            msg = f"{msg} — {' ; '.join(avertissements)}"
        return {
            "disponible": False,
            "statut": "indisponible",
            "ok": None,
            "ecarts": [],
            "message": msg,
            "piece_ids": ids,
            "provider": None,
            "failover_depuis": [],
            "avertissements": avertissements,
            "poppler": poppler_outils.etat_poppler(),
        }

    ecarts_bruts = brut.get("ecarts") if isinstance(brut.get("ecarts"), list) else []
    ecarts: list[dict[str, Any]] = []
    for item in ecarts_bruts:
        if not isinstance(item, dict):
            continue
        champ = str(item.get("champ") or "").strip()
        if champ and champ not in CHAMPS_IDENTITE:
            continue
        sev = str(item.get("severity") or "ecart").lower()
        if sev not in {"ecart", "info"}:
            sev = "ecart"
        pid_raw = item.get("piece_id")
        try:
            pid = int(pid_raw) if pid_raw is not None else None
        except (TypeError, ValueError):
            pid = None
        ecarts.append(
            {
                "champ": champ or None,
                "saisi": (
                    None
                    if item.get("saisi") is None
                    else str(item.get("saisi"))[:300]
                ),
                "lu_dans_piece": (
                    None
                    if item.get("lu_dans_piece") is None
                    else str(item.get("lu_dans_piece"))[:300]
                ),
                "piece_id": pid,
                "severity": sev,
                "message": str(item.get("message") or "")[:500],
            }
        )
    ok = bool(brut.get("ok")) if "ok" in brut else not any(
        e["severity"] == "ecart" for e in ecarts
    )
    notes = str(brut.get("notes") or "").strip() or None
    via = libelle_provider(provider_id, failover)
    if via:
        logger.info(
            "verifier_conformite %s provider=%s failover_depuis=%s",
            via,
            provider_id,
            list(failover),
        )
    message = notes or (
        "Aucun écart détecté."
        if ok
        else "Écarts proposés — l'humain décide (non bloquant)."
    )
    _enregistrer_proposition(
        session,
        tenant_id,
        piece_ids=ids,
        champs={"_conformite": {"ok": ok, "ecarts": ecarts}},
        citations=[],
        statut="brouillon",
        message=message,
        contribuable_id=contribuable_id,
        session_upload=session_upload,
    )
    return {
        "disponible": True,
        "statut": "ok" if ok else "ecarts",
        "ok": ok,
        "ecarts": ecarts,
        "message": message,
        "piece_ids": ids,
        "provider": provider_id,
        "failover_depuis": list(failover),
        "avertissements": avertissements,
        "poppler": poppler_outils.etat_poppler(),
    }


def marquer_proposition_appliquee(
    session: Session, proposition_id: int
) -> None:
    """Marque un brouillon comme appliqué après validation humaine UI."""
    n = session.execute(
        text(
            "UPDATE proposition_identite SET statut = 'applique' "
            "WHERE id = :id AND statut = 'brouillon'"
        ),
        {"id": proposition_id},
    ).rowcount
    if not n:
        raise ErreurPieceContribuable(
            f"proposition {proposition_id} introuvable ou non brouillon"
        )
    session.flush()
