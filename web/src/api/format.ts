import type { Rgb } from "./types";

export const rgb = ([r, g, b]: Rgb, alpha = 1): string =>
  `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${alpha})`;

export const timecode = (seconds: number): string => {
  const s = Math.max(0, seconds);
  const minutes = Math.floor(s / 60);
  const rest = s - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
};

export const ago = (epoch: number): string => {
  const diff = Date.now() / 1000 - epoch;
  if (diff < 60) return "hace un momento";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return new Date(epoch * 1000).toLocaleDateString("es", { day: "numeric", month: "short" });
};

/** Nombres legibles de las acciones que detecta el análisis. */
export const ACTIONS: Record<string, string> = {
  fast_swing: "Golpe rápido",
  spotlight: "Protagonista",
  prop_transfer: "Pase de objeto",
  prop_spin: "Giro de objeto",
  prop_worn: "Se lo pone",
  face_touch: "Mano en la cara",
  throw: "Lanzamiento",
  neck_slash: "Ya valió",
  stomp: "Pisotón",
  step: "Paso",
  frenzy: "Baile intenso",
  beat: "Golpe musical",
  heart_hands: "Corazón",
  arms_up: "Brazos arriba",
  arms_open: "Brazos en cruz",
  point: "Señalar",
  hand_ear: "Mano al oído",
  cover_eyes: "Ojos tapados",
  spin_body: "Giro",
  person_contact: "Impacto",
  fist_clash: "Choque de puños",
  body_bump: "Choque de cuerpos",
  lull: "Pausa",
  intent: "Intención",
  intended_strike: "Golpe con intención",
  blade_swing: "Tajo",
  blade_ground: "Hoja al piso",
  flip: "Voltereta",
  tumble: "Giro",
  jump: "Salto",
  landing: "Aterrizaje",
  entrance: "Entrada",
};

export const actionLabel = (action: string): string => ACTIONS[action] ?? action.replaceAll("_", " ");
export const choiceLabel = (choice: string): string =>
  choice.replace(" (espejo)", " · en la pareja").replace(" (fijado)", "").replaceAll("_", " ");

/** "person_1:left_wrist" → "Persona 2"; los objetivos sin persona no dicen nada. */
export const personLabel = (target: string): string | null => {
  const match = /^person_(\d+)/.exec(target);
  return match ? `Persona ${Number(match[1]) + 1}` : null;
};

/** Color estable por acción para los marcadores de la línea de tiempo. */
export const actionHue = (action: string): number => {
  let hash = 0;
  for (const char of action) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
};

/** Una duración en palabras: "menos de 1 min", "unos 3 min", "unos 12 min". */
export const approx = (seconds: number): string => {
  const minutes = Math.round(seconds / 60);
  if (seconds < 45) return "menos de 1 min";
  return `unos ${Math.max(minutes, 1)} min`;
};

/** Un trabajo y sus versiones: el video original es el primero (sin `parent`). */
export interface Group<T> {
  id: string;
  jobs: T[];
}

const latest = (jobs: { created: number }[]): number => Math.max(...jobs.map((job) => job.created));

/** Agrupa los trabajos por el video del que salen (`parent` apunta al primero), el grupo con la
 * actividad más reciente primero y, dentro de cada grupo, la versión más reciente primero. */
export function groupVersions<T extends { id: string; parent: string | null; created: number }>(jobs: T[]): Group<T>[] {
  const groups = new Map<string, T[]>();
  for (const job of jobs) {
    const key = job.parent ?? job.id;
    groups.set(key, [...(groups.get(key) ?? []), job]);
  }
  return [...groups.entries()]
    .map(([id, members]) => ({ id, jobs: members.sort((a, b) => b.created - a.created) }))
    .sort((a, b) => latest(b.jobs) - latest(a.jobs));
}

/** "02:14" — minutos y segundos enteros (los tiempos de los diseños). */
export const mmss = (seconds: number): string => {
  const total = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
};

/** "23 oct 2026 · 14:32" */
export const fullDate = (epoch: number): string => {
  const date = new Date(epoch * 1000);
  const day = date.toLocaleDateString("es", { day: "numeric", month: "short", year: "numeric" }).replace(/\./g, "");
  const time = date.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day} · ${time}`;
};

/** "1080p" desde el lado corto, o null si no se guardó el tamaño. */
export const resolutionLabel = (width: number | null, height: number | null): string | null =>
  width && height ? `${Math.min(width, height)}p` : null;

/** "poderes_de_agua.mp4" → "Poderes de agua". */
export const niceName = (filename: string): string => {
  const base = filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : filename;
};

/** El nombre del proyecto: el que puso la persona o el del archivo. */
export const projectName = (job: { title: string | null; filename: string }): string => job.title ?? niceName(job.filename);

export type ProjectStatus = "done" | "processing" | "failed";

/** El estado de un proyecto: en proceso si alguna versión se está haciendo; si no, completado si
 * alguna terminó; si ninguna, error. */
export function groupStatus(jobs: { status: "queued" | "running" | "done" | "failed" }[]): ProjectStatus {
  if (jobs.some((job) => job.status === "queued" || job.status === "running")) return "processing";
  return jobs.some((job) => job.status === "done") ? "done" : "failed";
}
