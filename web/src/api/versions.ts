import type { Job } from "./types";

type VersionJob = Pick<Job, "id" | "created" | "status">;

/** Número de versión de cada trabajo del proyecto: el más antiguo (el video raíz) es la 1. */
export function versionNumbers(jobs: VersionJob[]): Map<string, number> {
  const ordered = [...jobs].sort((a, b) => a.created - b.created);
  return new Map(ordered.map((job, index) => [job.id, index + 1]));
}

/** El par que se compara al abrir: la última versión terminada (B) y la anterior (A). */
export function defaultPair(jobs: VersionJob[]): [string, string] | null {
  const done = jobs.filter((job) => job.status === "done").sort((a, b) => b.created - a.created);
  const [last, previous] = done;
  return last && previous ? [previous.id, last.id] : null;
}

/** Lo que la tabla de diferencias necesita de una versión. */
export type DiffJob = Pick<Job, "style_current" | "season" | "fire_style" | "bolt_style" | "wardrobe" | "deep" | "take" | "seed" | "base"> & { edits?: unknown[] };

export interface DiffRow {
  label: string;
  a: string;
  b: string;
  differs: boolean;
}

const wardrobeText = (wardrobe: Record<string, string>): string => {
  const entries = Object.entries(wardrobe);
  if (!entries.length) return "Sin prendas";
  return entries.map(([who, what]) => (who === "*" ? what : `${who}: ${what}`)).join(", ");
};

/** Filas A/B de la tabla de diferencias, marcando las que cambian. */
export function diffRows(a: DiffJob, b: DiffJob): DiffRow[] {
  const take = (job: DiffJob): string => (job.seed !== null ? `Semilla ${job.seed}` : job.take === 0 ? "Mejor versión" : `Versión ${job.take + 1}`);
  const rows: [string, string, string][] = [
    ["Estilo", a.style_current, b.style_current],
    ["Temporada", a.season ?? "Ninguna", b.season ?? "Ninguna"],
    ["Fuego", a.fire_style ?? "Del estilo", b.fire_style ?? "Del estilo"],
    ["Rayo", a.bolt_style ?? "Del estilo", b.bolt_style ?? "Del estilo"],
    ["Vestuario", wardrobeText(a.wardrobe), wardrobeText(b.wardrobe)],
    ["Análisis", a.deep ? "Profundo" : "Económico", b.deep ? "Profundo" : "Económico"],
    ["Toma", take(a), take(b)],
    ["Edición", a.base ? "Sí" : "No", b.base ? "Sí" : "No"],
    ["Cambios", String(a.edits?.length ?? 0), String(b.edits?.length ?? 0)],
  ];
  return rows.map(([label, x, y]) => ({ label, a: x, b: y, differs: x !== y }));
}
