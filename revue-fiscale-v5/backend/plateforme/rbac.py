"""Matrice RBAC abonné — rôles cabinet uniquement.

Pas de droit fiscal ici : seules les capacités applicatives (CRUD, exécution,
invitations). L'isolation inter-cabinets reste garantie par RLS + SET LOCAL.
"""
from __future__ import annotations

from typing import Final

from fastapi import HTTPException, status

from backend.plateforme.auth import SessionUtilisateur

ROLE_ADMIN: Final = "admin"
ROLE_REVISEUR: Final = "reviseur"
ROLE_LECTEUR: Final = "lecteur"

ROLES_CABINET: Final[frozenset[str]] = frozenset(
    {ROLE_ADMIN, ROLE_REVISEUR, ROLE_LECTEUR}
)

# Capacités → rôles autorisés (matrice documentée).
CAPACITES: Final[dict[str, frozenset[str]]] = {
    "lire": frozenset({ROLE_ADMIN, ROLE_REVISEUR, ROLE_LECTEUR}),
    "ecrire_contribuable": frozenset({ROLE_ADMIN, ROLE_REVISEUR}),
    "creer_mission": frozenset({ROLE_ADMIN, ROLE_REVISEUR}),
    "cloturer_mission": frozenset({ROLE_ADMIN, ROLE_REVISEUR}),
    "importer_balance": frozenset({ROLE_ADMIN, ROLE_REVISEUR}),
    "executer_mission": frozenset({ROLE_ADMIN, ROLE_REVISEUR}),
    "lien_client": frozenset({ROLE_ADMIN, ROLE_REVISEUR}),
    "gerer_equipe": frozenset({ROLE_ADMIN}),
    "inviter": frozenset({ROLE_ADMIN}),
    "gerer_abonnement": frozenset({ROLE_ADMIN}),
}

MESSAGES: Final[dict[str, str]] = {
    "lire": "role insuffisant pour lire",
    "ecrire_contribuable": "role insuffisant pour modifier un contribuable",
    "creer_mission": "role lecteur : creation de mission interdite",
    "cloturer_mission": "role lecteur : changement de statut de mission interdit",
    "importer_balance": "role lecteur : import de balance interdit",
    "executer_mission": "role lecteur : execution de mission interdite",
    "lien_client": "role insuffisant pour creer un lien client",
    "gerer_equipe": "seul un admin peut lister les utilisateurs",
    "inviter": "seul un admin peut inviter",
    "gerer_abonnement": "seul un admin peut gérer facturation / demandes palier",
}


def exiger_capacite(
    utilisateur: SessionUtilisateur,
    capacite: str,
    *,
    detail: str | None = None,
) -> None:
    """Lève HTTP 403 si le rôle n'autorise pas la capacité."""
    roles = CAPACITES.get(capacite)
    if roles is None:
        raise ValueError(f"capacite RBAC inconnue : {capacite!r}")
    if utilisateur.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or MESSAGES.get(capacite, "role insuffisant"),
        )


def roles_pour(capacite: str) -> frozenset[str]:
    return CAPACITES[capacite]
