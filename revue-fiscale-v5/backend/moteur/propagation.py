"""Propagation des effets croises — detection de cycles."""
from __future__ import annotations


class ErreurCycle(Exception):
    """Cycle detecte dans le graphe d effets croises."""

    def __init__(self, chemin: list[str]) -> None:
        self.chemin = chemin
        super().__init__(f"cycle detecte : {' -> '.join(chemin)}")


def detect_cycles(effets: dict[str, list[str]]) -> None:
    """Detecte un cycle dans le graphe id -> listes de cibles.

    Leve ErreurCycle si un cycle existe. Sinon retourne None.
    """
    blanc, gris, noir = 0, 1, 2
    couleur: dict[str, int] = dict.fromkeys(effets, blanc)
    for cibles in effets.values():
        for c in cibles:
            couleur.setdefault(c, blanc)

    pile: list[str] = []

    def dfs(noeud: str) -> None:
        couleur[noeud] = gris
        pile.append(noeud)
        for voisin in effets.get(noeud, []):
            etat = couleur.get(voisin, blanc)
            if etat == gris:
                i = pile.index(voisin)
                raise ErreurCycle(pile[i:] + [voisin])
            if etat == blanc:
                dfs(voisin)
        pile.pop()
        couleur[noeud] = noir

    for n in list(couleur):
        if couleur[n] == blanc:
            dfs(n)
