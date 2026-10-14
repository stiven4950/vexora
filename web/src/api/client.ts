import { idToken } from "../auth/firebase";
import type { Season, Job, Moment, Style, StyleKind } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** La sesión de Firebase en la cabecera: la API verifica el token en cada petición. */
async function authHeaders(): Promise<Record<string, string>> {
  const token = await idToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { ...(init?.headers as Record<string, string> | undefined), ...(await authHeaders()) } });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // cuerpo sin JSON: queda el texto del estado
    }
    throw new ApiError(response.status, detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export const api = {
  styles: () => request<Style[]>("/api/styles"),
  seasons: () => request<Season[]>("/api/seasons"),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  choreography: (id: string) => request<Moment[]>(`/api/jobs/${id}/choreography`),
  remove: (id: string) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),

  /** Sube el video con progreso real (fetch no informa del envío; XHR sí). */
  async create(video: File, kind: StyleKind, style: string, seed: number | null, onUpload?: (fraction: number) => void, season: string | null = null): Promise<Job> {
    const headers = await authHeaders();
    const form = new FormData();
    form.append("video", video);
    form.append("style_kind", kind);
    form.append("style", style);
    if (seed !== null) form.append("seed", String(seed));
    if (season) form.append("season", season);
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
      xhr.upload.onprogress = (event) => event.lengthComputable && onUpload?.(event.loaded / event.total);
      xhr.onload = () => {
        const body = xhr.responseText ? JSON.parse(xhr.responseText) : {};
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as Job);
        else reject(new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : xhr.statusText));
      };
      xhr.onerror = () => reject(new ApiError(0, "No se pudo conectar con la API. ¿Está corriendo vfxglow-api?"));
      xhr.send(form);
    });
  },

  variation: (id: string, kind: StyleKind, style: string, seed: number | null, season: string | null = null) =>
    request<Job>(`/api/jobs/${id}/variations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style_kind: kind, style, seed, season }),
    }),
};
