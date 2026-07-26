"""Tests usages editoriaux — differentiel et conversion assistee."""
from backend.agent.usages import conversion_assistee_regle, differentiel_annexe


def test_differentiel_paragraphes():
    ancien = "Paragraphe A reste.\n\nParagraphe B change."
    nouveau = "Paragraphe A reste.\n\nParagraphe B modifie.\n\nParagraphe C ajoute."
    diffs = differentiel_annexe(ancien, nouveau)
    assert any(d.startswith("—") for d in diffs)
    assert any(d.startswith("+") and "C ajoute" in d for d in diffs)
    assert not any("Paragraphe A reste" in d for d in diffs)


def test_conversion_sans_taux_invente():
    texte = (
        "Article DEMO-18-G — [DÉMO FICTIF] texte non opposable.\n"
        "Plafond mentionne a 2,5 % et 200000000 dans un exemple fictif."
    )
    brouillon = conversion_assistee_regle(texte)
    assert brouillon["statut"] == "brouillon_non_opposable"
    assert brouillon["resultat"] == "A_CONFIRMER"
    assert brouillon["formule_plafonnement"] == "A_CONFIRMER"
    # Aucune valeur numerique operable
    assert "2,5" not in str(brouillon.get("resultat"))
    assert any("a confirmer" in x.lower() or "A_CONFIRMER" in x or "non operable" in x.lower()
               for x in brouillon["a_confirmer"])
    # Les nombres detectes sont dans a_confirmer, pas dans les champs de calcul
    assert any("2,5" in x or "200000000" in x for x in brouillon["a_confirmer"])
