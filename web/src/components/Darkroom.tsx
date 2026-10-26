import { useEffect, useRef } from "react";

import { approx } from "../api/format";
import type { Job } from "../api/types";
import { Icon } from "./Icon";
import styles from "./Darkroom.module.css";

const STAGES = [
  { key: "analyze", title: "Lectura del movimiento", detail: "Pose, manos, cara, hojas y eventos de cada fotograma" },
  { key: "direct", title: "Coreografía", detail: "Cada acción sortea su reacción visual" },
  { key: "render", title: "Revelado", detail: "Capas de luz compuestas sobre el plano original" },
] as const;

const ORDER = ["queued", "analyze", "direct", "render", "done"];

/** Lo que se le dice a la persona de la espera, sin tecnicismos. */
export function waitNote(job: Job): string {
  if (job.status === "queued") {
    const ahead = job.queue_ahead;
    const place = ahead === 0 ? "Eres el siguiente" : ahead === 1 ? "Hay 1 video antes del tuyo" : `Hay ${ahead} videos antes del tuyo`;
    return job.estimate_s ? `${place}. Cuando empiece, tardará ${approx(job.estimate_s)}.` : `${place}.`;
  }
  if (!job.estimate_s) return "Puedes cerrar esta pestaña: el video sigue en tu biblioteca.";
  // El avance se deduce de los mensajes del proceso y a veces va a saltos: es un rango, no un reloj.
  const left = Math.max(job.estimate_s * (1 - job.progress), 20);
  return `Faltan ${approx(left)}. Puedes cerrar esta pestaña: el video sigue en tu biblioteca.`;
}

/** Vista de proceso: el plano original desenfocado detrás, anillo de progreso, etapas y, si se pide, el detalle técnico. */
export function Darkroom({ job }: { job: Job }) {
  const scroller = useRef<HTMLDivElement>(null);
  const percent = Math.round(job.progress * 100);
  const radius = 92;
  const circumference = 2 * Math.PI * radius;
  const current = ORDER.indexOf(job.stage);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [job.log.length]);

  return (
    <div className={styles.room}>
      {job.original_url && <video className={styles.backdrop} src={job.original_url} autoPlay muted loop playsInline />}
      <div className={styles.center}>
        <svg className={styles.ring} viewBox="0 0 220 220" role="img" aria-label={`Progreso ${percent}%`}>
          <defs>
            <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#67e8f9" />
              <stop offset="0.6" stopColor="#8b5cf6" />
              <stop offset="1" stopColor="#ec4899" />
            </linearGradient>
          </defs>
          <circle cx="110" cy="110" r={radius} className={styles.track} />
          <circle
            cx="110"
            cy="110"
            r={radius}
            className={styles.value}
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - job.progress)}
          />
        </svg>
        <div className={styles.readout}>
          <strong>
            {percent}
            <small>%</small>
          </strong>
          <span>{job.status === "queued" ? "En cola" : job.message}</span>
        </div>
      </div>
      <p className={styles.note} role="status">
        {waitNote(job)}
      </p>

      <ol className={styles.stages}>
        {STAGES.map((stage, index) => {
          const position = index + 1;
          const state = current > position ? "done" : current === position ? "now" : "next";
          return (
            <li key={stage.key} className={styles[state]}>
              <span className={styles.mark}>{state === "done" ? <Icon name="check" size={14} /> : `0${position}`}</span>
              <div>
                <strong>{stage.title}</strong>
                <span>{stage.detail}</span>
              </div>
            </li>
          );
        })}
      </ol>

      <details className={styles.details}>
        <summary>Ver detalles técnicos</summary>
        <div className={styles.console} ref={scroller}>
          {job.log.length === 0 ? (
            <p className={styles.line}>Esperando turno en la cola…</p>
          ) : (
            job.log.map((line, index) => (
              <p key={`${index}-${line}`} className={styles.line}>
                <span>›</span> {line}
              </p>
            ))
          )}
          <p className={`${styles.line} ${styles.cursor}`}>▌</p>
        </div>
      </details>
    </div>
  );
}
