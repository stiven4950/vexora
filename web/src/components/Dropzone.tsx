import { useEffect, useRef, useState, type DragEvent } from "react";

import type { Limits } from "../api/types";
import { Icon } from "./Icon";
import styles from "./Dropzone.module.css";

const ACCEPT = ".mp4,.mov,.m4v,.webm,.mkv,video/*";

export interface VideoMeta {
  duration: number;
  width: number;
  height: number;
}

/** Qué avisar de un video antes de subirlo; vacío si cabe en los límites del servidor. */
export function problems(file: File, meta: VideoMeta | null, limits: Limits | null): string[] {
  if (!limits) return [];
  const found: string[] = [];
  if (file.size > limits.max_upload_mb * 1024 * 1024) found.push(`Pesa ${(file.size / 1e6).toFixed(0)} MB y el máximo es ${limits.max_upload_mb} MB.`);
  if (meta && Number.isFinite(meta.duration) && meta.duration > limits.max_video_seconds)
    found.push(`Dura ${Math.round(meta.duration)} s y el máximo es ${limits.max_video_seconds} s: recórtalo antes de subirlo.`);
  if (meta && Math.max(meta.width, meta.height) > limits.max_video_side)
    found.push(`Mide ${meta.width}×${meta.height} y el máximo es ${limits.max_video_side} px en el lado largo: expórtalo a 1080p.`);
  return found;
}

interface Props {
  file: File | null;
  onFile: (file: File | null) => void;
  /** Lo que se supo del video al cargarlo (duración y tamaño en píxeles). */
  onMeta?: (meta: VideoMeta | null) => void;
  limits?: Limits | null;
}

/** Zona de carga con forma de fotograma: arrastra un video o elígelo; muestra su vista previa. */
export function Dropzone({ file, onFile, onMeta, limits = null }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [meta, setMeta] = useState<VideoMeta | null>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      setMeta(null);
      onMeta?.(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const drop = (event: DragEvent) => {
    event.preventDefault();
    setOver(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped && dropped.type.startsWith("video")) onFile(dropped);
  };

  return (
    <div
      className={`${styles.zone} ${over ? styles.over : ""} ${file ? styles.filled : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <span className={styles.sprockets} aria-hidden="true" />
      <span className={`${styles.sprockets} ${styles.right}`} aria-hidden="true" />
      {preview ? (
        <div className={styles.preview}>
          <video
            src={preview}
            autoPlay
            muted
            loop
            playsInline
            onLoadedMetadata={(event) => {
              const video = event.currentTarget;
              const loaded = { duration: video.duration, width: video.videoWidth, height: video.videoHeight };
              setMeta(loaded);
              onMeta?.(loaded);
            }}
          />
          <div className={styles.info}>
            <div>
              <span className="eyebrow">Plano cargado</span>
              <strong>{file?.name}</strong>
              <span className="mono">
                {meta ? `${meta.width}×${meta.height} · ${meta.duration.toFixed(1)} s · ` : ""}
                {file ? `${(file.size / 1e6).toFixed(1)} MB` : ""}
              </span>
            </div>
            <button type="button" className={styles.change} onClick={() => input.current?.click()}>
              Cambiar
            </button>
          </div>
          {file && problems(file, meta, limits).map((text) => (
            <p key={text} className={styles.problem} role="alert">
              <Icon name="alert" size={16} /> {text}
            </p>
          ))}
        </div>
      ) : (
        <button type="button" className={styles.empty} onClick={() => input.current?.click()}>
          <span className={styles.orb}>
            <Icon name="upload" size={26} />
          </span>
          <strong>Arrastra tu plano aquí</strong>
          <span>o haz clic para elegir un video · MP4, MOV, WEBM</span>
        </button>
      )}
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          const chosen = event.target.files?.[0];
          if (chosen) onFile(chosen);
          event.target.value = "";
        }}
      />
    </div>
  );
}
