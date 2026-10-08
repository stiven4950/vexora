import { useEffect, useRef } from "react";

import { rgb } from "../api/format";
import type { Rgb } from "../api/types";

interface Props {
  palette: Rgb[];
  /** Semilla visual: cambia la forma de los trazos (la misma idea que la semilla del motor). */
  seed?: number;
  active?: boolean;
  className?: string;
}

/**
 * Muestra viva del estilo: arcos de neón que se dibujan, se desvanecen y renacen, con chispas.
 * Se dibuja en canvas para que cada tarjeta tenga su propio movimiento sin cargar videos.
 */
export function NeonPreview({ palette, seed = 1, active = false, className }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    const canvas = ref.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const colors = palette.length ? palette : ([[0.16, 0.94, 0.82]] as Rgb[]);
    let frame = 0;
    let raf = 0;
    let random = seed * 9301 + 49297;
    const rand = () => {
      random = (random * 9301 + 49297) % 233280;
      return random / 233280;
    };
    const strokes = Array.from({ length: 4 }, (_, index) => ({
      phase: rand() * Math.PI * 2,
      speed: 0.006 + rand() * 0.008,
      tilt: rand() * Math.PI,
      bend: 0.3 + rand() * 0.6,
      color: colors[index % colors.length] as Rgb,
    }));
    const sparks: { x: number; y: number; vx: number; vy: number; life: number; color: Rgb }[] = [];

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = canvas.clientWidth * ratio;
      canvas.height = canvas.clientHeight * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const draw = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      context.globalCompositeOperation = "source-over";
      context.fillStyle = "rgba(6, 6, 11, 0.22)";
      context.fillRect(0, 0, w, h);
      context.globalCompositeOperation = "lighter";
      const speedUp = activeRef.current ? 1.8 : 1;
      for (const stroke of strokes) {
        const t = (Math.sin(frame * stroke.speed * speedUp + stroke.phase) + 1) / 2;
        const cx = w / 2;
        const cy = h / 2;
        const radius = Math.min(w, h) * (0.28 + stroke.bend * 0.25);
        const start = stroke.tilt + frame * stroke.speed * 0.6 * speedUp;
        const sweep = Math.PI * (0.35 + t * 0.9);
        for (const [width, alpha] of [
          [9, 0.12],
          [3.5, 0.55],
          [1.2, 0.95],
        ] as const) {
          context.beginPath();
          context.ellipse(cx, cy, radius, radius * (0.45 + stroke.bend * 0.3), stroke.tilt, start, start + sweep);
          context.strokeStyle = width < 2 ? "rgba(255,255,255,0.9)" : rgb(stroke.color, alpha);
          context.lineWidth = width;
          context.lineCap = "round";
          context.stroke();
        }
        if (rand() < 0.25 * speedUp) {
          const angle = start + sweep;
          sparks.push({
            x: cx + Math.cos(angle) * radius * Math.cos(stroke.tilt),
            y: cy + Math.sin(angle) * radius * 0.6,
            vx: (rand() - 0.5) * 2.4,
            vy: (rand() - 0.7) * 2.4,
            life: 1,
            color: stroke.color,
          });
        }
      }
      for (let index = sparks.length - 1; index >= 0; index -= 1) {
        const spark = sparks[index]!;
        spark.x += spark.vx;
        spark.y += spark.vy;
        spark.vy += 0.05;
        spark.life -= 0.03;
        if (spark.life <= 0) {
          sparks.splice(index, 1);
          continue;
        }
        context.beginPath();
        context.moveTo(spark.x, spark.y);
        context.lineTo(spark.x - spark.vx * 3, spark.y - spark.vy * 3);
        context.strokeStyle = rgb(spark.color, spark.life);
        context.lineWidth = 1.4;
        context.stroke();
      }
      frame += 1;
      raf = requestAnimationFrame(draw);
    };
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) {
      frame = 120;
      draw();
      cancelAnimationFrame(raf);
    } else {
      raf = requestAnimationFrame(draw);
    }
    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [palette, seed]);

  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
