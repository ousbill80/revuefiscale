/** Agent fiscal question/réponse — corpus juridique indexé, citations et
 * références d'articles. État purement client (aucune persistance serveur
 * des échanges au-delà de l'historique transmis à chaque requête) ; rendu
 * en onglet dédié du poste de travail mission, en plein cadre. */
import {
  useCallback,
  useEffect,
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

type HistoriqueEchange = {
  question: string;
  reponse: string;
};

type MessageChat = {
  id: number;
  question: string;
  reponse?: AgentQuestionOut;
  enCours: boolean;
  erreur?: string;
};

const NB_ECHANGES_HISTORIQUE = 6;

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
  const finMessages = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    finMessages.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const envoyer = useCallback(async () => {
    const question = valeur.trim();
    if (!question || envoiEnCours) return;
    compteurId.current += 1;
    const id = compteurId.current;
    const historique: HistoriqueEchange[] = messages
      .filter(
        (msg): msg is MessageChat & { reponse: AgentQuestionOut } =>
          !!msg.reponse &&
          (msg.reponse.statut === "repondu" ||
            msg.reponse.statut === "abstention"),
      )
      .slice(-NB_ECHANGES_HISTORIQUE)
      .map((msg) => ({ question: msg.question, reponse: msg.reponse.texte }));
    setMessages((m) => [...m, { id, question, enCours: true }]);
    setValeur("");
    setEnvoiEnCours(true);
    try {
      const reponse = await api<AgentQuestionOut>(
        `/api/v1/missions/${missionId}/agent/question`,
        { jeton, method: "POST", json: { question, historique } },
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
  }, [valeur, envoiEnCours, jeton, missionId, messages]);

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
    <div className="panel dense agent-chat-panel">
      <h2 className="section-title agent-chat-title">
        Assistant IA — agent fiscal
      </h2>
      <p className="picker-hint agent-chat-hint">
        Réponses sourcées sur le corpus juridique indexé, avec citations et
        références d&apos;articles — l&apos;agent s&apos;abstient lorsque
        aucune source fiable n&apos;est disponible.
      </p>
      <div className="agent-chat-scroll">
        {messages.length === 0 ? (
          <p className="empty-state agent-chat-vide">
            Posez une question fiscale à l&apos;agent pour commencer.
          </p>
        ) : (
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
        <div ref={finMessages} />
      </div>
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
    </div>
  );
}
