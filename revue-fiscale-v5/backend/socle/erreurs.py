"""Exceptions nommees du socle de donnees."""


class ErreurSocle(Exception):
    """Base des erreurs du socle."""


class ErreurFiabilisation(ErreurSocle):
    """Echec de fiabilisation (mission introuvable, etc.)."""


class ErreurLectureBalance(ErreurSocle):
    """Fichier de balance illisible ou mal forme."""


class ErreurMapping(ErreurSocle):
    """Fichier de mapping invalide."""


class ErreurPiece(ErreurSocle):
    """Erreur métier sur les pièces de mission (source active / annexes)."""
