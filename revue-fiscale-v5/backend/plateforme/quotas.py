"""Gestion des quotas missions — enforcement a la creation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class ErreurQuota(Exception):
    """Quota depasse ou indisponible."""


def _premier_jour_mois(aujourd_hui: date | None = None) -> date:
    j = aujourd_hui or date.today()
    return j.replace(day=1)


@dataclass(frozen=True)
class ResumeQuota:
    periode: date
    missions_incluses: int
    missions_utilisees: int
    ratio: float
    alerte_80: bool
    bloque: bool

    def vers_dict(self) -> dict[str, Any]:
        return {
            "periode": self.periode.isoformat(),
            "missions_incluses": self.missions_incluses,
            "missions_utilisees": self.missions_utilisees,
            "ratio": round(self.ratio, 4),
            "alerte_80": self.alerte_80,
            "bloque": self.bloque,
        }


def lire_quota_periode(
    session: Session,
    tenant_id: int,
    *,
    periode: date | None = None,
) -> ResumeQuota | None:
    """Lit le quota du mois civil. Necessite contexte tenant pose."""
    p = periode or _premier_jour_mois()
    row = session.execute(
        text(
            "SELECT missions_incluses, missions_utilisees FROM quota "
            "WHERE tenant_id = :t AND periode = :p"
        ),
        {"t": tenant_id, "p": p},
    ).mappings().one_or_none()
    if row is None:
        return None
    inclus = int(row["missions_incluses"])
    utilisees = int(row["missions_utilisees"])
    ratio = (utilisees / inclus) if inclus > 0 else 0.0
    return ResumeQuota(
        periode=p,
        missions_incluses=inclus,
        missions_utilisees=utilisees,
        ratio=ratio,
        alerte_80=ratio >= 0.8,
        bloque=utilisees >= inclus,
    )


def verifier_et_incrementer_quota(session: Session, tenant_id: int) -> ResumeQuota:
    """Verifie le quota puis incremente. Appeler sous contexte_tenant.

    Leve ErreurQuota si plus de missions disponibles.
    """
    p = _premier_jour_mois()
    # Verrouillage pessimiste de la ligne quota du mois
    row = session.execute(
        text(
            "SELECT missions_incluses, missions_utilisees FROM quota "
            "WHERE tenant_id = :t AND periode = :p FOR UPDATE"
        ),
        {"t": tenant_id, "p": p},
    ).mappings().one_or_none()

    if row is None:
        raise ErreurQuota(
            "aucun quota pour la periode courante — contactez l administrateur billing"
        )

    inclus = int(row["missions_incluses"])
    utilisees = int(row["missions_utilisees"])
    if utilisees >= inclus:
        raise ErreurQuota(
            f"quota missions epuise ({utilisees}/{inclus} pour {p.isoformat()}). "
            "Passez a un palier superieur ou attendez le mois suivant."
        )

    session.execute(
        text(
            "UPDATE quota SET missions_utilisees = missions_utilisees + 1 "
            "WHERE tenant_id = :t AND periode = :p"
        ),
        {"t": tenant_id, "p": p},
    )
    nouvelles = utilisees + 1
    ratio = (nouvelles / inclus) if inclus > 0 else 0.0
    return ResumeQuota(
        periode=p,
        missions_incluses=inclus,
        missions_utilisees=nouvelles,
        ratio=ratio,
        alerte_80=ratio >= 0.8,
        bloque=nouvelles >= inclus,
    )
