import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { actionLabel, choiceLabel, rgb, timecode } from "../api/format";
import type { Moment, Style } from "../api/types";
import { Button } from "../components/Button";
import { CompareViewer } from "../components/CompareViewer";
import { Darkroom } from "../components/Darkroom";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { useJob } from "../hooks/useJob";
import styles from "./JobPage.module.css";

export function JobPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { job, error } = useJob(id);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [nextStyle, setNextStyle] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    api.styles().then(setStyleList).catch(() => setStyleList([]));
  }, []);

  useEffect(() => {
    if (job?.status === "done") api.choreography(job.id).then(setMoments).catch(() => setMoments([]));
    if (job) setNextStyle((current) => current || `${job.style_kind}:${job.style}`);
  }, [job?.status, job?.id]);

  const current = styleList.find((s) => s.name === job?.style);
  const aurora: [string, string] | undefined = current?.palette[0]
    ? [rgb(current.palette[0], 0.2), rgb(current.palette[1] ?? current.palette[0], 0.16)]
    : undefined;

  const summary = useMemo(() => {
    const counts = new Map<string, number>();
    for (const moment of moments) counts.set(moment.choice, (counts.get(moment.choice) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [moments]);

  const vary = async (seed: number | null) => {
    if (!job) return;
    const [kind, name] = nextStyle.split(":") as ["catalog" | "preset", string];
    setBusy(true);
    setActionError(null);
    try {
      const next = await api.variation(job.id, kind, name, kind === "catalog" ? seed : null);
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
            {job.seed !== null && ` · semilla ${job.seed}`}
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
            original={job.original_url}
            edited={job.output_url}
            moments={moments}
            originalPoster={`/api/jobs/${job.id}/thumbnail?original=true&first=true`}
            editedPoster={`/api/jobs/${job.id}/thumbnail?first=true`}
          />
          <aside className={styles.side}>
            <section className={styles.card}>
              <span className="eyebrow">Exportar</span>
              <a className={styles.download} href={`${job.output_url}?download=true`}>
                <Icon name="download" /> Descargar MP4
              </a>
              {job.duration && <span className={styles.meta}>Revelado en {timecode(job.duration)}</span>}
            </section>

            <section className={styles.card}>
              <span className="eyebrow">Otra versión</span>
              <p>El análisis queda guardado: una variación solo vuelve a coreografiar y revelar.</p>
              <select value={nextStyle} onChange={(event) => setNextStyle(event.target.value)} aria-label="Estilo de la variación">
                {styleList.map((style) => (
                  <option key={`${style.kind}:${style.name}`} value={`${style.kind}:${style.name}`}>
                    {style.kind === "catalog" ? "◆ " : "◇ "}
                    {style.title}
                  </option>
                ))}
              </select>
              <Button icon="dice" disabled={busy} onClick={() => vary(Math.floor(Math.random() * 9000) + 100)}>
                Nueva tirada
              </Button>
              {actionError && <span className={styles.error}>{actionError}</span>}
            </section>

            {summary.length > 0 && (
              <section className={styles.card}>
                <span className="eyebrow">La coreografía</span>
                <ul className={styles.choices}>
                  {summary.map(([choice, count]) => (
                    <li key={choice}>
                      <span>{choiceLabel(choice)}</span>
                      <b>{count}</b>
                    </li>
                  ))}
                </ul>
                <span className={styles.meta}>
                  {moments.length} reacciones en {new Set(moments.map((m) => m.action)).size} tipos de acción ·{" "}
                  {[...new Set(moments.map((m) => actionLabel(m.action)))].slice(0, 3).join(", ")}
                </span>
              </section>
            )}
          </aside>
        </div>
      )}
    </Shell>
  );
}
