"""Analyseur d expressions du referentiel.

Produit un arbre syntaxique. N EXECUTE JAMAIS DE CODE : ni eval, ni exec,
ni compile. Liste blanche stricte d operateurs et de fonctions.

Grammaire (voir docs/02-format-pivot.md) :

    condition   := comparaison (('et'|'ou') comparaison)*
    comparaison := 'non' comparaison | expression (op expression)?
    expression  := terme (('+'|'-') terme)*
    terme       := facteur (('*'|'/') facteur)*
    facteur     := '-'? primaire
    primaire    := nombre | fonction | reference | '(' condition ')'
    fonction    := ('min'|'max') '(' condition (';'|',') condition ')' | 'abs' '(' condition ')'
    reference   := 'solde' '(' ident ')' | 'agregat' '(' ident ')' | 'reponse' '(' ident ')'
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .erreurs import ErreurSyntaxe

FONCTIONS = {"min": 2, "max": 2, "abs": 1}
REFERENCES = {"solde", "agregat", "reponse"}
COMPARATEURS = {">", ">=", "<", "<=", "=", "<>"}
LOGIQUES = {"et", "ou"}


# ── Noeuds ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Nombre:
    valeur: float


@dataclass(frozen=True)
class Booleen:
    valeur: bool


@dataclass(frozen=True)
class Reference:
    genre: str  # solde | agregat | reponse
    cle: str


@dataclass(frozen=True)
class Appel:
    nom: str  # min | max | abs
    args: tuple[object, ...]


@dataclass(frozen=True)
class Binaire:
    operateur: str
    gauche: object
    droite: object


@dataclass(frozen=True)
class Unaire:
    operateur: str  # '-' | 'non'
    operande: object


# ── Lexeur ────────────────────────────────────────────────────────────
JETON = re.compile(
    r"""
    (?P<espace>\s+)
  | (?P<nombre>\d+(?:[.,]\d+)?)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<comp><>|>=|<=|>|<|=)
  | (?P<op>[+\-*/])
  | (?P<pargauche>\()
  | (?P<pardroite>\))
  | (?P<virgule>[;,])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Jeton:
    genre: str
    valeur: str
    position: int


def lexer(source: str) -> list[Jeton]:
    jetons: list[Jeton] = []
    i = 0
    while i < len(source):
        m = JETON.match(source, i)
        if not m:
            raise ErreurSyntaxe(f"caractere inattendu {source[i]!r} en position {i}")
        genre = m.lastgroup
        assert genre is not None
        if genre != "espace":
            jetons.append(Jeton(genre, m.group(), i))
        i = m.end()
    return jetons


# ── Analyseur descendant ──────────────────────────────────────────────
class _Analyseur:
    def __init__(self, jetons: list[Jeton]) -> None:
        self.jetons = jetons
        self.i = 0

    def _regarder(self) -> Jeton | None:
        return self.jetons[self.i] if self.i < len(self.jetons) else None

    def _avancer(self) -> Jeton:
        j = self._regarder()
        if j is None:
            raise ErreurSyntaxe("expression incomplete")
        self.i += 1
        return j

    def _attendre(self, valeur: str) -> None:
        j = self._avancer()
        if j.valeur != valeur:
            raise ErreurSyntaxe(
                f"attendu {valeur!r}, trouve {j.valeur!r} en position {j.position}"
            )

    def analyser(self) -> object:
        noeud = self.condition()
        reste = self._regarder()
        if reste is not None:
            raise ErreurSyntaxe(f"texte residuel {reste.valeur!r} en position {reste.position}")
        return noeud

    def condition(self) -> object:
        gauche = self.comparaison()
        while (j := self._regarder()) and j.genre == "ident" and j.valeur.lower() in LOGIQUES:
            self._avancer()
            gauche = Binaire(j.valeur.lower(), gauche, self.comparaison())
        return gauche

    def comparaison(self) -> object:
        j = self._regarder()
        if j and j.genre == "ident" and j.valeur.lower() == "non":
            self._avancer()
            return Unaire("non", self.comparaison())
        gauche = self.expression()
        j = self._regarder()
        if j and j.genre == "comp":
            self._avancer()
            return Binaire(j.valeur, gauche, self.expression())
        return gauche

    def expression(self) -> object:
        gauche = self.terme()
        while (j := self._regarder()) and j.genre == "op" and j.valeur in "+-":
            self._avancer()
            gauche = Binaire(j.valeur, gauche, self.terme())
        return gauche

    def terme(self) -> object:
        gauche = self.facteur()
        while (j := self._regarder()) and j.genre == "op" and j.valeur in "*/":
            self._avancer()
            gauche = Binaire(j.valeur, gauche, self.facteur())
        return gauche

    def facteur(self) -> object:
        j = self._regarder()
        if j and j.genre == "op" and j.valeur == "-":
            self._avancer()
            return Unaire("-", self.facteur())
        return self.primaire()

    def primaire(self) -> object:
        j = self._avancer()

        if j.genre == "nombre":
            return Nombre(float(j.valeur.replace(",", ".")))

        if j.genre == "pargauche":
            noeud = self.condition()
            self._attendre(")")
            return noeud

        if j.genre == "ident":
            nom = j.valeur.lower()

            if nom in ("vrai", "faux"):
                return Booleen(nom == "vrai")

            if nom in REFERENCES:
                self._attendre("(")
                cle = self._avancer()
                if cle.genre not in ("ident", "nombre"):
                    raise ErreurSyntaxe(f"cle invalide dans {nom}() en position {cle.position}")
                self._attendre(")")
                return Reference(nom, cle.valeur)

            if nom in FONCTIONS:
                self._attendre("(")
                args = [self.condition()]
                while (k := self._regarder()) and k.genre == "virgule":
                    self._avancer()
                    args.append(self.condition())
                self._attendre(")")
                attendu = FONCTIONS[nom]
                if len(args) != attendu:
                    raise ErreurSyntaxe(f"{nom}() attend {attendu} arguments, {len(args)} fournis")
                return Appel(nom, tuple(args))

            # Tout autre identifiant est refuse : c est la liste blanche.
            autorises = sorted(
                REFERENCES | set(FONCTIONS) | LOGIQUES | {"non", "vrai", "faux"}
            )
            raise ErreurSyntaxe(
                f"identifiant non autorise {j.valeur!r} en position {j.position}. "
                f"Autorises : {autorises}"
            )

        raise ErreurSyntaxe(f"jeton inattendu {j.valeur!r} en position {j.position}")


def analyser(source: str) -> object:
    """Analyse une expression et retourne son arbre. Leve ErreurSyntaxe si invalide.

    Appelee a la SAISIE dans la console editoriale, pas a l execution :
    une expression invalide ne doit jamais entrer dans le referentiel.
    """
    if not source or not source.strip():
        raise ErreurSyntaxe("expression vide")
    return _Analyseur(lexer(source)).analyser()
