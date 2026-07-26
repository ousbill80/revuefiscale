"""Usages editoriaux mutualises — differentiel d annexe, conversion assistee."""
from __future__ import annotations

import re
from typing import Any


def differentiel_annexe(texte_ancien: str, texte_nouveau: str) -> list[str]:
    """Diff ligne a ligne des paragraphes modifies (ajout / suppression / changement)."""
    anciens = _paragraphes(texte_ancien)
    nouveaux = _paragraphes(texte_nouveau)

    set_a = set(anciens)
    set_n = set(nouveaux)
    changements: list[str] = []

    for p in anciens:
        if p not in set_n:
            changements.append(f"— {p}")
    for p in nouveaux:
        if p not in set_a:
            changements.append(f"+ {p}")

    # Lignes internes si memes paragraphes mais contenu proche — deja couvert
    return changements


def _paragraphes(texte: str) -> list[str]:
    if not texte:
        return []
    blocs = re.split(r"\n\s*\n", texte.strip())
    return [" ".join(b.split()) for b in blocs if b.strip()]


_RE_NOMBRE = re.compile(
    r"(\d+(?:[.,]\d+)?\s*%|\d[\d\s]{2,})"
)


def conversion_assistee_regle(texte_article: str) -> dict[str, Any]:
    """Brouillon YAML squelette — AUCUN taux invente ; a_confirmer sur tout numerique.

    Ne produit que des placeholders. Les champs numeriques detectes dans le texte
    sont listes dans a_confirmer, jamais recopies comme valeurs operatoires.
    """
    texte = (texte_article or "").strip()
    ref = _deviner_reference(texte)
    nombres = _RE_NOMBRE.findall(texte)

    a_confirmer = [
        "Tous les champs numeriques sont a confirmer par le circuit editorial",
        "Aucun taux ni plafond n a ete extrait comme valeur operable",
    ]
    for n in nombres[:20]:
        a_confirmer.append(f"Valeur detectee dans le texte (non operable) : {n.strip()}")

    return {
        "identifiant": f"BROUILLON-{ref or 'SANS-REF'}",
        "impot": "A_CONFIRMER",
        "reference_legale": ref or "A_CONFIRMER",
        "reference_source": "conversion_assistee — brouillon",
        "date_effet": "A_CONFIRMER",
        "profils_applicables": ["A_CONFIRMER"],
        "comptes_declencheurs": [],
        "nature": "A_CONFIRMER",
        "condition_declenchement": "A_CONFIRMER",
        "conditions_fond": "A_CONFIRMER — a rediger depuis le texte source",
        "formule_plafonnement": "A_CONFIRMER",
        "questions_generees": [],
        "resultat": "A_CONFIRMER",
        "niveau_risque": "eleve",
        "effets_croises": [],
        "a_confirmer": a_confirmer,
        "extrait_source": texte[:500],
        "statut": "brouillon_non_opposable",
    }


def _deviner_reference(texte: str) -> str | None:
    m = re.search(
        r"(?:Art(?:icle)?\.?\s*)([A-Z]{2,}(?:-[\w]+)+|\d+[\s\-]?[A-Z]?)",
        texte,
        re.IGNORECASE,
    )
    if not m:
        return None
    return m.group(1).strip().upper().replace(" ", "-")
