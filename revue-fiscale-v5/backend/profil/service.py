"""Service profil mission."""
from __future__ import annotations

from collections.abc import Mapping, Sequence


class ErreurProfil(Exception):
    """Profil incomplet ou invalide."""


CLEFS_REQUISES = ("regime", "forme_juridique")
CLEFS_OPTIONNELLES = ("secteur", "type_entite", "cross_border", "etiquette_profil")


def valider_profil(profil: dict[str, object]) -> dict[str, object]:
    """Exige regime et forme_juridique. Conserve les cles optionnelles connues."""
    if not isinstance(profil, dict):
        raise ErreurProfil("profil doit etre un objet")
    manquants = [c for c in CLEFS_REQUISES if c not in profil or profil[c] in (None, "")]
    if manquants:
        raise ErreurProfil(f"profil incomplet : cles manquantes {manquants}")
    out: dict[str, object] = {k: profil[k] for k in CLEFS_REQUISES}
    for cle in CLEFS_OPTIONNELLES:
        if cle in profil and profil[cle] not in (None, ""):
            out[cle] = profil[cle]
    return out


def profil_compatible_regle(
    profils_applicables: Sequence[object] | None,
    profil: Mapping[str, object] | None,
) -> bool:
    """Filtre amont : True si la regle s applique au profil mission.

    - Sans profils_applicables → toujours applicable.
    - Sans etiquette / type_entite dans le profil → pas de filtre restrictif
      (compat Lot1 : regime + forme seuls).
    - Sinon : correspondance textuelle souple sur les libelles de profil.
    """
    if not profils_applicables:
        return True
    if not profil:
        return True

    joined = " ".join(str(p).lower() for p in profils_applicables)
    if "toutes" in joined or "tout " in joined:
        return True

    etiquette = profil.get("etiquette_profil") or profil.get("type_entite")
    if etiquette in (None, ""):
        # Profil minimal : exclure seulement les niches OBNL/startup explicites
        # si le regime n est pas aligne.
        if "obnl" in joined or "non lucratif" in joined:
            return False
        if "startup" in joined:
            return False
        return True

    cle = str(etiquette).lower()
    if cle in joined:
        return True
    # alias
    alias = {
        "obnl": ("obnl", "non lucratif", "organisme"),
        "startup": ("startup", "innovant"),
        "sa": ("societes anonymes", "sa"),
        "reel": ("regime reel", "reel"),
    }
    for jeton in alias.get(cle, (cle,)):
        if jeton in joined:
            return True
    return False
