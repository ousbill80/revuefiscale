import { useCallback, useEffect, useState } from "react";
import { api, fmtMontant } from "./api";
import { InfoTip } from "./Tooltip";

/** Suivi des contrôles fiscaux et contentieux — vue consultative.
 *
 * Le fiscaliste consigne les événements de procédure (avis de
 * vérification, notification de redressement, mise en demeure,
 * réclamation contentieuse…) avec date, montant en jeu éventuel et
 * commentaire. Les délais de riposte du LPF ivoirien sont calculés
 * côté serveur (déterministe) et les échéances proches ou dépassées
 * sont signalées — rien n'est automatique, l'humain décide.
 */
type DelaiRiposte = {
  duree: string | null;
  echeance: string | null;
  objet: string;
  reference: string;
};

type EcheanceEtat = {
  statut: string;
  jours_restants: number | null;
};

type EvenementControle = {
  id: number | null;
  type_evenement: string;
  libelle: string;
  date_evenement: string;
  montant_en_jeu: string | null;
  commentaire: string;
  delai_riposte: DelaiRiposte;
  echeance: EcheanceEtat;
};

type TypeEvenement = {
  type_evenement: string;
  libelle: string;
  delai: string | null;
  objet_delai: string;
  reference: string;
};

type ControlesFiscauxOut = {
  mission_id: number;
  exercice: number;
  aujourd_hui: string;
  evenements: EvenementControle[];
  synthese: {
    statut: string;
    nb_evenements: number;
    nb_echeances_proches: number;
    nb_echeances_depassees: number;
    montant_total_en_jeu: string;
    dernier_evenement: {
      type_evenement: string;
      libelle: string;
      date_evenement: string;
    } | null;
  };
  types_evenement: TypeEvenement[];
  note: string;
};

type Props = {
  missionId: number;
  jeton?: string | null;
  estLecteur?: boolean;
};

function badgeEcheance(e: EcheanceEtat): {
  classe: string;
  texte: string;
} | null {
  if (e.statut === "depassee") {
    return {
      classe: "cfx-badge cfx-badge-depassee",
      texte: `Dépassée de ${Math.abs(e.jours_restants ?? 0)} j`,
    };
  }
  if (e.statut === "proche") {
    return {
      classe: "cfx-badge cfx-badge-proche",
      texte: `J-${e.jours_restants ?? 0}`,
    };
  }
  if (e.statut === "a_venir") {
    return {
      classe: "cfx-badge cfx-badge-avenir",
      texte: `Dans ${e.jours_restants ?? 0} j`,
    };
  }
  return null;
}

export function ControlesFiscauxVue({ missionId, jeton, estLecteur }: Props) {
  const [etat, setEtat] = useState<ControlesFiscauxOut | null>(null);
  const [typeEvt, setTypeEvt] = useState("");
  const [dateEvt, setDateEvt] = useState("");
  const [montant, setMontant] = useState("");
  const [commentaire, setCommentaire] = useState("");
  const [msg, setMsg] = useState<{ texte: string; err: boolean } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    if (!jeton || !missionId) return;
    try {
      const out = await api<ControlesFiscauxOut>(
        `/api/v1/missions/${missionId}/controles`,
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

  const consigner = useCallback(async () => {
    if (!jeton || !missionId || !typeEvt || !dateEvt) return;
    setBusy(true);
    setMsg(null);
    try {
      await api(`/api/v1/missions/${missionId}/controles`, {
        method: "POST",
        jeton,
        json: {
          type_evenement: typeEvt,
          date_evenement: dateEvt,
          montant_en_jeu: montant || null,
          commentaire: commentaire || "",
        },
      });
      setTypeEvt("");
      setDateEvt("");
      setMontant("");
      setCommentaire("");
      setMsg({ texte: "Événement consigné.", err: false });
      await charger();
    } catch (e) {
      setMsg({
        texte: e instanceof Error ? e.message : "Consignation impossible.",
        err: true,
      });
    } finally {
      setBusy(false);
    }
  }, [jeton, missionId, typeEvt, dateEvt, montant, commentaire, charger]);

  if (!etat) return null;
  const s = etat.synthese;
  const specChoisie = etat.types_evenement.find(
    (t) => t.type_evenement === typeEvt,
  );
  return (
    <section
      className="cfx panel dense"
      aria-label="Contrôles fiscaux et contentieux"
    >
      <div className="cfx-head">
        <h4 className="cfx-titre label-with-tip">
          Contrôles fiscaux et contentieux
          <InfoTip
            label="Chronologie des actes de procédure consignés (avis de vérification, notification de redressement, mise en demeure, réclamation…). Les délais de riposte du LPF ivoirien sont calculés et les échéances proches ou dépassées signalées — vue consultative, l'humain décide."
            ariaLabel="Aide : contrôles fiscaux et contentieux"
          />
        </h4>
        <span className="cfx-synthese muted">
          {s.nb_evenements} événement{s.nb_evenements > 1 ? "s" : ""}
          {s.montant_total_en_jeu !== "0" && (
            <> · {fmtMontant(s.montant_total_en_jeu)} FCFA en jeu</>
          )}
          {s.nb_echeances_proches > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="cfx-badge cfx-badge-proche">
                {s.nb_echeances_proches} échéance
                {s.nb_echeances_proches > 1 ? "s" : ""} proche
                {s.nb_echeances_proches > 1 ? "s" : ""}
              </strong>
            </>
          )}
          {s.nb_echeances_depassees > 0 && (
            <>
              {" "}
              ·{" "}
              <strong className="cfx-badge cfx-badge-depassee">
                {s.nb_echeances_depassees} échéance
                {s.nb_echeances_depassees > 1 ? "s" : ""} dépassée
                {s.nb_echeances_depassees > 1 ? "s" : ""}
              </strong>
            </>
          )}
        </span>
      </div>

      {!estLecteur && (
        <div className="cfx-saisie">
          <label className="cfx-champ">
            Acte de procédure
            <select
              value={typeEvt}
              onChange={(e) => setTypeEvt(e.target.value)}
              aria-label="Type d'acte de procédure"
            >
              <option value="">— Choisir —</option>
              {etat.types_evenement.map((t) => (
                <option key={t.type_evenement} value={t.type_evenement}>
                  {t.libelle}
                  {t.delai ? ` (riposte : ${t.delai})` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="cfx-champ">
            Date de l'acte
            <input
              type="date"
              value={dateEvt}
              onChange={(e) => setDateEvt(e.target.value)}
              aria-label="Date de l'acte (AAAA-MM-JJ)"
            />
          </label>
          <label className="cfx-champ">
            Montant en jeu (FCFA)
            <input
              type="number"
              min="0"
              step="1"
              value={montant}
              onChange={(e) => setMontant(e.target.value)}
              placeholder="Optionnel"
              aria-label="Montant en jeu (FCFA, optionnel)"
            />
          </label>
          <label className="cfx-champ cfx-champ-commentaire">
            Commentaire
            <input
              type="text"
              value={commentaire}
              onChange={(e) => setCommentaire(e.target.value)}
              placeholder="Ex. rappels TVA 2024, sursis demandé…"
              aria-label="Commentaire"
            />
          </label>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={busy || !typeEvt || !dateEvt}
            onClick={() => void consigner()}
          >
            Consigner l'événement
          </button>
        </div>
      )}
      {specChoisie && (
        <p className="cfx-aide muted">
          {specChoisie.objet_delai} ({specChoisie.reference})
        </p>
      )}
      {msg && (
        <p className={`status${msg.err ? " err" : ""}`} role="status">
          {msg.texte}
        </p>
      )}

      {etat.evenements.length > 0 ? (
        <table className="cfx-table">
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Acte</th>
              <th scope="col">Montant en jeu</th>
              <th scope="col">Riposte (LPF)</th>
              <th scope="col">Échéance</th>
            </tr>
          </thead>
          <tbody>
            {etat.evenements.map((e) => {
              const badge = badgeEcheance(e.echeance);
              return (
                <tr key={e.id ?? `${e.type_evenement}-${e.date_evenement}`}>
                  <td className="cfx-date">{e.date_evenement}</td>
                  <td>
                    <span className="cfx-acte">{e.libelle}</span>
                    {e.commentaire && (
                      <span className="cfx-commentaire muted">
                        {" "}
                        — {e.commentaire}
                      </span>
                    )}
                  </td>
                  <td className="cfx-montant">
                    {e.montant_en_jeu !== null
                      ? fmtMontant(e.montant_en_jeu)
                      : "—"}
                  </td>
                  <td className="cfx-riposte">
                    {e.delai_riposte.duree ? (
                      <>
                        {e.delai_riposte.duree}{" "}
                        <span className="muted">
                          ({e.delai_riposte.reference})
                        </span>
                      </>
                    ) : (
                      <span className="muted">Sans délai</span>
                    )}
                  </td>
                  <td className="cfx-date">
                    {e.delai_riposte.echeance ?? "—"}
                    {badge && (
                      <span className={badge.classe}> {badge.texte}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="empty-state">
          Aucun événement de procédure consigné — consignez le premier
          acte reçu ou envoyé (avis de vérification, notification…)
          pour suivre les délais de riposte.
        </p>
      )}

    </section>
  );
}
