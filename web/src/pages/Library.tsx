import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { ago, groupVersions } from "../api/format";
import type { Job } from "../api/types";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import styles from "./Library.module.css";

const STATUS = { queued: "En cola", running: "Procesando", done: "Listo", failed: "Falló" } as const;

/** Cómo se llama una versión en la lista: el estilo y, si no es la primera, su número. */
function versionName(job: Job): string {
  const style = job.style_current;
  if (job.seed !== null) return `${style} · #${job.seed}`;
  return job.take > 0 ? `${style} · v${job.take + 1}` : style;
}

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

  const groups = useMemo(() => groupVersions(jobs ?? []), [jobs]);

  const remove = async (job: Job) => {
    if (!window.confirm(`¿Borrar "${job.filename}" (${job.style_current})? Se borran también su análisis y sus archivos.`)) return;
    try {
      await api.remove(job.id);
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : String(cause));
    }
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
        {groups.map((group, index) => {
          // La portada: la versión más reciente que ya tiene video; si ninguna, la más reciente.
          const cover = group.jobs.find((job) => job.status === "done") ?? group.jobs[0];
          if (!cover) return null;
          return (
            <article key={group.id} className={styles.item} style={{ animationDelay: `${Math.min(index, 12) * 45}ms` }}>
              <Link to={`/jobs/${cover.id}`} className={styles.thumb}>
                {cover.thumbnail_url && <img src={`${cover.thumbnail_url}&v=${cover.status}`} alt="" loading="lazy" />}
                {(cover.status === "running" || cover.status === "queued") && (
                  <div className={styles.progress}>
                    <i style={{ width: `${cover.progress * 100}%` }} />
                  </div>
                )}
                <span className={`${styles.badge} ${styles[cover.status]}`}>{STATUS[cover.status]}</span>
                {group.jobs.length > 1 && <span className={styles.count}>{group.jobs.length} versiones</span>}
              </Link>
              <div className={styles.meta}>
                <div>
                  <strong title={cover.filename}>{cover.filename}</strong>
                  <span className="mono">
                    {cover.style_current} · {ago(cover.created)}
                  </span>
                </div>
                {group.jobs.length === 1 && (
                  <button type="button" className={styles.delete} onClick={() => remove(cover)} aria-label="Borrar">
                    <Icon name="trash" size={16} />
                  </button>
                )}
              </div>
              {group.jobs.length > 1 && (
                <ul className={styles.versions}>
                  {group.jobs.map((job) => (
                    <li key={job.id}>
                      <Link to={`/jobs/${job.id}`}>
                        <span className={`${styles.dot} ${styles[job.status]}`} aria-label={STATUS[job.status]} />
                        <span className={styles.label}>{versionName(job)}</span>
                        <span className="mono">{ago(job.created)}</span>
                      </Link>
                      <button type="button" className={styles.delete} onClick={() => remove(job)} aria-label={`Borrar ${versionName(job)}`}>
                        <Icon name="trash" size={14} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          );
        })}
      </div>
    </Shell>
  );
}
