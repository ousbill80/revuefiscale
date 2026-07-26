"""Service de fiabilisation de balance — domaine abonne."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.plateforme.contexte import contexte_tenant
from backend.socle import depot
from backend.socle.controles import (
    controler_balance,
    controler_etats_financiers,
    controler_fec,
    controler_grand_livre,
)
from backend.socle.erreurs import ErreurFiabilisation
from backend.socle.mapping import appliquer_mapping
from backend.socle.modeles import (
    EcritureFec,
    EcritureGrandLivre,
    LigneBalance,
    LigneEtatFinancier,
    RapportFiab,
)

# Classes SYSCOHADA a solde crediteur habituel (passif / produits / capitaux).
# Convention de presentation comptable — aucun seuil ni taux fiscal.
_CLASSES_CREDITRICES = ("1", "4", "7")


def fiabiliser_balance(
    session: Session,
    tenant_id: int,
    mission_id: int,
    lignes: list[LigneBalance],
    *,
    remap: dict[str, str] | None = None,
) -> RapportFiab:
    """Controle, mappe, persiste solde_compte si ok, ecrit toujours le rapport.

    En cas de refus (anomalies), les soldes precedents sont conserves.
    """
    mappees = appliquer_mapping(lignes, remap)
    anomalies = controler_balance(mappees)
    statut = "refuse" if anomalies else "ok"

    with contexte_tenant(session, tenant_id):
        if not depot.mission_existe(session, mission_id):
            raise ErreurFiabilisation(f"mission {mission_id} introuvable pour ce tenant")

        if statut == "ok":
            depot.remplacer_soldes(session, tenant_id, mission_id, mappees)

        rapport_id = depot.inserer_rapport(
            session, tenant_id, mission_id, statut, anomalies
        )
        session.flush()

    return RapportFiab(
        mission_id=mission_id,
        statut=statut,
        anomalies=anomalies,
        rapport_id=rapport_id,
        nb_comptes=len(mappees) if statut == "ok" else 0,
    )


def agreger_ecritures_en_balance(
    ecritures: list[EcritureGrandLivre] | list[EcritureFec],
) -> list[LigneBalance]:
    """Agrege debit/credit par compte pour alimenter solde_compte."""
    debits: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    credits: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    libelles: dict[str, str] = {}
    for ecriture in ecritures:
        if isinstance(ecriture, EcritureFec):
            compte = ecriture.compte_num.strip()
            libelle = ecriture.compte_lib
            debit, credit = ecriture.debit, ecriture.credit
        else:
            compte = ecriture.compte.strip()
            libelle = ecriture.libelle
            debit, credit = ecriture.debit, ecriture.credit
        debits[compte] += debit
        credits[compte] += credit
        if libelle and compte not in libelles:
            libelles[compte] = libelle
    return [
        LigneBalance(
            compte=compte,
            libelle=libelles.get(compte),
            debit=debits[compte],
            credit=credits[compte],
        )
        for compte in sorted(debits)
    ]


def etats_financiers_en_balance(lignes: list[LigneEtatFinancier]) -> list[LigneBalance]:
    """Convertit des postes EF en lignes de solde (sens SYSCOHADA de presentation).

    Montant N positif : classes 1/4/7 en credit, sinon en debit.
    Montant N negatif : sens inverse. Aucun taux fiscal.
    """
    resultat: list[LigneBalance] = []
    for ligne in lignes:
        montant = ligne.montant_n
        abs_m = abs(montant)
        classe_creditrice = ligne.compte[:1] in _CLASSES_CREDITRICES
        if montant >= 0:
            debit = Decimal("0") if classe_creditrice else abs_m
            credit = abs_m if classe_creditrice else Decimal("0")
        else:
            debit = abs_m if classe_creditrice else Decimal("0")
            credit = Decimal("0") if classe_creditrice else abs_m
        resultat.append(
            LigneBalance(
                compte=ligne.compte.strip(),
                libelle=ligne.libelle,
                debit=debit,
                credit=credit,
            )
        )
    return resultat


def _fiabiliser_avec_anomalies_source(
    session: Session,
    tenant_id: int,
    mission_id: int,
    lignes: list[LigneBalance],
    anomalies_source: list[str],
    *,
    remap: dict[str, str] | None = None,
    controler_equilibre: bool = True,
) -> RapportFiab:
    """Persiste si aucune anomalie source (+ equilibre balance si demande)."""
    if anomalies_source:
        with contexte_tenant(session, tenant_id):
            if not depot.mission_existe(session, mission_id):
                raise ErreurFiabilisation(
                    f"mission {mission_id} introuvable pour ce tenant"
                )
            rapport_id = depot.inserer_rapport(
                session, tenant_id, mission_id, "refuse", anomalies_source
            )
            session.flush()
        return RapportFiab(
            mission_id=mission_id,
            statut="refuse",
            anomalies=anomalies_source,
            rapport_id=rapport_id,
            nb_comptes=0,
        )

    if not controler_equilibre:
        mappees = appliquer_mapping(lignes, remap)
        # Doublons / comptes vides uniquement (pas d'equilibre : EF partiels possibles).
        anomalies: list[str] = []
        if not mappees:
            anomalies.append("balance vide : aucune ligne")
        vus: set[str] = set()
        for i, ligne in enumerate(mappees, start=1):
            compte = (ligne.compte or "").strip()
            if not compte:
                anomalies.append(f"ligne {i} : compte vide")
            elif compte in vus:
                anomalies.append(f"compte en double : {compte}")
            else:
                vus.add(compte)
        statut = "refuse" if anomalies else "ok"
        with contexte_tenant(session, tenant_id):
            if not depot.mission_existe(session, mission_id):
                raise ErreurFiabilisation(
                    f"mission {mission_id} introuvable pour ce tenant"
                )
            if statut == "ok":
                depot.remplacer_soldes(session, tenant_id, mission_id, mappees)
            rapport_id = depot.inserer_rapport(
                session, tenant_id, mission_id, statut, anomalies
            )
            session.flush()
        return RapportFiab(
            mission_id=mission_id,
            statut=statut,
            anomalies=anomalies,
            rapport_id=rapport_id,
            nb_comptes=len(mappees) if statut == "ok" else 0,
        )

    return fiabiliser_balance(
        session, tenant_id, mission_id, lignes, remap=remap
    )


def fiabiliser_grand_livre(
    session: Session,
    tenant_id: int,
    mission_id: int,
    ecritures: list[EcritureGrandLivre],
    *,
    remap: dict[str, str] | None = None,
) -> RapportFiab:
    """Controle equilibre GL, agrege par compte, fiabilise comme une balance."""
    anomalies = controler_grand_livre(ecritures)
    lignes = agreger_ecritures_en_balance(ecritures) if not anomalies else []
    return _fiabiliser_avec_anomalies_source(
        session, tenant_id, mission_id, lignes, anomalies, remap=remap
    )


def fiabiliser_fec(
    session: Session,
    tenant_id: int,
    mission_id: int,
    ecritures: list[EcritureFec],
    *,
    remap: dict[str, str] | None = None,
) -> RapportFiab:
    """Controle equilibre FEC, agrege par CompteNum, fiabilise comme une balance."""
    anomalies = controler_fec(ecritures)
    lignes = agreger_ecritures_en_balance(ecritures) if not anomalies else []
    return _fiabiliser_avec_anomalies_source(
        session, tenant_id, mission_id, lignes, anomalies, remap=remap
    )


def fiabiliser_etats_financiers(
    session: Session,
    tenant_id: int,
    mission_id: int,
    lignes_ef: list[LigneEtatFinancier],
    *,
    remap: dict[str, str] | None = None,
) -> RapportFiab:
    """Controle postes non vides, convertit en soldes, persiste sans exiger l'equilibre."""
    anomalies = controler_etats_financiers(lignes_ef)
    lignes = etats_financiers_en_balance(lignes_ef) if not anomalies else []
    return _fiabiliser_avec_anomalies_source(
        session,
        tenant_id,
        mission_id,
        lignes,
        anomalies,
        remap=remap,
        controler_equilibre=False,
    )
