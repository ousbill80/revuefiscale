import { useState, type FormEvent } from "react";
import { InfoTip } from "./Tooltip";
import { PROCESS_TIPS } from "./processTips";

export type EquipeUser = {
  id: number;
  email: string;
  role: string;
  actif: boolean;
};

export type EquipeInvitation = {
  id: number;
  email: string;
  role: string;
  statut: string;
};

export type EquipeInviteToken = {
  email: string;
  token: string;
  emailEnvoi?: {
    statut?: string;
    mode?: string | null;
    outbox_id?: number | null;
    note?: string;
  };
};

export type EquipeOutbox = {
  resend?: {
    resend_configure?: boolean;
    mode_sans_cle?: string | null;
    note?: string;
  };
  lignes?: Array<{
    id: number;
    destinataire: string;
    sujet: string;
    statut: string;
    dernier_erreur?: string | null;
    cree_le?: string;
  }>;
};

export type InviteRole = "lecteur" | "reviseur" | "admin";

type Props = {
  users: EquipeUser[];
  invitations: EquipeInvitation[];
  inviteEmail: string;
  inviteRole: InviteRole;
  busy: boolean;
  equipeMsg: { msg: string; err: boolean } | null;
  inviteToken: EquipeInviteToken | null;
  emailOutbox: EquipeOutbox | null;
  onInviteEmailChange: (v: string) => void;
  onInviteRoleChange: (v: InviteRole) => void;
  onInviter: (e?: FormEvent) => void;
  onCopierToken: () => void;
  onMasquerToken: () => void;
  onChangerRole: (userId: number, role: InviteRole) => void;
  onRevoquerInvitation: (invitationId: number) => void;
};

function tipRole(role: string): string {
  const r = role.toLowerCase();
  if (r === "admin") return PROCESS_TIPS.roleAdmin;
  if (r === "reviseur") return PROCESS_TIPS.roleReviseur;
  return PROCESS_TIPS.roleLecteur;
}

function libelleRole(role: string): string {
  const map: Record<string, string> = {
    lecteur: "Lecteur",
    reviseur: "Réviseur",
    admin: "Admin",
  };
  return map[role.toLowerCase()] ?? role;
}

function libelleStatutInvitation(statut: string): string {
  const map: Record<string, string> = {
    en_attente: "En attente",
    acceptee: "Acceptée",
    expiree: "Expirée",
    annulee: "Révoquée",
  };
  return map[statut.toLowerCase()] ?? statut;
}

function libelleStatutOutbox(statut: string): string {
  const map: Record<string, string> = {
    simule_dev: "Simulé (dev)",
    echec: "Échec",
    envoye: "Envoyé",
  };
  return map[statut.toLowerCase()] ?? statut;
}

function roleBadgeClass(role: string): string {
  const r = role.toLowerCase();
  if (r === "admin") return "equipe-badge role-admin";
  if (r === "reviseur") return "equipe-badge role-reviseur";
  return "equipe-badge role-lecteur";
}

function invitStatutClass(statut: string): string {
  const s = statut.toLowerCase();
  if (s === "acceptee") return "equipe-badge statut-acceptee";
  if (s === "expiree" || s === "annulee") return "equipe-badge statut-expiree";
  return "equipe-badge statut-en_attente";
}

function outboxChipClass(statut: string): string {
  const s = statut.toLowerCase();
  if (s === "envoye") return "equipe-outbox-chip envoye";
  if (s === "echec") return "equipe-outbox-chip echec";
  if (s === "simule_dev") return "equipe-outbox-chip simule";
  return "equipe-outbox-chip";
}

function formatDateCourte(iso?: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function EquipeVue({
  users,
  invitations,
  inviteEmail,
  inviteRole,
  busy,
  equipeMsg,
  inviteToken,
  emailOutbox,
  onInviteEmailChange,
  onInviteRoleChange,
  onInviter,
  onCopierToken,
  onMasquerToken,
  onChangerRole,
  onRevoquerInvitation,
}: Props) {
  const outboxLignes = emailOutbox?.lignes || [];
  const resendAbsent =
    !!emailOutbox?.resend && !emailOutbox.resend.resend_configure;
  const [outboxDetailId, setOutboxDetailId] = useState<number | null>(null);

  return (
    <div className="page equipe-vue">
      <header className="page-head equipe-head">
        <div>
          <p className="page-eyebrow">Administration</p>
          <h2 className="section-title">Équipe</h2>
          <p className="section-sub">
            Membres du cabinet, invitations et journal des e-mails (admin).
          </p>
        </div>
      </header>

      <section
        className="panel dense equipe-card"
        aria-labelledby="equipe-users-title"
      >
        <div className="equipe-card-head">
          <div>
            <h3 id="equipe-users-title" className="equipe-card-title">
              Utilisateurs
            </h3>
            <p className="equipe-card-hint">
              Comptes actifs et rôles dans l&apos;espace cabinet.
            </p>
          </div>
          <p className="equipe-count">
            {users.length} membre{users.length !== 1 ? "s" : ""}
          </p>
        </div>

        {users.length > 0 ? (
          <>
            <div className="equipe-table-wrap equipe-desktop-only">
              <table className="equipe-table" aria-label="Liste des utilisateurs">
                <thead className="equipe-thead">
                  <tr>
                    <th scope="col">E-mail</th>
                    <th scope="col">
                      <span className="label-with-tip">
                        Rôle
                        <InfoTip
                          label="Admin : équipe. Réviseur : missions. Lecteur : consultation."
                          ariaLabel="Aide : rôles"
                        />
                      </span>
                    </th>
                    <th scope="col">Statut</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.id} className="equipe-tr">
                      <td className="equipe-cell-email">
                        <span className="equipe-email">{u.email}</span>
                      </td>
                      <td className="label-with-tip">
                        <span className={roleBadgeClass(u.role)}>
                          {libelleRole(u.role)}
                        </span>
                        <InfoTip
                          label={tipRole(u.role)}
                          ariaLabel={`Aide rôle ${libelleRole(u.role)}`}
                        />
                      </td>
                      <td>
                        <span
                          className={`equipe-badge ${u.actif ? "statut-actif" : "statut-inactif"}`}
                        >
                          {u.actif ? "Actif" : "Inactif"}
                        </span>
                      </td>
                      <td>
                        <select
                          className="field-select equipe-role-select"
                          aria-label={`Changer le rôle de ${u.email}`}
                          value={u.role}
                          disabled={busy}
                          onChange={(e) =>
                            onChangerRole(u.id, e.target.value as InviteRole)
                          }
                        >
                          <option value="lecteur">Lecteur</option>
                          <option value="reviseur">Réviseur</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="equipe-cards equipe-mobile-only">
              {users.map((u) => (
                <li key={u.id} className="equipe-card-item">
                  <strong className="equipe-email">{u.email}</strong>
                  <span className={roleBadgeClass(u.role)}>
                    {libelleRole(u.role)}
                  </span>
                  <label className="equipe-mobile-role">
                    Rôle
                    <select
                      className="field-select"
                      value={u.role}
                      disabled={busy}
                      onChange={(e) =>
                        onChangerRole(u.id, e.target.value as InviteRole)
                      }
                    >
                      <option value="lecteur">Lecteur</option>
                      <option value="reviseur">Réviseur</option>
                      <option value="admin">Admin</option>
                    </select>
                  </label>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div className="equipe-empty">
            <p className="equipe-empty-title">Aucun utilisateur</p>
            <p className="equipe-empty-body">
              Les comptes du cabinet apparaîtront ici. Invitez un collègue
              ci-dessous pour démarrer.
            </p>
          </div>
        )}
      </section>

      <section
        className="panel dense equipe-card"
        aria-labelledby="equipe-invite-title"
      >
        <div className="equipe-card-head">
          <div>
            <h3 id="equipe-invite-title" className="equipe-card-title">
              Inviter un collègue
            </h3>
            <p className="equipe-card-hint">
              Envoi d&apos;une invitation — le jeton n&apos;est affiché
              qu&apos;une fois.
            </p>
          </div>
        </div>

        <form className="equipe-invite-form" onSubmit={onInviter}>
          <div className="equipe-invite-field">
            <label htmlFor="inv-email">Adresse e-mail</label>
            <input
              id="inv-email"
              type="email"
              autoComplete="email"
              placeholder="prenom.nom@cabinet.ci"
              value={inviteEmail}
              onChange={(e) => onInviteEmailChange(e.target.value)}
              required
            />
          </div>
          <div className="equipe-invite-field equipe-invite-role">
            <label htmlFor="inv-role" className="label-with-tip">
              Rôle
              <InfoTip
                label={`${PROCESS_TIPS.roleLecteur} ${PROCESS_TIPS.roleReviseur} ${PROCESS_TIPS.roleAdmin}`}
                ariaLabel="Aide : choix du rôle"
              />
            </label>
            <select
              id="inv-role"
              className="field-select"
              value={inviteRole}
              onChange={(e) =>
                onInviteRoleChange(e.target.value as InviteRole)
              }
            >
              <option value="lecteur">Lecteur</option>
              <option value="reviseur">Réviseur</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="equipe-invite-actions">
            <button
              type="submit"
              className="btn btn-primary equipe-invite-cta"
              disabled={busy}
            >
              Envoyer l&apos;invitation
            </button>
          </div>
        </form>

        {equipeMsg && (
          <p className={`status${equipeMsg.err ? " err" : ""}`}>
            {equipeMsg.msg}
          </p>
        )}

        {inviteToken && (
          <div
            className="token-box"
            role="region"
            aria-label="Jeton d'invitation"
          >
            <div className="token-box-head">
              <strong>Jeton (une fois)</strong>
              <span className="token-box-email">{inviteToken.email}</span>
            </div>
            {inviteToken.emailEnvoi && (
              <p className="token-hint equipe-token-envoi">
                Email :{" "}
                <span
                  className={outboxChipClass(
                    inviteToken.emailEnvoi.statut || "",
                  )}
                >
                  {libelleStatutOutbox(inviteToken.emailEnvoi.statut || "?")}
                </span>
                {inviteToken.emailEnvoi.mode
                  ? ` · mode ${inviteToken.emailEnvoi.mode}`
                  : ""}
                {inviteToken.emailEnvoi.outbox_id != null
                  ? ` · outbox #${inviteToken.emailEnvoi.outbox_id}`
                  : ""}
                {inviteToken.emailEnvoi.statut === "simule_dev"
                  ? " — RESEND_API_KEY absent, simulation locale."
                  : ""}
              </p>
            )}
            <code className="token-value" tabIndex={0}>
              {inviteToken.token}
            </code>
            <div className="cta-row equipe-token-cta">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void onCopierToken()}
              >
                Copier le jeton
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={onMasquerToken}
              >
                Masquer
              </button>
            </div>
            <p className="token-hint">
              L&apos;invité reçoit un e-mail avec un lien d&apos;acceptation.
              Le jeton ci-dessus sert de secours (lien{" "}
              <code>/app/?invitation=…</code>).
            </p>
          </div>
        )}
      </section>

      <section
        className="panel dense equipe-card"
        aria-labelledby="equipe-invitations-title"
      >
        <div className="equipe-card-head">
          <div>
            <h3 id="equipe-invitations-title" className="equipe-card-title">
              Invitations
            </h3>
            <p className="equipe-card-hint">
              Suivi des invitations envoyées et de leur acceptation.
            </p>
          </div>
          <p className="equipe-count">
            {invitations.length} invitation
            {invitations.length !== 1 ? "s" : ""}
          </p>
        </div>

        {invitations.length > 0 ? (
          <>
            <div className="equipe-table-wrap equipe-desktop-only">
              <table
                className="equipe-table"
                aria-label="Liste des invitations"
              >
                <thead className="equipe-thead">
                  <tr>
                    <th scope="col">E-mail</th>
                    <th scope="col">Rôle</th>
                    <th scope="col">Statut</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {invitations.map((i) => (
                    <tr key={i.id} className="equipe-tr">
                      <td className="equipe-cell-email">
                        <span className="equipe-email">{i.email}</span>
                      </td>
                      <td>
                        <span className={roleBadgeClass(i.role)}>
                          {libelleRole(i.role)}
                        </span>
                      </td>
                      <td>
                        <span className={invitStatutClass(i.statut)}>
                          {libelleStatutInvitation(i.statut)}
                        </span>
                      </td>
                      <td>
                        {i.statut === "en_attente" ? (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={busy}
                            onClick={() => onRevoquerInvitation(i.id)}
                          >
                            Révoquer
                          </button>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="equipe-cards equipe-mobile-only">
              {invitations.map((i) => (
                <li key={i.id} className="equipe-card-item">
                  <strong className="equipe-email">{i.email}</strong>
                  <span className={roleBadgeClass(i.role)}>
                    {libelleRole(i.role)}
                  </span>
                  <span className={invitStatutClass(i.statut)}>
                    {libelleStatutInvitation(i.statut)}
                  </span>
                  {i.statut === "en_attente" && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busy}
                      onClick={() => onRevoquerInvitation(i.id)}
                    >
                      Révoquer
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </>
        ) : (
          <div className="equipe-empty">
            <p className="equipe-empty-title">Aucune invitation</p>
            <p className="equipe-empty-body">
              Aucune invitation en cours. Utilisez le formulaire ci-dessus pour
              inviter un collègue (lecteur, réviseur ou admin).
            </p>
          </div>
        )}
      </section>

      <section
        className="panel dense equipe-card"
        aria-labelledby="equipe-outbox-title"
      >
        <div className="equipe-card-head">
          <div>
            <h3 id="equipe-outbox-title" className="equipe-card-title">
              Outbox e-mail
            </h3>
            <p className="equipe-card-hint">
              Derniers envois (invitations, notifications) — journal technique.
            </p>
          </div>
          <p className="equipe-count">
            {outboxLignes.length} envoi{outboxLignes.length !== 1 ? "s" : ""}
          </p>
        </div>

        {resendAbsent && (
          <p className="equipe-outbox-banner" role="status">
            RESEND_API_KEY absent
            {emailOutbox?.resend?.mode_sans_cle
              ? ` · mode ${emailOutbox.resend.mode_sans_cle}`
              : ""}
            . Les e-mails sont simulés ou en échec — le jeton reste disponible
            dans l&apos;UI.
          </p>
        )}

        {outboxLignes.length > 0 ? (
          <div className="equipe-table-wrap">
            <table className="equipe-table" aria-label="Outbox e-mail">
              <thead className="equipe-thead">
                <tr>
                  <th scope="col" className="equipe-th-id">
                    #
                  </th>
                  <th scope="col">Destinataire</th>
                  <th scope="col">Sujet</th>
                  <th scope="col">Statut</th>
                  <th scope="col">Date</th>
                </tr>
              </thead>
              <tbody>
                {outboxLignes.map((l) => (
                  <tr key={l.id} className="equipe-tr">
                    <td>{l.id}</td>
                    <td className="equipe-cell-email">{l.destinataire}</td>
                    <td>{l.sujet}</td>
                    <td>
                      <button
                        type="button"
                        className={outboxChipClass(l.statut)}
                        onClick={() =>
                          setOutboxDetailId((id) =>
                            id === l.id ? null : l.id,
                          )
                        }
                        aria-expanded={outboxDetailId === l.id}
                      >
                        {libelleStatutOutbox(l.statut)}
                      </button>
                      {outboxDetailId === l.id && l.dernier_erreur && (
                        <p className="equipe-outbox-err">{l.dernier_erreur}</p>
                      )}
                      {outboxDetailId === l.id && !l.dernier_erreur && (
                        <p className="equipe-outbox-err muted">
                          Aucun détail d&apos;erreur.
                        </p>
                      )}
                    </td>
                    <td>{formatDateCourte(l.cree_le)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="equipe-empty">
            <p className="equipe-empty-title">Aucun e-mail</p>
            <p className="equipe-empty-body">
              Les tentatives d&apos;envoi (simulées ou Resend) apparaîtront ici
              après une invitation.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
