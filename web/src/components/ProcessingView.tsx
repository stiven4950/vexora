import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { approx, clock, megabytes, mmss, projectName, resolutionLabel } from "../api/format";
import { buildSteps, currentStep, metricsOf, STEPS, type StepKey } from "../api/stages";
import type { Job } from "../api/types";
import { ROUTES } from "../routes";
import { Icon, type IconName } from "./Icon";
import styles from "./ProcessingView.module.css";

/** Lo que la ficha de "Configuración aplicada" muestra, ya con los nombres de la persona. */
export interface AppliedConfig {
  style: string;
  season: string;
  looks: string;
  wardrobe: string;
  analysis: string;
}

interface Props {
  job: Job;
  config: AppliedConfig;
  onCancel: () => void;
  onRename: () => void;
  cancelling: boolean;
}

const STEP_ICON: Record<StepKey, IconName> = { analyze: "brain", direct: "sparkles", render: "play", finalize: "check" };

/** Qué hace la etapa en curso, en palabras de quien espera. */
const NOW: Record<StepKey, { title: string; text: string }> = {
  analyze: { title: "Análisis de movimiento", text: "Estamos identificando los gestos, la dirección y los momentos clave para aplicar los efectos." },
  direct: { title: "Coreografía", text: "Estamos eligiendo qué efecto dispara cada gesto y cuándo." },
  render: { title: "Renderizado de efectos", text: "Estamos dibujando las capas de luz sobre tu video." },
  finalize: { title: "Compresión y almacenamiento", text: "Estamos escribiendo el archivo final de tu video." },
};

/** Segundos epoch actuales, al segundo: así los cronómetros avanzan aunque el servidor no envíe nada. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** Un tramo de la barra de etapas: icono, título, descripción y su estado con el tiempo. */
function Step({ title, detail, state, ms, icon, index, last }: { title: string; detail: string; state: "done" | "now" | "next"; ms: number | null; icon: IconName; index: number; last: boolean }) {
  const status = state === "done" ? `${ms === null ? "" : `${mmss(ms / 1000)} · `}Completado` : state === "now" ? "En proceso…" : "Pendiente";
  return (
    <li className={`${styles.step} ${styles[state]}`}>
      <span className={styles.bubble}>
        <Icon name={state === "done" ? "check" : icon} size={22} />
      </span>
      {!last && <i className={styles.link} />}
      <strong>
        {index + 1}. {title}
      </strong>
      <span>{detail}</span>
      <em>{status}</em>
    </li>
  );
}

/** Estado de una fila de la tabla de detalle. */
function Cell({ state, ms }: { state: "done" | "now" | "next"; ms: number | null }) {
  return (
    <>
      <span className={`${styles.state} ${styles[state]}`}>
        <i />
        {state === "done" ? "Completado" : state === "now" ? "En proceso" : "Pendiente"}
      </span>
      <span className={styles.time}>{state === "next" || ms === null ? "-" : mmss(ms / 1000)}</span>
    </>
  );
}

/** "Tu video ya está en proceso": las etapas, el avance, el detalle y la ficha del proyecto. */
export function ProcessingView({ job, config, onCancel, onRename, cancelling }: Props) {
  const now = useNow();
  const [playing, setPlaying] = useState(false);
  const steps = buildSteps(job, now);
  const current = currentStep(job);
  const percent = Math.round(job.progress * 100);
  const queued = job.status === "queued";
  const metrics = metricsOf(job);
  const elapsed = job.started ? Math.max(now - job.started, 0) : 0;
  const stage = NOW[STEPS[Math.max(current, 0)]?.key ?? "analyze"];
  const radius = 54;
  const circumference = 2 * Math.PI * radius;
  const wait = metrics.queue_wait_ms ?? null;
  const resolution = resolutionLabel(job.video_width, job.video_height);
  const recent = [...job.activity].reverse();

  const rows: { icon: IconName; title: string; state: "done" | "now" | "next"; ms: number | null }[] = [
    { icon: "upload", title: "Carga y preparación del video", state: queued ? "now" : "done", ms: wait },
    { icon: "brain", title: "Análisis de movimiento", state: steps[0]?.state ?? "next", ms: steps[0]?.ms ?? null },
    { icon: "sparkles", title: "Selección de estilo y coreografía", state: steps[1]?.state ?? "next", ms: steps[1]?.ms ?? null },
    { icon: "play", title: "Renderizado de efectos", state: steps[2]?.state ?? "next", ms: steps[2]?.ms ?? null },
    { icon: "cloud", title: "Compresión y almacenamiento", state: steps[3]?.state ?? "next", ms: steps[3]?.ms ?? null },
  ];

  return (
    <div className={styles.page}>
      <div className={styles.center}>
        <section className={`${styles.card} ${styles.hero}`}>
          {job.thumbnail_url && <img className={styles.heroArt} src={`${job.thumbnail_url}&original=true&first=true`} alt="" />}
          <div className={styles.heroText}>
            <h1>
              Tu video ya está <span>{queued ? "en cola" : "en proceso"}</span>
            </h1>
            <p>
              Estamos analizando los movimientos, detectando los gestos
              <br />y aplicando los efectos visuales. Esto puede tomar unos minutos.
            </p>
          </div>
          <ol className={styles.steps}>
            {steps.map((step, index) => (
              <Step key={step.key} title={step.title} detail={step.detail} state={step.state} ms={step.ms} icon={STEP_ICON[step.key]} index={index} last={index === steps.length - 1} />
            ))}
          </ol>
        </section>

        <section className={`${styles.card} ${styles.progress}`}>
          <div className={styles.ring}>
            <svg viewBox="0 0 128 128" role="img" aria-label={`Progreso ${percent}%`}>
              <defs>
                <linearGradient id="ring-grad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#67e8f9" />
                  <stop offset="1" stopColor="#3b82f6" />
                </linearGradient>
              </defs>
              <circle cx="64" cy="64" r={radius} className={styles.track} />
              <circle cx="64" cy="64" r={radius} className={styles.value} stroke="url(#ring-grad)" strokeDasharray={circumference} strokeDashoffset={circumference * (1 - job.progress)} />
            </svg>
            <strong>{percent}%</strong>
            <small>Proceso general</small>
          </div>
          <div className={styles.current}>
            <span className={styles.nowIcon}>
              <Icon name={STEP_ICON[STEPS[Math.max(current, 0)]?.key ?? "analyze"]} size={28} />
            </span>
            <div>
              <strong>{queued ? "En cola" : stage.title}</strong>
              <p>
                {queued
                  ? job.queue_ahead === 0
                    ? "Eres el siguiente: empezamos en cuanto termine el video en curso."
                    : `Hay ${job.queue_ahead} ${job.queue_ahead === 1 ? "video" : "videos"} antes del tuyo.`
                  : stage.text}
              </p>
              <span className={styles.bar}>
                <i style={{ width: `${percent}%` }} />
              </span>
            </div>
            <span className={styles.clock}>
              {mmss(elapsed)}
              {job.estimate_s ? ` / ${mmss(job.estimate_s)}` : ""}
            </span>
          </div>
        </section>

        <section className={`${styles.card} ${styles.detail}`}>
          <h2>Detalle del proceso</h2>
          <ul>
            {rows.map((row) => (
              <li key={row.title}>
                <Icon name={row.icon} size={18} />
                <span>{row.title}</span>
                <Cell state={row.state} ms={row.ms} />
              </li>
            ))}
          </ul>
        </section>

        <div className={styles.notice}>
          <p>
            <Icon name="bulb" size={18} /> Mientras se procesa tu video, puedes salir de esta página. Te notificaremos cuando esté listo.
            {job.estimate_s ? ` Tiempo estimado: ${approx(job.estimate_s)}.` : ""}
          </p>
        </div>
        <button type="button" className={styles.cancel} onClick={onCancel} disabled={cancelling}>
          <Icon name="cancel" size={16} /> {cancelling ? "Cancelando…" : "Cancelar procesamiento"}
        </button>
      </div>

      <aside className={styles.side}>
        <section className={styles.card}>
          <div className={styles.preview}>
            {playing && job.original_url ? (
              <video src={job.original_url} controls autoPlay playsInline />
            ) : (
              <>
                {job.thumbnail_url && <img src={`${job.thumbnail_url}&original=true&first=true`} alt="" />}
                <span className={styles.tag}>Vista previa (baja resolución)</span>
                <button type="button" className={styles.playButton} onClick={() => setPlaying(true)} aria-label="Reproducir el video original">
                  <Icon name="play" size={26} />
                </button>
              </>
            )}
          </div>
          <div className={styles.sheet}>
            <h3>
              {projectName(job)}
              <button type="button" onClick={onRename} aria-label="Renombrar">
                <Icon name="edit" size={15} />
              </button>
            </h3>
            <p>
              <Icon name="film" size={14} /> {job.filename}
            </p>
            <p className={styles.facts}>
              {job.video_width && job.video_height ? <span>{`${job.video_width} × ${job.video_height}`}</span> : null}
              {job.video_seconds ? (
                <span>
                  <Icon name="clock" size={13} /> {mmss(job.video_seconds)}
                </span>
              ) : null}
              {job.video_bytes ? <span>{megabytes(job.video_bytes)}</span> : null}
              {resolution && !job.video_width ? <span>{resolution}</span> : null}
            </p>
          </div>
        </section>

        <section className={styles.card}>
          <h2>Configuración aplicada</h2>
          <dl className={styles.config}>
            <div><dt>Estilo</dt><dd>{config.style}</dd></div>
            <div><dt>Temporada</dt><dd>{config.season}</dd></div>
            <div><dt>Fuego y rayo</dt><dd>{config.looks}</dd></div>
            <div><dt>Vestuario</dt><dd>{config.wardrobe}</dd></div>
            <div><dt>Análisis</dt><dd>{config.analysis}</dd></div>
          </dl>
        </section>

        <section className={styles.card}>
          <h2>Actividad reciente</h2>
          <ol className={styles.activity}>
            {recent.map((line, index) => (
              <li key={`${line.at}-${line.text}`} className={index === 0 ? styles.latest : ""}>
                <time>{clock(line.at)}</time>
                <i />
                <div>
                  <strong>{line.text}</strong>
                  {line.detail && <small>{line.detail}</small>}
                </div>
              </li>
            ))}
          </ol>
          <Link to={ROUTES.project(job.parent ?? job.id)} className={styles.details}>
            Ver detalles del proyecto <Icon name="external" size={14} />
          </Link>
        </section>
      </aside>
    </div>
  );
}
