import { useEffect, useState } from "react";
import { api } from "./api";

/** Journal d'activité du cabinet (GET /api/v1/cabinet/journal). */
type EntreeJournal = {
  horodatage: string;
  acteur: string;
  action: string;
  libelle_action: string;
  mission_id: number | null;
  details: Record<string, string | number | boolean | null>;
};

type JournalOut = {
  total: number;
  page: number;
  taille: number;
  entrees: EntreeJournal[];
  filtres: { action: string | null; acteur: string | null };
  note: string;
};

type Props = {
  jeton?: string | null;
};

/** ISO « 2026-07-28T14:05:00+00:00 » → « 28/07/2026 14:05 ». */
function dateHeureFr(iso: string): string {
  const [datePart, timePart] = iso.split("T");
  if (!datePart) return iso;
  const [a, m, j] = datePart.split("-");
  const jour = a && m && j ? `${j}/${m}/${a}` : datePart;
  const heure = timePart ? timePart.slice(0, 5) : "";
  return heure ? `${jour} ${heure}` : jour;
}

function detailsTexte(
  details: Record<string, string | number | boolean | null>,
): string {
  return Object.entries(details)
    .map(([cle, valeur]) => `${cle} : ${String(valeur ?? "—")}`)
    .join(" · ");
}

export function JournalCabinetVue({ jeton }: Props) {
  const [vue, setVue] = useState<JournalOut | null>(null);
  const [page, setPage] = useState(1);
  const [filtreAction, setFiltreAction] = useState("");
  const [filtreActeur, setFiltreActeur] = useState("");
  /** Filtres appliqués (au clic) — la saisie seule ne recharge pas. */
  const [applique, setApplique] = useState<{
    action: string;
    acteur: string;
  }>({ action: "", acteur: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const qs = new URLSearchParams({ page: String(page) });
        if (applique.action) qs.set("action", applique.action);
        if (applique.acteur) qs.set("acteur", applique.acteur);
        const out = await api<JournalOut>(
          `/api/v1/cabinet/journal?${qs}`,
          { jeton },
        );
        if (!annule) setVue(out ?? null);
      } catch {
        if (!annule) {
          setVue(null);
          setErr("Journal indisponible pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton, page, applique]);

  const nbPages = vue ? Math.max(1, Math.ceil(vue.total / vue.taille)) : 1;

  function appliquerFiltres() {
    setPage(1);
    setApplique({
      action: filtreAction.trim(),
      acteur: filtreActeur.trim(),
    });
  }

  function reinitialiserFiltres() {
    setFiltreAction("");
    setFiltreActeur("");
    setPage(1);
    setApplique({ action: "", acteur: "" });
  }

  return (
    <section className="ctrale-zone" aria-label="Journal d'activité du cabinet">
      <div className="ctrale-head">
        <div>
          <h3 className="ctrale-title">Journal d'activité du cabinet</h3>
          <p className="ctrale-sub">
            Trace chronologique des événements enregistrés par
            l'application — consultations, exécutions, documents produits —
            pour la traçabilité professionnelle des diligences du cabinet.
          </p>
        </div>
      </div>

      <article className="panel dense ctrale-card">
        <form
          className="ctrale-exports"
          onSubmit={(e) => {
            e.preventDefault();
            appliquerFiltres();
          }}
        >
          <label className="calcab-horizon">
            Action{" "}
            <input
              type="text"
              value={filtreAction}
              onChange={(e) => setFiltreAction(e.target.value)}
              placeholder="ex. creation_mission"
              disabled={busy}
            />
          </label>
          <label className="calcab-horizon">
            Acteur{" "}
            <input
              type="text"
              value={filtreActeur}
              onChange={(e) => setFiltreActeur(e.target.value)}
              placeholder="email du collaborateur"
              disabled={busy}
            />
          </label>
          <button type="submit" className="btn btn-ghost btn-sm" disabled={busy}>
            Filtrer
          </button>
          {(applique.action || applique.acteur) && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={reinitialiserFiltres}
              disabled={busy}
            >
              Tout afficher
            </button>
          )}
        </form>

        {busy && !vue && <p className="ctrale-vide">Chargement du journal…</p>}
        {err && !busy && <p className="ctrale-err">{err}</p>}

        {vue && (
          <>
            <div className="ctrale-synthese">
              <span className="ctrale-chip">
                <strong>{vue.total}</strong> entrée
                {vue.total > 1 ? "s" : ""}
              </span>
              <span className="ctrale-chip">
                page <strong>{vue.page}</strong> / {nbPages}
              </span>
            </div>

            {!vue.entrees.length && (
              <p className="ctrale-vide">
                Aucune entrée pour ces critères.
              </p>
            )}

            {vue.entrees.length > 0 && (
              <div className="equipe-table-wrap">
                <table
                  className="equipe-table"
                  aria-label="Entrées du journal d'activité"
                >
                  <thead className="equipe-thead">
                    <tr>
                      <th scope="col">Date</th>
                      <th scope="col">Acteur</th>
                      <th scope="col">Activité</th>
                      <th scope="col">Mission</th>
                      <th scope="col">Détails</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vue.entrees.map((e, idx) => (
                      <tr key={`${e.horodatage}-${idx}`}>
                        <td>{dateHeureFr(e.horodatage)}</td>
                        <td>{e.acteur}</td>
                        <td title={e.action}>{e.libelle_action}</td>
                        <td>
                          {e.mission_id !== null ? `#${e.mission_id}` : "—"}
                        </td>
                        <td>{detailsTexte(e.details) || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="ctrale-exports">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={busy || vue.page <= 1}
              >
                ← Page précédente
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={busy || vue.page >= nbPages}
              >
                Page suivante →
              </button>
            </div>

            {vue.note && <p className="ctrale-note">{vue.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
