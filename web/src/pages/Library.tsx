import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { fullDate, groupStatus, groupVersions, projectName, type ProjectStatus } from "../api/format";
import type { Job } from "../api/types";
import { Icon } from "../components/Icon";
import { Pagination } from "../components/Pagination";
import { ProjectCard } from "../components/ProjectCard";
import { Shell } from "../components/Shell";
import { ROUTES } from "../routes";
import styles from "./Library.module.css";

type Filter = "all" | ProjectStatus;

const FILTERS: { id: Filter; label: string; dot?: string }[] = [
  { id: "all", label: "Todos" },
  { id: "done", label: "Completados", dot: "#34d399" },
  { id: "processing", label: "En proceso", dot: "#60a5fa" },
  { id: "failed", label: "Error", dot: "#fb7185" },
];

const normalize = (text: string): string => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Mis proyectos: un video y todas sus versiones por tarjeta, con búsqueda, estados y paginación. */
export function Library() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(12);

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
  const counts = useMemo(() => {
    const total: Record<Filter, number> = { all: groups.length, done: 0, processing: 0, failed: 0 };
    for (const group of groups) total[groupStatus(group.jobs)] += 1;
    return total;
  }, [groups]);
  const shown = useMemo(() => {
    const words = normalize(query).split(/\s+/).filter(Boolean);
    return groups.filter((group) => {
      if (filter !== "all" && groupStatus(group.jobs) !== filter) return false;
      const cover = group.jobs[0];
      if (!cover) return false;
      const haystack = normalize([projectName(cover), cover.filename, cover.style_current, ...cover.tags, fullDate(cover.created)].join(" "));
      return words.every((word) => haystack.includes(word));
    });
  }, [groups, filter, query]);

  const pages = Math.max(Math.ceil(shown.length / size), 1);
  const current = Math.min(page, pages);
  const visible = shown.slice((current - 1) * size, current * size);

  const rename = async (job: Job) => {
    const title = window.prompt("Nombre del proyecto", projectName(job));
    if (title === null) return;
    try {
      await api.rename(job.id, title);
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : String(cause));
    }
    void load();
  };

  const remove = async (job: Job) => {
    if (!window.confirm(`¿Borrar "${projectName(job)}" (${job.style_current})? Se borran también su análisis y sus archivos.`)) return;
    try {
      await api.remove(job.id);
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : String(cause));
    }
    void load();
  };

  const retry = async (job: Job) => {
    try {
      await api.retry(job.id);
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : String(cause));
    }
    void load();
  };

  return (
    <Shell>
      <header className={styles.head}>
        <div className={styles.title}>
          <h1>
            Mis <span>proyectos</span>
          </h1>
          <p>
            Todos tus videos, efectos y versiones en un solo lugar.
            <br />
            Organiza, edita, compara y vuelve a tus creaciones siempre que quieras.
          </p>
        </div>
        <div className={styles.tools}>
          <label className={styles.search}>
            <Icon name="search" size={18} />
            <input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="Buscar por nombre, estilo o fecha…" />
          </label>
          <label className={styles.select}>
            <Icon name="filter" size={16} />
            <select value={filter} onChange={(event) => { setFilter(event.target.value as Filter); setPage(1); }} aria-label="Filtrar por estado">
              <option value="all">Todos los estados</option>
              <option value="done">Completados</option>
              <option value="processing">En proceso</option>
              <option value="failed">Error</option>
            </select>
          </label>
          <Link to={ROUTES.studio} className={styles.create}>
            <Icon name="plus" size={16} /> Crear nuevo
          </Link>
        </div>
      </header>

      <div className={styles.chips} role="group" aria-label="Estado">
        {FILTERS.map((item) => (
          <button key={item.id} type="button" className={filter === item.id ? styles.on : ""} onClick={() => { setFilter(item.id); setPage(1); }} aria-pressed={filter === item.id}>
            {item.dot && <i style={{ background: item.dot }} />}
            {item.label} ({counts[item.id]})
          </button>
        ))}
      </div>

      {error && <p className={styles.error}>No se pudo leer la API: {error}</p>}
      {jobs?.length === 0 && (
        <div className={styles.empty}>
          <Icon name="film" size={36} />
          <p>Aún no hay proyectos. Sube tu primer video en el estudio.</p>
        </div>
      )}
      {jobs && jobs.length > 0 && shown.length === 0 && <p className={styles.none}>Ningún proyecto coincide con tu búsqueda.</p>}

      <div className={styles.grid}>
        {visible.map((group) => (
          <ProjectCard key={group.id} group={group} onRename={rename} onRemove={remove} onRetry={retry} />
        ))}
      </div>

      {shown.length > 0 && (
        <footer className={styles.foot}>
          <span>
            Mostrando {visible.length} de {shown.length} proyectos
          </span>
          <Pagination page={current} pages={pages} size={size} onPage={setPage} onSize={(value) => { setSize(value); setPage(1); }} />
        </footer>
      )}
    </Shell>
  );
}
