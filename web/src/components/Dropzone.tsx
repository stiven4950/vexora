import { useEffect, useRef, useState, type DragEvent } from "react";

import { Icon } from "./Icon";
import styles from "./Dropzone.module.css";

const ACCEPT = ".mp4,.mov,.m4v,.webm,.mkv,video/*";

interface Props {
  file: File | null;
  onFile: (file: File | null) => void;
}

/** Zona de carga con forma de fotograma: arrastra un video o elígelo; muestra su vista previa. */
export function Dropzone({ file, onFile }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ duration: number; width: number; height: number } | null>(null);

  useEffect(() => {
    if (!file) {
      setPreview(null);
      setMeta(null);
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
              setMeta({ duration: video.duration, width: video.videoWidth, height: video.videoHeight });
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
