import type {
  ChangeEventHandler,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";
import { InfoTip } from "./Tooltip";

type FieldProps = {
  id: string;
  label: string;
  hint?: ReactNode;
  /** Infobulle process (pastille) — pas de règle fiscale inventée. */
  tip?: string;
  value: string | number;
  onChange: ChangeEventHandler<HTMLInputElement>;
  trailing?: ReactNode;
  /** Champ identité requis encore vide — signal visuel rouge. */
  manquant?: boolean;
} & Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "id" | "value" | "onChange" | "className"
>;

/** Champ outline avec label flottant — usage wizard / formulaires métier. */
export function Field({
  id,
  label,
  hint,
  tip,
  value,
  onChange,
  trailing,
  required,
  manquant,
  ...rest
}: FieldProps) {
  const filled = String(value ?? "").length > 0;
  return (
    <div
      className={`field${filled ? " is-filled" : ""}${manquant ? " is-manquant" : ""}`}
    >
      <div className="field-control">
        <input
          id={id}
          className="field-input"
          value={value}
          onChange={onChange}
          required={required}
          placeholder=" "
          aria-invalid={manquant || undefined}
          {...rest}
        />
        <label className="field-label" htmlFor={id}>
          {label}
          {required ? (
            <span className="field-req" aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
        {tip ? (
          <span className="field-tip">
            <InfoTip label={tip} ariaLabel={`Aide : ${label}`} />
          </span>
        ) : null}
        {trailing ? <span className="field-trailing">{trailing}</span> : null}
      </div>
      {hint ? <p className="field-hint">{hint}</p> : null}
      {manquant ? (
        <p className="field-manquant-msg">À compléter</p>
      ) : null}
    </div>
  );
}

type SelectOption = { value: string; label: string };

type SelectFieldProps = {
  id: string;
  label: string;
  hint?: ReactNode;
  tip?: string;
  value: string;
  onChange: ChangeEventHandler<HTMLSelectElement>;
  options: SelectOption[];
  required?: boolean;
  disabled?: boolean;
  manquant?: boolean;
} & Omit<
  SelectHTMLAttributes<HTMLSelectElement>,
  "id" | "value" | "onChange" | "className" | "children"
>;

export function SelectField({
  id,
  label,
  hint,
  tip,
  value,
  onChange,
  options,
  required,
  disabled,
  manquant,
  ...rest
}: SelectFieldProps) {
  const filled = String(value ?? "").length > 0;
  return (
    <div
      className={`field${filled ? " is-filled" : ""}${manquant ? " is-manquant" : ""}`}
    >
      <div className="field-control">
        <select
          id={id}
          className="field-input field-select"
          value={value}
          onChange={onChange}
          required={required}
          disabled={disabled}
          aria-invalid={manquant || undefined}
          {...rest}
        >
          <option value="" disabled>
            Choisir…
          </option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <label className="field-label" htmlFor={id}>
          {label}
          {required ? (
            <span className="field-req" aria-hidden="true">
              *
            </span>
          ) : null}
        </label>
        {tip ? (
          <span className="field-tip">
            <InfoTip label={tip} ariaLabel={`Aide : ${label}`} />
          </span>
        ) : null}
      </div>
      {hint ? <p className="field-hint">{hint}</p> : null}
      {manquant ? (
        <p className="field-manquant-msg">À compléter</p>
      ) : null}
    </div>
  );
}
