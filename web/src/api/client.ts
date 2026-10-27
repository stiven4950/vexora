import { idToken } from "../auth/firebase";
import type { EditOp, EditorView, Season, Job, Limits, Looks, Moment, Person, Style, StyleKind, Wardrobe } from "./types";

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
  looks: () => request<Looks>("/api/looks"),
  limits: () => request<Limits>("/api/limits"),
  jobs: () => request<Job[]>("/api/jobs"),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  choreography: (id: string) => request<Moment[]>(`/api/jobs/${id}/choreography`),
  people: (id: string) => request<Person[]>(`/api/jobs/${id}/people`),
  remove: (id: string) => request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
  /** Pistas y momentos de una versión para el editor de efectos. */
  editor: (id: string) => request<EditorView>(`/api/jobs/${id}/editor`),
  /** Aplica los cambios del editor: crea una versión nueva y devuelve su trabajo. */
  edit: (id: string, edits: EditOp[]) =>
    request<Job>(`/api/jobs/${id}/edit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits }) }),
  /** Prepara una versión terminada antes del editor para editarla (unos segundos) y devuelve el trabajo ya editable. */
  prepareEdit: (id: string) => request<Job>(`/api/jobs/${id}/prepare-edit`, { method: "POST" }),
  /** Cancela un trabajo: en cola se borra ya; en curso se corta en unos segundos. */
  cancel: (id: string) => request<{ status: "removed" | "stopping" }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  /** Renombra el proyecto (el video y todas sus versiones); vacío = el nombre del archivo. */
  rename: (id: string, title: string) =>
    request<Job>(`/api/jobs/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }),
  /** Vuelve a procesar un trabajo que falló, con lo mismo que pidió. */
  retry: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),

  /** Sube el video con progreso real (fetch no informa del envío; XHR sí). */
  async create(
    video: File,
    kind: StyleKind,
    style: string,
    seed: number | null,
    onUpload?: (fraction: number) => void,
    season: string | null = null,
    wardrobe: Record<string, Wardrobe> = {},
    deep = false,
    fireStyle: string | null = null,
    boltStyle: string | null = null,
  ): Promise<Job> {
    const headers = await authHeaders();
    const form = new FormData();
    form.append("video", video);
    form.append("style_kind", kind);
    form.append("style", style);
    if (seed !== null) form.append("seed", String(seed));
    if (season) form.append("season", season);
    if (Object.keys(wardrobe).length) form.append("wardrobe", JSON.stringify(wardrobe));
    if (deep) form.append("deep", "true");
    if (fireStyle) form.append("fire_style", fireStyle);
    if (boltStyle) form.append("bolt_style", boltStyle);
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

  variation: (
    id: string,
    kind: StyleKind,
    style: string,
    seed: number | null,
    season: string | null = null,
    wardrobe: Record<string, Wardrobe> | null = null,
    deep: boolean | null = null,
    fireStyle: string | null = null,
    boltStyle: string | null = null,
  ) =>
    request<Job>(`/api/jobs/${id}/variations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ style_kind: kind, style, seed, season, wardrobe, deep, fire_style: fireStyle, bolt_style: boltStyle }),
    }),
};
