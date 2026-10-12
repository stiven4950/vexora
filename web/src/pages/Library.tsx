import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ago } from "../api/format";
import type { Job } from "../api/types";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import styles from "./Library.module.css";

const STATUS = { queued: "En cola", running: "Procesando", done: "Listo", failed: "Falló" } as const;

export function Library() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () =>
    api
      .jobs()
      .then(setJobs)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 4000);
    return () => window.clearInterval(timer);
  }, []);

  const remove = async (job: Job) => {
    if (!window.confirm(`¿Borrar "${job.filename}" (${job.style})?`)) return;
    await api.remove(job.id);
    void load();
  };

  return (
    <Shell>
      <header className={styles.head}>
        <div>
          <span className="eyebrow">Biblioteca</span>
          <h1>Tus revelados</h1>
        </div>
        <Link to="/">
          <Button icon="spark">Nuevo revelado</Button>
        </Link>
      </header>

      {error && <p className={styles.error}>No se pudo leer la API: {error}</p>}
      {jobs?.length === 0 && (
        <div className={styles.empty}>
          <Icon name="film" size={36} />
          <p>Aún no hay revelados. Sube tu primer plano en el estudio.</p>
        </div>
      )}

      <div className={styles.grid}>
        {jobs?.map((job, index) => (
          <article key={job.id} className={styles.item} style={{ animationDelay: `${Math.min(index, 12) * 45}ms` }}>
            <Link to={`/jobs/${job.id}`} className={styles.thumb}>
              {job.thumbnail_url && <img src={`${job.thumbnail_url}?v=${job.status}`} alt="" loading="lazy" />}
              {(job.status === "running" || job.status === "queued") && (
                <div className={styles.progress}>
                  <i style={{ width: `${job.progress * 100}%` }} />
                </div>
              )}
              <span className={`${styles.badge} ${styles[job.status]}`}>{STATUS[job.status]}</span>
            </Link>
            <div className={styles.meta}>
              <div>
                <strong title={job.filename}>{job.filename}</strong>
                <span className="mono">
                  {job.style}
                  {job.style_kind === "catalog" && job.seed === null && job.take > 0 && ` · v${job.take + 1}`}
                  {job.seed !== null && ` · #${job.seed}`} · {ago(job.created)}
                </span>
              </div>
              <button type="button" className={styles.delete} onClick={() => remove(job)} aria-label="Borrar">
                <Icon name="trash" size={16} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </Shell>
  );
}
