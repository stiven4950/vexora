import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { fullDate, groupStatus, groupVersions, projectName, sheetDate } from "../api/format";
import type { Job } from "../api/types";
import { defaultPair, diffRows, versionNumbers } from "../api/versions";
import { CompareViewer } from "../components/CompareViewer";
import { Icon } from "../components/Icon";
import { ProjectSidebar } from "../components/ProjectSidebar";
import { Segmented } from "../components/Segmented";
import { Shell } from "../components/Shell";
import { StatusBadge } from "../components/StatusBadge";
import { ROUTES } from "../routes";
import styles from "./Versions.module.css";

type Mode = "curtain" | "side";

const poster = (job: Job): string | undefined => (job.thumbnail_url ? `${job.thumbnail_url}&first=true` : undefined);
const capital = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

/** Dos videos lado a lado: el A manda y el B lo sigue; un solo control para los dos. */
function SideBySide({ a, b, labels }: { a: Job; b: Job; labels: [string, string] }) {
  const first = useRef<HTMLVideoElement>(null);
  const second = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);

  // El B sigue al A; si se desvía más de 1/15 s, se corrige.
  useEffect(() => {
    let raf = 0;
    const sync = () => {
      const x = first.current;
      const y = second.current;
      if (x && y) {
        if (Math.abs(x.currentTime - y.currentTime) > 0.066) y.currentTime = x.currentTime;
        if (x.paused !== y.paused) void (x.paused ? y.pause() : y.play());
        setTime(x.currentTime);
      }
      raf = requestAnimationFrame(sync);
    };
    raf = requestAnimationFrame(sync);
    return () => cancelAnimationFrame(raf);
  }, []);

  const toggle = () => {
    const x = first.current;
    if (!x) return;
    if (x.paused) void x.play();
    else x.pause();
  };

  return (
    <div className={styles.side}>
      <div className={styles.pair}>
        {([a, b] as const).map((job, index) => (
          <figure key={job.id}>
            <video
              ref={index === 0 ? first : second}
              src={job.output_url ?? undefined}
              poster={poster(job)}
              preload="auto"
              playsInline
              loop
              muted={index === 1}
              onLoadedMetadata={index === 0 ? (event) => setDuration(event.currentTarget.duration) : undefined}
              onPlay={index === 0 ? () => setPlaying(true) : undefined}
              onPause={index === 0 ? () => setPlaying(false) : undefined}
            />
            <figcaption>{labels[index]}</figcaption>
          </figure>
        ))}
      </div>
      <div className={styles.controls}>
        <button type="button" onClick={toggle} aria-label={playing ? "Pausar" : "Reproducir"}>
          <Icon name={playing ? "pause" : "play"} size={20} />
        </button>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(time, duration || 0)}
          onChange={(event) => {
            const t = Number(event.target.value);
            if (first.current) first.current.currentTime = t;
            if (second.current) second.current.currentTime = t;
          }}
          aria-label="Posición del video"
        />
      </div>
    </div>
  );
}

/** Las versiones de un proyecto: la lista, el comparador A/B y sus diferencias. */
export function Versions() {
  const { id: projectId = "" } = useParams();
  const [versions, setVersions] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[] | null>(null);
  const [mode, setMode] = useState<Mode>("curtain");

  useEffect(() => {
    api
      .jobs()
      .then((all) => setVersions(groupVersions(all).find((g) => g.id === projectId)?.jobs ?? []))
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [projectId]);

  const numbers = useMemo(() => versionNumbers(versions ?? []), [versions]);
  // Mientras la persona no elija, se comparan la última versión y la anterior.
  const pair = picked ?? (versions ? defaultPair(versions) : null) ?? [];
  const a = versions?.find((job) => job.id === pair[0]);
  const b = versions?.find((job) => job.id === pair[1]);
  const ready = (job?: Job): job is Job => !!job && job.status === "done" && !!job.output_url && !!job.original_url;

  const toggle = (id: string) => {
    const current = pair.filter((x) => x !== id);
    if (current.length === pair.length) setPicked([...pair, id].slice(-2));
    else setPicked(current);
  };

  const cover = versions?.find((job) => job.status === "done") ?? versions?.[0];
  const sidebar = cover ? (
    <ProjectSidebar
      projectId={projectId}
      title={projectName(cover)}
      when={sheetDate(cover.created)}
      thumbnail={cover.thumbnail_url ? `${cover.thumbnail_url}&original=true&first=true` : null}
      active="versions"
      state={versions && groupStatus(versions) === "processing" ? "processing" : "result"}
      onDownload={cover.status === "done" && cover.output_url ? () => window.location.assign(`${cover.output_url}&download=true`) : undefined}
    />
  ) : undefined;

  if (error || (versions && versions.length === 0)) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <div className={styles.empty}>
          <Icon name="alert" size={28} />
          <h2>No encontramos este proyecto</h2>
          <p>{error ?? "No hay versiones con este identificador."}</p>
          <Link to={ROUTES.library}>Volver a mis proyectos</Link>
        </div>
      </Shell>
    );
  }
  if (!versions) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <p className={styles.loading}>Cargando versiones…</p>
      </Shell>
    );
  }

  const label = (job: Job): string => `Versión ${numbers.get(job.id) ?? "?"}`;
  const labels: [string, string] | null = ready(a) && ready(b) ? [`A · ${label(a)}`, `B · ${label(b)}`] : null;

  return (
    <Shell sidebar={sidebar} footer={false}>
      <div className={styles.page}>
        <header className={styles.head}>
          <h1>Versiones</h1>
          <span className="mono">{versions.length} en total</span>
        </header>

        <section className={styles.compare} aria-label="Comparar versiones">
          {ready(a) && ready(b) && labels ? (
            <>
              <div className={styles.toolbar}>
                <h2>Comparar {label(a)} y {label(b)}</h2>
                <Segmented
                  label="Modo de comparación"
                  value={mode}
                  onChange={setMode}
                  options={[
                    { id: "curtain", label: "Cortina" },
                    { id: "side", label: "Lado a lado" },
                  ]}
                />
              </div>
              {mode === "curtain" ? (
                <CompareViewer
                  key={`${a.id}-${b.id}`}
                  original={a.output_url as string}
                  edited={b.output_url as string}
                  moments={[]}
                  originalPoster={poster(a)}
                  editedPoster={poster(b)}
                  labels={{ original: "Versión A", edited: "Versión B" }}
                />
              ) : (
                <SideBySide key={`${a.id}-${b.id}`} a={a} b={b} labels={labels} />
              )}
              <table className={styles.diff}>
                <thead>
                  <tr>
                    <th scope="col">Diferencias</th>
                    <th scope="col">A · {label(a)}</th>
                    <th scope="col">B · {label(b)}</th>
                  </tr>
                </thead>
                <tbody>
                  {diffRows(a, b).map((row) => (
                    <tr key={row.label} className={row.differs ? styles.changed : ""}>
                      <th scope="row">{row.label}</th>
                      <td>{row.a}</td>
                      <td>{row.b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className={styles.hint}>Marca dos versiones terminadas para compararlas.</p>
          )}
        </section>

        <ul className={styles.list}>
          {versions.map((job) => {
            const done = job.status === "done";
            const checked = pair.includes(job.id);
            return (
              <li key={job.id} className={checked ? styles.picked : ""}>
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!done}
                  onChange={() => toggle(job.id)}
                  aria-label={`Comparar ${label(job)}`}
                />
                <Link to={ROUTES.job(job.id)} className={styles.thumb}>
                  {job.thumbnail_url && <img src={`${job.thumbnail_url}&v=${job.status}`} alt="" loading="lazy" />}
                </Link>
                <div className={styles.info}>
                  <strong>
                    {label(job)} · {job.style_current}
                    {job.base && <em className={styles.edited}>Editada</em>}
                  </strong>
                  <div className={styles.tags}>
                    {job.tags.slice(0, 4).map((tag) => (
                      <span key={tag}>{capital(tag)}</span>
                    ))}
                  </div>
                  <span className="mono">{fullDate(job.created)}</span>
                </div>
                <StatusBadge status={groupStatus([job])} />
                <div className={styles.actions}>
                  <Link to={ROUTES.job(job.id)}>
                    <Icon name="play" size={14} /> Ver
                  </Link>
                  {job.editable && (
                    <Link to={`${ROUTES.edit(projectId)}?v=${job.id}`}>
                      <Icon name="wand" size={14} /> Editar efectos
                    </Link>
                  )}
                  {done && job.output_url && (
                    <a href={`${job.output_url}&download=true`}>
                      <Icon name="download" size={14} /> Descargar
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </Shell>
  );
}
