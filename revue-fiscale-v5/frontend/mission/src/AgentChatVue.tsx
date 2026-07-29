/** Agent fiscal question/réponse — corpus juridique indexé, citations et
 * références d'articles. État purement client (aucune persistance serveur
 * des échanges) ; accessible en panneau repliable depuis le poste de
 * travail mission, quel que soit l'onglet actif. */
import {
  useCallback,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { api, ApiError } from "./api";
import { TexteJuridique } from "./TexteJuridique";

type StatutReponse = "repondu" | "abstention" | "rejete";

type AgentQuestionOut = {
  statut: StatutReponse;
  texte: string;
  references: string[];
  citations: string[];
  contexte: string;
};

type MessageChat = {
  id: number;
  question: string;
  reponse?: AgentQuestionOut;
  enCours: boolean;
  erreur?: string;
};

const BANDEAU_STATUT: Partial<Record<StatutReponse, string>> = {
  abstention:
    "L'agent n'a pas trouvé de source fiable dans le corpus indexé pour répondre avec certitude — vérifiez auprès d'une source à jour.",
  rejete:
    "Cette question a été écartée par l'agent (hors périmètre ou non traitable en l'état).",
};

type Props = {
  jeton: string;
  missionId: number;
};

export function AgentChatVue({ jeton, missionId }: Props) {
  const [messages, setMessages] = useState<MessageChat[]>([]);
  const [valeur, setValeur] = useState("");
  const [envoiEnCours, setEnvoiEnCours] = useState(false);
  const compteurId = useRef(0);

  const envoyer = useCallback(async () => {
    const question = valeur.trim();
    if (!question || envoiEnCours) return;
    compteurId.current += 1;
    const id = compteurId.current;
    setMessages((m) => [...m, { id, question, enCours: true }]);
    setValeur("");
    setEnvoiEnCours(true);
    try {
      const reponse = await api<AgentQuestionOut>(
        `/api/v1/missions/${missionId}/agent/question`,
        { jeton, method: "POST", json: { question } },
      );
      setMessages((m) =>
        m.map((msg) =>
          msg.id === id ? { ...msg, reponse, enCours: false } : msg,
        ),
      );
    } catch (e) {
      const erreur =
        e instanceof ApiError
          ? e.message
          : "L'agent est momentanément indisponible — réessayez.";
      setMessages((m) =>
        m.map((msg) =>
          msg.id === id ? { ...msg, enCours: false, erreur } : msg,
        ),
      );
    } finally {
      setEnvoiEnCours(false);
    }
  }, [valeur, envoiEnCours, jeton, missionId]);

  function surSoumission(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void envoyer();
  }

  function surClavier(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void envoyer();
    }
  }

  return (
    <details className="panel dense compte-details agent-chat-panel">
      <summary>Agent fiscal — questions au corpus juridique</summary>
      <p className="picker-hint agent-chat-hint">
        Réponses sourcées sur le corpus juridique indexé, avec citations et
        références d&apos;articles — l&apos;agent s&apos;abstient lorsque
        aucune source fiable n&apos;est disponible.
      </p>
      {messages.length > 0 && (
        <ol className="agent-chat-messages">
          {messages.map((msg) => (
            <li key={msg.id} className="agent-chat-message">
              <p className="agent-chat-question">{msg.question}</p>
              {msg.enCours && (
                <p className="muted agent-chat-attente">
                  L&apos;agent recherche une réponse…
                </p>
              )}
              {msg.erreur && <p className="status err">{msg.erreur}</p>}
              {msg.reponse && (
                <div
                  className={`agent-chat-reponse${
                    msg.reponse.statut !== "repondu"
                      ? " agent-chat-reponse-hors-norme"
                      : ""
                  }`}
                >
                  {BANDEAU_STATUT[msg.reponse.statut] && (
                    <p className="agent-chat-bandeau">
                      {BANDEAU_STATUT[msg.reponse.statut]}
                    </p>
                  )}
                  {msg.reponse.texte && (
                    <p className="agent-chat-reponse-texte">
                      <TexteJuridique texte={msg.reponse.texte} />
                    </p>
                  )}
                  {msg.reponse.references.length > 0 && (
                    <ul className="agent-chat-references">
                      {msg.reponse.references.map((ref, i) => (
                        <li key={`${msg.id}-ref-${i}`}>{ref}</li>
                      ))}
                    </ul>
                  )}
                  {msg.reponse.contexte && (
                    <p className="agent-chat-contexte muted">
                      {msg.reponse.contexte}
                    </p>
                  )}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
      <form className="agent-chat-form" onSubmit={surSoumission}>
        <textarea
          className="agent-chat-textarea"
          rows={2}
          maxLength={2000}
          placeholder="Poser une question fiscale à l'agent (ex. « Quel est le régime de TVA applicable à… »)"
          aria-label="Question à l'agent fiscal"
          value={valeur}
          onChange={(e) => setValeur(e.target.value)}
          onKeyDown={surClavier}
          disabled={envoiEnCours}
        />
        <button
          type="submit"
          className="btn btn-primary btn-sm"
          disabled={envoiEnCours || !valeur.trim()}
        >
          {envoiEnCours ? "Envoi…" : "Envoyer"}
        </button>
      </form>
    </details>
  );
}
