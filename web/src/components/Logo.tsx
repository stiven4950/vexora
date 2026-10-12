import { useId } from "react";

/** Trazo del monograma UV de VEXORA: una sola cinta que baja como U, se arquea y se vuelve V. */
export const MARK_PATH = "M14 2 L14 46 C14 60 26 70 40 70 C54 70 64 60 64 46 L64 30 C64 24 68 22 72 26 L88 66 C90 70 96 70 98 66 L120 10";
/** Corte en diagonal de la punta de la U (como en el logo original). */
export const MARK_CUT = "M0 3 L21 12 L21 0 L128 0 L128 80 L0 80 Z";

interface MarkProps {
  size?: number;
  /** color: degradado de marca; mono: currentColor (fondos claros, monocromo). */
  variant?: "color" | "mono";
  className?: string;
}

export function LogoMark({ size = 32, variant = "color", className }: MarkProps) {
  const id = useId().replace(/:/g, "");
  const stroke = variant === "color" ? `url(#g${id})` : "currentColor";
  return (
    <svg viewBox="0 0 128 80" width={size * 1.6} height={size} className={className} aria-hidden="true">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="0.25">
          <stop offset="0" stopColor="var(--cyan)" />
          <stop offset="0.45" stopColor="var(--blue)" />
          <stop offset="0.72" stopColor="var(--violet)" />
          <stop offset="1" stopColor="var(--plasma)" />
        </linearGradient>
        <clipPath id={`c${id}`}>
          <path d={MARK_CUT} />
        </clipPath>
      </defs>
      <g clipPath={`url(#c${id})`}>
        <path d={MARK_PATH} fill="none" stroke={stroke} strokeWidth={14} strokeLinejoin="round" />
      </g>
    </svg>
  );
}

/** Logotipo: monograma y "VEXORA" con la X en el degradado de marca. */
export function Logo({ size = 26, tagline = false, className }: { size?: number; tagline?: boolean; className?: string }) {
  return (
    <span className={`vx-logo ${className ?? ""}`} style={{ fontSize: size * 0.62 }}>
      <LogoMark size={size} />
      <span className="vx-logo-text">
        <span className="vx-word">
          VE<span className="vx-x">X</span>ORA
        </span>
        {tagline && <span className="vx-tagline">Create beyond reality.</span>}
      </span>
    </span>
  );
}
