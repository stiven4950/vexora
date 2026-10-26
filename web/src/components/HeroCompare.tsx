import { useRef, useState, type PointerEvent } from "react";

import { NeonPreview } from "./NeonPreview";
import styles from "./HeroCompare.module.css";

/** Comparador de la portada: a la izquierda la escena sin tocar, a la derecha con los efectos,
 * con un tirador arrastrable. Es una ilustración viva (canvas), no un video real: ver
 * PENDIENTE(fase 1b) en pages/Landing.tsx. */
export function HeroCompare() {
  const stage = useRef<HTMLDivElement>(null);
  const [split, setSplit] = useState(0.5);
  const dragging = useRef(false);
  const move = (event: PointerEvent) => {
    const box = stage.current?.getBoundingClientRect();
    if (box) setSplit(Math.min(0.95, Math.max(0.05, (event.clientX - box.left) / box.width)));
  };
  return (
    <div
      ref={stage}
      className={styles.stage}
      onPointerDown={(event) => {
        dragging.current = true;
        (event.target as HTMLElement).setPointerCapture(event.pointerId);
        move(event);
      }}
      onPointerMove={(event) => dragging.current && move(event)}
      onPointerUp={() => (dragging.current = false)}
      role="img"
      aria-label="Comparación de una escena original y la misma con efectos de VEXORA"
    >
      <div className={`${styles.scene} ${styles.after}`}>
        <NeonPreview palette={[[0.3, 0.85, 1], [0.55, 0.4, 1], [0.25, 0.6, 1]]} seed={21} active className={styles.fx} />
        <span className={styles.person} />
      </div>
      <div className={`${styles.scene} ${styles.before}`} style={{ clipPath: `inset(0 ${(1 - split) * 100}% 0 0)` }}>
        <span className={styles.person} />
      </div>
      <span className={`${styles.tag} ${styles.left}`}>Original</span>
      <span className={`${styles.tag} ${styles.right}`}>Con efectos VEXORA</span>
      <div className={styles.handle} style={{ left: `${split * 100}%` }}>
        <span>‹›</span>
      </div>
    </div>
  );
}
