import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { projectName, rgb, sheetDate, timecode } from "../api/format";
import { notifyDone } from "../api/notify";
import { ROUTES } from "../routes";
import { WARDROBES, type Job, type Looks, type Moment, type Person, type Season, type Style, type Wardrobe } from "../api/types";
import { Button } from "../components/Button";
import { ChoreographyPanel } from "../components/ChoreographyPanel";
import { CompareViewer, type CompareViewerHandle } from "../components/CompareViewer";
import { Icon } from "../components/Icon";
import { PrepareButton } from "../components/editor/PrepareButton";
import { ProcessingView, type AppliedConfig } from "../components/ProcessingView";
import { ProjectSidebar } from "../components/ProjectSidebar";
import { CloudActions } from "../components/CloudActions";
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
  const { job: loaded, error } = useJob(id);
  // El nombre que la persona acaba de poner: se ve ya, sin esperar al siguiente aviso del servidor.
  const [renamed, setRenamed] = useState<string | null>(null);
  // Guardar en la nube o quitarlo cambia el trabajo sin que llegue otro evento del servidor.
  const [cloud, setCloud] = useState<Pick<Job, "saved" | "keep_until"> | null>(null);
  const titled = loaded && renamed !== null ? { ...loaded, title: renamed || null } : loaded;
  const job = titled && cloud ? { ...titled, ...cloud } : titled;
  const [cancelling, setCancelling] = useState(false);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [nextStyle, setNextStyle] = useState<string>("");
  const [seasonList, setSeasonList] = useState<Season[]>([]);
  // Temporada de la variación: "" = sin temporada. undefined hasta conocer la del trabajo.
  const [nextSeason, setNextSeason] = useState<string | undefined>(undefined);
  const [people, setPeople] = useState<Person[]>([]);
  // Vestuario de la variación, por persona (arranca en el del trabajo).
  const [nextWardrobe, setNextWardrobe] = useState<Record<string, Wardrobe> | null>(null);
  const [nextDeep, setNextDeep] = useState<boolean | null>(null);
  // Estilos de fuego y de rayo de la variación: "" = los del estilo; undefined = los del trabajo.
  const [looks, setLooks] = useState<Looks>({ fuego: [], rayo: [] });
  const [nextFire, setNextFire] = useState<string | undefined>(undefined);
  const [nextBolt, setNextBolt] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const viewer = useRef<CompareViewerHandle>(null);

  useEffect(() => {
    api.styles().then(setStyleList).catch(() => setStyleList([]));
    api.seasons().then(setSeasonList).catch(() => setSeasonList([]));
    api.looks().then(setLooks).catch(() => setLooks({ fuego: [], rayo: [] }));
  }, []);

  useEffect(() => {
    if (job?.status === "done") api.choreography(job.id).then(setMoments).catch(() => setMoments([]));
    if (job?.status === "done" && job.style_kind === "catalog")
      api
        .people(job.id)
        .then((list) => {
          setPeople(list);
          setNextWardrobe((current) => current ?? Object.fromEntries(list.map((p) => [p.id, job.wardrobe[p.id] ?? job.wardrobe["*"] ?? "ninguno"])));
        })
        .catch(() => setPeople([]));
    if (job) setNextStyle((current) => current || `${job.style_kind_current}:${job.style_current}`);
    if (job) setNextSeason((current) => (current === undefined ? (job.season ?? "") : current));
    if (job) setNextFire((current) => (current === undefined ? (job.fire_style ?? "") : current));
    if (job) setNextBolt((current) => (current === undefined ? (job.bolt_style ?? "") : current));
  }, [job?.status, job?.id]);

  const current = styleList.find((s) => s.name === job?.style_current);
  const [nextKind, nextName] = nextStyle.split(":");
  const nextChosen = styleList.find((s) => s.kind === nextKind && s.name === nextName);
  const nextHasFire = nextKind === "catalog" && !!nextChosen?.tags.some((t) => t === "fuego" || t === "rayos") && looks.fuego.length > 0;
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
      const wear = kind === "catalog" && nextWardrobe ? nextWardrobe : null;
      const deep = kind === "catalog" ? (nextDeep ?? job.deep) : false;
      // "" pide los del estilo; sin fuego en el estilo, tampoco se mandan.
      const fire = nextHasFire ? (nextFire ?? "") : "";
      const bolt = nextHasFire ? (nextBolt ?? "") : "";
      const next = await api.variation(job.id, kind, name, null, (nextSeason ?? job.season ?? "") || null, wear, deep, fire, bolt);
      navigate(ROUTES.job(next.id));
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  // El avance en el título de la pestaña, y un aviso del navegador cuando termina con la pestaña oculta.
  const lastStatus = useRef<string | null>(null);
  useEffect(() => {
    if (!job) return;
    const waiting = job.status === "queued" || job.status === "running";
    document.title = waiting ? `${Math.round(job.progress * 100)}% · VEXORA` : "VEXORA";
    if (lastStatus.current === "queued" || lastStatus.current === "running") {
      if (job.status === "done") notifyDone("Tu video está listo", job.filename);
      if (job.status === "failed") notifyDone("El revelado falló", `${job.filename}: abre VEXORA para reintentar.`);
    }
    lastStatus.current = job.status;
  }, [job?.status, job?.progress]);
  useEffect(() => () => void (document.title = "VEXORA"), []);

  // Mismo trabajo, misma petición: el servidor lo vuelve a encolar y la página sigue su progreso.
  const retry = async () => {
    if (!job) return;
    setBusy(true);
    setActionError(null);
    try {
      await api.retry(job.id);
      window.location.reload();
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const rename = async () => {
    if (!job) return;
    const title = window.prompt("Nombre del proyecto", projectName(job));
    if (title === null) return;
    try {
      const updated = await api.rename(job.id, title);
      setRenamed(updated.title ?? "");
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : String(cause));
    }
  };

  // Cancelar borra el video y todo lo que se hizo con él: se pide confirmación.
  const cancel = async () => {
    if (!job || !window.confirm("¿Cancelar el procesamiento? Se borrará este video y lo que se haya hecho con él.")) return;
    setCancelling(true);
    try {
      await api.cancel(job.id);
      navigate(ROUTES.library);
    } catch (cause) {
      setCancelling(false);
      window.alert(cause instanceof Error ? cause.message : String(cause));
    }
  };

  if (error) {
    return (
      <Shell>
        <div className={styles.failed}>
          <Icon name="alert" size={28} />
          <h2>No se encontró el trabajo</h2>
          <p>{error}</p>
          <Link to={ROUTES.studio}>Volver al estudio</Link>
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

  const waiting = job.status === "queued" || job.status === "running";
  const config: AppliedConfig = {
    style: current?.title ?? job.style,
    season: seasonList.find((s) => s.id === job.season)?.title ?? "Sin temporada",
    looks:
      [job.fire_style && looks.fuego.find((l) => l.id === job.fire_style)?.title, job.bolt_style && looks.rayo.find((l) => l.id === job.bolt_style)?.title].filter(Boolean).join(" / ") || "Los del estilo",
    wardrobe: Object.keys(job.wardrobe).length > 1 ? "Por persona" : (WARDROBES.find((w) => w.id === (job.wardrobe["*"] ?? Object.values(job.wardrobe)[0] ?? "ninguno"))?.label ?? "Sin prendas"),
    analysis: job.deep ? "Profundo con IA" : "Económico",
  };
  const sidebar = (
    <ProjectSidebar
      projectId={job.parent ?? job.id}
      title={projectName(job)}
      when={sheetDate(job.created)}
      thumbnail={job.thumbnail_url ? `${job.thumbnail_url}&original=true&first=true` : null}
      active={waiting ? "processing" : "result"}
      state={waiting ? "processing" : "result"}
      onRename={rename}
      onDownload={job.status === "done" && job.output_url ? () => window.location.assign(`${job.output_url}&download=true`) : undefined}
    />
  );

  if (waiting) {
    return (
      <Shell aurora={aurora} sidebar={sidebar} footer={false}>
        <ProcessingView job={job} config={config} onCancel={cancel} onRename={rename} cancelling={cancelling} />
      </Shell>
    );
  }

  return (
    <Shell aurora={aurora} sidebar={sidebar} footer={false}>
      <header className={styles.head}>
        <Link to={ROUTES.library} className={styles.back}>
          <Icon name="back" size={16} /> Biblioteca
        </Link>
        <div className={styles.title}>
          <span className="eyebrow">
            {current?.title ?? job.style}
            {job.style_kind === "catalog" && ` · ${versionLabel(job)}`}
            {job.season && ` · ${job.season.replace(/_/g, " ")}`}
            {job.deep && " · análisis profundo"}
            {job.fire_style && ` · fuego ${looks.fuego.find((l) => l.id === job.fire_style)?.title.toLowerCase() ?? job.fire_style}`}
            {job.bolt_style && ` · rayo ${looks.rayo.find((l) => l.id === job.bolt_style)?.title.toLowerCase() ?? job.bolt_style}`}
          </span>
          <h1>{job.filename}</h1>
        </div>
        <span className={`${styles.status} ${styles[job.status]}`}>
          {{ queued: "En cola", running: "Procesando", done: "Listo", failed: "Falló" }[job.status]}
        </span>
      </header>

      {job.status === "failed" && (
        <div className={styles.failed}>
          <Icon name="alert" size={28} />
          <h2>El revelado falló</h2>
          <p>{job.error ?? "Algo falló al revelar tu video."}</p>
          <Button icon="spark" disabled={busy} onClick={retry}>
            Reintentar
          </Button>
          {actionError && <span className={styles.error}>{actionError}</span>}
          <p className="mono">Referencia: {job.trace_id.slice(0, 12)}</p>
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
            {job.editable && (
              <Link to={`${ROUTES.edit(job.parent ?? job.id)}?v=${job.id}`} className={styles.editLink}>
                <Icon name="wand" size={18} /> Editar efectos
              </Link>
            )}
            {!job.editable && job.preparable && (
              <PrepareButton job={job} className={styles.editLink} onDone={(ready) => navigate(`${ROUTES.edit(ready.parent ?? ready.id)}?v=${ready.id}`)} />
            )}
            <section className={styles.card}>
              <span className="eyebrow">Exportar</span>
              <a className={styles.download} href={`${job.output_url}&download=true`}>
                <Icon name="download" /> Descargar MP4
              </a>
              <CloudActions job={job} title={projectName(job)} onChange={(next) => setCloud({ saved: next.saved, keep_until: next.keep_until })} />
              {job.duration && <span className={styles.meta}>Revelado en {timecode(job.duration)}</span>}
            </section>

            <section className={styles.card}>
              <span className="eyebrow">¿Otra opción?</span>
              <p>Probamos otra coreografía buena para el mismo video, con otro estilo o con otra temporada. No se vuelve a analizar: tarda poco.</p>
              <label className={styles.pick}>
                <span>Estilo</span>
                <select value={nextStyle} onChange={(event) => setNextStyle(event.target.value)}>
                {styleList.map((style) => (
                  <option key={`${style.kind}:${style.name}`} value={`${style.kind}:${style.name}`}>
                    {style.kind === "catalog" ? "◆ " : "◇ "}
                    {style.title}
                  </option>
                ))}
                </select>
              </label>
              {seasonList.length > 0 && (
                <label className={styles.pick}>
                  <span>Temporada</span>
                  <select value={nextSeason ?? ""} onChange={(event) => setNextSeason(event.target.value)}>
                    <option value="">Sin temporada</option>
                    {[...seasonList]
                      .sort((a, b) => Number(b.suggested) - Number(a.suggested))
                      .map((season) => (
                        <option key={season.id} value={season.id}>
                          {season.emoji} {season.title}
                          {season.suggested ? " · de temporada" : ""}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              {people.length > 0 && nextWardrobe && nextStyle.startsWith("catalog:") && (
                <div className={styles.pick}>
                  <span>Vestuario</span>
                  <ul className={styles.people}>
                    {people.map((person) => (
                      <li key={person.id}>
                        <img src={person.image_url} alt={person.label} loading="lazy" />
                        <label>
                          <span>{person.label}</span>
                          <select
                            value={nextWardrobe[person.id] ?? "ninguno"}
                            onChange={(event) => setNextWardrobe((current) => ({ ...(current ?? {}), [person.id]: event.target.value as Wardrobe }))}
                          >
                            {WARDROBES.map((w) => (
                              <option key={w.id} value={w.id}>
                                {w.label}
                              </option>
                            ))}
                          </select>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {nextHasFire && (
                <label className={styles.pick}>
                  <span>Fuego</span>
                  <select value={nextFire ?? ""} onChange={(event) => setNextFire(event.target.value)}>
                    <option value="">Fuego del estilo</option>
                    {looks.fuego
                      .filter((look) => look.id !== "clasico")
                      .map((look) => (
                        <option key={look.id} value={look.id}>
                          🔥 {look.title}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              {nextHasFire && (
                <label className={styles.pick}>
                  <span>Rayo</span>
                  <select value={nextBolt ?? ""} onChange={(event) => setNextBolt(event.target.value)}>
                    <option value="">Rayo del estilo</option>
                    {looks.rayo
                      .filter((look) => look.id !== "cian")
                      .map((look) => (
                        <option key={look.id} value={look.id}>
                          ⚡ {look.title}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              {nextStyle.startsWith("catalog:") && (
                <label className={styles.pick}>
                  <span>Análisis</span>
                  <select value={(nextDeep ?? job.deep) ? "deep" : "fast"} onChange={(event) => setNextDeep(event.target.value === "deep")}>
                    <option value="fast">Económico</option>
                    <option value="deep">✦ Profundo con IA (más lento, con costo)</option>
                  </select>
                </label>
              )}
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
