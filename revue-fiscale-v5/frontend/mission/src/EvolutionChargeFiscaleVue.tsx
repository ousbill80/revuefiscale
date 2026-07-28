import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant, fmtPct } from "./api";
import { InfoTip } from "./Tooltip";

/** Évolution pluriannuelle de la charge fiscale — vue consultative.
 *
 * Pour le client de la mission, le panorama de charge fiscale de
 * chaque exercice revu est repris tel quel (aucun recalcul) : IS
 * théorique, patente partielle, impôts sur salaires déclarés, TVA
 * nette déclarée (présentée séparément), total de charge propre.
 * Variations entre exercices consécutifs disponibles : variation
 * absolue et relative, sens descriptif « hausse » / « baisse » /
 * « stable » — les variations s'expliquent (activité, taux,
 * assiettes, exonérations), les liasses font foi, l'humain analyse.
 */
type ComposanteLigne = {
  libelle: string;
  montant_estime: string | null;
  incluse_dans_total: boolean;
};

type LigneExercice = {
  exercice: number;
  mission_id: number | null;
  disponible: boolean;
  total_charge_propre_estimee: string | null;
  composantes: Record<string, ComposanteLigne>;
};

type Variation = {
  variation_absolue: string;
  variation_relative_pct: string | null;
  sens: string;
} | null;

type VariationLigne = {
  exercice_precedent: number;
  exercice: number;
  total: Variation;
  composantes: Record<string, Variation>;
};

type EvolutionChargeFiscaleOut = {
  mission_id: number;
  exercice: number;
  disponible: boolean;
  exercices: LigneExercice[];
  variations: VariationLigne[];
  statut: string;
  synthese: {
    statut: string;
    libelle_statut: string;
    nb_exercices: number;
    nb_exercices_disponibles: number;
    nb_variations: number;
  };
  note: string;
  references: { reference: string; portee: string }[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

const COMPOSANTES: { cle: string; titre: string }[] = [
  { cle: "is", titre: "IS théorique" },
  { cle: "patente", titre: "Patente (partielle)" },
  { cle: "salaires", titre: "Impôts sur salaires" },
  { cle: "tva", titre: "TVA nette (séparée)" },
];

const SENS_FR: Record<string, string> = {
  hausse: "hausse",
  baisse: "baisse",
  stable: "stable",
};

/** Rendu texte d'une variation — jamais accusatoire, jamais de rouge. */
function libelleVariation(v: Variation): string {
  if (!v) return "—";
  const sens = SENS_FR[v.sens] ?? v.sens;
  if (v.variation_relative_pct == null) {
    return `${sens} (${fmtMontant(v.variation_absolue)} FCFA)`;
  }
  return `${sens} (${fmtPct(v.variation_relative_pct)} %)`;
}

export function EvolutionChargeFiscaleVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<EvolutionChargeFiscaleOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<EvolutionChargeFiscaleOut>(
        `/api/v1/missions/${missionId}/evolution-charge-fiscale`,
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
  return (
    <section
      className="matx panel dense"
      aria-label="Évolution pluriannuelle de la charge fiscale"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Évolution de la charge fiscale (pluriannuelle)
          <InfoTip
            label="Le panorama de charge fiscale de chaque exercice revu du client est repris tel quel (aucun recalcul) et les variations entre exercices consécutifs disponibles sont restituées à titre indicatif. Les variations s'expliquent (activité, taux, assiettes, exonérations) — vue indicative fondée sur les charges THÉORIQUES estimées, les liasses font foi ; l'humain analyse et décide."
            ariaLabel="Aide : évolution pluriannuelle de la charge fiscale"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            <>
              {etat.synthese.nb_exercices_disponibles} exercices
              disponibles — {etat.synthese.nb_variations} variation
              {etat.synthese.nb_variations > 1 ? "s" : ""} à expliquer
            </>
          ) : (
            "Indisponible"
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Évolution indisponible : moins de deux exercices du client
          portent un panorama de charge fiscale estimée — importez les
          balances et saisissez les déclarations des missions du client
          pour lire l'évolution pluriannuelle.
        </p>
      ) : (
        <>
          <table className="matx-table">
            <thead>
              <tr>
                <th scope="col">Exercice</th>
                {COMPOSANTES.map((c) => (
                  <th scope="col" key={c.cle}>
                    {c.titre} (FCFA)
                  </th>
                ))}
                <th scope="col">
                  Charge propre estimée (FCFA)
                  <InfoTip
                    label="Total PARTIEL par construction : somme des composantes estimées disponibles hors TVA (impôt collecté pour le compte de l'État) — repris du panorama de charge fiscale de chaque exercice, aucun recalcul."
                    ariaLabel="Aide : total de charge propre estimée"
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {etat.exercices.map((l) => (
                <tr key={l.exercice}>
                  <td className="matx-ref">{l.exercice}</td>
                  {COMPOSANTES.map((c) => {
                    const comp = l.composantes[c.cle];
                    return (
                      <td className="matx-montant" key={c.cle}>
                        {comp?.montant_estime != null
                          ? fmtMontant(comp.montant_estime)
                          : "—"}
                      </td>
                    );
                  })}
                  <td className="matx-montant">
                    {l.disponible &&
                    l.total_charge_propre_estimee != null
                      ? fmtMontant(l.total_charge_propre_estimee)
                      : "Indisponible"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {etat.variations.length > 0 && (
            <table className="matx-table">
              <thead>
                <tr>
                  <th scope="col">
                    Variation à expliquer
                    <InfoTip
                      label="Variation entre deux exercices consécutifs disponibles — sens descriptif (hausse / baisse / stable) et variation relative en pourcentage (aucun pourcentage si la base est nulle). Une variation s'explique : activité, taux, assiettes, exonérations."
                      ariaLabel="Aide : variations entre exercices"
                    />
                  </th>
                  {COMPOSANTES.map((c) => (
                    <th scope="col" key={c.cle}>
                      {c.titre}
                    </th>
                  ))}
                  <th scope="col">Charge propre</th>
                </tr>
              </thead>
              <tbody>
                {etat.variations.map((v) => (
                  <tr key={`${v.exercice_precedent}-${v.exercice}`}>
                    <td className="matx-ref">
                      {v.exercice_precedent} → {v.exercice}
                    </td>
                    {COMPOSANTES.map((c) => (
                      <td key={c.cle}>
                        {libelleVariation(v.composantes[c.cle] ?? null)}
                      </td>
                    ))}
                    <td>{libelleVariation(v.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted">{etat.synthese.libelle_statut}.</p>
        </>
      )}

      <details className="matx-detail">
        <summary>Références ({etat.references.length})</summary>
        <ul>
          {etat.references.map((r) => (
            <li key={r.reference}>
              <strong>{r.reference}</strong> — {r.portee}
            </li>
          ))}
        </ul>
      </details>

      <p className="matx-note muted">{etat.note}</p>
    </section>
  );
}
