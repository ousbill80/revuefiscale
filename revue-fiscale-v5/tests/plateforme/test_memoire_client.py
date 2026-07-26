"""Tests unitaires — validation des entrées mémoire client (Data Room)."""
from __future__ import annotations

import pytest

from backend.plateforme.memoire_client import (
    CONTENU_MAX,
    SOURCES_ENTREE,
    TYPES_ENTREE,
    ErreurMemoireClient,
    valider_entree_memoire,
)


def test_entree_valide_normalisee():
    te, contenu, st = valider_entree_memoire(
        type_entree=" Note ",
        contenu="  Le client change de commissaire aux comptes.  ",
        source_type="MANUEL",
    )
    assert te == "note"
    assert contenu == "Le client change de commissaire aux comptes."
    assert st == "manuel"


@pytest.mark.parametrize("type_entree", sorted(TYPES_ENTREE))
def test_tous_types_acceptes(type_entree):
    te, _, _ = valider_entree_memoire(
        type_entree=type_entree, contenu="x", source_type="manuel"
    )
    assert te == type_entree


@pytest.mark.parametrize("source_type", sorted(SOURCES_ENTREE))
def test_toutes_sources_acceptees(source_type):
    _, _, st = valider_entree_memoire(
        type_entree="fait", contenu="x", source_type=source_type
    )
    assert st == source_type


def test_type_entree_invalide():
    with pytest.raises(ErreurMemoireClient) as exc:
        valider_entree_memoire(
            type_entree="rumeur", contenu="x", source_type="manuel"
        )
    assert "type_entree invalide" in str(exc.value)


def test_source_type_invalide():
    with pytest.raises(ErreurMemoireClient) as exc:
        valider_entree_memoire(
            type_entree="fait", contenu="x", source_type="oracle"
        )
    assert "source_type invalide" in str(exc.value)


@pytest.mark.parametrize("contenu", ["", "   ", None])
def test_contenu_vide_refuse(contenu):
    with pytest.raises(ErreurMemoireClient) as exc:
        valider_entree_memoire(
            type_entree="note", contenu=contenu, source_type="manuel"
        )
    assert "contenu obligatoire" in str(exc.value)


def test_contenu_trop_long_refuse():
    with pytest.raises(ErreurMemoireClient) as exc:
        valider_entree_memoire(
            type_entree="note",
            contenu="x" * (CONTENU_MAX + 1),
            source_type="manuel",
        )
    assert "trop long" in str(exc.value)


def test_contenu_longueur_max_accepte():
    _, contenu, _ = valider_entree_memoire(
        type_entree="note",
        contenu="x" * CONTENU_MAX,
        source_type="manuel",
    )
    assert len(contenu) == CONTENU_MAX


def test_longueur_apres_strip():
    brut = "  " + "x" * CONTENU_MAX + "  "
    _, contenu, _ = valider_entree_memoire(
        type_entree="fait", contenu=brut, source_type="extraction"
    )
    assert len(contenu) == CONTENU_MAX
