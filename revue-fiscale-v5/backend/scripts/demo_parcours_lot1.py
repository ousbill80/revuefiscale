"""Demo executable : provisionne, importe, execute, restitue.

Usage :
    make seed
    make demolot1

Ne contient aucun taux fiscal en dur : lit le referentiel epingle.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.config import config
from backend.moteur.service import executer_mission
from backend.plateforme.contexte import contexte_tenant, effacer_contexte_tenant
from backend.plateforme.missions import creer_mission
from backend.plateforme.provisionnement import provisionner_cabinet
from backend.restitution.service import produire_restitution
from backend.socle.jeux_lot1 import balance_lot1_types, reponses_lot1_types
from backend.socle.service import fiabiliser_balance

VERSION = "v2026.7-complet"


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
        email = f"demo.lot1.{suffix}@exemple.ci"
        prov = provisionner_cabinet(
            session,
            denomination=f"Cabinet Demo Lot1 {suffix}",
            type_tenant="cabinet",
            palier="standard",
            email_admin=email,
            mot_de_passe_admin="DemoLot1!",
            creer_demo=True,
        )
        assert prov.demo_contribuable_id is not None

        mid = creer_mission(
            session,
            prov.tenant_id,
            contribuable_id=prov.demo_contribuable_id,
            exercice=2025,
            profil={"regime": "reel", "forme_juridique": "SA"},
        )
        with contexte_tenant(session, prov.tenant_id):
            session.execute(
                text("UPDATE mission SET version_referentiel_id = :v WHERE id = :m"),
                {"v": vid, "m": mid},
            )
        effacer_contexte_tenant(session)

        rapport = fiabiliser_balance(
            session, prov.tenant_id, mid, balance_lot1_types()
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
            reponses=reponses_lot1_types(),
        )
        rest = produire_restitution(session, prov.tenant_id, mid)
        session.commit()

        print(f"tenant={prov.tenant_id}  mission={mid}  version={VERSION} (id={vid})")
        print(f"fiabilisation=ok  comptes={rapport.nb_comptes}")
        print("--- conclusions declenchees ---")
        for c in sorted(conclusions, key=lambda x: x.regle_id):
            if not c.declenchee:
                continue
            mt = c.montant if c.montant is not None else "-"
            print(
                f"  {c.regle_id:28}  {mt:>18}  "
                f"{c.sens or '-':14}  risque={c.niveau_risque}"
            )
        n = sum(1 for c in conclusions if c.declenchee)
        print(f"--- {n} conclusion(s) ---")
        print("--- passage fiscal ---")
        print(f"  total reintegrations : {rest.passage.total_reintegration}")
        print(f"  total deductions     : {rest.passage.total_deduction}")
        print(f"  solde net            : {rest.passage.solde_net}")
        print(
            f"  score risque (heuristique, non CGI) : {rest.score_risque.score} "
            f"{rest.score_risque.comptages}"
        )
        print("Note : montants issus du referentiel YAML (mentions a confirmer).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
