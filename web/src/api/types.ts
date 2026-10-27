/** Contratos de la API (src/vfxglow/api/server.py). */

export type Rgb = [number, number, number];

export type StyleKind = "catalog" | "preset";

export interface Style {
  kind: StyleKind;
  name: string;
  title: string;
  description: string;
  /** La idea en pocas palabras (la tarjeta del estilo). */
  subtitle: string;
  palette: Rgb[];
  actions: string[];
  needs: string[];
  tags: string[];
}

/** Estilo de época (configs/seasons.yaml) que se aplica encima del estilo elegido. */
export interface Season {
  id: string;
  title: string;
  emoji: string;
  description: string;
  tags: string[];
  palette: Rgb[];
  particles: string[];
  /** La temporada que toca hoy: la web la propone. */
  suggested: boolean;
}

/** Estilo de fuego o de rayo (director/looks.py) que el cliente elige antes de renderizar. */
export interface Look {
  id: string;
  title: string;
  description: string;
}

export interface Looks {
  fuego: Look[];
  rayo: Look[];
}

export type JobStatus = "queued" | "running" | "done" | "failed";
export type JobStage = "queued" | "analyze" | "direct" | "render" | "done";

export interface Job {
  id: string;
  created: number;
  filename: string;
  style_kind: StyleKind;
  style: string;
  seed: number | null;
  /** Sin semilla: 0 = la mejor coreografía elegida sola; 1, 2... = "otra versión". */
  take: number;
  season: string | null;
  /** Estilos de fuego y de rayo elegidos (null = los del estilo). */
  fire_style: string | null;
  bolt_style: string | null;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  message: string;
  log: string[];
  error: string | null;
  started: number | null;
  finished: number | null;
  parent: string | null;
  duration: number | null;
  output_url: string | null;
  original_url: string | null;
  thumbnail_url: string | null;
  /** Progreso en vivo (SSE). Las URLs de archivos traen su llave (?k=): parámetros extra con "&". */
  events_url: string | null;
  /** El estilo con su nombre de hoy (los trabajos viejos pueden tener un nombre anterior). */
  style_current: string;
  /** El tipo de estilo de hoy (un preset viejo como avatar_fire hoy es el catálogo avatar). */
  style_kind_current: StyleKind;
  /** Vestuario por persona ({"*": "vestido", "person_1": "chaqueta"}). */
  wardrobe: Record<string, Wardrobe>;
  /** Análisis profundo: un modelo vio el video completo y escribió la coreografía. */
  deep: boolean;
  /** Si falló: el tipo de fallo (api/jobs.py, ERRORS); `error` trae el mensaje para la persona. */
  error_code: string | null;
  /** Referencia del trabajo en los registros del servidor (para soporte). */
  trace_id: string;
  /** Resumen medido: espera en cola, duración por etapa, tokens y costo de IA. */
  metrics: Record<string, unknown>;
  /** Duración del video subido. */
  video_seconds: number | null;
  /** Ficha del video subido. */
  video_width: number | null;
  video_height: number | null;
  video_bytes: number | null;
  /** Nombre del proyecto que puso la persona (de todo el video y sus versiones). */
  title: string | null;
  /** Etiquetas del estilo y de la temporada. */
  tags: string[];
  /** Se puede abrir en el editor de efectos. */
  editable: boolean;
  /** Versión terminada antes del editor: todavía no se puede editar, pero se puede preparar (POST prepare-edit). */
  preparable: boolean;
  /** Si es una versión editada: la versión de la que parte y sus cambios. */
  base: string | null;
  edits: EditOp[];
  /** Lo que fue pasando, en orden: "Video recibido", "Inicio del procesamiento", cada etapa. */
  activity: ActivityLine[];
  /** Segundos que se espera que tarde el revelado (mientras espera o procesa). */
  estimate_s: number | null;
  /** Cuántos trabajos van antes en la cola (hay un solo trabajador). */
  queue_ahead: number;
}

/** Lo que la web avisa antes de subir (GET /api/limits). */
export interface Limits {
  max_upload_mb: number;
  max_video_seconds: number;
  max_video_side: number;
  /** El análisis profundo es de pago: solo algunas cuentas lo tienen. */
  deep_allowed: boolean;
}

/** Prendas de cuerpo entero que puede llevar una persona. */
export type Wardrobe = "chaqueta" | "vestido" | "ambos" | "ninguno";

export const WARDROBES: { id: Wardrobe; label: string }[] = [
  { id: "ninguno", label: "Sin prendas" },
  { id: "chaqueta", label: "Chaquetas metaleras" },
  { id: "vestido", label: "Vestidos" },
  { id: "ambos", label: "Ambos" },
];

/** Una persona del video, con un recorte para reconocerla. */
export interface Person {
  id: string;
  label: string;
  image_url: string;
}

export interface Moment {
  second: number;
  action: string;
  target: string;
  choice: string;
  /** La intención del gesto (solo con análisis profundo). */
  note?: string;
}

/** Una línea de la actividad reciente de un trabajo (hora en segundos epoch). */
export interface ActivityLine {
  at: number;
  text: string;
  detail: string;
}

/** Lo que el servidor mide de un trabajo mientras corre (`job.metrics`). */
export interface JobMetrics {
  /** Milisegundos de cada etapa ya terminada (analyze, direct, deep, compose, finalize). */
  stages?: Record<string, number>;
  /** La etapa en curso (la más interna) y desde cuándo (epoch). */
  current?: string | null;
  current_started?: number | null;
  /** Cuándo empezó cada etapa (epoch). */
  started_at?: Record<string, number>;
  queue_wait_ms?: number;
  total_ms?: number;
}

/** Editor de efectos (GET /api/jobs/{id}/editor). Tiempos en segundos. */
export interface EditorMoment {
  id: string;
  start: number;
  end: number;
  choice: string;
  action: string;
  person: string | null;
  note: string;
}

export interface EditorTrack {
  key: string;
  label: string;
  icon: string;
  color: string;
  element: string | null;
  start: number;
  end: number;
  moments: EditorMoment[];
}

export interface EditorOption {
  option: string;
  action: string;
  /** La pista a la que pertenece (el nombre de la opción). */
  track: string;
  /** El elemento del efecto (fuego, agua, aire, rayo, tierra) o null. */
  element: string | null;
}

export interface EditorView {
  job_id: string;
  fps: number;
  frames: number;
  duration: number;
  tracks: EditorTrack[];
  options: EditorOption[];
}

/** Un cambio del editor, como lo recibe POST /api/jobs/{id}/edit (director/edits.py, Edit). */
export interface EditOp {
  op: "remove" | "track_off" | "move" | "add" | "style";
  moment?: string;
  track?: string;
  start?: number;
  end?: number;
  option?: string;
  action?: string;
  color?: string;
  intensity?: number;
  size?: number;
}

/** Un estilo sugerido tras analizar el video, con su razón. */
export interface RecommendedStyle {
  style: string;
  reason: string;
}

/** La recomendación de estilo: `style` es el `name` de un estilo de catálogo de /api/styles. */
export interface Recommendation extends RecommendedStyle {
  alternatives: RecommendedStyle[];
}

/** Aviso de calidad del video (nunca bloquea): `warn` ámbar, `info` cian. */
export interface QualityWarning {
  code: string;
  level: "info" | "warn";
  title: string;
  detail: string;
}

/** Un video subido por adelantado (POST /api/uploads) que se analiza mientras se elige el estilo. */
export interface UploadView {
  id: string;
  status: "analyzing" | "ready" | "failed" | "used";
  filename: string;
  created: number;
  video_seconds: number | null;
  video_width: number | null;
  video_height: number | null;
  video_bytes: number | null;
  error: string | null;
  recommendation: Recommendation | null;
  warnings: QualityWarning[];
}

/** Vista previa rápida del editor (POST/GET /api/jobs/{id}/preview): ~3 s con el motor real, sin crear versión. */
export interface PreviewView {
  preview_id: string;
  status: "rendering" | "ready" | "failed";
  /** MP4 firmado, cuando está lista. */
  url: string | null;
  start: number;
  end: number;
  error: string | null;
}
