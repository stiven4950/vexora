import { useState } from "react";
import { Link } from "react-router-dom";

import { fullDate, groupStatus, mmss, projectName, resolutionLabel, type Group } from "../api/format";
import type { Job } from "../api/types";
import { ROUTES } from "../routes";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";
import styles from "./ProjectCard.module.css";

interface Props {
  group: Group<Job>;
  onRename: (job: Job) => void;
  onRemove: (job: Job) => void;
  onRetry: (job: Job) => void;
}

/** Cómo se llama una versión en la lista: el estilo y, si no es la primera, su número. */
function versionName(job: Job): string {
  if (job.seed !== null) return `${job.style_current} · #${job.seed}`;
  return job.take > 0 ? `${job.style_current} · v${job.take + 1}` : job.style_current;
}

const capital = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

/** Un proyecto (un video y sus versiones) en Mis proyectos, como en el diseño. */
export function ProjectCard({ group, onRename, onRemove, onRetry }: Props) {
  const [menu, setMenu] = useState(false);
  // La portada: la versión más reciente que ya tiene video; si ninguna, la más reciente.
  const cover = group.jobs.find((job) => job.status === "done") ?? group.jobs[0];
  if (!cover) return null;
  const status = groupStatus(group.jobs);
  const resolution = resolutionLabel(cover.video_width, cover.video_height);
  return (
    <article className={styles.card}>
      <Link to={ROUTES.job(cover.id)} className={styles.thumb}>
        {cover.thumbnail_url && <img src={`${cover.thumbnail_url}&v=${cover.status}`} alt="" loading="lazy" />}
        <StatusBadge status={status} className={styles.status} />
        <span className={styles.play}>
          <Icon name="play" size={14} />
          {cover.video_seconds ? mmss(cover.video_seconds) : ""}
        </span>
        {(cover.status === "running" || cover.status === "queued") && (
          <span className={styles.progress}>
            <i style={{ width: `${cover.progress * 100}%` }} />
          </span>
        )}
      </Link>
      <h3 title={projectName(cover)}>{projectName(cover)}</h3>
      <div className={styles.tags}>
        {cover.tags.slice(0, 3).map((tag) => (
          <span key={tag}>{capital(tag)}</span>
        ))}
        {group.jobs.length > 1 && <span className={styles.versions}>{group.jobs.length} versiones</span>}
      </div>
      <div className={styles.foot}>
        <span className={styles.date}>
          <Icon name="calendar" size={14} /> {fullDate(cover.created)}
        </span>
        {resolution && <span className={styles.res}>{resolution}</span>}
        <span className={styles.actions}>
          {cover.status === "done" && cover.output_url && (
            <a href={`${cover.output_url}&download=true`} aria-label="Descargar" title="Descargar MP4">
              <Icon name="download" size={16} />
            </a>
          )}
          {status === "failed" && (
            <button type="button" onClick={() => onRetry(cover)} aria-label="Reintentar" title="Reintentar">
              <Icon name="refresh" size={16} />
            </button>
          )}
          <span className={styles.menuWrap}>
            <button type="button" onClick={() => setMenu((v) => !v)} aria-label="Más opciones" aria-expanded={menu}>
              <Icon name="more" size={16} />
            </button>
            {menu && (
              <div className={styles.menu} role="menu" onMouseLeave={() => setMenu(false)}>
                <button type="button" onClick={() => onRename(cover)}>
                  <Icon name="edit" size={14} /> Renombrar
                </button>
                <Link to={ROUTES.versions(group.id)}>
                  <Icon name="layers" size={14} /> Ver versiones
                </Link>
                <strong>{group.jobs.length > 1 ? "Versiones" : "Esta versión"}</strong>
                {group.jobs.map((job) => (
                  <div key={job.id} className={styles.version}>
                    <Link to={ROUTES.job(job.id)}>{versionName(job)}</Link>
                    <button type="button" onClick={() => onRemove(job)} aria-label={`Borrar ${versionName(job)}`}>
                      <Icon name="trash" size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </span>
        </span>
      </div>
    </article>
  );
}
