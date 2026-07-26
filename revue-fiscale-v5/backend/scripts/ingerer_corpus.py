"""CLI — ingestion d'une source réglementaire dans le corpus éditorial.

Usage :
  python -m backend.scripts.ingerer_corpus --fichier corpus_sources/CGI-CI-2026.pdf \\
      --type cgi --millesime 2026
  python -m backend.scripts.ingerer_corpus --fichier … --dry-run

N'écrit aucune règle fiscale. Ne purge aucun ``a_confirmer``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from backend.corpus.extraction import ErreurExtraction, extraire_texte  # noqa: E402
from backend.corpus.ingestion import _decouper_articles, ingerer_document  # noqa: E402
from backend.db import Fabrique  # noqa: E402

TYPES_AUTORISES = ("cgi", "annexe", "note_dgi", "doctrine", "autre")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ingère un PDF/MD/TXT dans source_document + article_corpus + fragment_corpus. "
            "Ne valide aucun taux/seuil. Ne touche pas au référentiel YAML."
        )
    )
    parser.add_argument(
        "--fichier",
        type=Path,
        required=True,
        help="Chemin PDF, Markdown ou TXT (absolu ou relatif au projet)",
    )
    parser.add_argument(
        "--type",
        choices=TYPES_AUTORISES,
        required=True,
        help="Type éditorial de la source (cgi | annexe | …)",
    )
    parser.add_argument("--millesime", type=int, default=None)
    parser.add_argument(
        "--titre",
        type=str,
        default=None,
        help="Titre source_document (défaut = nom du fichier)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extrait et compte les articles sans écrire en base",
    )
    args = parser.parse_args(argv)

    chemin = args.fichier
    if not chemin.is_absolute():
        candidat = (_RACINE / chemin).resolve()
        chemin = candidat if candidat.exists() else chemin.expanduser().resolve()

    try:
        texte = extraire_texte(chemin)
    except ErreurExtraction as e:
        print(f"ERREUR extraction : {e}", file=sys.stderr)
        return 1

    articles = _decouper_articles(texte)
    titre = args.titre or chemin.name
    print(
        f"Source : {chemin}\n"
        f"Titre  : {titre}\n"
        f"Type   : {args.type} | millésime : {args.millesime}\n"
        f"Texte  : {len(texte)} caractères | articles détectés : {len(articles)}"
    )
    if articles:
        apercu = ", ".join(ref for ref, _, _ in articles[:12])
        print(f"Aperçu références : {apercu}" + ("…" if len(articles) > 12 else ""))

    if args.type == "cgi" and args.millesime is None:
        print(
            "AVERTISSEMENT : millésime non fourni pour un CGI — "
            "préférer --millesime 2026.",
            file=sys.stderr,
        )

    if args.dry_run:
        print("Dry-run — aucune écriture DB.")
        return 0

    if args.type == "annexe":
        print(
            "Note : l'annexe seule ne suffit pas à purger les a_confirmer "
            "art. 18 G (dons) — CGI intégral requis."
        )

    session = Fabrique()
    try:
        resultat = ingerer_document(
            session,
            titre=titre,
            type=args.type,
            millesime=args.millesime,
            texte_brut=texte,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    print(
        f"Ingesté : source_document_id={resultat.source_document_id} "
        f"articles={resultat.articles} fragments={resultat.fragments}"
    )
    print(
        "Rappel : aucun a_confirmer purgé. "
        "Session fiscaliste → docs/15-session-fiscaliste-7-seuils.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
