import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { rgb } from "../api/format";
import type { Style } from "../api/types";
import { Button } from "../components/Button";
import { Dropzone } from "../components/Dropzone";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { StyleCard } from "../components/StyleCard";
import styles from "./Studio.module.css";

const randomSeed = () => Math.floor(Math.random() * 9000) + 100;

export function Studio() {
  const navigate = useNavigate();
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [chosen, setChosen] = useState<Style | null>(null);
  const [seed, setSeed] = useState<number>(randomSeed);
  const [showPresets, setShowPresets] = useState(false);
  const [upload, setUpload] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .styles()
      .then((list) => {
        setStyleList(list);
        setChosen((current) => current ?? list.find((s) => s.kind === "catalog") ?? null);
      })
      .catch((cause: unknown) => setLoadError(cause instanceof Error ? cause.message : String(cause)));
  }, []);

  const catalogs = useMemo(() => styleList.filter((s) => s.kind === "catalog"), [styleList]);
  const presets = useMemo(() => styleList.filter((s) => s.kind === "preset"), [styleList]);
  const aurora: [string, string] | undefined = chosen?.palette[0]
    ? [rgb(chosen.palette[0], 0.2), rgb(chosen.palette[1] ?? chosen.palette[0], 0.16)]
    : undefined;

  const launch = async () => {
    if (!file || !chosen) return;
    setError(null);
    setUpload(0);
    try {
      const job = await api.create(file, chosen.kind, chosen.name, chosen.kind === "catalog" ? seed : null, setUpload);
      navigate(`/jobs/${job.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setUpload(null);
    }
  };

  return (
    <Shell aurora={aurora}>
      <section className={styles.hero}>
        <span className="eyebrow">Estudio de efectos · v1</span>
        <h1>
          Tu movimiento,
          <br />
          <span className="neon-text">dibujado en luz.</span>
        </h1>
        <p>
          Sube un plano. El estudio lee cada golpe, cada giro y cada mirada, y pinta encima neón, fuego y energía que siguen al
          cuerpo. El video original no se toca.
        </p>
        <svg className={styles.swoosh} viewBox="0 0 600 160" aria-hidden="true">
          <defs>
            <linearGradient id="sw" x1="0" x2="1">
              <stop offset="0" stopColor="#28f0d0" />
              <stop offset="0.5" stopColor="#c6ff3a" />
              <stop offset="1" stopColor="#ff3ec8" />
            </linearGradient>
          </defs>
          <path d="M10 140 C 150 -20, 380 -10, 590 90" />
          <path d="M40 150 C 190 20, 400 30, 580 120" className={styles.second} />
        </svg>
      </section>

      <section className={styles.step}>
        <header>
          <span className={styles.num}>01</span>
          <div>
            <h2>El plano</h2>
            <p>Un video vertical u horizontal. Mejor si se ve el cuerpo entero.</p>
          </div>
        </header>
        <Dropzone file={file} onFile={setFile} />
      </section>

      <section className={styles.step}>
        <header>
          <span className={styles.num}>02</span>
          <div>
            <h2>El estilo</h2>
            <p>Una coreografía decide en cada acción qué efecto dispara, con algo de azar. Un preset aplica siempre lo mismo.</p>
          </div>
        </header>
        {loadError && (
          <div className={styles.error}>
            <Icon name="alert" /> No se pudo leer la API: {loadError}. Arráncala con <code>vfxglow-api</code>.
          </div>
        )}
        <div className={styles.grid}>
          {catalogs.map((style) => (
            <StyleCard key={style.name} style={style} selected={chosen?.name === style.name} onSelect={() => setChosen(style)} />
          ))}
        </div>
        {presets.length > 0 && (
          <div className={styles.presets}>
            <button type="button" className={styles.toggle} onClick={() => setShowPresets((v) => !v)} aria-expanded={showPresets}>
              {showPresets ? "Ocultar" : "Ver"} presets fijos ({presets.length})
            </button>
            {showPresets && (
              <div className={styles.presetGrid}>
                {presets.map((style) => (
                  <StyleCard key={style.name} style={style} compact selected={chosen?.name === style.name} onSelect={() => setChosen(style)} />
                ))}
              </div>
            )}
          </div>
        )}
      </section>

      <section className={`${styles.step} ${styles.last}`}>
        <header>
          <span className={styles.num}>03</span>
          <div>
            <h2>El azar</h2>
            <p>
              La semilla fija la coreografía: la misma semilla da siempre el mismo resultado. Otra semilla, otra versión del mismo video.
            </p>
          </div>
        </header>
        <div className={`${styles.seedRow} ${chosen?.kind === "preset" ? styles.disabled : ""}`}>
          <div className={styles.seed}>
            <span className="eyebrow">Semilla</span>
            <input
              type="number"
              min={0}
              value={seed}
              onChange={(event) => setSeed(Number(event.target.value) || 0)}
              disabled={chosen?.kind === "preset"}
              aria-label="Semilla"
            />
          </div>
          <Button variant="ghost" icon="dice" type="button" onClick={() => setSeed(randomSeed())} disabled={chosen?.kind === "preset"}>
            Tirar los dados
          </Button>
          {chosen?.kind === "preset" && <span className={styles.hint}>Los presets no usan semilla.</span>}
        </div>
      </section>

      <div className={styles.launch}>
        <div className={styles.summary}>
          <span className={`${styles.dot} ${file ? styles.ok : ""}`} />
          <span>{file ? file.name : "Sin plano"}</span>
          <span className={styles.sep}>/</span>
          <span className={`${styles.dot} ${chosen ? styles.ok : ""}`} />
          <span>{chosen ? chosen.title : "Sin estilo"}</span>
          {chosen?.kind === "catalog" && <span className="mono">#{seed}</span>}
        </div>
        {upload !== null ? (
          <div className={styles.uploading}>
            <span className="mono">Subiendo {Math.round(upload * 100)}%</span>
            <div className={styles.bar}>
              <i style={{ width: `${upload * 100}%` }} />
            </div>
          </div>
        ) : (
          <Button icon="arrow" disabled={!file || !chosen} onClick={launch}>
            Revelar en neón
          </Button>
        )}
        {error && (
          <div className={styles.launchError}>
            <Icon name="alert" size={16} /> {error}
          </div>
        )}
      </div>
    </Shell>
  );
}
