"""Erreurs de la grammaire d expressions."""


class ErreurExpression(Exception):
    """Base des erreurs d expression."""


class ErreurSyntaxe(ErreurExpression):
    """L expression ne respecte pas la grammaire."""


class ErreurEvaluation(ErreurExpression):
    """L expression est valide mais ne peut pas etre evaluee."""
