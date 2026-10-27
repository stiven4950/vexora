import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { buildEdits, countChanges, EMPTY, redrawSeconds, shownMoments, type Pending, type TrackChange } from "../api/editing";
import { approx, groupVersions, mmss, projectName, sheetDate } from "../api/format";
import type { EditorView, Job, Style } from "../api/types";
import { Icon } from "../components/Icon";
import { ProjectSidebar } from "../components/ProjectSidebar";
import { Shell } from "../components/Shell";
import { PreviewPlayer, type PlayerHandle } from "../components/editor/PreviewPlayer";
import { Timeline } from "../components/editor/Timeline";
import { TrackCard } from "../components/editor/TrackCard";
import { soonNotice } from "../mocks/pendientes";
import { ROUTES } from "../routes";
import styles from "./Editor.module.css";

/** Segundos de proceso por segundo de video dibujado: el de esta versión si se midió; si no, el medido en api_data. */
function renderRatio(job: Job): number {
  const compose = (job.metrics as { stages?: Record<string, number> }).stages?.compose;
  return compose && job.video_seconds ? compose / 1000 / job.video_seconds : 11;
}

/** El editor de efectos: la versión terminada, sus pistas y los cambios que crean una versión nueva. */
export function Editor() {
  const { id: projectId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [versions, setVersions] = useState<Job[] | null>(null);
  const [view, setView] = useState<EditorView | null>(null);
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(EMPTY);
  const [selected, setSelected] = useState<string | null>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const player = useRef<PlayerHandle>(null);

  useEffect(() => {
    api
      .jobs()
      .then((all) => setVersions(groupVersions(all).find((g) => g.id === projectId)?.jobs ?? []))
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
    api.styles().then(setStyleList).catch(() => setStyleList([]));
  }, [projectId]);

  // La versión que se edita: la pedida (?v=) o la más reciente que se puede editar.
  const job = useMemo(() => {
    if (!versions) return null;
    const wanted = params.get("v");
    return versions.find((v) => v.id === wanted && v.editable) ?? versions.find((v) => v.editable) ?? null;
  }, [versions, params]);

  useEffect(() => {
    if (!job) return;
    setPending(EMPTY);
    api
      .editor(job.id)
      .then(setView)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)));
  }, [job?.id]);

  const onTime = useCallback((seconds: number) => setTime(seconds), []);
  const changes = countChanges(pending);
  const tracks = view?.tracks ?? [];

  const setMoment = (id: string, patch: { removed?: boolean; start?: number; end?: number } | null) => {
    if (pending.added.some((a) => a.key === id)) {
      setPending((p) => ({ ...p, added: patch?.removed ? p.added.filter((a) => a.key !== id) : p.added.map((a) => (a.key === id ? { ...a, start: patch?.start ?? a.start, end: patch?.end ?? a.end } : a)) }));
      return;
    }
    setPending((p) => {
      const moments = { ...p.moments };
      if (patch === null) delete moments[id];
      else moments[id] = { ...(moments[id] ?? {}), ...patch };
      return { ...p, moments };
    });
  };
  const setTrack = (key: string, change: TrackChange | null) =>
    setPending((p) => {
      const next = { ...p.tracks };
      if (change === null) delete next[key];
      else next[key] = change;
      return { ...p, tracks: next };
    });

  const apply = async () => {
    if (!job || !view) return;
    setBusy(true);
    try {
      const created = await api.edit(job.id, buildEdits(pending, view.tracks));
      navigate(ROUTES.job(created.id));
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  const sidebar = job ? (
    <ProjectSidebar
      projectId={projectId}
      title={projectName(job)}
      when={sheetDate(job.created)}
      thumbnail={job.thumbnail_url ? `${job.thumbnail_url}&original=true&first=true` : null}
      active="edit"
      state="result"
      onDownload={job.output_url ? () => window.location.assign(`${job.output_url}&download=true`) : undefined}
    />
  ) : undefined;

  if (error || (versions && !job)) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <div className={styles.empty}>
          <Icon name="alert" size={28} />
          <h2>Esta versión no se puede editar</h2>
          <p>{error ?? "El editor abre las coreografías terminadas desde que existe. Crea otra versión del video y ábrela aquí."}</p>
          <Link to={ROUTES.library}>Volver a mis proyectos</Link>
        </div>
      </Shell>
    );
  }
  if (!job || !view || !job.output_url || !job.original_url) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <div className={styles.empty}>Cargando el editor…</div>
      </Shell>
    );
  }

  const style = styleList.find((s) => s.name === job.style_current);
  const filmstrip = job.thumbnail_url ? `${job.thumbnail_url.replace("/thumbnail", "/filmstrip")}&n=12` : undefined;
  const timelineTracks = tracks.map((track) => ({
    track,
    moments: shownMoments(track, pending),
    off: !!pending.tracks[track.key]?.off,
    color: pending.tracks[track.key]?.color ?? track.color,
  }));
  const seconds = redrawSeconds(pending, tracks, view.duration);
  const estimate = approx(seconds * renderRatio(job));
  const versionNumber = (versions?.length ?? 0) - (versions?.findIndex((v) => v.id === job.id) ?? 0);
  const selectedMoment = timelineTracks.flatMap((t) => t.moments).find((m) => m.id === selected) ?? null;

  return (
    <Shell sidebar={sidebar} footer={false}>
      <div className={styles.page}>
        <div className={styles.center}>
          <PreviewPlayer
            ref={player}
            original={job.original_url}
            edited={job.output_url}
            poster={job.thumbnail_url ? `${job.thumbnail_url}&first=true` : undefined}
            onTime={onTime}
            onPlaying={setPlaying}
          />
          <Timeline
            duration={view.duration}
            time={time}
            tracks={timelineTracks}
            filmstrip={filmstrip}
            selected={selected}
            playing={playing}
            onSeek={(s) => player.current?.seek(s)}
            onToggle={() => player.current?.toggle()}
            onSelect={setSelected}
            onChange={(id, start, end) => setMoment(id, { start, end })}
          />
          {selectedMoment && (
            <div className={styles.selection}>
              <span>
                <strong>{selectedMoment.choice.replace(/_/g, " ")}</strong> · {mmss(selectedMoment.start)}–{mmss(selectedMoment.end)}
                {selectedMoment.state !== "same" && <em> · {{ removed: "se quitará", moved: "movido", added: "nuevo", same: "" }[selectedMoment.state]}</em>}
              </span>
              {selectedMoment.state === "removed" || selectedMoment.state === "moved" ? (
                <button type="button" onClick={() => setMoment(selectedMoment.id, null)}>
                  <Icon name="refresh" size={14} /> Deshacer
                </button>
              ) : (
                <button type="button" onClick={() => setMoment(selectedMoment.id, { removed: true })}>
                  <Icon name="trash" size={14} /> Quitar
                </button>
              )}
            </div>
          )}
        </div>

        <aside className={styles.side}>
          <section className={styles.card}>
            <header>
              <h2>
                Efectos activos <span className={styles.count}>{tracks.filter((t) => !pending.tracks[t.key]?.off).length}</span>
              </h2>
              <span className={styles.addWrap}>
                <button type="button" className={styles.add} onClick={() => setAdding((v) => !v)}>
                  <Icon name="plus" size={14} /> Agregar efecto
                </button>
                {adding && (
                  <div className={styles.addPop} onMouseLeave={() => setAdding(false)}>
                    <strong>Agregar en {mmss(time)}</strong>
                    {tracks.map((track) => {
                      const options = view.options.filter((o) => o.track === track.key).slice(0, 8);
                      if (options.length === 0) return null;
                      return (
                        <div key={track.key}>
                          <small>{track.label}</small>
                          {options.map((o) => (
                            <button
                              key={`${o.action}:${o.option}`}
                              type="button"
                              onClick={() => {
                                const start = Math.min(time, view.duration - 0.8);
                                setPending((p) => ({ ...p, added: [...p.added, { key: `nuevo-${Date.now()}`, option: o.option, action: o.action, track: track.key, start, end: start + 0.8 }] }));
                                setAdding(false);
                              }}
                            >
                              {o.option.replace(/_/g, " ")}
                            </button>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                )}
              </span>
            </header>
            <div className={styles.tracks}>
              {tracks.map((track) => (
                <TrackCard key={track.key} track={track} change={pending.tracks[track.key]} onChange={(change) => setTrack(track.key, change)} />
              ))}
            </div>
          </section>

          <section className={styles.card}>
            <header>
              <h2>Configuración del proyecto</h2>
              <Link to={ROUTES.job(job.id)} className={styles.edit}>
                <Icon name="edit" size={14} /> Editar
              </Link>
            </header>
            <dl className={styles.config}>
              <div><dt>Estilo</dt><dd>{style?.title ?? job.style_current}</dd></div>
              <div><dt>Análisis</dt><dd>{job.deep ? "Profundo con IA" : "Económico"}</dd></div>
              <div><dt>Duración del video</dt><dd>{mmss(view.duration)}</dd></div>
              <div><dt>Resolución</dt><dd>{job.video_width && job.video_height ? `${Math.min(job.video_width, job.video_height)}p${Math.min(job.video_width, job.video_height) >= 1080 ? " (Full HD)" : ""}` : "—"}</dd></div>
              <div><dt>Versión</dt><dd>{versionNumber}</dd></div>
            </dl>
          </section>

          {changes > 0 && (
            <section className={`${styles.card} ${styles.pending}`}>
              <p>
                <strong>{changes} {changes === 1 ? "cambio" : "cambios"} sin aplicar.</strong> Se redibujan unos {Math.round(seconds)} s del video, el resto se conserva.
              </p>
              <button type="button" className={styles.apply} onClick={apply} disabled={busy}>
                {busy ? "Creando la versión…" : `Aplicar cambios (≈ ${estimate})`}
              </button>
              <button type="button" className={styles.discard} onClick={() => setPending(EMPTY)} disabled={busy}>
                Descartar
              </button>
            </section>
          )}

          <a className={styles.download} href={`${job.output_url}&download=true`}>
            <Icon name="download" size={18} /> Descargar video
          </a>
          {/* PENDIENTE(fase 3): compartir con un enlace público revocable. */}
          <button type="button" className={styles.share} onClick={() => soonNotice("Compartir")}>
            <Icon name="share" size={18} /> Compartir
          </button>
        </aside>
      </div>
    </Shell>
  );
}

