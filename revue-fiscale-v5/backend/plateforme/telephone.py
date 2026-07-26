"""Validation téléphone E.164 via phonenumbers."""
from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


class ErreurTelephone(ValueError):
    """Numéro invalide ou non joignable au format attendu."""


def normaliser_e164(numero: str, region_defaut: str = "CI") -> str:
    """Parse et retourne E.164 (+225…)."""
    brut = (numero or "").strip()
    if not brut:
        raise ErreurTelephone("téléphone obligatoire")
    try:
        parsed = phonenumbers.parse(brut, region_defaut if not brut.startswith("+") else None)
    except NumberParseException as e:
        raise ErreurTelephone("numéro de téléphone invalide") from e
    if not phonenumbers.is_possible_number(parsed):
        raise ErreurTelephone("numéro de téléphone impossible")
    if not phonenumbers.is_valid_number(parsed):
        raise ErreurTelephone("numéro de téléphone invalide pour ce pays")
    return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
