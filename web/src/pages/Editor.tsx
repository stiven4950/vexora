import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { effectLabel } from "../api/effectLabels";
import { buildEdits, countChanges, EMPTY, groupOptions, isPermanent, redrawSeconds, shownMoments, withPending, type Pending, type TrackChange } from "../api/editing";
import { approx, groupVersions, mmss, projectName, sheetDate } from "../api/format";
import { liveState } from "../api/liveLayers";
import type { EditorView, Job, LayersView, PreviewView, Style } from "../api/types";
import { Icon } from "../components/Icon";
import { ProjectSidebar } from "../components/ProjectSidebar";
import { ShareDialog } from "../components/ShareDialog";
import { Shell } from "../components/Shell";
import { PreviewPlayer, type PlayerHandle } from "../components/editor/PreviewPlayer";
import { PrepareButton } from "../components/editor/PrepareButton";
import { Timeline } from "../components/editor/Timeline";
import { TrackCard } from "../components/editor/TrackCard";
import { ROUTES } from "../routes";
import styles from "./Editor.module.css";

/** Segundos de proceso por segundo de video dibujado: el de esta versión si se midió; si no, el medido en api_data. */
function renderRatio(job: Job): number {
  const compose = (job.metrics as { stages?: Record<string, number> }).stages?.compose;
  return compose && job.video_seconds ? compose / 1000 / job.video_seconds : 11;
}

/** Lado largo con el que el servidor dibuja la vista previa (MAX_SIDE en api/previews.py). */
const PREVIEW_SIDE = 640;

/** Una vista previa dibuja 5 s (3 s de clip + 2 s de calentamiento) a PREVIEW_SIDE, más ~5 s de
 * preparar el motor. Dibujar más pequeño cuesta según el área, pero no baja del 40 % (medido en
 * 1280 px: 31 → 10 s; Avatar 44 → 22 s). */
function previewSeconds(job: Job): number {
  const long = Math.max(job.video_width ?? 0, job.video_height ?? 0);
  const scale = long > PREVIEW_SIDE ? Math.max((PREVIEW_SIDE / long) ** 2, 0.4) : 1;
  return Math.round(5 * renderRatio(job) * scale + 5);
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
  const [sharing, setSharing] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const player = useRef<PlayerHandle>(null);
  // Vista previa rápida: lo pedido (con los cambios que tenía) y su estado.
  const [preview, setPreview] = useState<{ id: string; key: string; view: PreviewView | null; error?: string } | null>(null);
  const [showClip, setShowClip] = useState(false);
  // Vista en vivo: las capas de la versión; se sondean mientras se dibujan.
  const [layers, setLayers] = useState<LayersView | null>(null);
  const [layersError, setLayersError] = useState<string | null>(null);
  const [showLive, setShowLive] = useState(0);
  const autoLive = useRef(false);

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

  // Sondea la vista previa cada 1 s hasta que esté lista o falle; se cancela al desmontar o al pedir otra.
  const previewId = preview?.id;
  useEffect(() => {
    if (!job || !previewId) return;
    let live = true;
    let timer = 0;
    const poll = async () => {
      try {
        const next = await api.getPreview(job.id, previewId);
        if (!live) return;
        setPreview((p) => (p && p.id === previewId ? { ...p, view: next } : p));
        if (next.status === "rendering") timer = window.setTimeout(poll, 1000);
        else if (next.status === "ready") setShowClip(true);
      } catch (cause) {
        if (live) setPreview((p) => (p && p.id === previewId ? { ...p, error: cause instanceof Error ? cause.message : String(cause) } : p));
      }
    };
    void poll();
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [job?.id, previewId]);

  useEffect(() => {
    setPreview(null);
    setShowClip(false);
  }, [job?.id]);

  const requestPreview = async () => {
    if (!job || !view) return;
    const edits = buildEdits(pending, view.tracks);
    const key = JSON.stringify(edits);
    setShowClip(false);
    setPreview({ id: "", key, view: null });
    try {
      const created = await api.preview(job.id, edits, time);
      setPreview({ id: created.preview_id, key, view: created });
    } catch (cause) {
      setPreview({ id: "", key, view: null, error: cause instanceof Error ? cause.message : String(cause) });
    }
  };

  // Al abrir la versión pregunta por las capas; mientras se dibujan, sondea cada 1,5 s (se cancela al desmontar o cambiar de versión).
  const layersStatus = layers?.status;
  useEffect(() => {
    if (!job) return;
    setLayers(null);
    setLayersError(null);
    let live = true;
    api
      .layers(job.id)
      .then((next) => live && setLayers(next))
      .catch((cause: unknown) => live && setLayersError(cause instanceof Error ? cause.message : String(cause)));
    return () => {
      live = false;
    };
  }, [job?.id]);

  useEffect(() => {
    if (!job || layersStatus !== "rendering") return;
    let live = true;
    let timer = 0;
    const poll = async () => {
      try {
        const next = await api.layers(job.id);
        if (!live) return;
        setLayers(next);
        if (next.status === "rendering") timer = window.setTimeout(poll, 1500);
      } catch (cause) {
        if (live) setLayersError(cause instanceof Error ? cause.message : String(cause));
      }
    };
    timer = window.setTimeout(poll, 1500);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [job?.id, layersStatus]);

  // La primera vez que quedan listas en esta sesión, el reproductor pasa a "En vivo".
  useEffect(() => {
    if (layersStatus === "ready" && !autoLive.current) {
      autoLive.current = true;
      setShowLive((n) => n + 1);
    }
  }, [layersStatus]);

  const requestLayers = async () => {
    if (!job) return;
    setLayersError(null);
    try {
      setLayers(await api.createLayers(job.id));
    } catch (cause) {
      setLayersError(cause instanceof Error ? cause.message : String(cause));
    }
  };

  const liveReady = layers?.status === "ready" && layers.url && layers.layout ? { url: layers.url, layout: layers.layout } : null;
  const liveView = useMemo(() => (liveReady && view ? liveState(liveReady.layout, view.tracks, pending) : null), [liveReady?.layout, view, pending]);

  const onTime = useCallback((seconds: number) => setTime(seconds), []);
  const changes = countChanges(pending);
  // Las pistas del servidor más las filas nuevas que crean los efectos agregados.
  const tracks = useMemo(() => (view ? withPending(view.tracks, pending) : []), [view, pending]);

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

  const preparable = !error && versions && !job ? (versions.find((v) => v.id === params.get("v") && v.preparable) ?? versions.find((v) => v.preparable)) : undefined;
  if (preparable) {
    return (
      <Shell sidebar={sidebar} footer={false}>
        <div className={styles.empty}>
          <Icon name="wand" size={28} />
          <h2>Falta preparar esta versión</h2>
          <p>Se hizo antes del editor. Prepararla toma unos segundos y no cambia el video.</p>
          <PrepareButton
            job={preparable}
            className={styles.prepare}
            onDone={(ready) => {
              setVersions((all) => all && all.map((v) => (v.id === ready.id ? ready : v)));
              navigate(`${ROUTES.edit(projectId)}?v=${ready.id}`, { replace: true });
            }}
          />
        </div>
      </Shell>
    );
  }
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
  const selectedFixed = timelineTracks.some((t) => isPermanent(t.track.key) && t.moments.some((m) => m.id === selected));
  const groups = groupOptions(view.options, query, effectLabel);

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
            clip={showClip && preview?.view?.status === "ready" && preview.view.url ? { url: preview.view.url, start: preview.view.start, end: preview.view.end, stale: preview.key !== JSON.stringify(buildEdits(pending, view.tracks)) } : null}
            onCloseClip={() => setShowClip(false)}
            live={liveReady && liveView ? { ...liveReady, state: liveView } : null}
            showLive={showLive}
          />
          {preview && !preview.error && preview.view?.status !== "ready" && preview.view?.status !== "failed" && <p className={styles.previewNote} role="status">Generando vista previa…</p>}
          {preview && (preview.error || preview.view?.status === "failed") && <p className={styles.previewNote} role="alert">{preview.error ?? preview.view?.error}</p>}
          {liveView && liveView.approximate.length > 0 && (
            <p className={styles.previewNote}>En vivo no se ve: {liveView.approximate.join(", ")} (mover o agregar). Usa Vista previa o aplica los cambios.</p>
          )}
          {layers?.status === "rendering" && !layersError && <p className={styles.previewNote} role="status">Preparando la vista en vivo…</p>}
          {(layersError || layers?.status === "failed") && <p className={styles.previewNote} role="alert">{layersError ?? layers?.error ?? "No se pudo preparar la vista en vivo."}</p>}
          {layers && (layers.status === "none" || layers.status === "failed") && (
            <button type="button" className={styles.previewBtn} onClick={requestLayers}>
              <Icon name="play" size={14} /> Activar vista en vivo (≈ {Math.round(layers.estimate_s)} s)
            </button>
          )}
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
                <strong>{effectLabel(selectedMoment.choice)}</strong> · {mmss(selectedMoment.start)}–{mmss(selectedMoment.end)}
                {selectedMoment.state !== "same" && <em> · {{ removed: "se quitará", moved: "movido", added: "nuevo", same: "" }[selectedMoment.state]}</em>}
              </span>
              {selectedFixed ? null : selectedMoment.state === "removed" || selectedMoment.state === "moved" ? (
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
                  <div className={styles.addPop}>
                    <strong>Agregar en {mmss(time)}</strong>
                    <input
                      type="search"
                      className={styles.search}
                      placeholder="Buscar efecto…"
                      value={query}
                      autoFocus
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => event.key === "Escape" && setAdding(false)}
                    />
                    {groups.length === 0 && <small>Sin resultados</small>}
                    {groups.map((group) => (
                      <div key={group.title}>
                        <small>{group.title}</small>
                        {group.options.map((o) => (
                          <button
                            key={`${o.action}:${o.option}`}
                            type="button"
                            onClick={() => {
                              const start = Math.max(Math.min(time, view.duration - 0.8), 0);
                              setPending((p) => ({ ...p, added: [...p.added, { key: `nuevo-${Date.now()}`, option: o.option, action: o.action, track: o.track, element: o.element, start, end: start + 0.8 }] }));
                              setAdding(false);
                              setQuery("");
                            }}
                          >
                            {effectLabel(o.option)}
                          </button>
                        ))}
                      </div>
                    ))}
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
              <button type="button" className={styles.previewBtn} onClick={requestPreview} disabled={busy || (!!preview && !preview.error && preview.view?.status !== "ready" && preview.view?.status !== "failed")}>
                <Icon name="play" size={14} /> Vista previa (≈ {previewSeconds(job)} s)
              </button>
              <button type="button" className={styles.discard} onClick={() => setPending(EMPTY)} disabled={busy}>
                Descartar
              </button>
            </section>
          )}

          <a className={styles.download} href={`${job.output_url}&download=true`}>
            <Icon name="download" size={18} /> Descargar video
          </a>
          <button type="button" className={styles.share} onClick={() => setSharing(true)}>
            <Icon name="share" size={18} /> Compartir
          </button>
          {sharing && <ShareDialog jobId={job.id} title={projectName(job)} onClose={() => setSharing(false)} />}
        </aside>
      </div>
    </Shell>
  );
}

