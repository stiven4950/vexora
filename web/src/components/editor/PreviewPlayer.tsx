import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { mmss } from "../../api/format";
import { Icon } from "../Icon";
import { Segmented } from "../Segmented";
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
}

/** "Vista previa" del editor: el video con efectos o el original, con los controles del diseño. */
export const PreviewPlayer = forwardRef<PlayerHandle, Props>(function PreviewPlayer({ original, edited, poster, onTime, onPlaying }, ref) {
  const video = useRef<HTMLVideoElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<"original" | "effects">("effects");
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);

  useImperativeHandle(ref, () => ({
    seek: (seconds) => {
      if (video.current) video.current.currentTime = Math.max(0, Math.min(seconds, video.current.duration || seconds));
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
        onTime(v.currentTime);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [onTime]);

  // Cambiar entre original y con efectos conserva el instante y si se estaba reproduciendo.
  const swap = (next: "original" | "effects") => {
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

  return (
    <section className={styles.card}>
      <header>
        <h2>
          Vista previa <Icon name="info" size={14} />
        </h2>
        <Segmented
          label="Qué ver"
          value={view}
          onChange={swap}
          options={[
            { id: "original", label: "Original" },
            { id: "effects", label: "Con efectos" },
          ]}
        />
      </header>
      <div className={styles.stage} ref={box}>
        <video
          ref={video}
          src={view === "effects" ? edited : original}
          poster={poster}
          playsInline
          preload="auto"
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
