"""Dependances FastAPI — staff billing uniquement."""
from __future__ import annotations

from typing import Annotated, Final

from fastapi import Depends, Header, HTTPException, status

from backend.billing.auth import SessionStaff, decoder_jeton_staff
from backend.plateforme.auth import ErreurAuth

ROLES_BILLING: Final[frozenset[str]] = frozenset({"billing", "ops"})


def staff_courant(
    authorization: Annotated[str | None, Header()] = None,
) -> SessionStaff:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer requis",
        )
    jeton = authorization.split(" ", 1)[1].strip()
    try:
        return decoder_jeton_staff(jeton)
    except ErreurAuth as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e


def exiger_staff_billing(staff: Annotated[SessionStaff, Depends(staff_courant)]) -> SessionStaff:
    """Roles autorises sur /api/v1/billing/* : billing | ops (pas editorial seul)."""
    if staff.role not in ROLES_BILLING:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="role staff insuffisant pour le billing",
        )
    return staff


StaffBillingDep = Annotated[SessionStaff, Depends(exiger_staff_billing)]
