type LogoProps = {
  variant?: "hero" | "bar";
  title?: string;
};

/** Marque visuelle — registre + balayage de contrôle (pas de taux / règle fiscale). */
export function LogoMark({ variant = "bar" }: { variant?: "hero" | "bar" }) {
  const isHero = variant === "hero";
  return (
    <svg
      className={`logo-mark logo-mark--${variant}`}
      viewBox="0 0 40 40"
      width="40"
      height="40"
      aria-hidden="true"
      focusable="false"
    >
      <rect
        x="1"
        y="1"
        width="38"
        height="38"
        rx="10"
        className="logo-mark__plate"
        fill={isHero ? "rgba(245,242,234,0.08)" : "#0f172a"}
        stroke={isHero ? "rgba(184,149,74,0.5)" : "none"}
        strokeWidth={isHero ? 1.25 : 0}
      />
      {/* Feuille / registre */}
      <rect
        x="10"
        y="9"
        width="16"
        height="20"
        rx="2.5"
        fill={isHero ? "rgba(245,242,234,0.94)" : "#f8fafc"}
      />
      <path
        className="logo-mark__lines"
        d="M14 15h8M14 19h8M14 23h5"
        stroke={isHero ? "#0c1628" : "#334155"}
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      {/* Balayage de revue */}
      <path
        className="logo-mark__scan"
        d="M22 11.5c5.2 2.2 7.8 6.4 7.8 11.2"
        fill="none"
        stroke={isHero ? "#d4b978" : "#2dd4bf"}
        strokeWidth="2.2"
        strokeLinecap="round"
      />
      <circle
        cx="29.5"
        cy="23"
        r="2.4"
        fill={isHero ? "#b8954a" : "#2dd4bf"}
        className="logo-mark__dot"
      />
    </svg>
  );
}

export function Logo({ variant = "bar", title = "Revue Fiscale" }: LogoProps) {
  const accentIdx = title.lastIndexOf(" ");
  const head = accentIdx > 0 ? title.slice(0, accentIdx) : title;
  const tail = accentIdx > 0 ? title.slice(accentIdx) : "";
  return (
    <span className={`logo logo--${variant}`}>
      <LogoMark variant={variant} />
      <span className="logo-name">
        {head}
        {tail ? <span>{tail}</span> : null}
      </span>
    </span>
  );
}
