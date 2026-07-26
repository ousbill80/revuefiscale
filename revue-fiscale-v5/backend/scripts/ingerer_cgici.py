"""CLI — scrape cgici.com → texte corpus → ingestion éditoriale (brouillon).

Usage :
  python -m backend.scripts.ingerer_cgici --dry-run
  python -m backend.scripts.ingerer_cgici --millesime 2026
  python -m backend.scripts.ingerer_cgici --depuis-cache  # sans re-télécharger
  python -m backend.scripts.ingerer_cgici --cache-seulement --offset 0 --limit 180
  python -m backend.scripts.ingerer_cgici --cache-seulement --from-page 500 --to-page 973

N'écrit aucune règle fiscale. Ne purge aucun ``a_confirmer``.
Le scrape n'est pas un visa fiscaliste.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from backend.corpus.cgici import (  # noqa: E402
    BASE_URL,
    DOSSIER_PAGES,
    PAUSE_DEFAUT_S,
    USER_AGENT,
    assembler_texte,
    ecrire_journal,
    ecrire_meta,
    extraire_texte_page,
    filtrer_pages,
    pages_depuis_index,
    pages_lpf_depuis_index,
    parser_index_articles,
    telecharger,
    telecharger_corpus_cgici,
)
from backend.corpus.ingestion import _decouper_articles, ingerer_document  # noqa: E402
from backend.db import Fabrique  # noqa: E402

DIR_CACHE = _RACINE / "corpus_sources" / "cgici_2026"
FICHIER_TEXTE = _RACINE / "corpus_sources" / "CGI-CI-2026-cgici.txt"
JOURNAL = DIR_CACHE / "journal_urls.jsonl"
META = DIR_CACHE / "meta.json"
BRUT = DIR_CACHE / "pages"

PAUSE_MIN_S = 0.4

EN_TETE = """\
# CGI Côte d'Ivoire + LPF — extraction HTML cgici.com (brouillon éditorial)
# Source : {base} — millésime {millesime}
# Mentions site : Publications DGI / EssiC — tous droits réservés (c) 2015-2026
# Usage : corpus interne R&D. Pas un visa fiscaliste. Ne purge aucun a_confirmer.
"""


def _charger_depuis_cache() -> tuple[dict[int, str], int]:
    """Reconstruit pages depuis HTML locaux ou depuis le .txt assemblé."""
    pages: dict[int, str] = {}
    if BRUT.is_dir():
        for f in sorted(BRUT.glob("page-*.html")):
            try:
                num = int(f.stem.split("-", 1)[1])
            except (IndexError, ValueError):
                continue
            pages[num] = extraire_texte_page(f.read_bytes())
        if pages:
            return pages, len(pages)

    if FICHIER_TEXTE.is_file():
        return {0: FICHIER_TEXTE.read_text(encoding="utf-8")}, 1

    raise SystemExit(
        f"Cache introuvable ({BRUT} ou {FICHIER_TEXTE}). "
        "Lancer sans --depuis-cache."
    )


def _resoudre_cibles(
    *,
    max_pages: int | None,
    from_page: int | None,
    to_page: int | None,
    offset: int | None,
    limit: int | None,
) -> list[int] | None:
    """Construit la liste de pages à télécharger, ou None = tout l'index."""
    besoin_index = any(
        v is not None for v in (max_pages, from_page, to_page, offset, limit)
    )
    if not besoin_index:
        return None

    index_path = BRUT / "ArticleLink.js"
    if index_path.is_file():
        idx = parser_index_articles(
            index_path.read_text(encoding="utf-8", errors="replace")
        )
    else:
        st, brut = telecharger(f"{BASE_URL}/js/ArticleLink.js")
        if st != 200:
            raise SystemExit(f"ERREUR ArticleLink.js HTTP {st}")
        BRUT.mkdir(parents=True, exist_ok=True)
        index_path.write_bytes(brut)
        idx = parser_index_articles(brut.decode("utf-8", errors="replace"))

    cibles = pages_depuis_index(idx)
    cibles = filtrer_pages(
        cibles,
        from_page=from_page,
        to_page=to_page,
        offset=offset,
        limit=limit if limit is not None else max_pages,
    )
    return cibles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Télécharge CGI+LPF depuis cgici.com et ingère en corpus éditorial. "
            "Brouillon sourcé — pas de validation fiscale."
        )
    )
    parser.add_argument("--millesime", type=int, default=2026)
    parser.add_argument(
        "--pause",
        type=float,
        default=PAUSE_DEFAUT_S,
        help=f"Pause entre requêtes HTTP (secondes, min {PAUSE_MIN_S})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limite de pages (smoke / debug) — alias de --limit sur l'index",
    )
    parser.add_argument(
        "--from-page",
        type=int,
        default=None,
        help="N° de page HTML minimum (inclusif, après lecture ArticleLink)",
    )
    parser.add_argument(
        "--to-page",
        type=int,
        default=None,
        help="N° de page HTML maximum (inclusif)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=None,
        help="Décalage dans la liste triée des pages ArticleLink",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Nombre max de pages après filtres / offset",
    )
    parser.add_argument(
        "--seulement-manquantes",
        action="store_true",
        help="Ne re-télécharge pas les page-N.html déjà présents en cache",
    )
    parser.add_argument(
        "--cache-seulement",
        action="store_true",
        help=(
            "Worker parallèle : écrit uniquement les HTML manquants + journal "
            "partiel. Pas d'assemblage texte, pas d'import DB."
        ),
    )
    parser.add_argument(
        "--depuis-cache",
        action="store_true",
        help="Réutilise HTML/texte déjà téléchargés sous corpus_sources/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Télécharge / assemble sans écrire en base",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Alias de --depuis-cache",
    )
    parser.add_argument(
        "--titre",
        type=str,
        default=None,
        help="Titre source_document",
    )
    args = parser.parse_args(argv)
    depuis_cache = args.depuis_cache or args.skip_download

    if args.pause < PAUSE_MIN_S:
        print(
            f"Pause {args.pause}s < {PAUSE_MIN_S}s — relevée à {PAUSE_MIN_S}s "
            "(rate-limit).",
            file=sys.stderr,
        )
        args.pause = PAUSE_MIN_S

    if args.cache_seulement and depuis_cache:
        print(
            "Incompatible : --cache-seulement et --depuis-cache.",
            file=sys.stderr,
        )
        return 2

    n_index = 0
    journal_ok = False
    pages_lpf: set[int] = set()

    if depuis_cache:
        pages_map, _ = _charger_depuis_cache()
        index_path = BRUT / "ArticleLink.js"
        index_arts = []
        if index_path.is_file():
            index_arts = parser_index_articles(
                index_path.read_text(encoding="utf-8", errors="replace")
            )
            n_index = len(index_arts)
            pages_lpf = pages_lpf_depuis_index(index_arts)
        if 0 in pages_map and len(pages_map) == 1:
            texte = pages_map[0]
            n_pages = max(texte.count("<!-- page-"), 1)
        else:
            en_tete = EN_TETE.format(base=BASE_URL, millesime=args.millesime)
            texte = assembler_texte(
                pages_map, en_tete=en_tete, pages_lpf=pages_lpf
            )
            n_pages = len(pages_map)
            FICHIER_TEXTE.parent.mkdir(parents=True, exist_ok=True)
            FICHIER_TEXTE.write_text(texte, encoding="utf-8")
            ecrire_meta(
                META,
                millesime=args.millesime,
                n_pages=n_pages,
                n_articles_index=n_index,
                n_caracteres=len(texte),
            )
        journal_ok = JOURNAL.is_file()
    else:
        try:
            cibles = _resoudre_cibles(
                max_pages=args.max_pages,
                from_page=args.from_page,
                to_page=args.to_page,
                offset=args.offset,
                limit=args.limit,
            )
        except SystemExit as e:
            print(str(e), file=sys.stderr)
            return 1

        cache_seulement = args.cache_seulement
        seulement_manquantes = args.seulement_manquantes or cache_seulement
        # Workers : réutiliser l'index local s'il existe pour ne pas écraser
        # ArticleLink.js pendant qu'un scrape principal tourne.
        index_local = BRUT / "ArticleLink.js"
        telecharger_index = not (cache_seulement and index_local.is_file())

        print(
            f"Téléchargement {BASE_URL}/{DOSSIER_PAGES}/ "
            f"— pause {args.pause}s — UA={USER_AGENT}"
        )
        if cibles is not None:
            print(
                f"Plage : {len(cibles)} pages "
                f"(from={args.from_page} to={args.to_page} "
                f"offset={args.offset} limit={args.limit or args.max_pages})"
            )
        if seulement_manquantes:
            print("Mode reprise : pages déjà en cache ignorées (pas de HTTP).")

        resultat = telecharger_corpus_cgici(
            pause_s=args.pause,
            pages=cibles,
            repertoire_brut=BRUT,
            seulement_manquantes=seulement_manquantes,
            telecharger_index=telecharger_index,
        )

        if cache_seulement:
            # Journal partiel : n'écrase pas journal_urls.jsonl du scrape principal.
            if args.offset is not None or args.limit is not None:
                journal_partiel = (
                    DIR_CACHE
                    / f"journal_urls.w-off{args.offset or 0}-lim{args.limit or 'all'}.jsonl"
                )
            elif args.from_page is not None or args.to_page is not None:
                tag_from = args.from_page if args.from_page is not None else (
                    cibles[0] if cibles else "min"
                )
                tag_to = args.to_page if args.to_page is not None else (
                    cibles[-1] if cibles else "max"
                )
                journal_partiel = (
                    DIR_CACHE / f"journal_urls.w-{tag_from}-{tag_to}.jsonl"
                )
            else:
                journal_partiel = DIR_CACHE / "journal_urls.w-gapfill.jsonl"
            ecrire_journal(resultat.journal, journal_partiel, mode="w")
            http_ok = sum(
                1
                for j in resultat.journal
                if j.page and j.statut == 200 and j.erreur != "cache"
            )
            cache_skip = sum(
                1 for j in resultat.journal if j.page and j.erreur == "cache"
            )
            echecs = [j for j in resultat.journal if j.page and j.statut != 200]
            print(
                f"Worker cache-seulement — HTTP nouveaux : {http_ok} | "
                f"déjà cache : {cache_skip} | échecs : {len(echecs)} | "
                f"journal : {journal_partiel}"
            )
            if echecs[:5]:
                print(
                    "Échecs (échantillon) :",
                    ", ".join(f"p{e.page}={e.statut}" for e in echecs[:5]),
                )
            print(
                "Pas d'assemblage / DB. Quand tous les workers ont fini : "
                "make ingerer-cgici DEPUIS_CACHE=1"
            )
            print("Rappel éditorial : corpus brouillon ; scrape ≠ visa fiscaliste.")
            return 0

        ecrire_journal(resultat.journal, JOURNAL)
        pages_lpf = pages_lpf_depuis_index(resultat.index_articles)
        en_tete = EN_TETE.format(base=BASE_URL, millesime=args.millesime)
        texte = assembler_texte(
            resultat.pages, en_tete=en_tete, pages_lpf=pages_lpf
        )
        FICHIER_TEXTE.parent.mkdir(parents=True, exist_ok=True)
        FICHIER_TEXTE.write_text(texte, encoding="utf-8")
        n_pages = len(resultat.pages)
        n_index = len(resultat.index_articles)
        ecrire_meta(
            META,
            millesime=args.millesime,
            n_pages=n_pages,
            n_articles_index=n_index,
            n_caracteres=len(texte),
        )
        journal_ok = True
        echecs = [j for j in resultat.journal if j.page and j.statut != 200]
        print(
            f"Pages OK : {n_pages} | index ArticleLink : {n_index} articles | "
            f"pages LPF (offset 5000) : {len(pages_lpf)} | "
            f"échecs HTTP : {len(echecs)}"
        )
        if echecs[:5]:
            print(
                "Échecs (échantillon) :",
                ", ".join(f"p{e.page}={e.statut}" for e in echecs[:5]),
            )

    articles = _decouper_articles(texte)
    titre = args.titre or (
        f"CGI + LPF Côte d'Ivoire {args.millesime} (cgici.com, brouillon)"
    )
    print(
        f"Texte : {len(texte)} caractères | pages : {n_pages} | "
        f"articles découpés : {len(articles)}"
    )
    if articles:
        apercu = ", ".join(ref for ref, _, _ in articles[:15])
        print(f"Aperçu refs : {apercu}" + ("…" if len(articles) > 15 else ""))

    print(
        "Rappel juridique : mention site « tous droits réservés » (DGI/EssiC). "
        "Corpus interne brouillon uniquement — pas de republication du produit numérique."
    )
    print("Rappel éditorial : aucun a_confirmer purgé ; scrape ≠ visa fiscaliste.")

    if args.dry_run:
        print(f"Dry-run — texte écrit : {FICHIER_TEXTE}")
        if journal_ok:
            print(f"Journal URLs : {JOURNAL}")
        return 0

    session = Fabrique()
    try:
        resultat_ing = ingerer_document(
            session,
            titre=titre,
            type="cgi",
            millesime=args.millesime,
            texte_brut=texte,
            fichier_uri=f"{BASE_URL}/{DOSSIER_PAGES}/",
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(
        f"Ingesté : source_document_id={resultat_ing.source_document_id} "
        f"articles={resultat_ing.articles} fragments={resultat_ing.fragments}"
    )
    print(f"Texte local : {FICHIER_TEXTE}")
    print(f"Journal     : {JOURNAL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
