import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Panorama consultatif de la charge fiscale estimée — vue d'ensemble.
 *
 * Agrège les estimations DÉJÀ calculées par les modules de la revue
 * (IS théorique du tableau de passage, patente partielle au droit sur
 * le chiffre d'affaires, impôts sur salaires et TVA tels que
 * déclarés, position d'acomptes) — aucun recalcul, aucune invention.
 * Le total de charge propre est PARTIEL et exclut la TVA (impôt
 * collecté) et les acomptes (position de trésorerie) — lecture seule,
 * l'humain décide.
 */
type Composante = {
  disponible: boolean;
  libelle: string;
  montant_estime: string | null;
  incluse_dans_total: boolean;
  imf_possible?: boolean;
  estimation_partielle?: boolean;
  impot_collecte?: boolean;
  position_libelle?: string | null;
  solde_signe?: string | null;
  total_verse?: string | null;
  is_du_estime?: string | null;
  nb_periodes_declarees?: number;
};

type Reference = { reference: string; portee: string };

type ChargeFiscaleOut = {
  mission_id: number;
  exercice: number | null;
  disponible: boolean;
  composantes: Record<string, Composante>;
  total_charge_propre_estimee: string;
  composantes_incluses_total: string[];
  composantes_indisponibles: string[];
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_composantes_disponibles: number;
    nb_composantes_suivies: number;
    total_partiel: boolean;
    tva_nette_declaree: string | null;
  };
  note: string;
  references: Reference[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const ORDRE_COMPOSANTES = [
  "is",
  "patente",
  "salaires",
  "tva",
  "acomptes",
] as const;

const TITRES_COURTS: Record<string, string> = {
  is: "IS théorique",
  patente: "Patente (partielle)",
  salaires: "Impôts sur salaires déclarés",
  tva: "TVA nette déclarée",
  acomptes: "Position acomptes IS",
};

export function ChargeFiscaleVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<ChargeFiscaleOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<ChargeFiscaleOut>(
        `/api/v1/missions/${missionId}/charge-fiscale`,
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

  if (!etat) return null;
  const s = etat.synthese;
  return (
    <section
      className="matx panel dense"
      aria-label="Panorama de la charge fiscale estimée"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Panorama de la charge fiscale estimée
          <InfoTip
            label="Vue d'ensemble consultative agrégeant les estimations déjà calculées par les écrans de la revue (IS théorique, patente partielle, impôts sur salaires et TVA déclarés, position d'acomptes) — aucun recalcul. Le total de charge propre est partiel et exclut la TVA (impôt collecté) et les acomptes (position de trésorerie). L'humain apprécie et décide."
            ariaLabel="Aide : panorama de la charge fiscale estimée"
          />
        </h4>
        <span className="matx-synthese muted">
          {s.nb_composantes_disponibles}/{s.nb_composantes_suivies}{" "}
          composantes estimées
          {etat.disponible && (
            <>
              {" "}
              ·{" "}
              <strong className="matx-badge-cible">
                charge propre partielle{" "}
                {fmtMontant(etat.total_charge_propre_estimee)} FCFA
              </strong>
            </>
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">{s.libelle_statut}</p>
      ) : (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Composante</th>
                <th scope="col">Montant estimé (FCFA)</th>
                <th scope="col">Dans le total</th>
              </tr>
            </thead>
            <tbody>
              {ORDRE_COMPOSANTES.map((cle) => {
                const c = etat.composantes[cle];
                if (!c) return null;
                return (
                  <tr key={cle}>
                    <td className="matx-ref">
                      {TITRES_COURTS[cle] ?? cle}
                      <InfoTip
                        label={c.libelle}
                        ariaLabel={`Détail : ${TITRES_COURTS[cle] ?? cle}`}
                      />
                    </td>
                    <td className="matx-montant">
                      {!c.disponible
                        ? "indisponible"
                        : cle === "acomptes"
                          ? (c.position_libelle ?? "—") +
                            (c.solde_signe
                              ? ` (${fmtMontant(c.solde_signe)} FCFA)`
                              : "")
                          : c.montant_estime !== null
                            ? fmtMontant(c.montant_estime)
                            : "—"}
                      {c.disponible && c.imf_possible && (
                        <InfoTip
                          label="Signal IMF : l'impôt minimum forfaitaire pourrait s'appliquer (non calculé ici — à vérifier par le fiscaliste)."
                          ariaLabel="Signal impôt minimum forfaitaire"
                        />
                      )}
                    </td>
                    <td>
                      {c.incluse_dans_total
                        ? c.disponible && c.montant_estime !== null
                          ? "oui"
                          : "oui (indisponible)"
                        : cle === "tva"
                          ? "non (impôt collecté)"
                          : "non (position)"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          <p className="muted">
            Total de charge propre estimée (partiel) :{" "}
            <strong>
              {fmtMontant(etat.total_charge_propre_estimee)} FCFA
            </strong>{" "}
            — somme des composantes disponibles hors TVA (collectée) et
            hors position d'acomptes.
            {etat.composantes_indisponibles.length > 0 && (
              <>
                {" "}
                Indisponibles :{" "}
                {etat.composantes_indisponibles
                  .map((cle) => TITRES_COURTS[cle] ?? cle)
                  .join(", ")}
                .
              </>
            )}
          </p>

          <details className="matx-detail">
            <summary>
              Références appliquées ({etat.references.length})
            </summary>
            <table className="matx-table">
              <thead>
                <tr>
                  <th scope="col">Référence</th>
                  <th scope="col">Portée</th>
                </tr>
              </thead>
              <tbody>
                {etat.references.map((r) => (
                  <tr key={r.reference}>
                    <td className="matx-ref">{r.reference}</td>
                    <td>{r.portee}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}

    </section>
  );
}
