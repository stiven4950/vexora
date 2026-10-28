import type { QualityWarning, Recommendation, UploadView } from "./types";

/** En qué va la subida anticipada del Estudio. */
export type UploadPhase = "uploading" | "analyzing" | "ready" | "failed";

export interface UploadState {
  phase: UploadPhase;
  /** Avance de la subida, de 0 a 1. */
  fraction: number;
  /** Lo último que dijo el servidor (null mientras se sube o si la subida falló). */
  view: UploadView | null;
  /** Por qué falló, para mostrarlo. */
  error: string | null;
}

/** El estado que corresponde a lo que devolvió el servidor ("used" ya terminó el análisis). */
export function fromView(view: UploadView): UploadState {
  if (view.status === "failed") return { phase: "failed", fraction: 1, view, error: view.error };
  return { phase: view.status === "analyzing" || view.status === "uploading" ? "analyzing" : "ready", fraction: 1, view, error: null };
}

/** El texto de la fila de estado del resumen. */
export function uploadStatusText(state: UploadState): string {
  switch (state.phase) {
    case "uploading":
      return `Subiendo video ${Math.round(state.fraction * 100)}%`;
    case "analyzing":
      return "Analizando tu video…";
    case "ready":
      return warningsOf(state).length > 0 ? `Análisis listo · ${warningsOf(state).length} ${warningsOf(state).length === 1 ? "aviso" : "avisos"}` : "Análisis listo";
    case "failed":
      return "No se pudo analizar el video";
  }
}

/** Los avisos de calidad, solo cuando el análisis terminó. */
export function warningsOf(state: UploadState | null): QualityWarning[] {
  return state?.phase === "ready" ? (state.view?.warnings ?? []) : [];
}

/** La recomendación, solo si ya llegó. */
export function recommendationOf(state: UploadState | null): Recommendation | null {
  return state?.phase === "ready" ? (state.view?.recommendation ?? null) : null;
}

/**
 * Qué estilo elige "Sorpréndeme": la recomendada; si ya es la elegida (o una alternativa), pasa a la
 * siguiente de la lista. Solo cuentan los estilos que existen en el catálogo. null = sin recomendación útil.
 */
export function pickSurprise(rec: Recommendation | null, current: string | null, available: readonly string[]): string | null {
  if (!rec) return null;
  const options = [rec.style, ...rec.alternatives.map((a) => a.style)].filter((name, i, all) => available.includes(name) && all.indexOf(name) === i);
  if (options.length === 0) return null;
  const at = current ? options.indexOf(current) : -1;
  return at < 0 ? (options[0] ?? null) : (options[(at + 1) % options.length] ?? null);
}

/** La razón de un estilo dentro de la recomendación (la principal o una alternativa). */
export function reasonFor(rec: Recommendation, name: string): string | null {
  if (rec.style === name) return rec.reason;
  return rec.alternatives.find((a) => a.style === name)?.reason ?? null;
}
