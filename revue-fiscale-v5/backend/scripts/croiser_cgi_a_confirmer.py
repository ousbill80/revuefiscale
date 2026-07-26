"""Régénère docs/21 + fusionne les NOUVELLES pistes claires CGI dans le catalogue.

Usage :
  python -m backend.scripts.croiser_cgi_a_confirmer
  python -m backend.scripts.croiser_cgi_a_confirmer --dry-run

Ne purge aucun a_confirmer. N'accepte aucune proposition.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[2]
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))

from backend.db import Fabrique  # noqa: E402
from backend.editorial.croisement_cgi import (  # noqa: E402
    croiser_inventaire,
    ecrire_catalogue_croisement,
    generer_markdown,
    resultats_vers_pistes_catalogue,
)
from backend.editorial.pistes_cgi import FICHIER_PISTES  # noqa: E402

DOC_V2 = _RACINE / "docs" / "21-cgi-vs-a-confirmer-v2.md"
DOC_V1 = _RACINE / "docs" / "19-cgi-vs-a-confirmer.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Croisement CGI × a_confirmer")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source-id", type=int, default=211)
    parser.add_argument(
        "--ecrire-catalogue",
        action="store_true",
        default=True,
        help="Fusionne les nouvelles pistes claires dans propositions_cgi_*.json",
    )
    parser.add_argument("--sans-catalogue", action="store_true")
    args = parser.parse_args(argv)

    with Fabrique() as session:
        rapport = croiser_inventaire(session, source_document_id=args.source_id)

    md = generer_markdown(rapport)
    comptes = rapport["comptes"]
    print(
        f"Croisement : claire={comptes['claire']} contraste={comptes['contraste']} "
        f"faible={comptes['faible']} bloque={comptes['bloque']}",
        file=sys.stderr,
    )

    if args.dry_run:
        print(md[:2000])
        print("… (dry-run, pas d'écriture)", file=sys.stderr)
        return 0

    DOC_V2.write_text(md, encoding="utf-8")
    json_path = ecrire_catalogue_croisement(rapport)
    print(f"OK — catalogue JSON {json_path}", file=sys.stderr)
    # Préserver le détail humain de docs/19 : bandeau v2 en tête si absent
    if DOC_V1.is_file():
        ancien = DOC_V1.read_text(encoding="utf-8")
        bandeau = (
            "> **v2** : croisement automatisé dans "
            "[`docs/21-cgi-vs-a-confirmer-v2.md`](21-cgi-vs-a-confirmer-v2.md) "
            f"(claire={comptes['claire']}, contraste={comptes['contraste']}, "
            f"faible={comptes['faible']}, bloque={comptes['bloque']}). "
            "`make croiser-cgi`.\n\n"
        )
        if "21-cgi-vs-a-confirmer-v2" not in ancien[:500]:
            lignes = ancien.splitlines(keepends=True)
            if lignes:
                DOC_V1.write_text(
                    lignes[0] + "\n" + bandeau + "".join(lignes[1:]),
                    encoding="utf-8",
                )

    n_ajoutees = 0
    if not args.sans_catalogue and args.ecrire_catalogue:
        cat = json.loads(FICHIER_PISTES.read_text(encoding="utf-8"))
        avant = {p["entree_id"] for p in cat.get("pistes") or []}
        # Enrichir existantes avec suggestion_structuree si absente
        for p in cat.get("pistes") or []:
            if "suggestion_structuree" not in p:
                eid = str(p.get("entree_id") or "")
                idx = int(eid.split("#")[-1]) if "#" in eid else 0
                p["suggestion_structuree"] = {
                    "champ": None,
                    "valeur": p.get("suggestion_valeur"),
                    "index_a_confirmer": idx,
                    "entree_id": eid,
                    "retirer_a_confirmer_autorise": False,
                    "article_corpus": p.get("article_corpus"),
                    "extrait": p.get("extrait_cgi"),
                }
            if "classe_croisement" not in p:
                p["classe_croisement"] = (
                    "contraste" if "contraste" in str(p.get("piste_id") or "").lower()
                    or "contraste" in str(p.get("suggestion") or "").lower()
                    else "claire"
                )
                if p.get("piste_id") == "C6-18A3-FRAISSIEGE-contraste":
                    p["classe_croisement"] = "contraste"
        fusion = resultats_vers_pistes_catalogue(rapport, pistes_existantes=cat["pistes"])
        apres = {p["entree_id"] for p in fusion}
        n_ajoutees = len(apres - avant)
        cat["pistes"] = fusion
        cat["rapport"] = "docs/21-cgi-vs-a-confirmer-v2.md"
        cat["checklist"] = "docs/21-cgi-vs-a-confirmer-v2.md"
        cat["lot"] = "cgi_2026_pistes_claires"
        cat["avertissement"] = (
            "Propositions sourcées CGI cgici — statut a_valider_humain. "
            "Aucune purge YAML auto. Seed = nouvelles pistes seulement."
        )
        FICHIER_PISTES.write_text(
            json.dumps(cat, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"OK — écrit {DOC_V2}", file=sys.stderr)
    print(f"Nouvelles pistes catalogue : {n_ajoutees}", file=sys.stderr)
    print(
        json.dumps(
            {"comptes": comptes, "n_pistes_ajoutees": n_ajoutees, "doc": str(DOC_V2)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
