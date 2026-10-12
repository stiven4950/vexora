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
  decor: string[];
  /** La temporada que toca hoy: la web la propone. */
  suggested: boolean;
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
}

export interface Moment {
  second: number;
  action: string;
  target: string;
  choice: string;
}
