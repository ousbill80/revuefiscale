import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Complétude déclarative mensuelle de l'exercice — vue consultative.
 *
 * Compare, par impôt mensuel (TVA, impôts sur salaires), les périodes
 * AAAA-MM échues de l'exercice aux déclarations saisies dans l'outil
 * et signale les périodes manquantes. La saisie dans l'outil ne
 * prouve pas le dépôt effectif à la DGI : seuls les quittances et
 * accusés de dépôt font foi — lecture seule, l'humain vérifie.
 */
type BlocImpot = {
  impot: string;
  libelle: string;
  disponible: boolean;
  attendues: string[];
  saisies: string[];
  manquantes: string[];
  nb_attendues: number;
  nb_saisies: number;
  nb_manquantes: number;
  taux_couverture: string;
  statut: string;
};

type Reference = {
  reference: string;
  portee: string;
};

type CompletudeOut = {
  mission_id: number;
  disponible: boolean;
  exercice: number;
  aujourd_hui: string;
  impots: {
    tva: BlocImpot;
    salaires: BlocImpot;
  };
  synthese: {
    statut_global: string;
    nb_periodes_attendues: number;
    nb_manquantes_total: number;
  };
  note: string;
  references: Reference[];
};

type Props = {
  missionId: number;
  jeton?: string | null;
};

/** Périodes AAAA-MM triées condensées en plages contiguës (« 2023-01 → 2023-04, 2023-06 »). */
function condenserPeriodes(periodes: string[]): string {
  const rang = (p: string): number => {
    const [a, m] = p.split("-").map(Number);
    return a * 12 + m;
  };
  const plages: string[] = [];
  let debut = "";
  let fin = "";
  for (const p of periodes) {
    if (debut && rang(p) === rang(fin) + 1) {
      fin = p;
    } else {
      if (debut) plages.push(debut === fin ? debut : `${debut} → ${fin}`);
      debut = p;
      fin = p;
    }
  }
  if (debut) plages.push(debut === fin ? debut : `${debut} → ${fin}`);
  return plages.join(", ");
}

const STATUT_LABELS: Record<string, string> = {
  complet: "Complet",
  lacunaire: "Lacunaire",
  aucune_saisie: "Aucune saisie",
  sans_periode_echue: "Sans période échue",
};

export function CompletudeDeclarativeVue({ missionId, jeton }: Props) {
  const [etat, setEtat] = useState<CompletudeOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<CompletudeOut>(
        `/api/v1/missions/${missionId}/completude-declarative`,
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
  const blocs = [etat.impots.tva, etat.impots.salaires];
  return (
    <section
      className="matx panel dense"
      aria-label="Complétude déclarative mensuelle"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Complétude déclarative mensuelle — exercice {etat.exercice}
          <InfoTip
            label="Compare les périodes mensuelles échues de l'exercice aux déclarations saisies dans l'outil (TVA et impôts sur salaires) et signale les périodes sans déclaration. La saisie dans l'outil ne prouve pas le dépôt à la DGI : seuls les quittances et accusés de dépôt font foi — vue consultative, l'humain vérifie."
            ariaLabel="Aide : complétude déclarative mensuelle"
          />
        </h4>
        <span className="matx-synthese muted">
          {STATUT_LABELS[s.statut_global] ?? s.statut_global}
          {s.nb_manquantes_total > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="matx-badge-cible">
                {s.nb_manquantes_total} période
                {s.nb_manquantes_total > 1 ? "s" : ""} sans
                déclaration saisie
              </strong>
            </>
          )}
        </span>
      </div>

      {s.statut_global === "sans_periode_echue" ? (
        <p className="empty-state">
          Aucune période mensuelle de l'exercice {etat.exercice} n'est
          encore échue au {etat.aujourd_hui} — rien à contrôler pour
          l'instant.
        </p>
      ) : (
        <table className="matx-table">
          <thead>
            <tr>
              <th scope="col">Impôt</th>
              <th scope="col">Statut</th>
              <th scope="col">Saisies / attendues</th>
              <th scope="col">Couverture</th>
              <th scope="col">Périodes manquantes</th>
            </tr>
          </thead>
          <tbody>
            {blocs.map((b) => (
              <tr key={b.impot}>
                <td className="matx-ref">{b.libelle}</td>
                <td>
                  {b.disponible
                    ? (STATUT_LABELS[b.statut] ?? b.statut)
                    : "Indisponible"}
                </td>
                <td className="matx-montant">
                  {b.nb_attendues - b.nb_manquantes} / {b.nb_attendues}
                </td>
                <td className="matx-montant">
                  {b.taux_couverture.replace(".", ",")} %
                </td>
                <td>
                  {b.nb_manquantes === 0 ? (
                    <span className="muted">—</span>
                  ) : (
                    condenserPeriodes(b.manquantes)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <details className="matx-detail">
        <summary>
          Références et périodes attendues ({s.nb_periodes_attendues}{" "}
          période{s.nb_periodes_attendues > 1 ? "s" : ""} échue
          {s.nb_periodes_attendues > 1 ? "s" : ""} au{" "}
          {etat.aujourd_hui})
        </summary>
        {blocs.map((b) => (
          <p key={b.impot} className="muted">
            <strong>{b.libelle}</strong> — saisies :{" "}
            {b.saisies.length > 0 ? b.saisies.join(", ") : "aucune"}
          </p>
        ))}
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

    </section>
  );
}
