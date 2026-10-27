import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { mmss, mmssd } from "../../api/format";
import { Icon } from "../Icon";
import type { LayerLayout, LiveState } from "../../api/liveLayers";
import { Segmented } from "../Segmented";
import { LayerCanvas } from "./LayerCanvas";
import styles from "./PreviewPlayer.module.css";

export interface PlayerHandle {
  seek: (seconds: number) => void;
  toggle: () => void;
}

interface Props {
  original: string;
  edited: string;
  poster?: string;
  /** El tiempo actual, para la línea de tiempo (como mucho cada 0,05 s). */
  onTime: (seconds: number) => void;
  onPlaying?: (playing: boolean) => void;
  /** Un clip de vista previa que reemplaza al video: se repite en bucle y su tiempo se cuenta desde `start`. */
  clip?: { url: string; start: number; end: number; stale: boolean } | null;
  onCloseClip?: () => void;
  /** La vista en vivo: el mosaico de capas (con el audio) y los cambios pendientes ya aplicados en el navegador. */
  live?: { url: string; layout: LayerLayout; state: LiveState } | null;
  /** Cambia el valor para pasar el reproductor a esta vista (p. ej. la primera vez que la vista en vivo está lista). */
  showLive?: number;
}

type View = "original" | "effects" | "live";

/** "Vista previa" del editor: el video con efectos o el original, con los controles del diseño. */
export const PreviewPlayer = forwardRef<PlayerHandle, Props>(function PreviewPlayer({ original, edited, poster, onTime, onPlaying, clip, onCloseClip, live, showLive }, ref) {
  const video = useRef<HTMLVideoElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>("effects");
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);

  // Con un clip, el tiempo del video es relativo a su inicio en la línea de tiempo.
  const offset = clip?.start ?? 0;
  // El clip del servidor manda; si no, la vista en vivo dibuja el mosaico en un canvas.
  const showingLive = !clip && view === "live" && !!live;

  useImperativeHandle(ref, () => ({
    seek: (seconds) => {
      if (video.current) video.current.currentTime = Math.max(0, Math.min(seconds - offset, video.current.duration || seconds));
    },
    toggle: () => {
      const v = video.current;
      if (v) void (v.paused ? v.play() : v.pause());
    },
  }));

  useEffect(() => {
    let raf = 0;
    let last = -1;
    const tick = () => {
      const v = video.current;
      if (v && Math.abs(v.currentTime - last) >= 0.05) {
        last = v.currentTime;
        setTime(v.currentTime);
        onTime(v.currentTime + offset);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [onTime, offset]);

  // Cambiar entre original y con efectos conserva el instante y si se estaba reproduciendo.
  const swap = (next: View) => {
    const v = video.current;
    const at = v?.currentTime ?? 0;
    const wasPlaying = v ? !v.paused : false;
    setView(next);
    requestAnimationFrame(() => {
      const nv = video.current;
      if (!nv) return;
      const resume = () => {
        nv.currentTime = at;
        if (wasPlaying) void nv.play();
        nv.removeEventListener("loadedmetadata", resume);
      };
      nv.addEventListener("loadedmetadata", resume);
    });
  };

  // Sin capas ya no hay vista en vivo; y cuando se activan por primera vez se pasa a ella.
  const hasLive = !!live;
  useEffect(() => {
    if (!hasLive && view === "live") setView("effects");
  }, [hasLive, view]);
  const swapRef = useRef(swap);
  swapRef.current = swap;
  useEffect(() => {
    if (showLive) swapRef.current("live");
  }, [showLive]);

  return (
    <section className={styles.card}>
      <header>
        <h2>
          Vista previa <Icon name="info" size={14} />
        </h2>
        {clip ? (
          <button type="button" className={styles.closeClip} onClick={onCloseClip}>
            Cerrar vista previa
          </button>
        ) : (
          <Segmented
            label="Qué ver"
            value={view}
            onChange={swap}
            options={[
              { id: "original", label: "Original" },
              { id: "effects", label: "Con efectos" },
              ...(live ? [{ id: "live" as const, label: "En vivo" }] : []),
            ]}
          />
        )}
      </header>
      <div className={styles.stage} ref={box}>
        <video
          ref={video}
          key={clip?.url ?? (showingLive ? "live" : "video")}
          src={clip ? clip.url : showingLive && live ? live.url : view === "effects" ? edited : original}
          poster={clip || showingLive ? undefined : poster}
          loop={!!clip}
          autoPlay={!!clip}
          playsInline
          preload="auto"
          className={showingLive ? styles.hidden : undefined}
          muted={muted}
          onLoadedMetadata={(event) => setDuration(event.currentTarget.duration)}
          onPlay={() => {
            setPlaying(true);
            onPlaying?.(true);
          }}
          onPause={() => {
            setPlaying(false);
            onPlaying?.(false);
          }}
          onClick={() => video.current && void (video.current.paused ? video.current.play() : video.current.pause())}
        />
        {showingLive && live && (
          <div className={styles.canvasBox} onClick={() => video.current && void (video.current.paused ? video.current.play() : video.current.pause())}>
            <LayerCanvas video={video} layout={live.layout} live={live.state} className={styles.canvas} />
          </div>
        )}
        {clip && (
          <span className={`${styles.badge} ${clip.stale ? styles.stale : ""}`}>
            Vista previa · {mmssd(clip.start)}–{mmssd(clip.end)}
            {clip.stale ? " · desactualizada" : ""}
          </span>
        )}
      </div>
      <div className={styles.controls}>
        <button type="button" onClick={() => video.current && void (video.current.paused ? video.current.play() : video.current.pause())} aria-label={playing ? "Pausar" : "Reproducir"}>
          <Icon name={playing ? "pause" : "play"} size={20} />
        </button>
        <span className="mono">
          {mmss(time)} / {mmss(duration)}
        </span>
        <input
          type="range"
          min={0}
          max={duration || 1}
          step={0.01}
          value={time}
          onChange={(event) => {
            if (video.current) video.current.currentTime = Number(event.target.value);
          }}
          style={{ ["--fill" as string]: `${duration ? (time / duration) * 100 : 0}%` }}
          aria-label="Posición"
        />
        <button type="button" onClick={() => setMuted((v) => !v)} aria-label={muted ? "Activar sonido" : "Silenciar"}>
          <Icon name="volume" size={18} />
        </button>
        <button type="button" onClick={() => void box.current?.requestFullscreen?.()} aria-label="Pantalla completa">
          <Icon name="fullscreen" size={18} />
        </button>
      </div>
    </section>
  );
});
