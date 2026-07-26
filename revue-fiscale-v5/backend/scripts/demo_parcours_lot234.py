"""Demo Lots 2/3/4 : provisionne, importe, execute, exporte Word/PDF.

Usage :
    make seed
    make demolot234
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.config import config
from backend.moteur.service import executer_mission
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.missions import creer_mission
from backend.plateforme.provisionnement import provisionner_cabinet
from backend.restitution.rapport_docx import rendre_rapport_docx
from backend.restitution.rapport_pdf import rendre_rapport_pdf
from backend.restitution.service import lire_audit, produire_restitution
from backend.socle.jeux_lot1 import balance_lot1_types, reponses_lot1_types
from backend.socle.modeles import LigneBalance
from backend.socle.service import fiabiliser_balance

VERSION = "v2026.7-complet"
OUT = Path(__file__).resolve().parents[2] / "fixtures" / "demo_exports"


def _ligne(compte: str, debit: str = "0", credit: str = "0", libelle: str = "") -> LigneBalance:
    return LigneBalance(
        compte=compte,
        libelle=libelle or None,
        debit=Decimal(debit),
        credit=Decimal(credit),
    )


def balance_multidomaines() -> list[LigneBalance]:
    base = balance_lot1_types()
    extra = [
        _ligne("443", credit="18000000", libelle="TVA collectee"),
        _ligne("445", debit="20000000", libelle="TVA deductible"),
        _ligne("457", credit="20000000", libelle="Dividendes"),
        _ligne("695", debit="50000000", libelle="Impot resultat"),
        _ligne("21", debit="50000000", libelle="Immobilisations"),
    ]
    debit_extra = sum((x.debit for x in extra), Decimal("0"))
    credit_extra = sum((x.credit for x in extra), Decimal("0"))
    ecart = debit_extra - credit_extra
    if ecart > 0:
        extra.append(_ligne("101", credit=str(ecart), libelle="Capital equilibre"))
    elif ecart < 0:
        extra.append(_ligne("512", debit=str(-ecart), libelle="Banque equilibre"))
    return list(base) + extra


def reponses_demo() -> dict[str, object]:
    r = dict(reponses_lot1_types())
    r.update(
        {
            "q_ecart_ca_tva": True,
            "q_montant_ecart": Decimal("5000000"),
            "q_operations_mixtes": True,
            "q_tva_non_ded": Decimal("3000000"),
            "q_distrib": True,
            "q_irvm_due": Decimal("3000000"),
            # Ne pas ecraser q_montant (partage OBL-108 / plusieurs RA).
            "q_ecart_taux": True,
            "q_montant": Decimal("7500000"),
        }
    )
    return r


def main() -> int:
    engine = create_engine(config.database_url, future=True)
    with Session(engine) as session:
        vid = session.execute(
            text(
                "SELECT id FROM version_referentiel "
                "WHERE libelle = :l AND publiee_le IS NOT NULL"
            ),
            {"l": VERSION},
        ).scalar_one_or_none()
        if vid is None:
            print(f"Version {VERSION} absente. Lancez : make seed")
            return 1

        suffix = session.execute(text("SELECT floor(random()*100000)::int")).scalar_one()
        email = f"demo.lot234.{suffix}@exemple.ci"
        prov = provisionner_cabinet(
            session,
            denomination=f"Cabinet Demo Lot234 {suffix}",
            type_tenant="cabinet",
            palier="standard",
            email_admin=email,
            mot_de_passe_admin="DemoLot234!",
            creer_demo=True,
        )
        assert prov.demo_contribuable_id is not None

        mid = creer_mission(
            session,
            prov.tenant_id,
            contribuable_id=prov.demo_contribuable_id,
            exercice=2025,
            profil={
                "regime": "reel",
                "forme_juridique": "SA",
                "secteur": "services",
            },
        )
        with contexte_tenant(session, prov.tenant_id):
            session.execute(
                text("UPDATE mission SET version_referentiel_id = :v WHERE id = :m"),
                {"v": vid, "m": mid},
            )
        effacer_contexte_tenant(session)

        rapport = fiabiliser_balance(
            session, prov.tenant_id, mid, balance_multidomaines()
        )
        if rapport.statut != "ok":
            print("Fiabilisation refusee :", rapport.anomalies)
            session.rollback()
            return 1

        conclusions = executer_mission(
            session,
            prov.tenant_id,
            mid,
            acteur=email,
            reponses=reponses_demo(),
        )
        rest = produire_restitution(session, prov.tenant_id, mid)
        audit = lire_audit(session, prov.tenant_id, mid, limite=10)
        meta = {
            "mission_id": mid,
            "exercice": 2025,
            "contribuable_denomination": f"Demo {suffix}",
            "contribuable_ncc": "—",
            "version_referentiel_id": int(vid),
        }
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"rapport-{mid}.docx").write_bytes(
            rendre_rapport_docx(
                meta=meta,
                passage=rest.passage,
                conclusions=rest.conclusions,
                score=rest.score_risque,
                extrait_audit=audit,
            )
        )
        (OUT / f"rapport-{mid}.pdf").write_bytes(
            rendre_rapport_pdf(
                meta=meta,
                passage=rest.passage,
                conclusions=rest.conclusions,
                score=rest.score_risque,
                extrait_audit=audit,
            )
        )
        session.commit()

        print(f"tenant={prov.tenant_id}  mission={mid}  version={VERSION} (id={vid})")
        print(f"fiabilisation=ok  comptes={rapport.nb_comptes}")
        print("--- conclusions declenchees ---")
        for c in sorted(conclusions, key=lambda x: x.regle_id):
            if not c.declenchee:
                continue
            mt = c.montant if c.montant is not None else "-"
            print(
                f"  {c.regle_id:32}  {mt:>18}  "
                f"{c.sens or '-':14}  risque={c.niveau_risque}"
            )
        n = sum(1 for c in conclusions if c.declenchee)
        print(f"--- {n} conclusion(s) ---")
        print("--- passage fiscal ---")
        print(f"  solde net : {rest.passage.solde_net}")
        print(
            f"  score risque (heuristique) : {rest.score_risque.score} "
            f"{rest.score_risque.comptages}"
        )
        print(f"exports : {OUT / f'rapport-{mid}.docx'}")
        print(f"         {OUT / f'rapport-{mid}.pdf'}")
        print("Note : montants YAML a_confirmer.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
