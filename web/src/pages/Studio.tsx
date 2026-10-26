import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { rgb } from "../api/format";
import { askPermission } from "../api/notify";
import { WARDROBES, type Limits, type Looks, type Season, type Style, type Wardrobe } from "../api/types";
import { ChoiceCard } from "../components/ChoiceCard";
import { Dropzone, problems, type VideoMeta } from "../components/Dropzone";
import { Icon } from "../components/Icon";
import { NeonPreview } from "../components/NeonPreview";
import { Shell } from "../components/Shell";
import { StepCard } from "../components/StepCard";
import { StudioAside } from "../components/StudioAside";
import { StyleTile } from "../components/StyleTile";
import { Tile } from "../components/Tile";
import { SURPRISE_STYLES } from "../mocks/pendientes";
import { ROUTES } from "../routes";
import styles from "./Studio.module.css";

/** Los filtros de estilo del diseño: cada elemento tiene su catálogo; "Otros" junta el resto. */
const FILTERS = [
  { id: "all", label: "Todos" },
  { id: "avatar", label: "Avatar" },
  { id: "fuego", label: "Fuego" },
  { id: "agua", label: "Agua" },
  { id: "rayo", label: "Rayo" },
  { id: "tierra", label: "Tierra" },
  { id: "viento", label: "Viento" },
  { id: "other", label: "Otros" },
] as const;
type Filter = (typeof FILTERS)[number]["id"];

const NAMED = new Set<string>(FILTERS.map((f) => f.id).filter((id) => id !== "all" && id !== "other"));

/** El color de cada look, para su icono (director/looks.py los define por nombre). */
const LOOK_COLOR: Record<string, string> = {
  clasico: "#ff8a1f",
  plano: "#ffd23f",
  mixto: "#ff9a2e",
  azul: "#4aa3ff",
  verde: "#5be05b",
  pixel: "#ff7a1a",
  cian: "#35e0ff",
  blanco: "#e8f1ff",
  violeta: "#b06bff",
  rojo: "#ff4d5e",
  fuego: "#ff9a2e",
};

export function Studio() {
  const navigate = useNavigate();
  const [styleList, setStyleList] = useState<Style[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [chosen, setChosen] = useState<Style | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [seasonList, setSeasonList] = useState<Season[]>([]);
  const [season, setSeason] = useState<string | null>(null);
  const [wardrobe, setWardrobe] = useState<Wardrobe>("ninguno");
  const [wardrobeOpen, setWardrobeOpen] = useState(false);
  // Análisis profundo: opcional, más lento y de pago. Por defecto, el económico.
  const [deep, setDeep] = useState(false);
  // Estilos de fuego y de rayo (director/looks.py); null = los del estilo elegido.
  const [looks, setLooks] = useState<Looks>({ fuego: [], rayo: [] });
  const [fireStyle, setFireStyle] = useState<string | null>(null);
  const [boltStyle, setBoltStyle] = useState<string | null>(null);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [meta, setMeta] = useState<VideoMeta | null>(null);
  const [upload, setUpload] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .styles()
      .then((list) => {
        setStyleList(list);
        setChosen((current) => current ?? list.find((s) => s.name === "avatar") ?? list.find((s) => s.kind === "catalog") ?? null);
      })
      .catch((cause: unknown) => setLoadError(cause instanceof Error ? cause.message : String(cause)));
    // Las temporadas son opcionales: si la API no las tiene, simplemente no se muestran.
    api.seasons().then(setSeasonList).catch(() => setSeasonList([]));
    api.looks().then(setLooks).catch(() => setLooks({ fuego: [], rayo: [] }));
    // Sin límites conocidos, la web no avisa: el servidor sigue rechazando lo que no cabe.
    api.limits().then(setLimits).catch(() => setLimits(null));
  }, []);
  const suggested = seasonList.find((s) => s.suggested) ?? null;

  const isCatalog = chosen?.kind === "catalog";
  // Fuego y rayo, cada uno en los estilos que lo dibujan.
  const hasFire = isCatalog && !!chosen?.tags.includes("fuego") && looks.fuego.length > 0;
  const hasBolt = isCatalog && !!chosen?.tags.some((t) => t === "rayo" || t === "rayos") && looks.rayo.length > 0;
  // El análisis profundo es de pago: solo las cuentas que el servidor permite, y solo en catálogos.
  const deepAllowed = limits?.deep_allowed ?? false;
  const deepOn = deep && deepAllowed && isCatalog;
  const found = file ? problems(file, meta, limits) : [];
  const shown = useMemo(
    () =>
      styleList.filter((style) => {
        if (filter === "all") return true;
        if (filter === "other") return !NAMED.has(style.name);
        return style.name === filter;
      }),
    [styleList, filter],
  );
  const aurora: [string, string] | undefined = chosen?.palette[0] ? [rgb(chosen.palette[0], 0.2), rgb(chosen.palette[1] ?? chosen.palette[0], 0.16)] : undefined;

  // El número de cada paso: el de fuego y rayo solo cuenta si el estilo lo pide.
  let n = 2;
  const next = () => ++n;

  const launch = async () => {
    if (!file || !chosen) return;
    setError(null);
    setUpload(0);
    // Un clic es el único momento en que el navegador deja pedir permiso de avisos.
    void askPermission();
    try {
      // Sin semilla: el servidor prueba varias coreografías y se queda con la mejor.
      const wear: Record<string, Wardrobe> = isCatalog && wardrobe !== "ninguno" ? { "*": wardrobe } : {};
      const job = await api.create(file, chosen.kind, chosen.name, null, setUpload, season, wear, deepOn, hasFire ? fireStyle : null, hasBolt ? boltStyle : null);
      navigate(ROUTES.job(job.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setUpload(null);
    }
  };

  // PENDIENTE(fase 2): la recomendación real de estilo (sin LLM, desde el análisis) necesita analizar
  // al subir. Mientras tanto elige uno de una lista fija (mocks/pendientes.ts).
  const surprise = () => {
    const names = SURPRISE_STYLES.filter((name) => styleList.some((s) => s.name === name));
    const pick = names[Math.floor(Math.random() * names.length)];
    const style = styleList.find((s) => s.name === pick);
    if (style) {
      setChosen(style);
      setFilter("all");
    }
  };

  const seasonTitle = seasonList.find((s) => s.id === season)?.title ?? null;
  const lookSummary = [hasFire && fireStyle && looks.fuego.find((l) => l.id === fireStyle)?.title, hasBolt && boltStyle && looks.rayo.find((l) => l.id === boltStyle)?.title].filter(Boolean).join(" / ");

  return (
    <Shell aurora={aurora}>
      <div className={styles.page}>
        <div className={styles.main}>
          <section className={styles.hero}>
            <NeonPreview palette={chosen?.palette ?? [[0.25, 0.85, 1], [0.55, 0.4, 1]]} seed={5} active className={styles.heroArt} />
            <div className={styles.heroText}>
              <h1>
                Tu movimiento,
                <br />
                <span>más allá de lo real.</span>
              </h1>
              <p>
                Carga tu video y convierte tus movimientos en efectos visuales épicos. El video original nunca se toca, solo se le añaden capas de magia.
              </p>
            </div>
            <ul className={styles.features}>
              <li>
                <Icon name="wand" size={18} /> Efectos automáticos
              </li>
              <li>
                <Icon name="brain" size={18} /> IA que entiende tus movimientos
              </li>
              <li>
                <Icon name="clock" size={18} /> Resultados en minutos
              </li>
            </ul>
          </section>

          <StepCard
            n={1}
            title="El plano"
            note={`Sube tu video o arrástralo aquí. Admite: .mp4 .mov .m4v .webm .mkv${limits ? ` (máx. ${limits.max_upload_mb} MB)` : ""}.`}
          >
            <Dropzone file={file} onFile={setFile} onMeta={setMeta} limits={limits} />
          </StepCard>

          <StepCard
            n={2}
            title="El estilo"
            note="Elige un estilo o deja que la IA te sorprenda."
            action={
              <button type="button" className={styles.surprise} onClick={surprise} disabled={styleList.length === 0}>
                <Icon name="sparkles" size={16} /> Sorpréndeme con IA
              </button>
            }
          >
            {loadError && (
              <div className={styles.error}>
                <Icon name="alert" /> No se pudo leer la API: {loadError}.
              </div>
            )}
            <div className={styles.chips} role="group" aria-label="Filtrar estilos">
              {FILTERS.map((item) => (
                <button key={item.id} type="button" className={filter === item.id ? styles.on : ""} onClick={() => setFilter(item.id)} aria-pressed={filter === item.id}>
                  {item.label}
                </button>
              ))}
            </div>
            <div className={styles.styles}>
              {shown.map((style) => (
                <StyleTile key={`${style.kind}:${style.name}`} style={style} selected={chosen?.name === style.name && chosen.kind === style.kind} onSelect={() => setChosen(style)} />
              ))}
              {shown.length === 0 && <p className={styles.none}>Ningún estilo en este filtro.</p>}
            </div>
          </StepCard>

          {seasonList.length > 0 && (
            <StepCard
              n={next()}
              title="Toque de temporada"
              optional
              note={suggested ? `Estamos en temporada de ${suggested.title} ${suggested.emoji}: añade un toque especial a tu estilo.` : "Añade un toque especial a tu estilo."}
            >
              <div className={styles.seasons}>
                <Tile selected={season === null} onSelect={() => setSeason(null)} icon={<span aria-hidden="true">✕</span>} label="Sin temporada" />
                {[...seasonList]
                  .sort((a, b) => Number(b.suggested) - Number(a.suggested))
                  .map((s) => (
                    <Tile
                      key={s.id}
                      selected={season === s.id}
                      onSelect={() => setSeason(s.id)}
                      icon={<span aria-hidden="true">{s.emoji}</span>}
                      label={s.title}
                      title={s.description}
                      ribbon={s.suggested ? "De temporada" : undefined}
                      swatches={s.palette.slice(0, 4).map((c) => rgb(c))}
                    />
                  ))}
              </div>
            </StepCard>
          )}

          {(hasFire || hasBolt) && (
            <StepCard n={next()} title="Fuego y rayo" note="Personaliza el look de los elementos de este estilo. La coreografía es la misma: cambia cómo se pinta.">
              <div className={styles.looks}>
                {hasFire && (
                  <div>
                    <h3>Look del fuego</h3>
                    <div className={styles.lookRow}>
                      {looks.fuego.map((look) => (
                        <Tile
                          key={look.id}
                          small
                          selected={look.id === "clasico" ? fireStyle === null : fireStyle === look.id}
                          onSelect={() => setFireStyle(look.id === "clasico" ? null : look.id)}
                          icon={<span style={{ color: LOOK_COLOR[look.id] }}><Icon name="flame" size={26} /></span>}
                          label={look.title}
                          title={look.description}
                        />
                      ))}
                    </div>
                  </div>
                )}
                {hasBolt && (
                  <div>
                    <h3>Look del rayo</h3>
                    <div className={styles.lookRow}>
                      {looks.rayo.map((look) => (
                        <Tile
                          key={look.id}
                          small
                          selected={look.id === "cian" ? boltStyle === null : boltStyle === look.id}
                          onSelect={() => setBoltStyle(look.id === "cian" ? null : look.id)}
                          icon={<span style={{ color: LOOK_COLOR[look.id] }}><Icon name="bolt" size={26} /></span>}
                          label={look.id === "cian" ? "Del estilo" : look.title}
                          title={look.description}
                        />
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </StepCard>
          )}

          {isCatalog && (
            <section className={styles.wardrobe}>
              <button type="button" onClick={() => setWardrobeOpen((v) => !v)} aria-expanded={wardrobeOpen}>
                <span className={styles.num}>{next()}</span>
                <span className={styles.wardrobeText}>
                  <strong>
                    Vestuario <small>(solo catálogos)</small>
                  </strong>
                  <small>{WARDROBES.map((w) => w.label).join(" / ")}.</small>
                </span>
                <em>{wardrobe === "ninguno" ? "Opcional" : WARDROBES.find((w) => w.id === wardrobe)?.label}</em>
              </button>
              {wardrobeOpen && (
                <div className={styles.wardrobeChoices}>
                  {WARDROBES.map((w) => (
                    <Tile key={w.id} small selected={wardrobe === w.id} onSelect={() => setWardrobe(w.id)} icon={<Icon name={w.id === "ninguno" ? "close" : "sparkles"} size={22} />} label={w.label} />
                  ))}
                  <p>Después, en la página del video, puedes elegir la prenda de cada persona por separado.</p>
                </div>
              )}
            </section>
          )}

          {isCatalog && (
            <StepCard n={next()} title="Análisis" note="Elige cómo quieres que se analice tu video.">
              <div className={styles.analysis}>
                <ChoiceCard selected={!deepOn} onSelect={() => setDeep(false)} icon="bolt" title="Económico" text="Reacciona a cada gesto detectado." />
                {/* PENDIENTE(fase 3): el costo real del análisis profundo (créditos); hoy "+$" es el del diseño. */}
                <ChoiceCard
                  selected={deepOn}
                  onSelect={() => setDeep(true)}
                  icon="brain"
                  title="Profundo con IA"
                  price="+ $"
                  text={deepAllowed ? "Ve el video completo, entiende la intención y crea una historia. Tarda unos minutos más (experimental)." : "Aún no está disponible para tu cuenta."}
                  disabled={!deepAllowed}
                  hint={deepAllowed ? undefined : "Aún no está disponible para tu cuenta"}
                />
              </div>
            </StepCard>
          )}
        </div>

        <StudioAside
          file={file}
          meta={meta}
          style={chosen}
          season={seasonTitle}
          wardrobe={WARDROBES.find((w) => w.id === wardrobe)?.label ?? "Sin prendas"}
          analysis={deepOn ? "Profundo con IA" : "Económico"}
          looks={lookSummary || null}
          upload={upload}
          error={error}
          canLaunch={!!file && !!chosen && found.length === 0}
          onLaunch={launch}
        />
      </div>
    </Shell>
  );
}
