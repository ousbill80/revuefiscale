"""Evaluateur d arbres d expressions.

Deterministe et total : toute donnee manquante leve une erreur nommee.
Jamais de valeur par defaut silencieuse sur un calcul fiscal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .analyseur import Appel, Binaire, Booleen, Nombre, Reference, Unaire, analyser
from .erreurs import ErreurEvaluation


@dataclass
class Contexte:
    """Donnees disponibles pour l evaluation d une regle."""

    soldes: dict[str, Decimal] = field(default_factory=dict)
    agregats: dict[str, Decimal] = field(default_factory=dict)
    reponses: dict[str, object] = field(default_factory=dict)


def _dec(v: object) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ErreurEvaluation("un booleen ne peut pas servir dans un calcul arithmetique")
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    raise ErreurEvaluation(f"valeur non numerique : {v!r}")


def _evaluer(noeud: object, ctx: Contexte) -> object:
    match noeud:
        case Nombre(valeur):
            return Decimal(str(valeur))

        case Booleen(valeur):
            return valeur

        case Reference(genre, cle):
            if genre == "solde":
                # Resolution des sous-comptes : solde(66) agrege 661, 663, 664...
                total = sum(
                    (v for k, v in ctx.soldes.items() if k == cle or k.startswith(cle)),
                    Decimal(0),
                )
                if not any(k == cle or k.startswith(cle) for k in ctx.soldes):
                    raise ErreurEvaluation(f"compte {cle} absent des donnees de la mission")
                return total
            if genre == "agregat":
                if cle.upper() not in {k.upper() for k in ctx.agregats}:
                    raise ErreurEvaluation(f"agregat {cle} non defini")
                return next(v for k, v in ctx.agregats.items() if k.upper() == cle.upper())
            if genre == "reponse":
                if cle not in ctx.reponses:
                    raise ErreurEvaluation(f"reponse {cle} non saisie")
                return ctx.reponses[cle]
            raise ErreurEvaluation(f"reference inconnue : {genre}")

        case Appel(nom, args):
            valeurs = [_evaluer(a, ctx) for a in args]
            if nom == "abs":
                return abs(_dec(valeurs[0]))
            if nom == "min":
                return min(_dec(valeurs[0]), _dec(valeurs[1]))
            if nom == "max":
                return max(_dec(valeurs[0]), _dec(valeurs[1]))
            raise ErreurEvaluation(f"fonction inconnue : {nom}")

        case Unaire(op, operande):
            v = _evaluer(operande, ctx)
            if op == "-":
                return -_dec(v)
            if op == "non":
                if not isinstance(v, bool):
                    raise ErreurEvaluation("'non' attend un booleen")
                return not v
            raise ErreurEvaluation(f"operateur unaire inconnu : {op}")

        case Binaire(op, gauche, droite):
            if op in ("et", "ou"):
                g = _evaluer(gauche, ctx)
                d = _evaluer(droite, ctx)
                if not isinstance(g, bool) or not isinstance(d, bool):
                    raise ErreurEvaluation(f"'{op}' attend deux booleens")
                return (g and d) if op == "et" else (g or d)

            g_val = _evaluer(gauche, ctx)
            d_val = _evaluer(droite, ctx)

            if op in ("=", "<>"):
                egaux = g_val == d_val
                return egaux if op == "=" else not egaux

            g_num, d_num = _dec(g_val), _dec(d_val)
            match op:
                case "+":
                    return g_num + d_num
                case "-":
                    return g_num - d_num
                case "*":
                    return g_num * d_num
                case "/":
                    if d_num == 0:
                        raise ErreurEvaluation("division par zero")
                    return g_num / d_num
                case ">":
                    return g_num > d_num
                case ">=":
                    return g_num >= d_num
                case "<":
                    return g_num < d_num
                case "<=":
                    return g_num <= d_num
            raise ErreurEvaluation(f"operateur inconnu : {op}")

    raise ErreurEvaluation(f"noeud inconnu : {noeud!r}")


def evaluer(source_ou_arbre: str | object, ctx: Contexte) -> object:
    """Evalue une expression. Accepte une chaine ou un arbre deja analyse."""
    arbre = analyser(source_ou_arbre) if isinstance(source_ou_arbre, str) else source_ou_arbre
    return _evaluer(arbre, ctx)
