import { idToken } from "../auth/firebase";
import type { DeletionSummary, NotificationsView, Profile, ProfileChanges, PublicVideo, ShareLink, PlansView, StudioPreviewOpts, EditOp, EditorView, PreviewView, LayersView, Season, Job, Limits, Looks, Moment, PropChoice, Person, Style, StyleKind, UploadView, Wardrobe } from "./types";

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

const JSON_HEADERS = { "Content-Type": "application/json" };

export const api = {
  /** Perfil y ajustes de la cuenta. */
  me: () => request<Profile>("/api/me"),
  updateMe: (changes: ProfileChanges) => request<Profile>("/api/me", { method: "PATCH", headers: JSON_HEADERS, body: JSON.stringify(changes) }),
  /** Foto de perfil (JPG, PNG o WEBP de hasta 2 MB); el servidor la recorta al cuadrado a 512 px. */
  uploadAvatar: (file: File) => {
    const form = new FormData();
    form.append("avatar", file);
    return request<Profile>("/api/me/avatar", { method: "POST", body: form });
  },
  deleteAvatar: () => request<Profile>("/api/me/avatar", { method: "DELETE" }),
  /** Registra que la persona aceptó los términos y la privacidad vigentes. */
  acceptTerms: () => request<Profile>("/api/me/terms", { method: "POST" }),
  /** Borra la cuenta entera en el servidor (la de Firebase la borra la web después). */
  deleteAccount: (confirm: string) => request<DeletionSummary>("/api/me", { method: "DELETE", headers: JSON_HEADERS, body: JSON.stringify({ confirm }) }),
  notifications: () => request<NotificationsView>("/api/notifications"),
  /** Marca avisos como leídos: los `ids`, o todos. */
  markRead: (ids: string[] | "all") =>
    request<NotificationsView>("/api/notifications/read", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(ids === "all" ? { all: true } : { ids }) }),
  /** El enlace público activo de un video terminado (404 si no hay). */
  getShare: (id: string) => request<ShareLink>(`/api/jobs/${id}/share`),
  /** Crea el enlace público o devuelve el que ya está activo. */
  createShare: (id: string) => request<ShareLink>(`/api/jobs/${id}/share`, { method: "POST" }),
  /** Revoca el enlace: deja de funcionar al instante. */
  revokeShare: (id: string) => request<void>(`/api/jobs/${id}/share`, { method: "DELETE" }),
  /** Lo que ve quien abre un enlace compartido: sin sesión. */
  publicVideo: async (token: string): Promise<PublicVideo> => {
    const response = await fetch(`/api/public/${encodeURIComponent(token)}`);
    if (!response.ok) throw new ApiError(response.status, response.status === 404 ? "Este enlace no existe o ya no está disponible." : response.statusText);
    return (await response.json()) as PublicVideo;
  },
  styles: () => request<Style[]>("/api/styles"),
  seasons: () => request<Season[]>("/api/seasons"),
  looks: () => request<Looks>("/api/looks"),
  props: () => request<PropChoice[]>("/api/props"),
  limits: () => request<Limits>("/api/limits"),
  /** Catálogo de planes y paquetes de créditos (precios de referencia mientras `draft`). */
  plans: () => request<PlansView>("/api/plans"),
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
  /** Pide la vista previa de ~3 s alrededor de `at` (segundos) con los cambios pendientes; no crea versión. */
  preview: (id: string, edits: EditOp[], at: number) =>
    request<PreviewView>(`/api/jobs/${id}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ edits, at }) }),
  /** Estado de una vista previa pedida. */
  getPreview: (id: string, previewId: string) => request<PreviewView>(`/api/jobs/${id}/preview/${previewId}`),
  /** Estado de la vista en vivo (las capas) de una versión. */
  layers: (id: string) => request<LayersView>(`/api/jobs/${id}/layers`),
  /** Pide dibujar las capas de la vista en vivo; responde al instante y se sondea con `layers`. */
  createLayers: (id: string) => request<LayersView>(`/api/jobs/${id}/layers`, { method: "POST" }),
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
    uploadId: string | null = null,
    prop: string | null = null,
  ): Promise<Job> {
    const headers = await authHeaders();
    const form = new FormData();
    // Con una subida ya hecha se manda su id y no el archivo (sin barra de subida).
    if (uploadId) form.append("upload_id", uploadId);
    else form.append("video", video);
    form.append("style_kind", kind);
    form.append("style", style);
    if (seed !== null) form.append("seed", String(seed));
    if (season) form.append("season", season);
    if (Object.keys(wardrobe).length) form.append("wardrobe", JSON.stringify(wardrobe));
    if (deep) form.append("deep", "true");
    if (fireStyle) form.append("fire_style", fireStyle);
    if (boltStyle) form.append("bolt_style", boltStyle);
    if (prop) form.append("prop", prop);
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

  /** Sube el video por adelantado (el servidor lo analiza); se puede cortar con `signal`. */
  async upload(video: File, onUpload?: (fraction: number) => void, signal?: AbortSignal): Promise<UploadView> {
    const headers = await authHeaders();
    const form = new FormData();
    form.append("video", video);
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/uploads");
      for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value);
      xhr.upload.onprogress = (event) => event.lengthComputable && onUpload?.(event.loaded / event.total);
      xhr.onload = () => {
        let body: { detail?: unknown } = {};
        try {
          body = xhr.responseText ? JSON.parse(xhr.responseText) : {};
        } catch {
          // cuerpo sin JSON: queda el texto del estado
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as unknown as UploadView);
        else reject(new ApiError(xhr.status, typeof body.detail === "string" ? body.detail : xhr.statusText));
      };
      xhr.onerror = () => reject(new ApiError(0, "No se pudo conectar con la API. ¿Está corriendo vfxglow-api?"));
      xhr.onabort = () => reject(new DOMException("Subida cancelada", "AbortError"));
      signal?.addEventListener("abort", () => xhr.abort(), { once: true });
      if (signal?.aborted) return reject(new DOMException("Subida cancelada", "AbortError"));
      xhr.send(form);
    });
  },
  getUpload: (id: string) => request<UploadView>(`/api/uploads/${id}`),
  deleteUpload: (id: string) => request<void>(`/api/uploads/${id}`, { method: "DELETE" }),
  /** Pide ~3 s con efectos reales del estilo elegido sobre una subida lista; no crea trabajo. */
  uploadPreview: (uploadId: string, opts: StudioPreviewOpts) =>
    request<PreviewView>(`/api/uploads/${uploadId}/preview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(opts) }),
  getUploadPreview: (uploadId: string, previewId: string) => request<PreviewView>(`/api/uploads/${uploadId}/preview/${previewId}`),

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
