import type { Job, JobMetrics } from "./types";

/** Las 4 etapas que ve la persona (el diseño de "en proceso"); `stage` es la del motor que las mide. */
export const STEPS = [
  { key: "analyze", stage: "analyze", title: "Análisis del video", detail: "Detectando personas, movimientos y gestos." },
  { key: "direct", stage: "direct", title: "IA y coreografía", detail: "Seleccionando el mejor estilo y generando la secuencia." },
  { key: "render", stage: "compose", title: "Renderizado", detail: "Aplicando los efectos y componiendo el video." },
  { key: "finalize", stage: "finalize", title: "Finalización", detail: "Revisando calidad y generando el archivo final." },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];
export type StepState = "done" | "now" | "next";

export interface Step {
  key: StepKey;
  title: string;
  detail: string;
  state: StepState;
  /** Milisegundos que lleva o que tardó; null si aún no empieza. */
  ms: number | null;
}

/** La etapa del motor en curso, al paso del diseño que le toca (deep va dentro de la coreografía). */
const INDEX: Record<string, number> = { analyze: 0, direct: 1, deep: 1, compose: 2, finalize: 3 };

export const metricsOf = (job: Job): JobMetrics => job.metrics as JobMetrics;

/** El paso en curso: -1 si espera en cola, 4 si terminó. */
export function currentStep(job: Job): number {
  if (job.status === "done") return STEPS.length;
  if (job.status === "queued") return -1;
  const metrics = metricsOf(job);
  if (metrics.current && metrics.current in INDEX) return INDEX[metrics.current] ?? 0;
  const finished = Object.keys(metrics.stages ?? {}).map((stage) => INDEX[stage] ?? -1);
  return Math.min(Math.max(...finished, -1) + 1, STEPS.length - 1);
}

/** Cuánto lleva o tardó un paso; `now` en segundos epoch. */
export function stepMs(job: Job, key: StepKey, now: number): number | null {
  const metrics = metricsOf(job);
  const stages = metrics.stages ?? {};
  const started = metrics.started_at ?? {};
  const elapsed = (stage: string): number | null => (started[stage] === undefined ? null : Math.max(Math.round((now - (started[stage] ?? now)) * 1000), 0));
  switch (key) {
    case "analyze":
      return stages.analyze ?? elapsed("analyze");
    case "direct":
      return stages.direct ?? elapsed("direct");
    case "render": {
      // El renderizado es el tramo de compose antes de cerrar el archivo.
      if (stages.compose !== undefined) return Math.max(stages.compose - (stages.finalize ?? 0), 0);
      if (started.compose !== undefined && started.finalize !== undefined) return Math.round((started.finalize - started.compose) * 1000);
      return elapsed("compose");
    }
    case "finalize":
      return stages.finalize ?? elapsed("finalize");
  }
}

export function buildSteps(job: Job, now: number): Step[] {
  const current = currentStep(job);
  return STEPS.map((step, index) => {
    const state: StepState = index < current ? "done" : index === current ? "now" : "next";
    return { key: step.key, title: step.title, detail: step.detail, state, ms: state === "next" ? null : stepMs(job, step.key, now) };
  });
}
