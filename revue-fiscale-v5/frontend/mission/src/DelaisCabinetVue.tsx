import { useEffect, useState } from "react";
import { api } from "./api";

/** Délais moyens de traitement (GET /api/v1/cabinet/delais). */
type TransitionDelais = {
  de: string;
  a: string;
  libelle_de: string;
  libelle_a: string;
  moyenne_jours: string | null;
  nb_missions: number;
};

type DelaisCabinetOut = {
  transitions: TransitionDelais[];
  duree_totale_moyenne_jours: string | null;
  nb_missions: number;
  transition_la_plus_lente: TransitionDelais | null;
  note: string;
};

type Props = {
  jeton?: string | null;
};

/** « 6.5 » → « 6,5 j en moyenne » (affichage FR). */
function fmtJours(jours: string | null): string {
  return jours == null ? "—" : `${jours.replace(".", ",")} j en moyenne`;
}

export function DelaisCabinetVue({ jeton }: Props) {
  const [delais, setDelais] = useState<DelaisCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<DelaisCabinetOut>("/api/v1/cabinet/delais", {
          jeton,
        });
        if (!annule) setDelais(out ?? null);
      } catch {
        if (!annule) {
          setDelais(null);
          setErr("Délais moyens indisponibles pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton]);

  const plusLente = delais?.transition_la_plus_lente ?? null;

  return (
    <section
      className="delaiscab-zone"
      aria-label="Délais moyens de traitement"
    >
      <div className="delaiscab-head">
        <div>
          <h3 className="delaiscab-title">Délais moyens de traitement</h3>
          <p className="delaiscab-sub">
            Durée moyenne observée entre les étapes du processus de
            mission, d'après le journal d'audit.
          </p>
        </div>
      </div>

      <article className="panel dense delaiscab-card">
        {busy && !delais && (
          <p className="delaiscab-vide">Chargement des délais moyens…</p>
        )}
        {err && !busy && <p className="delaiscab-err">{err}</p>}

        {delais && (
          <>
            <div className="delaiscab-synthese">
              <span className="delaiscab-chip">
                <strong>{delais.nb_missions}</strong> mission
                {delais.nb_missions > 1 ? "s" : ""} examinée
                {delais.nb_missions > 1 ? "s" : ""}
              </span>
              <span className="delaiscab-chip">
                Durée totale moyenne :{" "}
                <strong>
                  {delais.duree_totale_moyenne_jours != null
                    ? `${delais.duree_totale_moyenne_jours.replace(".", ",")} j`
                    : "—"}
                </strong>
              </span>
            </div>

            {!delais.transitions.some((t) => t.nb_missions > 0) && (
              <p className="delaiscab-vide">
                Aucune transition observée pour le moment — les moyennes
                apparaîtront au fil des étapes journalisées.
              </p>
            )}

            <ul className="delaiscab-liste">
              {delais.transitions.map((t) => {
                const lente =
                  plusLente != null &&
                  plusLente.de === t.de &&
                  plusLente.a === t.a;
                return (
                  <li
                    key={`${t.de}-${t.a}`}
                    className={`delaiscab-row${lente ? " lente" : ""}`}
                  >
                    <span className="delaiscab-libelle">
                      {t.libelle_de} → {t.libelle_a}
                    </span>
                    <span className="delaiscab-meta">
                      {t.nb_missions} mission
                      {t.nb_missions > 1 ? "s" : ""} observée
                      {t.nb_missions > 1 ? "s" : ""}
                    </span>
                    <span
                      className={`delaiscab-badge${lente ? " lente" : ""}`}
                    >
                      {fmtJours(t.moyenne_jours)}
                      {lente ? " · la plus lente" : ""}
                    </span>
                  </li>
                );
              })}
            </ul>

            {delais.note && <p className="delaiscab-note">{delais.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
