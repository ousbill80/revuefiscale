"""Croisement CGI corpus × inventaire ``a_confirmer``.

Outillage éditorial déterministe — pas un visa fiscaliste.
N'écrit aucun taux dans le code métier. Ne purge aucun YAML.
Classes : claire | contraste | faible | bloque.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.editorial.inventaire_a_confirmer import (
    MentionAConfirmer,
    scanner_mentions,
)

ClasseCroisement = Literal["claire", "contraste", "faible", "bloque"]

SOURCE_DOCUMENT_CGI_DEFAUT = 211  # offset LPF — art. 18 charges

# Catalogue JSON complet (claire / contraste / faible / bloque) — pas de purge.
FICHIER_CROISEMENT_JSON = (
    Path(__file__).resolve().parents[2] / "referentiel" / "croisement_cgi_2026.json"
)

# Libellés dérivés de l'identifiant de fiche → co-occurrence dans l'article.
LIBELLES_PAR_CLE: dict[str, tuple[str, ...]] = {
    "DONS": ("dons", "libéralités", "liberalites"),
    "ADMIN": ("administrateurs", "indemnités de fonction", "indemnites de fonction"),
    "SOUSCAP": ("bceao", "intérêts servis", "interets servis"),
    "FRAISSIEGE": ("frais de siège", "frais de siege", "frais généraux"),
    "INTERETS": ("intérêts", "interets", "redevances", "frais généraux"),
    "HONORAIRES": ("honoraires", "commissions", "courtages", "droits d'auteur"),
    "CBCR": ("pays par pays", "250 000 000 000", "déclaration"),
    "CADEAUX": ("cadeaux",),
    "PENALITES": ("pénalités", "penalites", "amendes"),
    "PATENTE": ("patente",),
    "RBE": ("bénéficiaires effectifs", "beneficiaires effectifs"),
}

# Pièges connus : marqueur trouvé sous un autre alinéa / article que celui allégué.
CONTRASTES_CONNUS: dict[str, dict[str, str]] = {
    "BIC-CHG-18A3-FRAISSIEGE#2": {
        "raison": (
            "Le plafond 5 %/20 % est sous art. 18 A) 5°, pas sous 3° "
            "(3° = salaire du conjoint). « frais de siège » absent du texte art. 18."
        ),
        "alinea_attendu": "3°",
        "alinea_observe": "5°",
    },
}


@dataclass(frozen=True)
class MarqueurNumerique:
    type: Literal["taux", "seuil", "taux_bceao"]
    brut: str
    valeur: float | int | None = None


@dataclass
class ResultatCroisement:
    entree_id: str
    rule_id: str
    index: int
    texte: str
    categorie: str
    priorite: str
    classe: ClasseCroisement
    article_reference: str | None = None
    article_trouve: bool = False
    marqueurs: list[dict[str, Any]] = field(default_factory=list)
    extrait: str | None = None
    raison: str = ""
    libelle_ok: bool | None = None
    alinea_ok: bool | None = None
    faux_amis: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).lower().strip()


def extraire_references_article(
    rule_id: str, reference_legale: str | None
) -> list[str]:
    """Références candidates (numéro, bis/ter, lettre) — ordre de préférence."""
    refs: list[str] = []
    if reference_legale:
        for m in re.finditer(
            r"art\.?\s*(\d+)\s*(bis|ter|quater|quinquies)?"
            r"(?:\s*[-–]?\s*([A-G]))?(?:\s*(\d+)\s*[°o])?",
            reference_legale,
            re.IGNORECASE,
        ):
            num, suf, lettre, _alinea = m.group(1), m.group(2), m.group(3), m.group(4)
            if suf:
                refs.append(f"{num} {suf.lower()}")
            else:
                refs.append(num)
            if lettre and not suf:
                refs.append(num)  # bloc A–G souvent fusionné sous le numéro
    # Identifiant : OBL-36BIS-CBCR → 36 bis ; BIC-CHG-18G-DONS → 18 ; BIC-CHG-18A4 → 18
    m = re.search(
        r"-(\d+)(BIS|TER|QUATER)?([A-G])?(?:-|$)",
        rule_id,
        re.IGNORECASE,
    )
    if m:
        num, suf, _lettre = m.group(1), m.group(2), m.group(3)
        if suf:
            refs.insert(0, f"{num} {suf.lower()}")
        else:
            refs.insert(0, num)
    out: list[str] = []
    seen: set[str] = set()
    for r in refs:
        k = _norm(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def extraire_alinea_allege(reference_legale: str | None, rule_id: str) -> str | None:
    if reference_legale:
        m = re.search(r"(\d+)\s*[°o]", reference_legale)
        if m:
            return f"{m.group(1)}°"
        m = re.search(r"\b([A-G])\b", reference_legale)
        if m and re.search(r"art\.?\s*\d+", reference_legale, re.I):
            # lettre de section (A–G), pas alinéa numéroté
            pass
    m = re.search(r"-(\d+)([A-G])(\d+)-", rule_id)
    if m:
        return f"{m.group(3)}°"
    m = re.search(r"-18([A-G])(\d+)-", rule_id)
    if m:
        return f"{m.group(2)}°"
    return None


def extraire_marqueurs(texte: str) -> list[MarqueurNumerique]:
    marks: list[MarqueurNumerique] = []
    t = texte
    if re.search(r"BCEAO\s*\+\s*2", t, re.I):
        marks.append(MarqueurNumerique("taux_bceao", "BCEAO + 2"))
    if re.search(r"\b250\s*Md\b", t, re.I):
        marks.append(MarqueurNumerique("seuil", "250 Md", 250_000_000_000))
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*%", t):
        marks.append(
            MarqueurNumerique(
                "taux",
                m.group(0),
                float(m.group(1).replace(",", ".")) / 100.0,
            )
        )
    # Montants espacés (éviter 01/01/2026 → 01, 01, 2026)
    for m in re.finditer(r"(?<![/\d])(\d{1,3}(?:\s\d{3})+)(?![/\d])", t):
        digits = m.group(1).replace(" ", "")
        if len(digits) >= 4:
            marks.append(MarqueurNumerique("seuil", m.group(1).strip(), int(digits)))
    for m in re.finditer(r"(?<![/\d])(\d{4,})(?![/\d])", t):
        # déjà capturé via espaces ? skip doublons
        val = int(m.group(1))
        if not any(x.type == "seuil" and x.valeur == val for x in marks):
            marks.append(MarqueurNumerique("seuil", m.group(1), val))
    return marks


def _fenetre(texte: str, idx: int, rayon: int = 90) -> str:
    a = max(0, idx - rayon)
    b = min(len(texte), idx + rayon)
    return re.sub(r"\s+", " ", texte[a:b]).strip()


def chercher_marqueur_dans_texte(
    article_txt: str, mark: MarqueurNumerique
) -> tuple[bool, str]:
    """Correspondance stricte (évite 50 000 ≠ 50 000 000)."""
    n = _norm(article_txt)
    if mark.type == "taux_bceao":
        ok = "bceao" in n and (
            "majore de deux" in n or "deux points" in n or "majoré de deux" in article_txt.lower()
        )
        if not ok:
            return False, ""
        idx = n.find("bceao")
        return True, _fenetre(article_txt, idx)

    if mark.type == "taux" and mark.valeur is not None:
        pct = float(mark.valeur) * 100.0
        # Formes acceptées
        candidats: list[str] = []
        if abs(pct - round(pct)) < 1e-9:
            i = int(round(pct))
            candidats += [f"{i} %", f"{i}%", f"{i} pour cent"]
        else:
            s = f"{pct:.10g}".replace(".", ",")
            candidats += [f"{s} %", f"{s}%"]
            s2 = f"{pct:.10g}"
            candidats += [f"{s2} %", f"{s2}%"]
        for c in candidats:
            cn = _norm(c)
            # ancrage : pas de chiffre immédiatement avant (évite 25 % pour 5 %)
            pat = re.compile(
                r"(?<!\d)" + re.escape(c).replace(r"\ ", r"\s*"),
                re.IGNORECASE,
            )
            m = pat.search(article_txt)
            if m:
                return True, _fenetre(article_txt, m.start())
            if cn in n:
                # vérifier bordure chiffre
                idx = n.find(cn)
                if idx > 0 and n[idx - 1].isdigit():
                    continue
                return True, _fenetre(article_txt, idx)
        return False, ""

    if mark.type == "seuil" and mark.valeur is not None:
        val = int(mark.valeur)
        formes = [f"{val:,}".replace(",", " "), str(val)]
        if val == 200_000_000:
            formes += ["200 millions"]
        if val == 250_000_000_000:
            formes += ["250 000 000 000", "250 milliards"]
        for f in formes:
            # Match exact sur tokens numériques : « 50 000 » ne matche pas « 50 000 000 »
            if f.replace(" ", "").isdigit() or re.fullmatch(r"[\d\s]+", f):
                digits = f.replace(" ", "")
                # Isolé : pas de digit avant, pas d'autre groupe numérique après
                spaced = f"{val:,}".replace(",", " ")
                pat_spaced = re.compile(
                    r"(?<!\d)"
                    + r"[\s\u00a0]*".join(re.escape(p) for p in spaced.split())
                    + r"(?![\s\u00a0]*\d)",
                )
                pat_compact = re.compile(rf"(?<!\d){re.escape(digits)}(?!\d)")
                txt_norm = article_txt.replace("\u00a0", " ")
                for p in (pat_spaced, pat_compact):
                    m = p.search(txt_norm)
                    if m:
                        return True, _fenetre(article_txt, m.start())
            else:
                if _norm(f) in n:
                    return True, _fenetre(article_txt, n.find(_norm(f)))
        return False, ""

    return False, ""


def resoudre_article(
    articles: dict[str, str], refs: list[str]
) -> tuple[str | None, str | None]:
    """Retourne (reference, texte) ou (None, None)."""
    by_norm = {_norm(k): (k, v) for k, v in articles.items()}
    for r in refs:
        if r in articles:
            return r, articles[r]
        hit = by_norm.get(_norm(r))
        if hit:
            return hit
        # « 36bis » vs « 36 bis »
        compact = _norm(r).replace(" ", "")
        for kn, (k, v) in by_norm.items():
            if kn.replace(" ", "") == compact:
                return k, v
    # Fallback : numéro seul
    for r in refs:
        m = re.match(r"^(\d+)", r)
        if m and m.group(1) in articles:
            return m.group(1), articles[m.group(1)]
    return None, None


def libelles_pour(rule_id: str) -> tuple[str, ...]:
    for cle, libs in LIBELLES_PAR_CLE.items():
        if cle in rule_id.upper():
            return libs
    return ()


def verifier_libelle(article_txt: str, rule_id: str) -> bool | None:
    libs = libelles_pour(rule_id)
    if not libs:
        return None
    n = _norm(article_txt)
    return any(_norm(lib) in n for lib in libs)


def verifier_alinea(article_txt: str, alinea: str | None, mark: MarqueurNumerique) -> bool | None:
    """Si un alinéa est allégué, vérifie que le marqueur tombe dans ce bloc."""
    if not alinea:
        return None
    # Découpe heuristique « N°- »
    parts = re.split(r"(?=(?:^|\n)\s*\d+\s*-°?\s*)", article_txt)
    if len(parts) < 2:
        parts = re.split(r"(?=\d+-°?\s)", article_txt)
    cible = alinea.replace("°", "").strip()
    bloc = None
    for p in parts:
        head = p[:20]
        if re.match(rf"\s*{re.escape(cible)}\s*-°?", head) or re.match(
            rf"\s*{re.escape(cible)}-°?", head
        ):
            bloc = p
            break
        if re.match(rf"\s*{re.escape(cible)}°-?", head):
            bloc = p
            break
    if bloc is None:
        # Essai « 4°- » littéral
        m = re.search(
            rf"{re.escape(cible)}°-?\s*(.*?)(?=\d+-°|\Z)",
            article_txt,
            re.S,
        )
        if m:
            bloc = m.group(0)
    if bloc is None:
        return None  # découpe incertaine — ne force pas
    ok, _ = chercher_marqueur_dans_texte(bloc, mark)
    return ok


def charger_articles_cgi(
    session: Session, *, source_document_id: int = SOURCE_DOCUMENT_CGI_DEFAUT
) -> dict[str, str]:
    rows = session.execute(
        text(
            "SELECT reference, texte FROM article_corpus "
            "WHERE source_document_id = :sid"
        ),
        {"sid": source_document_id},
    ).mappings().all()
    return {str(r["reference"]): str(r["texte"]) for r in rows}


def _chercher_faux_amis(
    articles: dict[str, str],
    mark: MarqueurNumerique,
    ref_attendue: str | None,
    rule_id: str,
) -> list[str]:
    """Articles où le marqueur apparaît hors de la référence attendue (+ libellé)."""
    libs = libelles_pour(rule_id)
    amis: list[str] = []
    for ref, txt in articles.items():
        if ref_attendue and _norm(ref) == _norm(ref_attendue):
            continue
        ok, _ = chercher_marqueur_dans_texte(txt, mark)
        if not ok:
            continue
        if libs and not any(_norm(lib) in _norm(txt) for lib in libs):
            # chiffre seul ailleurs sans libellé → faux ami faible, on note quand même
            # si montant « proche » (même préfixe)
            amis.append(ref)
            continue
        amis.append(ref)
    return amis[:8]


def classer_mention(
    mention: MentionAConfirmer,
    articles: dict[str, str],
) -> ResultatCroisement:
    eid = f"{mention.identifiant}#{mention.index}"
    base = ResultatCroisement(
        entree_id=eid,
        rule_id=mention.identifiant,
        index=mention.index,
        texte=mention.texte,
        categorie=mention.categorie,
        priorite=mention.priorite,
        classe="bloque",
    )

    if mention.priorite == "hors_perimetre":
        base.classe = "bloque"
        base.raison = "hors_perimetre (doc client / validation métier)"
        return base

    if mention.priorite == "bloqueur" and mention.categorie != "agregat":
        base.classe = "bloque"
        base.raison = "bloqueur sémantique (périmètre / définition)"
        return base

    refs = extraire_references_article(mention.identifiant, mention.reference_legale)
    ref, txt = resoudre_article(articles, refs)
    base.article_reference = ref
    base.article_trouve = txt is not None

    # Contraste éditorial connu (piège de libellé)
    if eid in CONTRASTES_CONNUS and txt:
        meta = CONTRASTES_CONNUS[eid]
        marks = extraire_marqueurs(mention.texte)
        extrait = None
        for mk in marks:
            ok, ex = chercher_marqueur_dans_texte(txt, mk)
            if ok:
                extrait = ex
                break
        base.classe = "contraste"
        base.raison = meta["raison"]
        base.extrait = extrait
        base.marqueurs = [asdict(m) for m in marks]
        base.alinea_ok = False
        return base

    if mention.categorie == "date":
        if txt:
            # Présence art. ≠ preuve de date d'effet seed
            base.classe = "faible"
            base.raison = "article_present_date_non_prouvee"
        else:
            base.classe = "bloque"
            base.raison = "article_absent_ou_hors_cgi"
        return base

    if not txt:
        # 49 ter etc.
        base.classe = "bloque"
        base.raison = f"article_introuvable refs={refs}"
        return base

    if mention.priorite == "bloqueur" and mention.categorie == "agregat":
        # Ex. assiette 30 % — chiffre peut être là, assiette non figée
        marks = extraire_marqueurs(mention.texte)
        hits = []
        for mk in marks:
            ok, ex = chercher_marqueur_dans_texte(txt, mk)
            if ok:
                hits.append((mk, ex))
        base.marqueurs = [asdict(m) for m in marks]
        base.libelle_ok = verifier_libelle(txt, mention.identifiant)
        if hits:
            base.classe = "contraste"
            base.extrait = hits[0][1]
            base.raison = (
                "chiffre présent dans l'article allégué, mais mention bloqueur "
                "(assiette / agrégat à figer) — pas une piste claire de purge"
            )
        else:
            base.classe = "bloque"
            base.raison = "bloqueur_agregat_sans_chiffre_confirme"
        return base

    marks = extraire_marqueurs(mention.texte)
    base.marqueurs = [asdict(m) for m in marks]
    base.libelle_ok = verifier_libelle(txt, mention.identifiant)

    if not marks:
        base.classe = "faible"
        base.raison = "pas_de_marqueur_chiffre_extractible"
        return base

    alinea = extraire_alinea_allege(mention.reference_legale, mention.identifiant)
    hits: list[tuple[MarqueurNumerique, str]] = []
    alinea_results: list[bool | None] = []
    for mk in marks:
        ok, ex = chercher_marqueur_dans_texte(txt, mk)
        if ok:
            hits.append((mk, ex))
            alinea_results.append(verifier_alinea(txt, alinea, mk))
            base.faux_amis = _chercher_faux_amis(articles, mk, ref, mention.identifiant)

    if not hits:
        base.classe = "faible"
        base.raison = "marqueur_absent_du_texte_article"
        return base

    base.extrait = hits[0][1]
    # Alinéa : si un False explicite → contraste
    if any(a is False for a in alinea_results):
        base.classe = "contraste"
        base.alinea_ok = False
        base.raison = (
            f"marqueur trouvé dans l'article {ref} mais hors alinéa allégué "
            f"({alinea})"
        )
        return base

    # Libellé requis pour les fiches à clé connue : absence → contraste / faible
    if base.libelle_ok is False:
        base.classe = "contraste"
        base.raison = (
            f"chiffre trouvé dans art. {ref} mais libellé fiche absent du texte "
            f"(risque de faux ami)"
        )
        return base

    base.classe = "claire"
    base.alinea_ok = True if any(a is True for a in alinea_results) else None
    base.raison = "marqueur_chiffre_sous_article_allege"
    if base.faux_amis:
        # Informer sans déclasser si libellé + article OK
        base.raison += f" ; faux_amis_potentiels={base.faux_amis}"
    return base


def croiser_inventaire(
    session: Session,
    *,
    source_document_id: int = SOURCE_DOCUMENT_CGI_DEFAUT,
    mentions: list[MentionAConfirmer] | None = None,
) -> dict[str, Any]:
    """Produit le rapport de croisement (structure JSON)."""
    articles = charger_articles_cgi(session, source_document_id=source_document_id)
    items = mentions if mentions is not None else scanner_mentions()
    resultats = [classer_mention(m, articles) for m in items]
    par_classe: dict[str, list[dict[str, Any]]] = {
        "claire": [],
        "contraste": [],
        "faible": [],
        "bloque": [],
    }
    for r in resultats:
        par_classe[r.classe].append(asdict(r))

    return {
        "genere_le": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_document_id": source_document_id,
        "n_articles": len(articles),
        "n_mentions": len(resultats),
        "comptes": {k: len(v) for k, v in par_classe.items()},
        "par_classe": par_classe,
        "avertissement": (
            "Croisement heuristique — pas une validation fiscale. "
            "Aucune purge a_confirmer. L'humain valide."
        ),
    }


def generer_markdown(rapport: dict[str, Any]) -> str:
    c = rapport["comptes"]
    lignes = [
        "# CGI CI 2026 × inventaire `a_confirmer` (v2)",
        "",
        "> Rapport de croisement éditorial **automatisé** — pas une validation fiscale.",
        "> Aucun `a_confirmer` retiré des YAML. Matching article / numéro / libellé / alinéa.",
        "> Classes : **claire** · **contraste** · **faible** · **bloque**.",
        "",
        "| | |",
        "|---|---|",
        f"| Source corpus | `source_document_id={rapport['source_document_id']}` "
        f"· **{rapport['n_articles']}** articles |",
        f"| Inventaire | **{rapport['n_mentions']}** mentions |",
        f"| Généré | {rapport['genere_le']} |",
        "| Script | `make croiser-cgi` → `backend.scripts.croiser_cgi_a_confirmer` |",
        "",
        "---",
        "",
        "## Verdict chiffré",
        "",
        "| Classe | Mentions | Sens |",
        "|---|---:|---|",
        f"| **Claire** | **{c['claire']}** | Marqueur taux/seuil sous l'article allégué "
        f"(+ libellé si connu) |",
        f"| **Contraste** | **{c['contraste']}** | Chiffre trouvé mais alinéa / libellé / "
        f"bloqueur d'assiette conflictuel |",
        f"| **Faible** | **{c['faible']}** | Article présent sans preuve du marqueur "
        f"(surtout dates 01/01/2026) |",
        f"| **Bloqué** | **{c['bloque']}** | Hors périmètre, bloqueur, article absent |",
        "",
        "**0 purge** YAML. Ne pas forcer un match douteux.",
        "",
        "---",
        "",
        "## A. Pistes claires",
        "",
    ]
    for r in rapport["par_classe"]["claire"]:
        lignes += [
            f"### `{r['entree_id']}` — art. {r.get('article_reference')}",
            "",
            f"- Mention : {r['texte']}",
            f"- Extrait : « {r.get('extrait') or '—'} »",
            f"- Raison : {r.get('raison')}",
            "- Statut : `a_valider_humain`",
            "",
        ]
    if not rapport["par_classe"]["claire"]:
        lignes.append("_Aucune._")
        lignes.append("")

    lignes += ["## B. Contrastes", ""]
    for r in rapport["par_classe"]["contraste"]:
        lignes += [
            f"### `{r['entree_id']}`",
            "",
            f"- {r.get('raison')}",
            f"- Extrait : « {r.get('extrait') or '—'} »",
            "",
        ]
    if not rapport["par_classe"]["contraste"]:
        lignes.append("_Aucun._")
        lignes.append("")

    lignes += [
        "## C. Faibles (échantillon)",
        "",
        "Article présent ≠ confirmation de date / marqueur non extractible.",
        "",
    ]
    for r in rapport["par_classe"]["faible"][:25]:
        lignes.append(
            f"- `{r['entree_id']}` — {r.get('raison')} "
            f"(art. {r.get('article_reference') or '—'})"
        )
    reste_f = len(rapport["par_classe"]["faible"]) - 25
    if reste_f > 0:
        lignes.append(f"- … +{reste_f} autres")
    lignes += ["", "## D. Bloqués (échantillon)", ""]
    for r in rapport["par_classe"]["bloque"][:20]:
        lignes.append(f"- `{r['entree_id']}` — {r.get('raison')}")
    reste_b = len(rapport["par_classe"]["bloque"]) - 20
    if reste_b > 0:
        lignes.append(f"- … +{reste_b} autres")

    lignes += [
        "",
        "---",
        "",
        "## Seed propositions",
        "",
        "```bash",
        "make croiser-cgi          # régénère ce rapport + catalogue pistes claires",
        "make seed-pistes-cgi      # dépose seulement les NOUVELLES pistes (idempotent)",
        "```",
        "",
        "Catalogue : `referentiel/propositions_cgi_2026_pistes.json`.",
        "",
        "**À confirmer** : toute lecture d'un taux / seuil / date comme droit positif "
        "reste soumise au fiscaliste 2AàZ.",
        "",
    ]
    return "\n".join(lignes)


def resultats_vers_pistes_catalogue(
    rapport: dict[str, Any],
    *,
    pistes_existantes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Construit / fusionne des entrées catalogue pour classes claire (+ contraste connus).

    N'invente aucune valeur fiscale : reprend extrait + suggestion éditoriale générique.
    **Ne promeut jamais** une classe ``faible`` en claire.
    """
    existantes = list(pistes_existantes or [])
    par_entree = {str(p.get("entree_id")): p for p in existantes if p.get("entree_id")}
    nouvelles: list[dict[str, Any]] = []

    def _piste_id(entree_id: str, classe: str) -> str:
        safe = entree_id.replace("#", "-")
        prefix = "C" if classe == "claire" else "X"
        return f"{prefix}-{safe}"

    for classe in ("claire", "contraste"):
        for r in rapport["par_classe"][classe]:
            eid = r["entree_id"]
            if eid in par_entree:
                continue
            # Ne seed auto que les claires ; contrastes seulement s'ils sont dans
            # CONTRASTES_CONNUS ou agregat avec chiffre (signal éditorial).
            if (
                classe == "contraste"
                and eid not in CONTRASTES_CONNUS
                and "bloqueur" not in (r.get("raison") or "")
            ):
                continue
            sug_val = None
            marks = r.get("marqueurs") or []
            if marks and marks[0].get("valeur") is not None:
                sug_val = str(marks[0]["valeur"])
            elif marks and marks[0].get("brut"):
                sug_val = marks[0]["brut"]
            index_m = int(r["index"])
            piste = {
                "piste_id": _piste_id(eid, classe),
                "entree_id": eid,
                "rule_id": r["rule_id"],
                "categorie_mention": r["categorie"],
                "classe_croisement": classe,
                "article_corpus": r.get("article_reference"),
                "extrait_cgi": r.get("extrait") or "",
                "suggestion": (
                    r.get("raison")
                    if classe == "contraste"
                    else (
                        "Croiser le marqueur seed avec l'extrait CGI. "
                        "Ne pas purger sans visa fiscaliste."
                    )
                ),
                "suggestion_valeur": sug_val,
                "suggestion_structuree": {
                    "champ": None,
                    "valeur": sug_val,
                    "index_a_confirmer": index_m,
                    "entree_id": eid,
                    "retirer_a_confirmer_autorise": False,
                    "source_document_id": rapport["source_document_id"],
                    "article_corpus": r.get("article_reference"),
                    "extrait": r.get("extrait"),
                },
                "interdiction": (
                    "Ne pas retirer a_confirmer sans action humaine explicite "
                    "d'acceptation + visa."
                    if classe == "claire"
                    else "Interdit de purger sur un contraste / faux ami."
                ),
                "statut_editorial": "a_valider_humain",
            }
            nouvelles.append(piste)
            par_entree[eid] = piste

    return existantes + nouvelles


def ecrire_catalogue_croisement(
    rapport: dict[str, Any],
    *,
    chemin: Path | None = None,
) -> Path:
    """Persiste le rapport JSON (faibles inclus) pour la console — sans promotion."""
    path = chemin or FICHIER_CROISEMENT_JSON
    payload = {
        "genere_le": rapport.get("genere_le"),
        "source_document_id": rapport.get("source_document_id"),
        "n_articles": rapport.get("n_articles"),
        "n_mentions": rapport.get("n_mentions"),
        "comptes": rapport.get("comptes") or {},
        "par_classe": {
            "claire": list((rapport.get("par_classe") or {}).get("claire") or []),
            "contraste": list((rapport.get("par_classe") or {}).get("contraste") or []),
            "faible": list((rapport.get("par_classe") or {}).get("faible") or []),
            "bloque": list((rapport.get("par_classe") or {}).get("bloque") or []),
        },
        "rapport_md": "docs/21-cgi-vs-a-confirmer-v2.md",
        "avertissement": (
            "Catalogue croisement CGI — revue humaine priorisée. "
            "Les matches faibles ne sont PAS promus en claire. "
            "Aucune purge a_confirmer."
        ),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def charger_catalogue_croisement(
    chemin: Path | None = None,
) -> dict[str, Any] | None:
    """Charge le JSON croisement (None si absent)."""
    path = chemin or FICHIER_CROISEMENT_JSON
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def index_classes_croisement(
    catalogue: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map ``entree_id`` → méta croisement (classe, raison, extrait…)."""
    cat = catalogue if catalogue is not None else charger_catalogue_croisement()
    if not cat:
        return {}
    out: dict[str, dict[str, Any]] = {}
    par = cat.get("par_classe") or {}
    for classe, items in par.items():
        if not isinstance(items, list):
            continue
        for r in items:
            if not isinstance(r, dict):
                continue
            eid = str(r.get("entree_id") or "").strip()
            if not eid:
                continue
            faux = r.get("faux_amis")
            if not isinstance(faux, list):
                faux = []
            out[eid] = {
                "classe_croisement": classe,
                "raison": r.get("raison"),
                "article_reference": r.get("article_reference"),
                "extrait": r.get("extrait"),
                "article_trouve": r.get("article_trouve"),
                "categorie": r.get("categorie"),
                "priorite": r.get("priorite"),
                "texte": r.get("texte"),
                "rule_id": r.get("rule_id"),
                "faux_amis": [str(x) for x in faux if x is not None and str(x).strip()],
                "faux_amis_potentiels": [
                    str(x) for x in faux if x is not None and str(x).strip()
                ],
            }
    return out


def enrichir_entrees_croisement(
    entrees: list[dict[str, Any]],
    index: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Ajoute ``classe_croisement`` / méta (faibles inclus) — pas de promotion."""
    idx = index if index is not None else index_classes_croisement()
    enrichies: list[dict[str, Any]] = []
    for e in entrees:
        if not isinstance(e, dict):
            continue
        copie = dict(e)
        eid = str(e.get("id") or "")
        meta = idx.get(eid)
        if meta:
            copie["classe_croisement"] = meta.get("classe_croisement")
            copie["croisement_cgi_meta"] = meta
        enrichies.append(copie)
    return enrichies