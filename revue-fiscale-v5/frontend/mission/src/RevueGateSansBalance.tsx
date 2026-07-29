type Props = {
  onAllerSources: () => void;
  onReprendreImport?: () => void;
  estLecteur?: boolean;
};

/** Écran unique avant import de balance sur l'onglet Revue. */
export function RevueGateSansBalance({
  onAllerSources,
  onReprendreImport,
  estLecteur = false,
}: Props) {
  return (
    <section
      className="rest-onboarding revue-gate-sans-balance"
      role="status"
      aria-label="Démarrer la revue"
    >
      <h3 className="rest-onboarding-titre">Démarrez la revue</h3>
      <p className="rest-onboarding-intro">
        Aucune exécution encore — importez la balance pour produire le
        passage, les conclusions et les vues fiscales détaillées.
      </p>
      <ol className="rest-onboarding-etapes">
        <li>
          <strong>Importez la balance</strong> — depuis l&apos;onglet Sources,
          la source active alimente tous les contrôles.
        </li>
        <li>
          <strong>Retenez le seuil de matérialité</strong> — onglet Travaux,
          pour cibler les diligences significatives.
        </li>
        <li>
          <strong>Lancez la revue</strong> — passage, conclusions et volets
          fiscaux apparaîtront ici.
        </li>
      </ol>
      <div className="cta-row revue-gate-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={onAllerSources}
        >
          Aller à Sources
        </button>
        {!estLecteur && onReprendreImport && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onReprendreImport}
          >
            Reprendre l&apos;import
          </button>
        )}
      </div>
    </section>
  );
}
