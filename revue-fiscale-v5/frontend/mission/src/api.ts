/** Base API — même origine en prod (/app via FastAPI) ; proxy Vite en dev. */
const API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Signale une session expirée (401) — App écoute cet événement pour nettoyer la session. */
export const AUTH_EXPIREE_EVENT = "rf:auth-expiree";

function signalerAuthExpiree(status: number): void {
  if (status !== 401) return;
  try {
    window.dispatchEvent(new Event(AUTH_EXPIREE_EVENT));
  } catch {
    /* ignore */
  }
}

function detailMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    try {
      return JSON.stringify(d);
    } catch {
      return fallback;
    }
  }
  return fallback;
}

export async function api<T>(
  path: string,
  opts: RequestInit & { jeton?: string | null; json?: unknown } = {},
): Promise<T> {
  const { jeton, json, headers: extra, ...rest } = opts;
  const headers = new Headers(extra);
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (jeton) {
    headers.set("Authorization", `Bearer ${jeton}`);
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    signalerAuthExpiree(res.status);
    throw new ApiError(detailMessage(data, res.statusText), res.status);
  }
  return data as T;
}

export async function apiUpload<T>(
  path: string,
  fichier: File,
  jeton: string | null,
  champs?: Record<string, string>,
): Promise<T> {
  const fd = new FormData();
  fd.append("fichier", fichier);
  if (champs) {
    for (const [k, v] of Object.entries(champs)) {
      fd.append(k, v);
    }
  }
  const headers = new Headers();
  if (jeton) headers.set("Authorization", `Bearer ${jeton}`);
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: fd,
  });
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!res.ok) {
    signalerAuthExpiree(res.status);
    throw new ApiError(detailMessage(data, res.statusText), res.status);
  }
  return data as T;
}

export async function telecharger(
  path: string,
  jeton: string | null,
  nomFichier: string,
): Promise<void> {
  const { blob } = await apiBlob(path, jeton);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nomFichier;
  a.click();
  URL.revokeObjectURL(url);
}

/** Blob authentifié (aperçu / téléchargement). */
export async function apiBlob(
  path: string,
  jeton: string | null,
): Promise<{ blob: Blob; contentType: string | null }> {
  const headers = new Headers();
  if (jeton) headers.set("Authorization", `Bearer ${jeton}`);
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) {
    let detail = `téléchargement impossible (${res.status})`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      /* ignore */
    }
    signalerAuthExpiree(res.status);
    throw new ApiError(detail, res.status);
  }
  const blob = await res.blob();
  return { blob, contentType: res.headers.get("content-type") };
}

/** Pourcentage API (chaîne à point décimal) rendu en notation française. */
export function fmtPct(v: string): string {
  return v.replace(".", ",");
}

export function fmtMontant(v: string | number): string {
  try {
    return new Intl.NumberFormat("fr-FR").format(Number(v));
  } catch {
    return String(v);
  }
}
