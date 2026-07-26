"""Dependances FastAPI — staff editorial / ops (publication)."""
from __future__ import annotations

from typing import Annotated, Final

from fastapi import Depends, HTTPException, status

from backend.billing.auth import SessionStaff
from backend.billing.dependances import staff_courant

# À CONFIRMER : billing pur refuse sur publication ; editorial + ops autorises.
ROLES_EDITORIAL: Final[frozenset[str]] = frozenset({"editorial", "ops"})


def exiger_staff_editorial(
    staff: Annotated[SessionStaff, Depends(staff_courant)],
) -> SessionStaff:
    """Roles autorises sur /api/v1/editorial/* : editorial | ops (pas billing seul)."""
    if staff.role not in ROLES_EDITORIAL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "role staff insuffisant pour l editorial "
                "(requis : editorial ou ops ; billing seul refuse)"
            ),
        )
    return staff


StaffEditorialDep = Annotated[SessionStaff, Depends(exiger_staff_editorial)]
