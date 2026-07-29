import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Seuil de matérialité et ciblage des travaux — vue consultative.
 *
 * Propose des seuils de signification calculés depuis la balance
 * importée (1 % du CA classe 70, 5 % du résultat courant approché,
 * 1 % du total bilan approché — pratique ISA 320). Le fiscaliste
 * CONFIRME une proposition ou fixe un seuil MANUEL (clic explicite) ;
 * les comptes dont le solde dépasse le seuil retenu sont restitués par
 * classe SYSCOHADA avec le taux de couverture des masses. Strictement
 * consultatif : l'humain décide du programme de travail.
 */
type PropositionSeuil = {
  referentiel: string;
  libelle: string;
  taux: string;
  base: string;
  seuil_propose: string | null;
  calculable: boolean;
};

type SeuilRetenu = {
  seuil_retenu: string;
  source: string;
  referentiel: string;
  commentaire: string;
  decide_par: string;
  cree_le: string | null;
  mis_a_jour_le: string | null;
};

type CompteCible = {
  compte: string;
  libelle: string;
  classe: string;
  solde: string;
};

type CouvertureClasse = {
  classe: string;
  libelle: string;
  nb_comptes: number;
  nb_comptes_cibles: number;
  masse: string;
  masse_ciblee: string;
  taux_couverture: string;
};

type MaterialiteOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  agregats: {
    chiffre_affaires: string;
    resultat: string;
    total_bilan: string;
  };
  propositions: PropositionSeuil[];
  seuil_retenu: SeuilRetenu | null;
  comptes_cibles: CompteCible[];
  couverture: {
    par_classe: CouvertureClasse[];
    masse_totale: string;
    masse_ciblee: string;
    taux_global: string;
  };
  synthese: {
    statut: string;
    nb_comptes_balance: number;
    nb_comptes_cibles: number;
    taux_couverture_global: string;
  };
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

export function MaterialiteVue({ missionId, jeton, estLecteur }: Props) {
  const [etat, setEtat] = useState<MaterialiteOut | null>(null);
  const [montantManuel, setMontantManuel] = useState("");
  const [commentaire, setCommentaire] = useState("");
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<MaterialiteOut>(
        `/api/v1/missions/${missionId}/materialite`,
        { jeton },
      );
      setEtat(out ?? null);
    } catch {
      setEtat(null);
    }
  }, [jeton, missionId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  const retenir = useCallback(
    async (corps: {
      source: string;
      referentiel?: string;
      montant?: string;
      commentaire?: string;
    }) => {
      if (!jeton || !missionId) return;
      setBusy(true);
      setMsg(null);
      try {
        await api(`/api/v1/missions/${missionId}/materialite`, {
          method: "POST",
          jeton,
          json: corps,
        });
        setMontantManuel("");
        setCommentaire("");
        setMsg({ texte: "Seuil de matérialité retenu.", err: false });
        await charger();
      } catch (e) {
        setMsg({
          texte:
            e instanceof Error ? e.message : "Retenue impossible.",
          err: true,
        });
      } finally {
        setBusy(false);
      }
    },
    [jeton, missionId, charger],
  );

  if (!etat) return null;
  const s = etat.synthese;
  const retenu = etat.seuil_retenu;
  return (
    <section
      className="matx panel dense"
      aria-label="Seuil de matérialité et ciblage des travaux"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Seuil de matérialité et ciblage des travaux
          <InfoTip
            label="Seuils de signification proposés depuis la balance (1 % du CA, 5 % du résultat courant approché, 1 % du total bilan approché). Confirmez une proposition ou fixez un seuil manuel : les comptes dont le solde dépasse le seuil retenu méritent une revue détaillée — vue consultative, l'humain décide du programme de travail."
            ariaLabel="Aide : seuil de matérialité"
          />
        </h4>
        <span className="matx-synthese muted">
          {s.nb_comptes_balance} compte
          {s.nb_comptes_balance > 1 ? "s" : ""} en balance
          {retenu && (
            <>
              {" "}
              · seuil retenu {fmtMontant(retenu.seuil_retenu)} FCFA ·{" "}
              <strong className="matx-badge-cible">
                {s.nb_comptes_cibles} compte
                {s.nb_comptes_cibles > 1 ? "s" : ""} ciblé
                {s.nb_comptes_cibles > 1 ? "s" : ""} (
                {s.taux_couverture_global} % des masses)
              </strong>
            </>
          )}
        </span>
      </div>

      {etat.disponible ? (
        <table className="matx-table">
          <thead>
            <tr>
              <th scope="col">Référentiel</th>
              <th scope="col">Base (FCFA)</th>
              <th scope="col">Seuil proposé</th>
              {!estLecteur && <th scope="col" />}
            </tr>
          </thead>
          <tbody>
            {etat.propositions.map((p) => (
              <tr key={p.referentiel}>
                <td className="matx-ref">{p.libelle}</td>
                <td className="matx-montant">{fmtMontant(p.base)}</td>
                <td className="matx-montant">
                  {p.calculable && p.seuil_propose ? (
                    fmtMontant(p.seuil_propose)
                  ) : (
                    <span className="muted">Non calculable</span>
                  )}
                  {retenu &&
                    retenu.source === "proposition" &&
                    retenu.referentiel === p.referentiel && (
                      <span className="matx-badge-retenu"> Retenu</span>
                    )}
                </td>
                {!estLecteur && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost"
                      disabled={busy || !p.calculable}
                      onClick={() =>
                        void retenir({
                          source: "proposition",
                          referentiel: p.referentiel,
                          commentaire: commentaire || undefined,
                        })
                      }
                    >
                      Confirmer
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty-state">
          Matérialité indisponible : importez une balance pour calculer
          les seuils de signification proposés. Un seuil manuel reste
          possible.
        </p>
      )}

      {!estLecteur && (
        <div className="matx-saisie">
          <label className="matx-champ">
            Seuil manuel (FCFA)
            <input
              type="number"
              min="1"
              step="1"
              value={montantManuel}
              onChange={(e) => setMontantManuel(e.target.value)}
              placeholder="0"
              aria-label="Seuil manuel en FCFA"
            />
          </label>
          <label className="matx-champ matx-champ-large">
            Commentaire (facultatif)
            <input
              type="text"
              value={commentaire}
              onChange={(e) => setCommentaire(e.target.value)}
              placeholder="Justification du seuil retenu…"
              aria-label="Commentaire sur le seuil retenu"
            />
          </label>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || !montantManuel}
            onClick={() =>
              void retenir({
                source: "manuel",
                montant: montantManuel,
                commentaire: commentaire || undefined,
              })
            }
          >
            Retenir ce seuil manuel
          </button>
        </div>
      )}
      {msg && (
        <p className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.texte}
        </p>
      )}

      {retenu && etat.disponible && (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Classe SYSCOHADA</th>
                <th scope="col">Comptes ciblés</th>
                <th scope="col">Masse (FCFA)</th>
                <th scope="col">Masse ciblée</th>
                <th scope="col">Couverture</th>
              </tr>
            </thead>
            <tbody>
              {etat.couverture.par_classe.map((c) => (
                <tr key={c.classe}>
                  <td className="matx-ref">{c.libelle}</td>
                  <td className="matx-montant">
                    {c.nb_comptes_cibles} / {c.nb_comptes}
                  </td>
                  <td className="matx-montant">{fmtMontant(c.masse)}</td>
                  <td className="matx-montant">
                    {fmtMontant(c.masse_ciblee)}
                  </td>
                  <td className="matx-montant">
                    {c.taux_couverture} %
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {etat.comptes_cibles.length > 0 && (
            <details className="matx-detail">
              <summary>
                Comptes méritant une revue détaillée (
                {etat.comptes_cibles.length})
              </summary>
              <table className="matx-table">
                <thead>
                  <tr>
                    <th scope="col">Compte</th>
                    <th scope="col">Libellé</th>
                    <th scope="col">Solde (FCFA)</th>
                  </tr>
                </thead>
                <tbody>
                  {etat.comptes_cibles.map((c) => (
                    <tr key={c.compte}>
                      <td>{c.compte}</td>
                      <td>{c.libelle}</td>
                      <td className="matx-montant">
                        {fmtMontant(c.solde)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </>
      )}

      <p className="matx-note muted">
        {retenu
          ? `Seuil retenu : ${fmtMontant(retenu.seuil_retenu)} FCFA (${
              retenu.source === "manuel"
                ? "seuil manuel"
                : "proposition confirmée"
            }, par ${retenu.decide_par}). `
          : "Aucun seuil retenu pour l'instant."}
      </p>
    </section>
  );
}
