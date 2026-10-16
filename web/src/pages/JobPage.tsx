import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { rgb, timecode } from "../api/format";
import { WARDROBES, type Moment, type Person, type Season, type Style, type Wardrobe } from "../api/types";
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
  const [seasonList, setSeasonList] = useState<Season[]>([]);
  // Temporada de la variación: "" = sin temporada. undefined hasta conocer la del trabajo.
  const [nextSeason, setNextSeason] = useState<string | undefined>(undefined);
  const [people, setPeople] = useState<Person[]>([]);
  // Vestuario de la variación, por persona (arranca en el del trabajo).
  const [nextWardrobe, setNextWardrobe] = useState<Record<string, Wardrobe> | null>(null);
  const [nextDeep, setNextDeep] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const viewer = useRef<CompareViewerHandle>(null);

  useEffect(() => {
    api.styles().then(setStyleList).catch(() => setStyleList([]));
    api.seasons().then(setSeasonList).catch(() => setSeasonList([]));
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
      const wear = kind === "catalog" && nextWardrobe ? nextWardrobe : null;
      const deep = kind === "catalog" ? (nextDeep ?? job.deep) : false;
      const next = await api.variation(job.id, kind, name, null, (nextSeason ?? job.season ?? "") || null, wear, deep);
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
            {job.deep && " · análisis profundo"}
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
