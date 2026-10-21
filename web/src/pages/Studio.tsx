import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { rgb } from "../api/format";
import { WARDROBES, type Looks, type Season, type Style, type Wardrobe } from "../api/types";
import { Button } from "../components/Button";
import { Dropzone } from "../components/Dropzone";
import { Icon } from "../components/Icon";
import { Shell } from "../components/Shell";
import { StyleCard } from "../components/StyleCard";
import styles from "./Studio.module.css";

export function Studio() {
  const navigate = useNavigate();
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [chosen, setChosen] = useState<Style | null>(null);
  const [seasonList, setSeasonList] = useState<Season[]>([]);
  const [season, setSeason] = useState<string | null>(null);
  const [wardrobe, setWardrobe] = useState<Wardrobe>("ninguno");
  // Análisis profundo: opcional, más lento y de pago. Por defecto, el económico.
  const [deep, setDeep] = useState(false);
  // Estilos de fuego y de rayo (director/looks.py); null = los del estilo elegido.
  const [looks, setLooks] = useState<Looks>({ fuego: [], rayo: [] });
  const [fireStyle, setFireStyle] = useState<string | null>(null);
  const [boltStyle, setBoltStyle] = useState<string | null>(null);
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
    // Las temporadas son opcionales: si la API no las tiene, simplemente no se muestran.
    api.seasons().then(setSeasonList).catch(() => setSeasonList([]));
    api.looks().then(setLooks).catch(() => setLooks({ fuego: [], rayo: [] }));
  }, []);
  const suggested = seasonList.find((s) => s.suggested) ?? null;

  // Fuego y rayo solo en los estilos que los dibujan (el avatar); los pasos se numeran en orden.
  const hasFire = chosen?.kind === "catalog" && chosen.tags.some((t) => t === "fuego" || t === "rayos") && looks.fuego.length > 0;
  let step = 2;
  const nextStep = () => String(++step).padStart(2, "0");
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
      // Sin semilla: el servidor prueba varias coreografías y se queda con la mejor.
      const wear: Record<string, Wardrobe> = chosen.kind === "catalog" && wardrobe !== "ninguno" ? { "*": wardrobe } : {};
      const job = await api.create(file, chosen.kind, chosen.name, null, setUpload, season, wear, chosen.kind === "catalog" && deep, hasFire ? fireStyle : null, hasFire ? boltStyle : null);
      navigate(`/jobs/${job.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setUpload(null);
    }
  };

  return (
    <Shell aurora={aurora}>
      <section className={styles.hero}>
        <span className="eyebrow">VEXORA Studio · efectos visuales con IA</span>
        <h1>
          Tu movimiento,
          <br />
          <span className="neon-text">más allá de lo real.</span>
        </h1>
        <p>
          Sube un plano. La IA lee cada gesto, cada giro y hacia dónde va la energía, y crea encima los efectos que esa escena pide.
          El video original no se toca.
        </p>
        <svg className={styles.swoosh} viewBox="0 0 600 160" aria-hidden="true">
          <defs>
            <linearGradient id="sw" x1="0" x2="1">
              <stop offset="0" stopColor="#67e8f9" />
              <stop offset="0.5" stopColor="#8b5cf6" />
              <stop offset="1" stopColor="#ec4899" />
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
            <p>Una coreografía decide en cada momento qué efecto dispara y elige sola la mejor versión para tu video. Un preset aplica siempre lo mismo.</p>
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

      {seasonList.length > 0 && (
        <section className={`${styles.step} ${chosen?.kind === "catalog" ? "" : styles.last}`}>
          <header>
            <span className={styles.num}>{nextStep()}</span>
            <div>
              <h2>Toque de temporada</h2>
              <p>
                {suggested
                  ? `Estamos en temporada de ${suggested.title} ${suggested.emoji}. Puedes darle esa decoración y paleta a tu video.`
                  : "Opcional: una decoración y una paleta de época encima del estilo elegido."}
              </p>
            </div>
          </header>
          <div className={styles.seasons}>
            <button type="button" className={`${styles.season} ${season === null ? styles.on : ""}`} onClick={() => setSeason(null)}>
              Sin temporada
            </button>
            {[...seasonList]
              .sort((a, b) => Number(b.suggested) - Number(a.suggested))
              .map((s) => (
                <button
                  key={s.id}
                  type="button"
                  title={s.description}
                  className={`${styles.season} ${season === s.id ? styles.on : ""}`}
                  onClick={() => setSeason(s.id)}
                >
                  <span aria-hidden="true">{s.emoji}</span> {s.title}
                  {s.suggested && <span className={styles.badge}>de temporada</span>}
                  <span className={styles.swatches}>
                    {s.palette.slice(0, 4).map((c, i) => (
                      <i key={i} style={{ background: rgb(c) }} />
                    ))}
                  </span>
                </button>
              ))}
          </div>
        </section>
      )}

      {hasFire && (
        <section className={styles.step}>
          <header>
            <span className={styles.num}>{nextStep()}</span>
            <div>
              <h2>Fuego y rayo</h2>
              <p>Cómo se pintan el fuego y los rayos de este estilo. La coreografía es la misma: cambia el look.</p>
            </div>
          </header>
          <div className={styles.seasons}>
            <button type="button" className={`${styles.season} ${fireStyle === null ? styles.on : ""}`} onClick={() => setFireStyle(null)}>
              Fuego del estilo
            </button>
            {looks.fuego
              .filter((look) => look.id !== "clasico")
              .map((look) => (
                <button key={look.id} type="button" title={look.description} className={`${styles.season} ${fireStyle === look.id ? styles.on : ""}`} onClick={() => setFireStyle(look.id)}>
                  🔥 {look.title}
                </button>
              ))}
          </div>
          <div className={styles.seasons}>
            <button type="button" className={`${styles.season} ${boltStyle === null ? styles.on : ""}`} onClick={() => setBoltStyle(null)}>
              Rayo del estilo
            </button>
            {looks.rayo
              .filter((look) => look.id !== "cian")
              .map((look) => (
                <button key={look.id} type="button" title={look.description} className={`${styles.season} ${boltStyle === look.id ? styles.on : ""}`} onClick={() => setBoltStyle(look.id)}>
                  ⚡ {look.title}
                </button>
              ))}
          </div>
        </section>
      )}

      {chosen?.kind === "catalog" && (
        <section className={styles.step}>
          <header>
            <span className={styles.num}>{nextStep()}</span>
            <div>
              <h2>Vestuario</h2>
              <p>Opcional: de vez en cuando se dibuja una prenda de cuerpo entero sobre las personas. Después, en la página del video, puedes elegirla para cada persona por separado.</p>
            </div>
          </header>
          <div className={styles.seasons}>
            {WARDROBES.map((w) => (
              <button key={w.id} type="button" className={`${styles.season} ${wardrobe === w.id ? styles.on : ""}`} onClick={() => setWardrobe(w.id)}>
                {w.label}
              </button>
            ))}
          </div>
        </section>
      )}

      {chosen?.kind === "catalog" && (
        <section className={`${styles.step} ${styles.last}`}>
          <header>
            <span className={styles.num}>{nextStep()}</span>
            <div>
              <h2>Análisis</h2>
              <p>
                El económico reacciona a cada gesto. El profundo le pasa el video completo, con su música, a una IA que lo lee
                como un animador: entiende la intención de cada movimiento y arma metáforas con historia. Tarda unos minutos más
                y tiene costo.
              </p>
            </div>
          </header>
          <div className={styles.seasons}>
            <button type="button" className={`${styles.season} ${!deep ? styles.on : ""}`} onClick={() => setDeep(false)}>
              Económico
            </button>
            <button type="button" className={`${styles.season} ${deep ? styles.on : ""}`} onClick={() => setDeep(true)}>
              ✦ Profundo con IA
            </button>
          </div>
        </section>
      )}

      <div className={styles.launch}>
        <div className={styles.summary}>
          <span className={`${styles.dot} ${file ? styles.ok : ""}`} />
          <span>{file ? file.name : "Sin plano"}</span>
          <span className={styles.sep}>/</span>
          <span className={`${styles.dot} ${chosen ? styles.ok : ""}`} />
          <span>{chosen ? chosen.title : "Sin estilo"}</span>
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
