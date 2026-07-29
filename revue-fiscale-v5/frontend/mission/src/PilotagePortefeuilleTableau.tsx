import { useMemo, useState } from "react";
import { fmtMontant } from "./api";

/** Sous-ensemble de GET /api/v1/pilotage — lignes aplaties pour le tableau filtrable. */
export type PilotagePortefeuilleData = {
  exposition_par_client: Array<{
    contribuable_id: number;
    denomination: string;
    exposition_ouverte: string;
    nb_risques_ouverts: number;
    score: number;
    niveau: string;
  }>;
  missions_a_cloturer: Array<{
    mission_id: number;
    contribuable_id: number;
    denomination: string;
    exercice: number;
    jours_inactivite: number;
  }>;
  alertes_source: Array<{
    mission_id: number;
    contribuable_id: number;
    denomination: string;
    exercice: number;
    codes_alerte: string[];
  }>;
  risques_en_retard: {
    total: number;
    top: Array<{
      risque_id: number;
      contribuable_id: number;
      denomination: string;
      libelle: string;
      montant_estime: string;
      echeance: string | null;
    }>;
  };
  echeances_portefeuille: {
    total: number;
    lignes: Array<{
      contribuable_id: number;
      denomination: string;
      code: string;
      libelle: string;
      date_limite: string;
      statut: string;
    }>;
  };
  relances_circularisation: {
    missions: Array<{
      mission_id: number;
      client: string;
      exercice: number;
      en_attente: number;
      recu: number;
      a_relancer: number;
      plus_ancienne_attente: string | null;
    }>;
  };
};

type Categorie =
  | "exposition"
  | "inactive"
  | "source"
  | "retard"
  | "echeance"
  | "relance";

type LignePilotage = {
  id: string;
  categorie: Categorie;
  client: string;
  detail: string;
  metrique: string;
  badge?: { label: string; cls: string };
  contribuableId?: number;
  missionId?: number;
};

const CATEGORIES: Array<{ id: Categorie | ""; label: string }> = [
  { id: "", label: "Toutes" },
  { id: "exposition", label: "Exposition" },
  { id: "inactive", label: "Inactives" },
  { id: "source", label: "Sources" },
  { id: "retard", label: "Retards" },
  { id: "echeance", label: "Échéances" },
  { id: "relance", label: "Relances" },
];

const LIBELLE_CATEGORIE: Record<Categorie, string> = {
  exposition: "Exposition",
  inactive: "Inactive >30 j",
  source: "Source",
  retard: "Retard",
  echeance: "Échéance",
  relance: "Relance",
};

function fmtDateFr(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

function aplatir(pilotage: PilotagePortefeuilleData): LignePilotage[] {
  const lignes: LignePilotage[] = [];

  for (const e of pilotage.exposition_par_client) {
    lignes.push({
      id: `expo-${e.contribuable_id}`,
      categorie: "exposition",
      client: e.denomination,
      detail: `${e.nb_risques_ouverts} risque${e.nb_risques_ouverts !== 1 ? "s" : ""} · score ${e.score} · ${e.niveau}`,
      metrique: `${fmtMontant(e.exposition_ouverte)} FCFA`,
      contribuableId: e.contribuable_id,
    });
  }

  for (const m of pilotage.missions_a_cloturer) {
    lignes.push({
      id: `inact-${m.mission_id}`,
      categorie: "inactive",
      client: m.denomination,
      detail: `Exercice ${m.exercice}`,
      metrique: `${m.jours_inactivite} j d'inactivité`,
      badge: { label: "Inactive", cls: "relance" },
      contribuableId: m.contribuable_id,
      missionId: m.mission_id,
    });
  }

  for (const a of pilotage.alertes_source) {
    lignes.push({
      id: `src-${a.mission_id}`,
      categorie: "source",
      client: a.denomination,
      detail: `Exercice ${a.exercice} · ${a.codes_alerte.join(", ")}`,
      metrique: a.codes_alerte.length
        ? `${a.codes_alerte.length} code${a.codes_alerte.length !== 1 ? "s" : ""}`
        : "—",
      badge: { label: "Source", cls: "relance" },
      contribuableId: a.contribuable_id,
      missionId: a.mission_id,
    });
  }

  for (const r of pilotage.risques_en_retard.top) {
    lignes.push({
      id: `ret-${r.risque_id}`,
      categorie: "retard",
      client: r.denomination,
      detail: r.echeance
        ? `${r.libelle} · éch. ${fmtDateFr(r.echeance)}`
        : r.libelle,
      metrique: `${fmtMontant(r.montant_estime)} FCFA`,
      badge: { label: "Retard", cls: "depasse" },
      contribuableId: r.contribuable_id,
    });
  }

  for (const e of pilotage.echeances_portefeuille.lignes) {
    const depasse = e.statut === "depassee";
    lignes.push({
      id: `ech-${e.contribuable_id}-${e.code}-${e.date_limite}`,
      categorie: "echeance",
      client: e.denomination,
      detail: `${e.libelle} · ${fmtDateFr(e.date_limite)}`,
      metrique: depasse ? "Dépassé" : "Imminent",
      badge: {
        label: depasse ? "Dépassé" : "Imminent",
        cls: depasse ? "depasse" : "imminent",
      },
      contribuableId: e.contribuable_id,
    });
  }

  for (const m of pilotage.relances_circularisation.missions) {
    lignes.push({
      id: `rel-${m.mission_id}`,
      categorie: "relance",
      client: m.client,
      detail: [
        `Ex. ${m.exercice}`,
        `${m.en_attente} en attente`,
        `${m.recu} reçu(s)`,
        m.plus_ancienne_attente
          ? `depuis ${fmtDateFr(m.plus_ancienne_attente)}`
          : null,
      ]
        .filter(Boolean)
        .join(" · "),
      metrique:
        m.a_relancer > 0
          ? `${m.a_relancer} à relancer`
          : `${m.en_attente} en attente`,
      badge:
        m.a_relancer > 0
          ? { label: `${m.a_relancer} à relancer`, cls: "relance" }
          : { label: "En attente", cls: "attente" },
      missionId: m.mission_id,
    });
  }

  return lignes;
}

type Props = {
  pilotage: PilotagePortefeuilleData;
  onOuvrirClient: (contribuableId: number) => void;
  onOuvrirMission: (missionId: number) => void;
};

export function PilotagePortefeuilleTableau({
  pilotage,
  onOuvrirClient,
  onOuvrirMission,
}: Props) {
  const [categorie, setCategorie] = useState<Categorie | "">("");
  const [recherche, setRecherche] = useState("");

  const toutes = useMemo(() => aplatir(pilotage), [pilotage]);

  const compteurs = useMemo(() => {
    const c: Record<Categorie | "", number> = {
      "": toutes.length,
      exposition: 0,
      inactive: 0,
      source: 0,
      retard: 0,
      echeance: 0,
      relance: 0,
    };
    for (const l of toutes) c[l.categorie] += 1;
    return c;
  }, [toutes]);

  const filtrees = useMemo(() => {
    const q = recherche.trim().toLocaleLowerCase("fr");
    return toutes.filter((l) => {
      if (categorie && l.categorie !== categorie) return false;
      if (!q) return true;
      return (
        l.client.toLocaleLowerCase("fr").includes(q) ||
        l.detail.toLocaleLowerCase("fr").includes(q) ||
        LIBELLE_CATEGORIE[l.categorie].toLocaleLowerCase("fr").includes(q)
      );
    });
  }, [toutes, categorie, recherche]);

  function ouvrirLigne(l: LignePilotage) {
    if (l.missionId != null) {
      onOuvrirMission(l.missionId);
      return;
    }
    if (l.contribuableId != null) onOuvrirClient(l.contribuableId);
  }

  return (
    <article
      className="panel dense pilotage-card pilotage-tableau"
      aria-label="Tableau filtrable du pilotage"
    >
      <div className="pilotage-tableau-head">
        <p className="pilotage-tableau-resume">
          <strong>{filtrees.length}</strong>
          {filtrees.length !== toutes.length
            ? ` signal${filtrees.length !== 1 ? "s" : ""} affiché${filtrees.length !== 1 ? "s" : ""} sur ${toutes.length}`
            : ` signal${toutes.length !== 1 ? "s" : ""}`}
        </p>
        <label className="pilotage-tableau-recherche">
          <span className="pilotage-tableau-recherche-lbl">Rechercher</span>
          <input
            type="search"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
            placeholder="Client ou détail…"
            autoComplete="off"
            aria-label="Filtrer par client ou détail"
          />
        </label>
      </div>

      <div
        className="pilotage-tableau-filtres"
        role="group"
        aria-label="Filtrer par type de signal"
      >
        {CATEGORIES.map(({ id, label }) => (
          <button
            key={id || "toutes"}
            type="button"
            className={`pilotage-tableau-filtre${categorie === id ? " is-active" : ""}`}
            aria-pressed={categorie === id}
            onClick={() => setCategorie(id)}
          >
            {label}
            <strong>{compteurs[id]}</strong>
          </button>
        ))}
      </div>

      <div className="missions-table-wrap">
        <table className="missions-table supervision-table pilotage-tableau-table">
          <thead className="missions-thead">
            <tr>
              <th>Client</th>
              <th>Type</th>
              <th>Détail</th>
              <th>Enjeu</th>
              <th>Statut</th>
            </tr>
          </thead>
          <tbody>
            {filtrees.map((l) => (
              <tr
                key={l.id}
                className="missions-tr"
                onClick={() => ouvrirLigne(l)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    ouvrirLigne(l);
                  }
                }}
                tabIndex={0}
                role="link"
                aria-label={`Ouvrir ${l.client} — ${LIBELLE_CATEGORIE[l.categorie]}`}
              >
                <td>{l.client}</td>
                <td>
                  <span className="pilotage-tableau-type">
                    {LIBELLE_CATEGORIE[l.categorie]}
                  </span>
                </td>
                <td className="pilotage-tableau-detail">{l.detail}</td>
                <td className="pilotage-tableau-metrique">{l.metrique}</td>
                <td>
                  {l.badge ? (
                    <span className={`pilotage-badge ${l.badge.cls}`}>
                      {l.badge.label}
                    </span>
                  ) : (
                    <span className="pilotage-badge ok">Suivi</span>
                  )}
                </td>
              </tr>
            ))}
            {!filtrees.length && (
              <tr>
                <td colSpan={5} className="pilotage-vide">
                  {toutes.length === 0
                    ? "Aucun signal au portefeuille pour le moment."
                    : "Aucun signal ne correspond au filtre."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </article>
  );
}
