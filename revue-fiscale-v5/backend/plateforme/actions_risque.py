"""Actions sur risques — corrective / préventive (docs/25)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant

NATURES: Final[frozenset[str]] = frozenset({"corrective", "preventive"})
STATUTS_ACTION: Final[frozenset[str]] = frozenset(
    {
        "proposee",
        "acceptee",
        "refusee",
        "en_cours",
        "preuve_deposee",
        "verifiee",
        "close",
        "abandonnee",
    }
)
STATUTS_ACTIFS: Final[frozenset[str]] = frozenset(
    {"proposee", "acceptee", "en_cours", "preuve_deposee", "verifiee"}
)
STATUTS_RETARD: Final[frozenset[str]] = frozenset(
    {"acceptee", "en_cours", "preuve_deposee"}
)

# Transitions autorisées (source → cibles)
TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "proposee": frozenset({"acceptee", "refusee", "abandonnee"}),
    "acceptee": frozenset({"en_cours", "abandonnee"}),
    "en_cours": frozenset({"preuve_deposee", "abandonnee"}),
    "preuve_deposee": frozenset({"verifiee", "en_cours"}),
    "verifiee": frozenset({"close"}),
    "refusee": frozenset(),
    "close": frozenset(),
    "abandonnee": frozenset(),
}


class ErreurActionRisque(Exception):
    """Echec CRUD / transition action."""


def _serialiser(row: dict[str, Any]) -> dict[str, Any]:
    echeance = row.get("echeance")
    cree = row.get("cree_le")
    maj = row.get("maj_le")
    preuve_le = row.get("preuve_deposee_le")
    verif_le = row.get("verifiee_le")
    return {
        "id": int(row["id"]),
        "risque_id": int(row["risque_id"]),
        "nature": str(row["nature"]),
        "libelle": str(row["libelle"]),
        "responsable_user_id": (
            int(row["responsable_user_id"])
            if row.get("responsable_user_id") is not None
            else None
        ),
        "responsable_label": row.get("responsable_label"),
        "echeance": (
            echeance.isoformat() if isinstance(echeance, date) else echeance
        ),
        "statut": str(row.get("statut") or "proposee"),
        "motif_refus": row.get("motif_refus"),
        "preuve_piece_id": (
            int(row["preuve_piece_id"])
            if row.get("preuve_piece_id") is not None
            else None
        ),
        "preuve_uri": row.get("preuve_uri"),
        "preuve_deposee_le": (
            preuve_le.isoformat()
            if hasattr(preuve_le, "isoformat")
            else preuve_le
        ),
        "verifiee_par": row.get("verifiee_par"),
        "verifiee_le": (
            verif_le.isoformat() if hasattr(verif_le, "isoformat") else verif_le
        ),
        "cree_le": cree.isoformat() if hasattr(cree, "isoformat") else cree,
        "maj_le": maj.isoformat() if hasattr(maj, "isoformat") else maj,
        "contribuable_id": (
            int(row["contribuable_id"])
            if row.get("contribuable_id") is not None
            else None
        ),
        "contribuable_denomination": row.get("contribuable_denomination"),
        "risque_libelle": row.get("risque_libelle"),
        "en_retard": bool(row.get("en_retard")),
    }


def _lire(session: Session, action_id: int) -> dict[str, Any]:
    row = session.execute(
        text(
            "SELECT a.*, r.contribuable_id, r.libelle AS risque_libelle, "
            "c.denomination AS contribuable_denomination, "
            "(a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
            " AND a.statut = ANY(:retards)) AS en_retard "
            "FROM action_risque a "
            "JOIN risque r ON r.id = a.risque_id "
            "JOIN contribuable c ON c.id = r.contribuable_id "
            "WHERE a.id = :id"
        ),
        {"id": action_id, "retards": list(STATUTS_RETARD)},
    ).mappings().one_or_none()
    if row is None:
        raise ErreurActionRisque(f"action_risque {action_id} introuvable")
    return _serialiser(dict(row))


def _resync_statut_risque(session: Session, risque_id: int) -> None:
    """Dérive risque.statut depuis les actions (sans toucher accepte/prescrit)."""
    risque = session.execute(
        text("SELECT id, statut FROM risque WHERE id = :id"),
        {"id": risque_id},
    ).mappings().one_or_none()
    if risque is None:
        return
    actuel = str(risque["statut"] or "ouvert")
    if actuel in {"accepte", "prescrit"}:
        return

    rows = session.execute(
        text("SELECT statut FROM action_risque WHERE risque_id = :r"),
        {"r": risque_id},
    ).mappings().all()
    if not rows:
        if actuel == "en_traitement":
            session.execute(
                text(
                    "UPDATE risque SET statut = 'ouvert', maj_le = now() "
                    "WHERE id = :id"
                ),
                {"id": risque_id},
            )
        return

    statuts = {str(r["statut"]) for r in rows}
    if all(s == "close" for s in statuts):
        session.execute(
            text(
                "UPDATE risque SET statut = 'resolu', maj_le = now() "
                "WHERE id = :id"
            ),
            {"id": risque_id},
        )
        return
    if (
        (statuts & STATUTS_ACTIFS or "refusee" in statuts or "abandonnee" in statuts)
        and actuel not in ("en_traitement", "resolu")
    ):
        session.execute(
            text(
                "UPDATE risque SET statut = 'en_traitement', maj_le = now() "
                "WHERE id = :id"
            ),
            {"id": risque_id},
        )


def lister_actions_risque(
    session: Session,
    tenant_id: int,
    risque_id: int,
) -> list[dict[str, Any]]:
    with contexte_tenant(session, tenant_id):
        mid = session.execute(
            text("SELECT id FROM risque WHERE id = :r"),
            {"r": risque_id},
        ).scalar_one_or_none()
        if mid is None:
            raise ErreurActionRisque(f"risque {risque_id} introuvable")
        rows = session.execute(
            text(
                "SELECT a.*, r.contribuable_id, r.libelle AS risque_libelle, "
                "c.denomination AS contribuable_denomination, "
                "(a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
                " AND a.statut = ANY(:retards)) AS en_retard "
                "FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "JOIN contribuable c ON c.id = r.contribuable_id "
                "WHERE a.risque_id = :r "
                "ORDER BY a.echeance NULLS LAST, a.id ASC"
            ),
            {"r": risque_id, "retards": list(STATUTS_RETARD)},
        ).mappings().all()
        return [_serialiser(dict(r)) for r in rows]


def lister_actions_en_retard(
    session: Session, tenant_id: int
) -> list[dict[str, Any]]:
    with contexte_tenant(session, tenant_id):
        rows = session.execute(
            text(
                "SELECT a.*, r.contribuable_id, r.libelle AS risque_libelle, "
                "c.denomination AS contribuable_denomination, "
                "TRUE AS en_retard "
                "FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "JOIN contribuable c ON c.id = r.contribuable_id "
                "WHERE a.echeance IS NOT NULL AND a.echeance < CURRENT_DATE "
                "AND a.statut = ANY(:retards) "
                "ORDER BY a.echeance ASC, a.id ASC"
            ),
            {"retards": list(STATUTS_RETARD)},
        ).mappings().all()
        return [_serialiser(dict(r)) for r in rows]


def creer_action_risque(
    session: Session,
    tenant_id: int,
    risque_id: int,
    *,
    nature: str,
    libelle: str,
    responsable_user_id: int | None = None,
    responsable_label: str | None = None,
    echeance: date | None = None,
) -> dict[str, Any]:
    nat = (nature or "").strip().lower()
    if nat not in NATURES:
        raise ErreurActionRisque(
            f"nature invalide {nature!r} — attendu : corrective|preventive"
        )
    lib = (libelle or "").strip()
    if not lib:
        raise ErreurActionRisque("libelle obligatoire")

    with contexte_tenant(session, tenant_id):
        risque = session.execute(
            text(
                "SELECT id, contribuable_id, statut FROM risque WHERE id = :r"
            ),
            {"r": risque_id},
        ).mappings().one_or_none()
        if risque is None:
            raise ErreurActionRisque(f"risque {risque_id} introuvable")

        if responsable_user_id is not None:
            u = session.execute(
                text(
                    "SELECT id FROM utilisateur "
                    "WHERE id = :u AND tenant_id = :t"
                ),
                {"u": responsable_user_id, "t": tenant_id},
            ).scalar_one_or_none()
            if u is None:
                raise ErreurActionRisque(
                    f"utilisateur {responsable_user_id} introuvable"
                )

        aid = session.execute(
            text(
                "INSERT INTO action_risque "
                "(tenant_id, risque_id, nature, libelle, responsable_user_id, "
                "responsable_label, echeance, statut) "
                "VALUES (:t, :r, :n, :lib, :ru, :rl, :ech, 'proposee') "
                "RETURNING id"
            ),
            {
                "t": tenant_id,
                "r": risque_id,
                "n": nat,
                "lib": lib,
                "ru": responsable_user_id,
                "rl": (responsable_label or "").strip() or None,
                "ech": echeance,
            },
        ).scalar_one()
        _resync_statut_risque(session, risque_id)
        session.flush()
        return _lire(session, int(aid))


def patcher_action_risque(
    session: Session,
    tenant_id: int,
    action_id: int,
    *,
    acteur: str,
    statut: object | None = ...,
    motif_refus: object | None = ...,
    preuve_piece_id: object | None = ...,
    preuve_uri: object | None = ...,
    responsable_user_id: object | None = ...,
    responsable_label: object | None = ...,
    echeance: object | None = ...,
    libelle: object | None = ...,
) -> dict[str, Any]:
    champs = {
        "statut": statut is not ...,
        "motif_refus": motif_refus is not ...,
        "preuve_piece_id": preuve_piece_id is not ...,
        "preuve_uri": preuve_uri is not ...,
        "responsable_user_id": responsable_user_id is not ...,
        "responsable_label": responsable_label is not ...,
        "echeance": echeance is not ...,
        "libelle": libelle is not ...,
    }
    if not any(champs.values()):
        raise ErreurActionRisque("aucun champ fourni")

    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT a.*, r.contribuable_id "
                "FROM action_risque a "
                "JOIN risque r ON r.id = a.risque_id "
                "WHERE a.id = :id"
            ),
            {"id": action_id},
        ).mappings().one_or_none()
        if row is None:
            raise ErreurActionRisque(f"action_risque {action_id} introuvable")
        ancien = dict(row)
        risque_id = int(ancien["risque_id"])
        contribuable_id = int(ancien["contribuable_id"])

        nouveau_statut = str(ancien.get("statut") or "proposee")
        if champs["statut"]:
            if statut is None:
                raise ErreurActionRisque("statut ne peut pas être null")
            st = str(statut).strip().lower()
            if st not in STATUTS_ACTION:
                raise ErreurActionRisque(f"statut invalide {statut!r}")
            actuel = nouveau_statut
            if st != actuel:
                autorises = TRANSITIONS.get(actuel, frozenset())
                if st not in autorises:
                    raise ErreurActionRisque(
                        f"transition interdite : {actuel} → {st}"
                    )
            nouveau_statut = st

        motif = ancien.get("motif_refus")
        if champs["motif_refus"]:
            motif = (
                None
                if motif_refus is None
                else str(motif_refus).strip() or None
            )
        if nouveau_statut == "refusee" and not motif:
            raise ErreurActionRisque(
                "motif_refus obligatoire quand statut=refusee"
            )

        verifiee_par = ancien.get("verifiee_par")
        verifiee_le = ancien.get("verifiee_le")
        if nouveau_statut == "verifiee" and ancien.get("statut") != "verifiee":
            verifiee_par = acteur
            verifiee_le = datetime.utcnow()
        if nouveau_statut == "close" and (not verifiee_par or not verifiee_le):
            # close depuis verifiee : conserver ; sinon exiger
            if ancien.get("statut") != "verifiee":
                raise ErreurActionRisque(
                    "close uniquement depuis verifiee "
                    "(vérification cabinet requise)"
                )
            verifiee_par = ancien.get("verifiee_par") or acteur
            verifiee_le = ancien.get("verifiee_le") or datetime.utcnow()

        preuve_pid = ancien.get("preuve_piece_id")
        preuve_uri_v = ancien.get("preuve_uri")
        preuve_le = ancien.get("preuve_deposee_le")
        if champs["preuve_uri"]:
            preuve_uri_v = (
                None
                if preuve_uri is None
                else str(preuve_uri).strip() or None
            )
            if preuve_uri_v:
                preuve_le = datetime.utcnow()
        if champs["preuve_piece_id"]:
            if preuve_piece_id is None:
                preuve_pid = None
            else:
                pid = int(preuve_piece_id)
                piece = session.execute(
                    text(
                        "SELECT p.id, m.contribuable_id "
                        "FROM piece_mission p "
                        "JOIN mission m ON m.id = p.mission_id "
                        "WHERE p.id = :p"
                    ),
                    {"p": pid},
                ).mappings().one_or_none()
                if piece is None:
                    raise ErreurActionRisque(
                        f"piece_mission {pid} introuvable"
                    )
                if int(piece["contribuable_id"]) != contribuable_id:
                    raise ErreurActionRisque(
                        f"piece_mission {pid} n'appartient pas au même contribuable"
                    )
                preuve_pid = pid
                preuve_le = datetime.utcnow()

        lib = str(ancien["libelle"])
        if champs["libelle"]:
            lib = str(libelle or "").strip()
            if not lib:
                raise ErreurActionRisque("libelle obligatoire")

        ru = ancien.get("responsable_user_id")
        if champs["responsable_user_id"]:
            if responsable_user_id is None:
                ru = None
            else:
                uid = int(responsable_user_id)
                u = session.execute(
                    text(
                        "SELECT id FROM utilisateur "
                        "WHERE id = :u AND tenant_id = :t"
                    ),
                    {"u": uid, "t": tenant_id},
                ).scalar_one_or_none()
                if u is None:
                    raise ErreurActionRisque(
                        f"utilisateur {uid} introuvable"
                    )
                ru = uid

        rl = ancien.get("responsable_label")
        if champs["responsable_label"]:
            rl = (
                None
                if responsable_label is None
                else str(responsable_label).strip() or None
            )

        ech = ancien.get("echeance")
        if champs["echeance"]:
            if echeance is None or echeance == "":
                ech = None
            else:
                ech = date.fromisoformat(str(echeance)[:10])

        # preuve_deposee : si on dépose une preuve sans changer statut
        if (
            (champs["preuve_piece_id"] or champs["preuve_uri"])
            and not champs["statut"]
            and nouveau_statut == "en_cours"
            and (preuve_pid or preuve_uri_v)
        ):
            nouveau_statut = "preuve_deposee"

        session.execute(
            text(
                "UPDATE action_risque SET statut = :st, motif_refus = :mot, "
                "preuve_piece_id = :pp, preuve_uri = :pu, "
                "preuve_deposee_le = :pl, verifiee_par = :vp, verifiee_le = :vl, "
                "responsable_user_id = :ru, responsable_label = :rl, "
                "echeance = :ech, libelle = :lib, maj_le = now() "
                "WHERE id = :id"
            ),
            {
                "st": nouveau_statut,
                "mot": motif,
                "pp": preuve_pid,
                "pu": preuve_uri_v,
                "pl": preuve_le,
                "vp": verifiee_par,
                "vl": verifiee_le,
                "ru": ru,
                "rl": rl,
                "ech": ech,
                "lib": lib,
                "id": action_id,
            },
        )
        _resync_statut_risque(session, risque_id)
        session.flush()
        return _lire(session, action_id)
