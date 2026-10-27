import { useRef, useState, type PointerEvent } from "react";

import { isPermanent, type ShownMoment } from "../../api/editing";
import { effectLabel } from "../../api/effectLabels";
import { mmss, mmssd } from "../../api/format";
import type { EditorTrack } from "../../api/types";
import { Icon, type IconName } from "../Icon";
import styles from "./Timeline.module.css";

export interface TimelineTrack {
  track: EditorTrack;
  moments: ShownMoment[];
  off: boolean;
  color: string;
}

interface Props {
  duration: number;
  time: number;
  tracks: TimelineTrack[];
  filmstrip?: string;
  selected: string | null;
  playing: boolean;
  onSeek: (seconds: number) => void;
  onToggle: () => void;
  onSelect: (id: string | null) => void;
  /** Mover o alargar una barra: su nuevo inicio y fin. */
  onChange: (id: string, start: number, end: number) => void;
}

type Drag = { id: string; mode: "move" | "start" | "end"; x: number; start: number; end: number };

const MIN = 0.2; // segundos: la barra más corta
const LABEL = 170; // ancho de la columna de nombres

/** La línea de tiempo del editor (como la de Canva): regla y fotogramas arriba, una fila por efecto y el cabezal. */
export function Timeline({ duration, time, tracks, filmstrip, selected, playing, onSeek, onToggle, onSelect, onChange }: Props) {
  const [zoom, setZoom] = useState(1);
  const [hot, setHot] = useState<string | null>(null);
  const lanes = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [live, setLive] = useState<{ id: string; start: number; end: number } | null>(null);
  const pct = (seconds: number) => `${(Math.min(Math.max(seconds, 0), duration) / (duration || 1)) * 100}%`;
  const ticks = Array.from({ length: Math.floor(duration / 5) + 1 }, (_, i) => i * 5);

  const secondsAt = (clientX: number): number => {
    const box = lanes.current?.getBoundingClientRect();
    if (!box) return 0;
    return Math.min(Math.max(((clientX - box.left) / box.width) * duration, 0), duration);
  };

  const seek = (event: PointerEvent) => {
    onSelect(null);
    onSeek(secondsAt(event.clientX));
  };

  const begin = (event: PointerEvent, moment: ShownMoment, mode: Drag["mode"], fixed: boolean) => {
    event.stopPropagation();
    onSelect(moment.id);
    // Uno quitado se puede elegir (para restaurarlo) pero no arrastrar.
    if (moment.state === "removed" || fixed) return;
    (event.target as HTMLElement).setPointerCapture(event.pointerId);
    drag.current = { id: moment.id, mode, x: event.clientX, start: moment.start, end: moment.end };
  };

  const move = (event: PointerEvent) => {
    const d = drag.current;
    const box = lanes.current?.getBoundingClientRect();
    if (!d || !box) return;
    const delta = ((event.clientX - d.x) / box.width) * duration;
    let { start, end } = d;
    if (d.mode === "move") {
      const length = end - start;
      start = Math.min(Math.max(start + delta, 0), duration - length);
      end = start + length;
    } else if (d.mode === "start") start = Math.min(Math.max(start + delta, 0), end - MIN);
    else end = Math.max(Math.min(end + delta, duration), start + MIN);
    setLive({ id: d.id, start, end });
  };

  const finish = () => {
    if (drag.current && live && live.id === drag.current.id && (live.start !== drag.current.start || live.end !== drag.current.end)) onChange(live.id, live.start, live.end);
    drag.current = null;
    setLive(null);
  };

  return (
    <section className={styles.card}>
      <header>
        <div className={styles.tabs} role="tablist">
          <button type="button" className={styles.on} role="tab" aria-selected="true">
            Línea de tiempo
          </button>
          {/* PENDIENTE(fase 2): "Vista de efectos" (los efectos en lista, con su nota). */}
          <button type="button" role="tab" aria-selected="false" disabled title="Disponible pronto">
            Vista de efectos
          </button>
        </div>
        <div className={styles.transport}>
          <button type="button" onClick={onToggle} aria-label={playing ? "Pausar" : "Reproducir"}>
            <Icon name={playing ? "pause" : "play"} size={16} />
          </button>
          <span className="mono">
            {mmss(time)} / {mmss(duration)}
          </span>
        </div>
        <div className={styles.zoom}>
          <button type="button" onClick={() => setZoom((z) => Math.max(1, z / 1.5))} aria-label="Alejar">
            <Icon name="zoomOut" size={16} />
          </button>
          <input type="range" min={1} max={6} step={0.1} value={zoom} onChange={(event) => setZoom(Number(event.target.value))} aria-label="Zoom" />
          <button type="button" onClick={() => setZoom((z) => Math.min(6, z * 1.5))} aria-label="Acercar">
            <Icon name="zoomIn" size={16} />
          </button>
        </div>
      </header>

      <div className={styles.scroller}>
        <div className={styles.inner} style={{ width: `calc(${LABEL}px + (100% - ${LABEL}px) * ${zoom})` }}>
          <div className={styles.head}>
            <span className={styles.corner} />
            <div className={styles.time} ref={lanes} onPointerDown={seek}>
              <div className={styles.ruler}>
                {ticks.map((t) => (
                  <span key={t} style={{ left: pct(t) }}>
                    {t}s
                  </span>
                ))}
                <span className={styles.end}>{Math.round(duration)}s</span>
              </div>
              <div className={styles.strip} style={filmstrip ? { backgroundImage: `url(${filmstrip})` } : undefined} />
            </div>
          </div>
          {tracks.map(({ track, moments, off, color }) => {
            const name = effectLabel(track.label);
            const fixed = isPermanent(track.key);
            return (
              <div key={track.key} className={`${styles.row} ${off ? styles.dim : ""} ${hot === track.key ? styles.hot : ""}`}>
                <span className={styles.name} title={name} onPointerEnter={() => setHot(track.key)} onPointerLeave={() => setHot(null)}>
                  <span className={styles.nameIcon} style={{ color }}>
                    <Icon name={track.icon as IconName} size={15} />
                  </span>
                  <span className={styles.nameText}>{name}</span>
                </span>
                <div className={styles.lane} onPointerDown={seek}>
                  {moments.map((moment) => {
                    const now = live && live.id === moment.id ? live : moment;
                    const length = now.end - now.start;
                    return (
                      <span key={moment.id}>
                        {moment.was && (
                          <i className={styles.ghost} style={{ left: pct(moment.was.start), width: `calc(${pct(moment.was.end)} - ${pct(moment.was.start)})`, borderColor: color }} />
                        )}
                        <button
                          type="button"
                          title={`${name} · ${mmssd(now.start)} – ${mmssd(now.end)} · ${length.toFixed(1).replace(".", ",")} s`}
                          className={`${styles.bar} ${styles[moment.state]} ${fixed ? styles.fixed : ""} ${selected === moment.id ? styles.selected : ""}`}
                          style={{ left: pct(now.start), width: `max(calc(${pct(now.end)} - ${pct(now.start)}), 8px)`, ["--bar" as string]: color }}
                          onPointerDown={(event) => begin(event, moment, "move", fixed)}
                          onPointerMove={move}
                          onPointerUp={finish}
                        >
                          {!fixed && (
                            <>
                              <i className={styles.handle} onPointerDown={(event) => begin(event, moment, "start", fixed)} onPointerMove={move} onPointerUp={finish} />
                              <i className={`${styles.handle} ${styles.right}`} onPointerDown={(event) => begin(event, moment, "end", fixed)} onPointerMove={move} onPointerUp={finish} />
                            </>
                          )}
                        </button>
                      </span>
                    );
                  })}
                </div>
              </div>
            );
          })}
          {/* El cabezal cruza todas las filas: solo cubre la zona de tiempo. */}
          <div className={styles.overlay} style={{ left: LABEL }}>
            <div className={styles.playhead} style={{ left: pct(time) }}>
              <i />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
