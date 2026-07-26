"""Ingestion déterministe du CGI / LPF depuis cgici.com (corpus éditorial brouillon).

Ne valide aucune règle fiscale. Ne purge aucun ``a_confirmer``.
Le scrape n'est pas un visa fiscaliste.

Source : version HTML « officielle » 2026 publiée sur https://cgici.com/
(Publications DGI / EssiC — mention « tous droits réservés »). Usage prévu :
corpus interne R&D pour croisement éditorial, pas republication du produit numérique.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

BASE_URL = "https://cgici.com"
USER_AGENT = (
    "RevueFiscaleIntelligent/1.0 (+corpus-editorial-rd; "
    "editeur=2AaZ; contact=corpus@zenapi.local)"
)
DOSSIER_PAGES = "V2026"
PAUSE_DEFAUT_S = 0.6

# Ancres / blocs d'historique millésime (à exclure du texte courant)
_RE_HIST_ID = re.compile(r"^h\d+$", re.I)
_RE_ARTICLE_INDEX = re.compile(
    r'Article\.insert\(\{art:(\d+),aType:"([^"]*)",html:"page-(\d+)\.html"\}'
)
_RE_PAGE_TITLE = re.compile(
    r'pageText\.insert\(\{pageno:(\d+),seqno:(\d+),title:"([^"]*)"\}'
)


@dataclass(frozen=True)
class EntreeArticleIndex:
    numero: int
    suffixe: str
    page: int

    @property
    def reference(self) -> str:
        if self.suffixe:
            return f"{self.numero} {self.suffixe}".strip()
        return str(self.numero)


@dataclass
class EntreeJournal:
    url: str
    page: int
    statut: int
    octets: int
    erreur: str | None = None


@dataclass
class ResultatTelechargement:
    pages: dict[int, str] = field(default_factory=dict)
    journal: list[EntreeJournal] = field(default_factory=list)
    index_articles: list[EntreeArticleIndex] = field(default_factory=list)


class _ExtracteurPage(HTMLParser):
    """Extrait le texte courant d'une page V2026 (hors scripts / historiques)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._ignorer = 0  # profondeur balises à ignorer
        self._dans_no_article = False
        self._buf_no_article: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        classes = attrs_d.get("class", "").lower()
        ident = attrs_d.get("id", "")

        if self._ignorer:
            self._ignorer += 1
            return

        if tag in {"script", "style", "noscript"}:
            self._ignorer = 1
            return
        if "historique" in classes or "histtext" in classes:
            self._ignorer = 1
            return
        if _RE_HIST_ID.match(ident):
            self._ignorer = 1
            return

        if tag == "h6" and "noarticle" in classes:
            self._dans_no_article = True
            self._buf_no_article = []
            self._parts.append("\n")
            return

        if tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5"}:
            self._parts.append("\n")
        elif tag == "td":
            self._parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if self._ignorer:
            self._ignorer -= 1
            return
        if tag == "h6" and self._dans_no_article:
            titre = unescape("".join(self._buf_no_article))
            titre = re.sub(r"\s+", " ", titre).strip()
            # Retire les boutons d'historique (« 2025... », « 2023... »)
            titre = re.sub(r"\b20\d{2}\.{2,}\s*", "", titre).strip()
            titre = re.sub(r"\s{2,}", " ", titre)
            if titre:
                self._parts.append(titre)
                self._parts.append("\n")
            self._dans_no_article = False
            self._buf_no_article = []
            return
        if tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "table"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignorer:
            return
        if self._dans_no_article:
            self._buf_no_article.append(data)
            return
        if data:
            self._parts.append(data)

    def texte(self) -> str:
        brut = "".join(self._parts)
        brut = unescape(brut)
        brut = brut.replace("\xa0", " ")
        brut = re.sub(r"[ \t]+\n", "\n", brut)
        brut = re.sub(r"\n{3,}", "\n\n", brut)
        brut = re.sub(r"[ \t]{2,}", " ", brut)
        return brut.strip()


def parser_index_articles(js_article_link: str) -> list[EntreeArticleIndex]:
    """Parse ``js/ArticleLink.js`` → liste d'articles (CGI + LPF)."""
    sorties: list[EntreeArticleIndex] = []
    for m in _RE_ARTICLE_INDEX.finditer(js_article_link):
        sorties.append(
            EntreeArticleIndex(
                numero=int(m.group(1)),
                suffixe=(m.group(2) or "").strip(),
                page=int(m.group(3)),
            )
        )
    return sorties


def pages_depuis_index(index: Iterable[EntreeArticleIndex]) -> list[int]:
    return sorted({e.page for e in index})


def filtrer_pages(
    pages: list[int],
    *,
    from_page: int | None = None,
    to_page: int | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> list[int]:
    """Découpe une liste de n° de pages (index trié) pour workers parallèles.

    Ordre d'application : filtre ``from_page``/``to_page`` (inclusifs sur le
    numéro de page), puis tranche ``offset``/``limit`` sur la liste restante.
    """
    cibles = list(pages)
    if from_page is not None:
        cibles = [p for p in cibles if p >= from_page]
    if to_page is not None:
        cibles = [p for p in cibles if p <= to_page]
    if offset is not None:
        if offset < 0:
            raise ValueError("offset doit être ≥ 0")
        cibles = cibles[offset:]
    if limit is not None:
        if limit < 0:
            raise ValueError("limit doit être ≥ 0")
        cibles = cibles[:limit]
    return cibles


def url_page(numero: int, *, base: str = BASE_URL, dossier: str = DOSSIER_PAGES) -> str:
    return f"{base.rstrip('/')}/{dossier}/page-{numero}.html"


def telecharger(
    url: str,
    *,
    timeout: float = 60.0,
    user_agent: str = USER_AGENT,
) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/javascript,*/*;q=0.8",
            "Accept-Language": "fr",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — URL contrôlée
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as e:
        return int(e.code), e.read() if e.fp else b""


def extraire_texte_page(html: str | bytes) -> str:
    if isinstance(html, bytes):
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                html = html.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            html = html.decode("utf-8", errors="replace")
    parser = _ExtracteurPage()
    parser.feed(html)
    parser.close()
    return parser.texte()


# LPF : le HTML reprend Art. 1, 2… alors qu'ArticleLink numérote 5001, 5002…
# Sans offset, l'ingestion écrase le CGI (UNIQUE source_document_id, reference).
OFFSET_LPF = 5000
_RE_ART_LIGNE = re.compile(
    r"^(Art(?:icle)?\.?\s*)(\d+)(\s*(?:"
    r"bis|ter|quater|quinquies|sexies|septies|octies|nonies|"
    r"decies|undecies|duodecies"
    r"))?",
    re.IGNORECASE | re.MULTILINE,
)


def pages_lpf_depuis_index(index: Iterable[EntreeArticleIndex]) -> set[int]:
    """Pages dont au moins un article ArticleLink a un numéro ≥ OFFSET_LPF."""
    return {e.page for e in index if e.numero >= OFFSET_LPF}


def reecrire_refs_lpf(texte: str, *, offset: int = OFFSET_LPF) -> str:
    """Réécrit ``Art. N`` → ``Art. {N+offset}`` sur les pages LPF."""

    def _rempl(m: re.Match[str]) -> str:
        num = int(m.group(2))
        if num >= offset:
            return m.group(0)
        suffixe = m.group(3) or ""
        return f"{m.group(1)}{num + offset}{suffixe}"

    return _RE_ART_LIGNE.sub(_rempl, texte)


def assembler_texte(
    pages: dict[int, str],
    *,
    en_tete: str | None = None,
    pages_lpf: set[int] | None = None,
) -> str:
    """Concatène les pages triées en un texte Art.-découpable.

    ``pages_lpf`` : numéros de page Livre de procédures → offset 5000 sur les
    en-têtes ``Art.`` pour éviter la collision avec le CGI.
    """
    lpf = pages_lpf or set()
    blocs: list[str] = []
    if en_tete:
        blocs.append(en_tete.rstrip() + "\n")
    for num in sorted(pages):
        texte = pages[num].strip()
        if not texte:
            continue
        if num in lpf:
            texte = reecrire_refs_lpf(texte)
            marque = f"<!-- page-{num} livre=LPF offset={OFFSET_LPF} -->"
        else:
            marque = f"<!-- page-{num} livre=CGI -->"
        blocs.append(f"\n\n{marque}\n\n{texte}")
    return "\n".join(blocs).strip() + "\n"


def telecharger_corpus_cgici(
    *,
    base: str = BASE_URL,
    dossier_pages: str = DOSSIER_PAGES,
    pause_s: float = PAUSE_DEFAUT_S,
    pages: list[int] | None = None,
    repertoire_brut: Path | None = None,
    timeout: float = 60.0,
    seulement_manquantes: bool = False,
    telecharger_index: bool = True,
) -> ResultatTelechargement:
    """Télécharge l'index + les pages HTML, journalise chaque URL.

    Si ``pages`` est None : toutes les pages référencées par ArticleLink.js
    (CGI + LPF numérotés).

    ``seulement_manquantes`` : si un ``page-N.html`` existe déjà sous
    ``repertoire_brut``, pas de re-téléchargement (safe pour workers parallèles).
    ``telecharger_index`` : False réutilise ``ArticleLink.js`` local (évite de
    réécrire l'index pendant qu'un autre worker scrape).
    """
    resultat = ResultatTelechargement()
    url_index = f"{base.rstrip('/')}/js/ArticleLink.js"
    index_local = (
        (repertoire_brut / "ArticleLink.js") if repertoire_brut is not None else None
    )

    if not telecharger_index and index_local is not None and index_local.is_file():
        brut = index_local.read_bytes()
        statut = 200
        resultat.journal.append(
            EntreeJournal(
                url=url_index,
                page=0,
                statut=statut,
                octets=len(brut),
                erreur="cache",
            )
        )
    else:
        statut, brut = telecharger(url_index, timeout=timeout)
        resultat.journal.append(
            EntreeJournal(url=url_index, page=0, statut=statut, octets=len(brut))
        )
        if statut != 200:
            raise RuntimeError(f"Échec téléchargement ArticleLink.js : HTTP {statut}")
        if repertoire_brut is not None:
            repertoire_brut.mkdir(parents=True, exist_ok=True)
            (repertoire_brut / "ArticleLink.js").write_bytes(brut)

    js = brut.decode("utf-8", errors="replace")
    resultat.index_articles = parser_index_articles(js)
    cibles = pages if pages is not None else pages_depuis_index(resultat.index_articles)

    http_faits = 0
    for num in cibles:
        url = url_page(num, base=base, dossier=dossier_pages)
        chemin_page = (
            (repertoire_brut / f"page-{num}.html") if repertoire_brut is not None else None
        )
        if (
            seulement_manquantes
            and chemin_page is not None
            and chemin_page.is_file()
            and chemin_page.stat().st_size > 0
        ):
            corps = chemin_page.read_bytes()
            resultat.journal.append(
                EntreeJournal(
                    url=url,
                    page=num,
                    statut=200,
                    octets=len(corps),
                    erreur="cache",
                )
            )
            resultat.pages[num] = extraire_texte_page(corps)
            continue

        if http_faits and pause_s > 0:
            time.sleep(pause_s)
        try:
            statut, corps = telecharger(url, timeout=timeout)
            erreur = None if statut == 200 else f"HTTP {statut}"
        except Exception as e:  # noqa: BLE001 — journaliser et continuer
            statut, corps, erreur = 0, b"", str(e)
        http_faits += 1
        resultat.journal.append(
            EntreeJournal(
                url=url,
                page=num,
                statut=statut,
                octets=len(corps),
                erreur=erreur,
            )
        )
        if statut != 200 or not corps:
            continue
        if chemin_page is not None:
            chemin_page.parent.mkdir(parents=True, exist_ok=True)
            # Écriture atomique : un worker parallèle ne lit pas un HTML tronqué.
            tmp = chemin_page.with_suffix(".html.partial")
            tmp.write_bytes(corps)
            tmp.replace(chemin_page)
        resultat.pages[num] = extraire_texte_page(corps)

    return resultat


def ecrire_journal(
    journal: list[EntreeJournal],
    chemin: Path,
    *,
    mode: str = "w",
) -> None:
    """Écrit le journal JSONL. ``mode='a'`` pour workers (n'écrase pas le principal)."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with chemin.open(mode, encoding="utf-8") as f:
        for e in journal:
            f.write(
                json.dumps(
                    {
                        "url": e.url,
                        "page": e.page,
                        "statut": e.statut,
                        "octets": e.octets,
                        "erreur": e.erreur,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def ecrire_meta(
    chemin: Path,
    *,
    millesime: int,
    n_pages: int,
    n_articles_index: int,
    n_caracteres: int,
    source: str = BASE_URL,
) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(
            {
                "source": source,
                "millesime": millesime,
                "dossier_pages": DOSSIER_PAGES,
                "pages_telechargees": n_pages,
                "articles_index_articlelink": n_articles_index,
                "caracteres_texte": n_caracteres,
                "mention": (
                    "Édité par Les Publications de la DGI et produit par EssiC "
                    "Ingénierie — tous droits réservés (c) 2015-2026. "
                    "Corpus éditorial brouillon interne ; pas un visa fiscaliste."
                ),
                "type_editorial": "cgi",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
