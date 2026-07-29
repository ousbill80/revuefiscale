import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api";
import { AcomptesVue } from "./AcomptesVue";
import { ChargeFiscaleVue } from "./ChargeFiscaleVue";
import { CoherenceCaVue } from "./CoherenceCaVue";
import { CompletudeDeclarativeVue } from "./CompletudeDeclarativeVue";
import { ControlesFiscauxVue } from "./ControlesFiscauxVue";
import { DeficitsReportablesVue } from "./DeficitsReportablesVue";
import { DeductibiliteVue } from "./DeductibiliteVue";
import { EvolutionChargeFiscaleVue } from "./EvolutionChargeFiscaleVue";
import { PatenteVue } from "./PatenteVue";
import { RapprochementAcomptesVue } from "./RapprochementAcomptesVue";
import { RapprochementSalairesVue } from "./RapprochementSalairesVue";
import { RapprochementTvaVue } from "./RapprochementTvaVue";
import { ResultatFiscalVue } from "./ResultatFiscalVue";
import { RetenueHonorairesVue } from "./RetenueHonorairesVue";
import { RetenueLoyersVue } from "./RetenueLoyersVue";
import {
  compterAttentionTheme,
  type ThemeRevueId,
} from "./revueVoletsRegistry";

type NiveauxPanorama = Map<string, string>;

type ThemeDef = {
  id: ThemeRevueId;
  label: string;
  render: () => ReactNode;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
  /** Thème à ouvrir (depuis le panorama ou le fil conducteur). */
  themeDemande?: ThemeRevueId | null;
  /** Niveaux d'attention par clé volet (panorama). */
  niveauxPanorama?: NiveauxPanorama;
  onThemeChange?: (theme: ThemeRevueId | null) => void;
};

export function RevueVoletsFiscaux({
  missionId,
  jeton,
  estLecteur = false,
  themeDemande = null,
  niveauxPanorama: niveauxExternes,
  onThemeChange,
}: Props) {
  const [themeOuvert, setThemeOuvert] = useState<ThemeRevueId | null>(null);
  const [niveauxInternes, setNiveauxInternes] = useState<NiveauxPanorama>(
    new Map(),
  );

  useEffect(() => {
    if (niveauxExternes || !jeton || !missionId) return;
    let annule = false;
    void (async () => {
      try {
        const out = await api<{
          volets: Array<{ volet: string; niveau: string }>;
        }>(`/api/v1/missions/${missionId}/panorama-conformite`, { jeton });
        if (annule || !out?.volets) return;
        const m = new Map<string, string>();
        for (const v of out.volets) m.set(v.volet, v.niveau);
        setNiveauxInternes(m);
      } catch {
        /* badges optionnels */
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, missionId, niveauxExternes]);

  const niveauxPanorama = niveauxExternes ?? niveauxInternes;

  const themes: ThemeDef[] = useMemo(
    () => [
      {
        id: "tva",
        label: "TVA et déclarations",
        render: () => (
          <>
            <RapprochementTvaVue
              missionId={missionId}
              jeton={jeton}
              estLecteur={estLecteur}
            />
            <CompletudeDeclarativeVue missionId={missionId} jeton={jeton} />
            <CoherenceCaVue missionId={missionId} jeton={jeton} />
          </>
        ),
      },
      {
        id: "is",
        label: "Impôt sur les sociétés",
        render: () => (
          <>
            <AcomptesVue
              missionId={missionId}
              jeton={jeton}
              estLecteur={estLecteur}
            />
            <RapprochementAcomptesVue missionId={missionId} jeton={jeton} />
            <ResultatFiscalVue
              missionId={missionId}
              jeton={jeton}
              estLecteur={estLecteur}
            />
            <DeficitsReportablesVue missionId={missionId} jeton={jeton} />
            <DeductibiliteVue missionId={missionId} jeton={jeton} />
          </>
        ),
      },
      {
        id: "social",
        label: "Social et retenues",
        render: () => (
          <>
            <RapprochementSalairesVue
              missionId={missionId}
              jeton={jeton}
              estLecteur={estLecteur}
            />
            <RetenueLoyersVue missionId={missionId} jeton={jeton} />
            <RetenueHonorairesVue missionId={missionId} jeton={jeton} />
          </>
        ),
      },
      {
        id: "taxes_locales",
        label: "Taxes locales et charge fiscale",
        render: () => (
          <>
            <PatenteVue missionId={missionId} jeton={jeton} />
            <ChargeFiscaleVue missionId={missionId} jeton={jeton} />
            <EvolutionChargeFiscaleVue missionId={missionId} jeton={jeton} />
          </>
        ),
      },
      {
        id: "contentieux",
        label: "Contrôles et contentieux",
        render: () => (
          <ControlesFiscauxVue
            missionId={missionId}
            jeton={jeton}
            estLecteur={estLecteur}
          />
        ),
      },
    ],
    [missionId, jeton, estLecteur],
  );

  const ouvrirTheme = useCallback(
    (id: ThemeRevueId) => {
      setThemeOuvert(id);
      onThemeChange?.(id);
      requestAnimationFrame(() => {
        document
          .getElementById(`revue-volet-${id}`)
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    },
    [onThemeChange],
  );

  useEffect(() => {
    if (themeDemande) ouvrirTheme(themeDemande);
  }, [themeDemande, ouvrirTheme]);

  function onToggleTheme(id: ThemeRevueId, ouvert: boolean) {
    if (ouvert) {
      ouvrirTheme(id);
    } else if (themeOuvert === id) {
      setThemeOuvert(null);
      onThemeChange?.(null);
    }
  }

  return (
    <section
      id="revue-volets"
      className="revue-volets panel dense"
      aria-label="Vues fiscales de la revue"
    >
      <h4 className="revue-volets-titre">Vues fiscales</h4>
      <p className="revue-volets-intro muted">
        Ouvrez un thème pour charger les contrôles — un seul thème à la fois.
      </p>
      <div className="revue-volets-liste">
        {themes.map((t) => {
          const ouvert = themeOuvert === t.id;
          const attention =
            niveauxPanorama != null
              ? compterAttentionTheme(niveauxPanorama, t.id)
              : 0;
          return (
            <details
              key={t.id}
              id={`revue-volet-${t.id}`}
              className={`revue-volet-theme compte-details${ouvert ? " is-open" : ""}`}
              open={ouvert}
              onToggle={(e) => {
                const el = e.currentTarget;
                onToggleTheme(t.id, el.open);
              }}
            >
              <summary className="revue-volet-summary">
                <span>{t.label}</span>
                {attention > 0 ? (
                  <span className="revue-volet-badge warn">
                    {attention} à examiner
                  </span>
                ) : null}
              </summary>
              {ouvert ? (
                <div className="revue-volet-corps">{t.render()}</div>
              ) : null}
            </details>
          );
        })}
      </div>
    </section>
  );
}

export type { ThemeRevueId };
