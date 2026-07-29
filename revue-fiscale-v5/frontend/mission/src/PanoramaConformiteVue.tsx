import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { InfoTip } from "./Tooltip";

/** Panorama consultatif de conformité de la mission.
 *
 * Bandeau compact qui agrège les STATUTS (jamais les montants) déjà
 * produits par les vues fiscales consultatives ci-dessous, classés en
 * niveaux d'attention (à examiner, à qualifier, à suivre, sans
 * signal, indisponible). Aucun score, aucun cumul pondéré : le
 * panorama oriente la lecture, il ne conclut rien — chaque volet
 * s'apprécie dans sa vue détaillée, l'humain décide.
 */
type VoletPanorama = {
  volet: string;
  libelle: string;
  disponible: boolean;
  statut_source: string | null;
  niveau: string;
};

type PanoramaConformiteOut = {
  mission_id: number;
  exercice: number | null;
  disponible: boolean;
  volets: VoletPanorama[];
  compteurs: Record<string, number>;
  volets_en_echec: string[];
  nb_volets_suivis: number;
  nb_volets_disponibles: number;
  libelles_niveaux: Record<string, string>;
  note: string;
};

/** Libellés courts des niveaux — formulations non accusatoires. */
const NIVEAUX_ORDRE = [
  "a_examiner",
  "a_qualifier",
  "a_suivre",
  "sans_signal",
  "indisponible",
] as const;

const LIBELLES_COURTS: Record<string, string> = {
  a_examiner: "à examiner",
  a_qualifier: "à qualifier",
  a_suivre: "à suivre",
  sans_signal: "sans signal",
  indisponible: "indisponible",
};

import { themePourVolet, type ThemeRevueId } from "./revueVoletsRegistry";

type Props = {
  missionId: number;
  jeton?: string | null;
  onOuvrirTheme?: (theme: ThemeRevueId) => void;
  onOuvrirVolet?: (volet: string) => void;
};

export function PanoramaConformiteVue({
  missionId,
  jeton,
  onOuvrirTheme,
  onOuvrirVolet,
}: Props) {
  const [etat, setEtat] = useState<PanoramaConformiteOut | null>(null);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<PanoramaConformiteOut>(
        `/api/v1/missions/${missionId}/panorama-conformite`,
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
      aria-label="Panorama de conformité de la mission"
    >
      <div className="matx-head">
        <h4 className="matx-titre label-with-tip">
          Panorama de conformité
          <InfoTip
            label="Agrégat consultatif des statuts déjà produits par les vues fiscales ci-dessous, classés en niveaux d'attention — aucun score, aucun montant repris. Le panorama oriente la lecture, il ne conclut rien : chaque volet s'apprécie dans sa vue détaillée, l'humain décide."
            ariaLabel="Aide : panorama de conformité de la mission"
          />
        </h4>
        <span className="matx-synthese muted">
          {etat.disponible ? (
            NIVEAUX_ORDRE.filter(
              (n) => (etat.compteurs[n] ?? 0) > 0,
            ).map((n, i) => (
              <span key={n}>
                {i > 0 ? " · " : null}
                {n === "a_examiner" || n === "a_qualifier" ? (
                  <strong className="matx-badge-cible">
                    {etat.compteurs[n]} {LIBELLES_COURTS[n]}
                  </strong>
                ) : (
                  <>
                    {etat.compteurs[n]} {LIBELLES_COURTS[n]}
                  </>
                )}
              </span>
            ))
          ) : (
            <>Aucun volet disponible pour le moment</>
          )}
        </span>
      </div>

      {!etat.disponible ? (
        <p className="empty-state">
          Panorama indisponible : importez la balance et alimentez les
          vues fiscales pour orienter la lecture.
        </p>
      ) : (
        <table className="matx-table">
          <thead>
            <tr>
              <th scope="col">Volet</th>
              <th scope="col">Statut de la vue</th>
              <th scope="col">Niveau d'attention</th>
            </tr>
          </thead>
          <tbody>
            {etat.volets.map((v) => {
              const theme = themePourVolet(v.volet);
              const cliquable =
                Boolean(onOuvrirVolet || (theme && onOuvrirTheme));
              return (
              <tr
                key={v.volet}
                className={cliquable ? "matx-tr-cliquable" : undefined}
                onClick={
                  cliquable
                    ? () => {
                        if (onOuvrirVolet) onOuvrirVolet(v.volet);
                        else if (theme && onOuvrirTheme) onOuvrirTheme(theme);
                      }
                    : undefined
                }
                onKeyDown={
                  cliquable
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          if (onOuvrirVolet) onOuvrirVolet(v.volet);
                          else if (theme && onOuvrirTheme) onOuvrirTheme(theme);
                        }
                      }
                    : undefined
                }
                tabIndex={cliquable ? 0 : undefined}
                role={cliquable ? "link" : undefined}
              >
                <td className="matx-ref">{v.libelle}</td>
                <td className="muted">
                  {v.statut_source
                    ? v.statut_source.replace(/_/g, " ")
                    : "—"}
                </td>
                <td>
                  {v.niveau === "a_examiner" ||
                  v.niveau === "a_qualifier" ? (
                    <strong className="matx-badge-cible">
                      {LIBELLES_COURTS[v.niveau] ?? v.niveau}
                    </strong>
                  ) : (
                    <span className="muted">
                      {LIBELLES_COURTS[v.niveau] ?? v.niveau}
                    </span>
                  )}
                  {etat.volets_en_echec.includes(v.volet) ? (
                    <InfoTip
                      label="Ce volet n'a pas pu être servi (module en échec ou données absentes) — il reste consultable depuis sa vue détaillée."
                      ariaLabel={`Aide : volet ${v.libelle} indisponible`}
                    />
                  ) : null}
                </td>
              </tr>
            );
            })}
          </tbody>
        </table>
      )}

    </section>
  );
}
