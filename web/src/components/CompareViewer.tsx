import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";

import { actionHue, actionLabel, choiceLabel, timecode } from "../api/format";
import type { Moment } from "../api/types";
import { Icon } from "./Icon";
import styles from "./CompareViewer.module.css";

interface Props {
  original: string;
  edited: string;
  moments: Moment[];
  /** Fotogramas fijos mientras los videos cargan (si no, se ve negro hasta reproducir). */
  originalPoster?: string;
  editedPoster?: string;
}

/**
 * Antes/después: el editado de fondo y el original recortado encima, con una cortina arrastrable.
 * Los dos videos van sincronizados (el editado manda). Debajo, la línea de tiempo marca cada
 * reacción que sorteó la coreografía; clic en una marca salta a ese momento.
 */
export function CompareViewer({ original, edited, moments, originalPoster, editedPoster }: Props) {
  const main = useRef<HTMLVideoElement>(null);
  const follower = useRef<HTMLVideoElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [split, setSplit] = useState(0.5);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [ratio, setRatio] = useState(9 / 16);
  const [hover, setHover] = useState<Moment | null>(null);
  const dragging = useRef(false);

  // El original sigue al editado; si se desvía más de 1/15 s, se corrige.
  useEffect(() => {
    let raf = 0;
    const sync = () => {
      const a = main.current;
      const b = follower.current;
      if (a && b) {
        if (Math.abs(a.currentTime - b.currentTime) > 0.066) b.currentTime = a.currentTime;
        if (a.paused !== b.paused) void (a.paused ? b.pause() : b.play());
        setTime(a.currentTime);
      }
      raf = requestAnimationFrame(sync);
    };
    raf = requestAnimationFrame(sync);
    return () => cancelAnimationFrame(raf);
  }, []);

  const toggle = useCallback(() => {
    const video = main.current;
    if (!video) return;
    if (video.paused) void video.play();
    else video.pause();
  }, []);

  const seek = (seconds: number) => {
    if (main.current) main.current.currentTime = Math.max(0, Math.min(seconds, duration));
  };

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.target as HTMLElement).tagName === "INPUT") return;
      if (event.code === "Space") {
        event.preventDefault();
        toggle();
      }
      if (event.code === "ArrowRight") seek(time + 1 / 30);
      if (event.code === "ArrowLeft") seek(time - 1 / 30);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });

  const moveSplit = (event: PointerEvent) => {
    const box = stage.current?.getBoundingClientRect();
    if (!box) return;
    setSplit(Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)));
  };

  return (
    <div className={styles.viewer}>
      <div
        ref={stage}
        className={styles.stage}
        style={{ aspectRatio: String(ratio), maxWidth: `calc(72vh * ${ratio})` }}
        onPointerDown={(event) => {
          dragging.current = true;
          (event.target as HTMLElement).setPointerCapture(event.pointerId);
          moveSplit(event);
        }}
        onPointerMove={(event) => dragging.current && moveSplit(event)}
        onPointerUp={() => (dragging.current = false)}
      >
        <video
          ref={main}
          src={edited}
          poster={editedPoster}
          preload="auto"
          playsInline
          loop
          onLoadedMetadata={(event) => {
            const video = event.currentTarget;
            setDuration(video.duration);
            if (video.videoWidth && video.videoHeight) setRatio(video.videoWidth / video.videoHeight);
          }}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        <video ref={follower} src={original} poster={originalPoster} preload="auto" playsInline muted loop className={styles.original} style={{ clipPath: `inset(0 ${(1 - split) * 100}% 0 0)` }} />
        <div className={styles.handle} style={{ left: `${split * 100}%` }}>
          <span>
            <Icon name="back" size={14} />
            <Icon name="arrow" size={14} />
          </span>
        </div>
        <span className={`${styles.tag} ${styles.left}`}>Original</span>
        <span className={`${styles.tag} ${styles.right}`}>VFX Glow</span>
      </div>

      <div className={styles.controls}>
        <button type="button" className={styles.play} onClick={toggle} aria-label={playing ? "Pausar" : "Reproducir"}>
          <Icon name={playing ? "pause" : "play"} size={20} />
        </button>
        <span className="mono">
          {timecode(time)} <span className={styles.total}>/ {timecode(duration)}</span>
        </span>
        <div
          className={styles.track}
          onPointerDown={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            seek(((event.clientX - box.left) / box.width) * duration);
          }}
        >
          <div className={styles.fill} style={{ width: `${duration ? (time / duration) * 100 : 0}%` }} />
          {duration > 0 &&
            moments.map((moment, index) => (
              <button
                type="button"
                key={`${moment.second}-${index}`}
                className={styles.marker}
                style={{ left: `${(moment.second / duration) * 100}%`, ["--hue" as string]: actionHue(moment.action) }}
                onPointerDown={(event) => {
                  event.stopPropagation();
                  seek(moment.second);
                }}
                onMouseEnter={() => setHover(moment)}
                onMouseLeave={() => setHover(null)}
                aria-label={`${actionLabel(moment.action)}: ${choiceLabel(moment.choice)} en ${timecode(moment.second)}`}
              />
            ))}
          {hover && duration > 0 && (
            <div className={styles.tooltip} style={{ left: `${(hover.second / duration) * 100}%` }}>
              <strong>{choiceLabel(hover.choice)}</strong>
              <span>
                {actionLabel(hover.action)} · {timecode(hover.second)}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
