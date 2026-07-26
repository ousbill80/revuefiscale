import { useEffect, useMemo, useState } from "react";
import {
  AsYouType,
  getCountries,
  getCountryCallingCode,
  getExampleNumber,
  Metadata,
  parsePhoneNumberFromString,
  type CountryCode,
} from "libphonenumber-js";
import examples from "libphonenumber-js/mobile/examples";

const NOMS_PAYS: Partial<Record<CountryCode, string>> = {
  CI: "Côte d'Ivoire",
  SN: "Sénégal",
  BF: "Burkina Faso",
  ML: "Mali",
  GN: "Guinée",
  FR: "France",
  BE: "Belgique",
  CH: "Suisse",
  CA: "Canada",
  US: "États-Unis",
  GB: "Royaume-Uni",
  MA: "Maroc",
  TN: "Tunisie",
  CM: "Cameroun",
  TG: "Togo",
  BJ: "Bénin",
  NE: "Niger",
  GH: "Ghana",
  NG: "Nigeria",
};

type PhoneFieldProps = {
  id?: string;
  valueE164: string;
  onChangeE164: (e164: string) => void;
  defaultCountry?: CountryCode;
  required?: boolean;
  disabled?: boolean;
};

function labelPays(code: CountryCode): string {
  const nom = NOMS_PAYS[code] ?? code;
  return `${nom} (+${getCountryCallingCode(code)})`;
}

function maxNationalDigits(country: CountryCode): number {
  const meta = new Metadata();
  meta.selectNumberingPlan(country);
  const lengths = meta.numberingPlan?.possibleLengths() ?? [];
  return lengths.length > 0 ? Math.max(...lengths) : 15;
}

function formatNationalInput(country: CountryCode, raw: string): string {
  const max = maxNationalDigits(country);
  const digits = raw.replace(/\D/g, "").slice(0, max);
  return new AsYouType(country).input(digits);
}

function placeholderNational(country: CountryCode): string {
  if (country === "CI") return "07 00 00 00 00";
  const example = getExampleNumber(country, examples);
  return example?.formatNational() ?? "Numéro national";
}

const PAYS_TRIES = (getCountries() as CountryCode[]).slice().sort((a, b) => {
  const priorite = ["CI", "SN", "BF", "ML", "FR", "BE"];
  const ia = priorite.indexOf(a);
  const ib = priorite.indexOf(b);
  if (ia >= 0 || ib >= 0) {
    if (ia < 0) return 1;
    if (ib < 0) return -1;
    return ia - ib;
  }
  return labelPays(a).localeCompare(labelPays(b), "fr");
});

export function PhoneField({
  id = "telephone",
  valueE164,
  onChangeE164,
  defaultCountry = "CI",
  required,
  disabled,
}: PhoneFieldProps) {
  const initial = useMemo(() => {
    if (valueE164) {
      const p = parsePhoneNumberFromString(valueE164);
      if (p) {
        return {
          country: (p.country ?? defaultCountry) as CountryCode,
          national: p.formatNational(),
        };
      }
    }
    return { country: defaultCountry, national: "" };
  }, [defaultCountry, valueE164]);

  const [country, setCountry] = useState<CountryCode>(initial.country);
  const [national, setNational] = useState(initial.national);

  useEffect(() => {
    if (!valueE164) return;
    const p = parsePhoneNumberFromString(valueE164);
    if (p) {
      setCountry((p.country ?? defaultCountry) as CountryCode);
      setNational(p.formatNational());
    }
  }, [valueE164, defaultCountry]);

  function syncE164(c: CountryCode, nat: string) {
    const formatted = formatNationalInput(c, nat);
    const parsed = parsePhoneNumberFromString(formatted, c);
    if (parsed?.isValid()) {
      onChangeE164(parsed.format("E.164"));
    } else {
      onChangeE164("");
    }
    return formatted;
  }

  const digitsSaisis = national.replace(/\D/g, "").length > 0;
  const e164Valide = Boolean(
    parsePhoneNumberFromString(national, country)?.isValid(),
  );
  const invalidePartiel = digitsSaisis && !e164Valide;

  return (
    <div className="phone-field">
      <select
        className="phone-country"
        aria-label="Indicatif pays"
        value={country}
        disabled={disabled}
        onChange={(e) => {
          const c = e.target.value as CountryCode;
          setCountry(c);
          const fmt = syncE164(c, national);
          setNational(fmt);
        }}
      >
        {PAYS_TRIES.map((c) => (
          <option key={c} value={c}>
            {labelPays(c)}
          </option>
        ))}
      </select>
      <input
        id={id}
        className="phone-national"
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        placeholder={placeholderNational(country)}
        value={national}
        required={required}
        disabled={disabled}
        aria-invalid={invalidePartiel || undefined}
        aria-describedby={invalidePartiel ? `${id}-hint` : undefined}
        onChange={(e) => {
          const fmt = syncE164(country, e.target.value);
          setNational(fmt);
        }}
      />
      {invalidePartiel ? (
        <p id={`${id}-hint`} className="field-hint warn phone-field-hint">
          Numéro incomplet ou invalide pour ce pays.
        </p>
      ) : null}
    </div>
  );
}
