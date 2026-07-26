"""Seed / parcours démo commercial pour ``/app`` (cabinet isolé + mission FICTIF).

Chemin unique recommandé ::

    make seed && make demolot

Compte UI (ENV=dev / localhost uniquement) : variables ``CABINET_DEMO_*``
dans ``.env`` / ``.env.example``. Aucun taux fiscal en dur — montants issus
du référentiel YAML épinglé (mentions ``a_confirmer`` possibles).

Idempotent : ré-exécuter crée une nouvelle mission sur le même cabinet démo.
``demolot1`` / ``demolot234`` restent des parcours techniques (lots moteur).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.config import config
from backend.moteur.service import executer_mission
from backend.plateforme.auth import hasher_mot_de_passe, verifier_mot_de_passe
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.missions import QuotaEpuise, creer_mission
from backend.plateforme.provisionnement import (
    ErreurProvisionnement,
    derniere_version_publiee,
    provisionner_cabinet,
)
from backend.restitution.service import produire_restitution
from backend.socle.lecteurs.balance import parser_balance
from backend.socle.modeles import LigneBalance
from backend.socle.service import fiabiliser_balance

RACINE = Path(__file__).resolve().parents[2]
FIXTURE_CSV = RACINE / "fixtures" / "balance_demo.csv"
DENOM_CABINET = "Cabinet Démo 2AàZ"
DENOM_CONTRIB = "Société Démo CI [FICTIF]"
NCC_CONTRIB = "CI-DEMO-0001"


@dataclass(frozen=True)
class IdentifiantsDemo:
    email: str
    mot_de_passe: str


@dataclass(frozen=True)
class ResultatDemoCommercial:
    tenant_id: int
    utilisateur_id: int
    contribuable_id: int
    mission_id: int
    version_libelle: str
    version_id: int
    nb_comptes: int
    conclusions_declenchees: int
    passage: dict[str, str]


def identifiants_demo() -> IdentifiantsDemo:
    """Lit ``CABINET_DEMO_*`` via config (.env / .env.example)."""
    return IdentifiantsDemo(
        email=config.cabinet_demo_email.strip().lower(),
        mot_de_passe=config.cabinet_demo_password,
    )


def refuser_hors_dev(*, forcer: bool = False) -> None:
    """Bloque le seed démo hors ENV=dev sauf ``FORCE_DEMO_SEED=1`` / ``--force``."""
    if forcer or os.getenv("FORCE_DEMO_SEED", "").strip() == "1":
        return
    if config.env == "dev":
        return
    raise SystemExit(
        f"Refusé : ENV={config.env!r} (attendu 'dev'). "
        "Pour forcer localement : FORCE_DEMO_SEED=1 ou --force. "
        "Jamais en production."
    )


def _charger_balance_fictive() -> list[LigneBalance]:
    brut = FIXTURE_CSV.read_bytes()
    return parser_balance(brut)


def _trouver_utilisateur_demo(
    session: Session, email: str, mot_de_passe: str
) -> tuple[int, int] | None:
    row = session.execute(
        text(
            "SELECT id AS utilisateur_id, tenant_id, password_hash "
            "FROM auth_lookup_utilisateur(:e)"
        ),
        {"e": email},
    ).mappings().one_or_none()
    if row is None:
        return None
    if not verifier_mot_de_passe(mot_de_passe, row["password_hash"]):
        with contexte_tenant(session, int(row["tenant_id"])):
            session.execute(
                text("UPDATE utilisateur SET password_hash = :h WHERE id = :id"),
                {
                    "h": hasher_mot_de_passe(mot_de_passe),
                    "id": row["utilisateur_id"],
                },
            )
            session.flush()
        effacer_contexte_tenant(session)
        print(f"Mot de passe réaligné pour {email} (local / ENV=dev uniquement).")
    return int(row["utilisateur_id"]), int(row["tenant_id"])


def _assurer_contribuable_demo(session: Session, tenant_id: int) -> int:
    with contexte_tenant(session, tenant_id):
        cid = session.execute(
            text(
                "SELECT id FROM contribuable "
                "WHERE ncc = :ncc OR denomination ILIKE '%démo%' "
                "   OR denomination ILIKE '%demo%' "
                "ORDER BY id LIMIT 1"
            ),
            {"ncc": NCC_CONTRIB},
        ).scalar_one_or_none()
        if cid is None:
            cid = session.execute(
                text(
                    "INSERT INTO contribuable (tenant_id, denomination, ncc) "
                    "VALUES (:t, :n, :ncc) RETURNING id"
                ),
                {"t": tenant_id, "n": DENOM_CONTRIB, "ncc": NCC_CONTRIB},
            ).scalar_one()
        else:
            session.execute(
                text(
                    "UPDATE contribuable SET denomination = :n, ncc = :ncc "
                    "WHERE id = :id"
                ),
                {"n": DENOM_CONTRIB, "ncc": NCC_CONTRIB, "id": cid},
            )
    effacer_contexte_tenant(session)
    return int(cid)


def assurer_cabinet_demo(
    session: Session, ids: IdentifiantsDemo | None = None
) -> tuple[int, int, int]:
    """Retourne (tenant_id, utilisateur_id, contribuable_id)."""
    ids = ids or identifiants_demo()
    trouve = _trouver_utilisateur_demo(session, ids.email, ids.mot_de_passe)
    if trouve is not None:
        uid, tid = trouve
        cid = _assurer_contribuable_demo(session, tid)
        return tid, uid, cid

    try:
        prov = provisionner_cabinet(
            session,
            denomination=DENOM_CABINET,
            type_tenant="cabinet",
            palier="standard",
            email_admin=ids.email,
            mot_de_passe_admin=ids.mot_de_passe,
            creer_demo=True,
        )
    except ErreurProvisionnement as e:
        raise SystemExit(f"Provisionnement impossible : {e}") from e

    assert prov.demo_contribuable_id is not None
    with contexte_tenant(session, prov.tenant_id):
        session.execute(
            text(
                "UPDATE contribuable SET denomination = :n, ncc = :ncc WHERE id = :id"
            ),
            {
                "n": DENOM_CONTRIB,
                "ncc": NCC_CONTRIB,
                "id": prov.demo_contribuable_id,
            },
        )
    effacer_contexte_tenant(session)
    print(f"Cabinet créé : tenant={prov.tenant_id} email={ids.email}")
    return prov.tenant_id, prov.utilisateur_id, int(prov.demo_contribuable_id)


def _elargir_quota_demo(session: Session, tenant_id: int, besoin: int = 5) -> None:
    """Élargit le quota du mois pour permettre de rejouer la démo (dev uniquement)."""
    periode = date.today().replace(day=1)
    with contexte_tenant(session, tenant_id):
        row = session.execute(
            text(
                "SELECT missions_incluses, missions_utilisees FROM quota "
                "WHERE tenant_id = :t AND periode = :p FOR UPDATE"
            ),
            {"t": tenant_id, "p": periode},
        ).mappings().one_or_none()
        if row is None:
            session.execute(
                text(
                    "INSERT INTO quota (tenant_id, periode, missions_incluses, "
                    "missions_utilisees) VALUES (:t, :p, :inc, 0)"
                ),
                {"t": tenant_id, "p": periode, "inc": max(besoin, 10)},
            )
        else:
            utilisees = int(row["missions_utilisees"])
            inclus = int(row["missions_incluses"])
            if utilisees >= inclus:
                nouveau = utilisees + besoin
                session.execute(
                    text(
                        "UPDATE quota SET missions_incluses = :inc "
                        "WHERE tenant_id = :t AND periode = :p"
                    ),
                    {"inc": nouveau, "t": tenant_id, "p": periode},
                )
                print(
                    f"Quota démo élargi : {inclus} → {nouveau} "
                    f"(rejeu local, pas une offre commerciale)."
                )
    effacer_contexte_tenant(session)


def provisionner_parcours_demo(
    session: Session,
    *,
    ids: IdentifiantsDemo | None = None,
) -> ResultatDemoCommercial:
    """Cabinet + client + mission + balance FICTIF + exécution + restitution."""
    if not FIXTURE_CSV.is_file():
        raise SystemExit(f"Fixture absente : {FIXTURE_CSV}")

    ids = ids or identifiants_demo()
    vid = derniere_version_publiee(session)
    if vid is None:
        raise SystemExit("Aucune version publiée. Lancez : make seed")

    libelle = session.execute(
        text("SELECT libelle FROM version_referentiel WHERE id = :id"),
        {"id": vid},
    ).scalar_one()

    tid, uid, cid = assurer_cabinet_demo(session, ids)
    _elargir_quota_demo(session, tid)

    try:
        mid = creer_mission(
            session,
            tid,
            contribuable_id=cid,
            exercice=2025,
            profil={
                "regime": "reel",
                "forme_juridique": "SA",
                "secteur": "services",
            },
        )
    except QuotaEpuise:
        _elargir_quota_demo(session, tid, besoin=10)
        try:
            mid = creer_mission(
                session,
                tid,
                contribuable_id=cid,
                exercice=2025,
                profil={
                    "regime": "reel",
                    "forme_juridique": "SA",
                    "secteur": "services",
                },
            )
        except QuotaEpuise as e2:
            raise SystemExit(f"Quota épuisé après élargissement : {e2}") from e2

    lignes = _charger_balance_fictive()
    rapport = fiabiliser_balance(session, tid, mid, lignes)
    if rapport.statut != "ok":
        session.rollback()
        raise SystemExit(f"Fiabilisation refusée : {rapport.anomalies}")

    conclusions = executer_mission(
        session, tid, mid, acteur=ids.email, reponses={}
    )
    rest = produire_restitution(session, tid, mid)

    n = sum(1 for c in conclusions if c.declenchee)
    return ResultatDemoCommercial(
        tenant_id=tid,
        utilisateur_id=uid,
        contribuable_id=cid,
        mission_id=mid,
        version_libelle=str(libelle),
        version_id=int(vid),
        nb_comptes=int(rapport.nb_comptes),
        conclusions_declenchees=n,
        passage={
            "reintegrations": str(rest.passage.total_reintegration),
            "deductions": str(rest.passage.total_deduction),
            "solde_net": str(rest.passage.solde_net),
        },
    )


def _afficher_resultat(r: ResultatDemoCommercial, ids: IdentifiantsDemo) -> None:
    print("--- démo commercial OK ---")
    print(f"email={ids.email}  mot_de_passe={ids.mot_de_passe}")
    print(
        f"tenant={r.tenant_id}  mission={r.mission_id}  "
        f"version_épinglée={r.version_libelle} (id={r.version_id})"
    )
    print(f"client={DENOM_CONTRIB}  (id={r.contribuable_id})")
    print(f"balance=FICTIF ({FIXTURE_CSV.name})  comptes={r.nb_comptes}")
    print(f"conclusions_declenchees={r.conclusions_declenchees}")
    print("passage : " + json.dumps(r.passage, ensure_ascii=False))
    print("UI : make frontend && make dev → http://localhost:8000/app/")
    print("Connexion : chip « Remplir Cabinet » / « Connexion démo » (localhost + ENV=dev)")
    print("Rejouer : make demolot")
    print("Note : montants issus du référentiel YAML (mentions a_confirmer).")


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    forcer = "--force" in args
    refuser_hors_dev(forcer=forcer)

    ids = identifiants_demo()
    engine = create_engine(config.database_url, future=True)
    with Session(engine) as session:
        resultat = provisionner_parcours_demo(session, ids=ids)
        session.commit()
        _afficher_resultat(resultat, ids)
    return 0


if __name__ == "__main__":
    sys.exit(main())
