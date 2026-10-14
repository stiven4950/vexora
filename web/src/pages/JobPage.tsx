import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { rgb, timecode } from "../api/format";
import type { Moment, Style } from "../api/types";
import { Button } from "../components/Button";
import { ChoreographyPanel } from "../components/ChoreographyPanel";
import { CompareViewer, type CompareViewerHandle } from "../components/CompareViewer";
import { Darkroom } from "../components/Darkroom";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { useJob } from "../hooks/useJob";
import styles from "./JobPage.module.css";

/** "Mejor versión" para la elegida sola; "Versión N" para las que pidió el usuario. Una semilla
 * explícita (CLI o API) se muestra tal cual. */
function versionLabel(job: { seed: number | null; take: number }): string {
  if (job.seed !== null) return `semilla ${job.seed}`;
  return job.take === 0 ? "mejor versión" : `versión ${job.take + 1}`;
}

export function JobPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { job, error } = useJob(id);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [nextStyle, setNextStyle] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const viewer = useRef<CompareViewerHandle>(null);

  useEffect(() => {
    api.styles().then(setStyleList).catch(() => setStyleList([]));
  }, []);

  useEffect(() => {
    if (job?.status === "done") api.choreography(job.id).then(setMoments).catch(() => setMoments([]));
    if (job) setNextStyle((current) => current || `${job.style_kind}:${job.style_current}`);
  }, [job?.status, job?.id]);

  const current = styleList.find((s) => s.name === job?.style_current);
  const aurora: [string, string] | undefined = current?.palette[0]
    ? [rgb(current.palette[0], 0.2), rgb(current.palette[1] ?? current.palette[0], 0.16)]
    : undefined;

  // Otra versión: el servidor elige la siguiente mejor coreografía; el usuario no ve semillas.
  const vary = async () => {
    if (!job) return;
    const [kind, name] = nextStyle.split(":") as ["catalog" | "preset", string];
    setBusy(true);
    setActionError(null);
    try {
      const next = await api.variation(job.id, kind, name, null, job.season);
      navigate(`/jobs/${next.id}`);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <Shell>
        <div className={styles.failed}>
          <Icon name="alert" size={28} />
          <h2>No se encontró el trabajo</h2>
          <p>{error}</p>
          <Link to="/">Volver al estudio</Link>
        </div>
      </Shell>
    );
  }
  if (!job) {
    return (
      <Shell>
        <div className={styles.loading}>Cargando…</div>
      </Shell>
    );
  }

  return (
    <Shell aurora={aurora}>
      <header className={styles.head}>
        <Link to="/library" className={styles.back}>
          <Icon name="back" size={16} /> Biblioteca
        </Link>
        <div className={styles.title}>
          <span className="eyebrow">
            {current?.title ?? job.style}
            {job.style_kind === "catalog" && ` · ${versionLabel(job)}`}
            {job.season && ` · ${job.season.replace(/_/g, " ")}`}
          </span>
          <h1>{job.filename}</h1>
        </div>
        <span className={`${styles.status} ${styles[job.status]}`}>
          {{ queued: "En cola", running: "Procesando", done: "Listo", failed: "Falló" }[job.status]}
        </span>
      </header>

      {(job.status === "queued" || job.status === "running") && <Darkroom job={job} />}

      {job.status === "failed" && (
        <div className={styles.failed}>
          <Icon name="alert" size={28} />
          <h2>El revelado falló</h2>
          <p className="mono">{job.error}</p>
          <details>
            <summary>Ver registro</summary>
            <pre>{job.log.join("\n")}</pre>
          </details>
        </div>
      )}

      {job.status === "done" && job.output_url && job.original_url && (
        <div className={styles.result}>
          <CompareViewer
            ref={viewer}
            onTime={setPlayhead}
            original={job.original_url}
            edited={job.output_url}
            moments={moments}
            originalPoster={job.thumbnail_url ? `${job.thumbnail_url}&original=true&first=true` : undefined}
            editedPoster={job.thumbnail_url ? `${job.thumbnail_url}&first=true` : undefined}
          />
          <aside className={styles.side}>
            <section className={styles.card}>
              <span className="eyebrow">Exportar</span>
              <a className={styles.download} href={`${job.output_url}&download=true`}>
                <Icon name="download" /> Descargar MP4
              </a>
              {job.duration && <span className={styles.meta}>Revelado en {timecode(job.duration)}</span>}
            </section>

            <section className={styles.card}>
              <span className="eyebrow">¿Otra opción?</span>
              <p>Probamos otra coreografía buena para el mismo video, o el mismo video con otro estilo. No se vuelve a analizar: tarda poco.</p>
              <select value={nextStyle} onChange={(event) => setNextStyle(event.target.value)} aria-label="Estilo de la variación">
                {styleList.map((style) => (
                  <option key={`${style.kind}:${style.name}`} value={`${style.kind}:${style.name}`}>
                    {style.kind === "catalog" ? "◆ " : "◇ "}
                    {style.title}
                  </option>
                ))}
              </select>
              <Button variant="ghost" icon="spark" disabled={busy} onClick={vary}>
                Probar otra versión
              </Button>
              {actionError && <span className={styles.error}>{actionError}</span>}
            </section>

            {moments.length > 0 && (
              <ChoreographyPanel moments={moments} time={playhead} onSelect={(moment) => viewer.current?.seekTo(moment.second)} />
            )}
          </aside>
        </div>
      )}
    </Shell>
  );
}
