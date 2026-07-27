import { useEffect, useMemo, useState } from "react";
import { api } from "./api";

/** Relances à faire du cabinet (GET /api/v1/cabinet/relances). */
type ItemRelance = {
  mission_id: number;
  client: string;
  exercice: number;
  libelle: string;
  date_relance: string;
  note: string | null;
};

type RelancesCabinetOut = {
  aujourd_hui: string;
  total: number;
  synthese: {
    total: number;
    clients: number;
    plus_ancienne: string | null;
  };
  items: ItemRelance[];
  note: string;
};

/** Date ISO (aaaa-mm-jj) → jj/mm/aaaa ; valeur inattendue renvoyée telle quelle. */
function fmtDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso || "—";
}

/** Groupe les items par date de relance en conservant l'ordre trié du backend. */
function grouperParDate(
  items: ItemRelance[],
): Array<{ date: string; lignes: ItemRelance[] }> {
  const groupes: Array<{ date: string; lignes: ItemRelance[] }> = [];
  const index = new Map<string, number>();
  for (const it of items) {
    const i = index.get(it.date_relance);
    if (i === undefined) {
      index.set(it.date_relance, groupes.length);
      groupes.push({ date: it.date_relance, lignes: [it] });
    } else {
      groupes[i].lignes.push(it);
    }
  }
  return groupes;
}

type Props = {
  jeton?: string | null;
  onOuvrirMission: (missionId: number) => void;
};

export function RelancesCabinetVue({ jeton, onOuvrirMission }: Props) {
  const [relances, setRelances] = useState<RelancesCabinetOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!jeton) return;
    let annule = false;
    setBusy(true);
    setErr(null);
    void (async () => {
      try {
        const out = await api<RelancesCabinetOut>("/api/v1/cabinet/relances", {
          jeton,
        });
        if (!annule) setRelances(out ?? null);
      } catch {
        if (!annule) {
          setRelances(null);
          setErr("Relances indisponibles pour le moment.");
        }
      } finally {
        if (!annule) setBusy(false);
      }
    })();
    return () => {
      annule = true;
    };
  }, [jeton]);

  const groupes = useMemo(
    () => grouperParDate(relances?.items ?? []),
    [relances],
  );

  return (
    <section className="relances2-zone" aria-label="Relances à faire">
      <div className="relances2-head">
        <div>
          <h3 className="relances2-title">Relances à faire</h3>
          <p className="relances2-sub">
            Demandes de renseignements en attente dont la relance planifiée
            est échue, tous clients confondus.
          </p>
        </div>
      </div>

      <article className="panel dense relances2-card">
        {busy && !relances && (
          <p className="relances2-vide">Chargement des relances…</p>
        )}
        {err && !busy && <p className="relances2-err">{err}</p>}

        {relances && (
          <>
            <div className="relances2-synthese">
              <span
                className={`relances2-chip${
                  relances.synthese.total > 0 ? " alerte" : ""
                }`}
              >
                <strong>{relances.synthese.total}</strong> relance
                {relances.synthese.total > 1 ? "s" : ""}
              </span>
              <span className="relances2-chip">
                <strong>{relances.synthese.clients}</strong> client
                {relances.synthese.clients > 1 ? "s" : ""}
              </span>
              {relances.synthese.plus_ancienne && (
                <span className="relances2-chip ancienne">
                  Plus ancienne : {fmtDate(relances.synthese.plus_ancienne)}
                </span>
              )}
            </div>

            {!relances.items.length && (
              <p className="relances2-vide">Aucune relance à faire.</p>
            )}

            {groupes.map((g) => (
              <div key={g.date} className="relances2-groupe">
                <p className="relances2-date">{fmtDate(g.date)}</p>
                <ul className="relances2-liste">
                  {g.lignes.map((it, i) => (
                    <li key={`${g.date}-${it.mission_id}-${i}`}>
                      <button
                        type="button"
                        className="relances2-row"
                        title={`Ouvrir la mission #${it.mission_id} · ${it.client}`}
                        onClick={() => onOuvrirMission(it.mission_id)}
                      >
                        <span className="relances2-libelle">{it.libelle}</span>
                        <span className="relances2-meta">
                          {it.client} · exercice {it.exercice}
                          {it.note ? ` · ${it.note}` : ""}
                        </span>
                        <span className="relances2-badge">À relancer</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}

            {relances.note && <p className="relances2-note">{relances.note}</p>}
          </>
        )}
      </article>
    </section>
  );
}
