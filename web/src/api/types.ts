/** Contratos de la API (src/vfxglow/api/server.py). */

export type Rgb = [number, number, number];

export type StyleKind = "catalog" | "preset";

export interface Style {
  kind: StyleKind;
  name: string;
  title: string;
  description: string;
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
