import { useId } from "react";

/** Monograma de VEXORA: una V hecha de una cinta que se pliega en el brazo izquierdo. */
export const MARK_PATH = "M6 8 C16 5 32 5 40 7 L66 64 L98 12 C104 8 114 7 123 7 L76 82 C70 92 56 92 51 82 Z";
/** Pliegue de la cinta (solo en la versión a color). */
export const MARK_FOLD = "M38 7 C30 14 34 30 44 46 C50 56 54 66 58 78";

interface MarkProps {
  size?: number;
  /** color: degradado de marca; mono: currentColor (fondos claros, monocromo). */
  variant?: "color" | "mono";
  className?: string;
}

export function LogoMark({ size = 32, variant = "color", className }: MarkProps) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 128 96" width={(size * 4) / 3} height={size} className={className} aria-hidden="true">
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="0.3">
          <stop offset="0" stopColor="var(--cyan)" />
          <stop offset="0.4" stopColor="var(--blue)" />
          <stop offset="0.75" stopColor="var(--violet)" />
          <stop offset="1" stopColor="var(--plasma)" />
        </linearGradient>
      </defs>
      <path d={MARK_PATH} fill={variant === "color" ? `url(#g${id})` : "currentColor"} />
      {variant === "color" && <path d={MARK_FOLD} fill="none" stroke="var(--text)" strokeOpacity={0.55} strokeWidth={1.6} />}
    </svg>
  );
}

/** Logotipo: monograma, "VEXORA" en blanco y, opcional, el eslogan en el degradado de marca. */
export function Logo({ size = 26, tagline = false, className }: { size?: number; tagline?: boolean; className?: string }) {
  return (
    <span className={`vx-logo ${className ?? ""}`} style={{ fontSize: size * 0.62 }}>
      <LogoMark size={size} />
      <span className="vx-logo-text">
        <span className="vx-word">VEXORA</span>
        {tagline && <span className="vx-tagline">Create beyond reality.</span>}
      </span>
    </span>
  );
}
