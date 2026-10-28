import { useId, type ReactNode } from "react";

import { Backdrop, Glow, type Ref } from "./StyleEmblem";
import styles from "./StyleEmblem.module.css";

interface Props {
  /** Id de la temporada (configs/seasons.yaml); null = "Sin temporada". */
  season: string | null;
  active?: boolean;
  className?: string;
}

/** Una esfera con volumen: luz arriba a la izquierda, sombra abajo a la derecha. */
function Shade({ r, name, light, base, dark }: { r: Ref; name: string; light: string; base: string; dark: string }) {
  return (
    <radialGradient id={r(name).id} cx="36%" cy="30%" r="75%">
      <stop offset="0" stopColor={light} />
      <stop offset="0.45" stopColor={base} />
      <stop offset="1" stopColor={dark} />
    </radialGradient>
  );
}

/** Sombra suave en el piso, bajo la figura. */
function Floor({ r, cx, cy, rx }: { r: Ref; cx: number; cy: number; rx: number }) {
  return <ellipse cx={cx} cy={cy} rx={rx} ry={rx * 0.16} fill="#000" opacity="0.55" filter={r("soft").url} />;
}

function Soft({ r }: { r: Ref }) {
  return (
    <filter id={r("soft").id} x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="5" />
    </filter>
  );
}

function halloween(r: Ref): ReactNode {
  const glow = r("glow");
  const pumpkin = r("pumpkin");
  const inner = r("inner");
  // Gajos de la calabaza: cada uno con su propia luz para que se vea redonda.
  const lobes = [
    { cx: 110, rx: 34 },
    { cx: 190, rx: 34 },
    { cx: 128, rx: 32 },
    { cx: 172, rx: 32 },
    { cx: 150, rx: 36 },
  ];
  return (
    <>
      <defs>
        <Glow r={r} blur={8} />
        <Soft r={r} />
        <Shade r={r} name="pumpkin" light="#ffc06a" base="#f07a12" dark="#7a2a04" />
        <radialGradient id={inner.id} cx="50%" cy="50%" r="60%">
          <stop offset="0" stopColor="#fff6b0" />
          <stop offset="1" stopColor="#ffb300" />
        </radialGradient>
      </defs>
      <Backdrop r={r} colors={["#3a1a40", "#140a1c"]} cx={70} cy={25} />
      <circle cx="236" cy="44" r="22" fill="#fde68a" opacity="0.9" />
      <circle cx="244" cy="38" r="20" fill="#2a1430" opacity="0.85" />
      <Floor r={r} cx={150} cy={186} rx={84} />
      {lobes.map(({ cx, rx }) => (
        <ellipse key={cx} cx={cx} cy={130} rx={rx} ry={54} fill={pumpkin.url} stroke="#5a1f04" strokeOpacity="0.45" strokeWidth="1.5" />
      ))}
      <path d="M146 78 C144 64 150 56 160 52 C158 62 156 70 158 80Z" fill="#4d7c0f" />
      <g className={styles.flicker}>
        <g fill="#ffb300" opacity="0.8" filter={glow.url}>
          <path d="M112 116 l16 -14 l10 18z M188 116 l-16 -14 l-10 18z M110 146 q40 30 80 0 l-10 4 l-8 -8 l-8 10 l-8 -10 l-8 10 l-8 -10 l-8 10 l-8 -8z" />
        </g>
        <g fill={inner.url}>
          <path d="M112 116 l16 -14 l10 18z M188 116 l-16 -14 l-10 18z M110 146 q40 30 80 0 l-10 4 l-8 -8 l-8 10 l-8 -10 l-8 10 l-8 -10 l-8 10 l-8 -8z" />
        </g>
      </g>
      <g fill="#0d0710" className={styles.drift}>
        <path d="M56 54 q8 -8 14 0 q4 -6 8 0 q6 -8 14 0 q-8 2 -12 8 q-4 -4 -6 0 q-4 -6 -6 0 q-4 -6 -12 -8z" />
        <path d="M200 92 q6 -6 10 0 q3 -4 6 0 q4 -6 10 0 q-6 2 -9 6 q-3 -3 -4 0 q-3 -4 -4 0 q-3 -4 -9 -6z" />
      </g>
    </>
  );
}

function diaDeMuertos(r: Ref): ReactNode {
  const glow = r("glow");
  const bone = r("bone");
  const petal = r("petal");
  const marigold = (x: number, y: number, s: number, key: string) => (
    <g key={key} transform={`translate(${x} ${y}) scale(${s})`}>
      {Array.from({ length: 10 }, (_, i) => (
        <ellipse key={i} cx="0" cy="-9" rx="5" ry="9" fill={petal.url} transform={`rotate(${i * 36})`} />
      ))}
      <circle r="5" fill="#b45309" />
    </g>
  );
  return (
    <>
      <defs>
        <Glow r={r} blur={7} />
        <Soft r={r} />
        <Shade r={r} name="bone" light="#ffffff" base="#ede4d3" dark="#9c8f7a" />
        <radialGradient id={petal.id} cx="50%" cy="80%" r="80%">
          <stop offset="0" stopColor="#fde047" />
          <stop offset="1" stopColor="#f97316" />
        </radialGradient>
      </defs>
      <Backdrop r={r} colors={["#3b0d3a", "#140a1c"]} cy={40} />
      <Floor r={r} cx={150} cy={188} rx={70} />
      <path d="M96 100 C96 56 124 34 150 34 C176 34 204 56 204 100 C204 126 192 138 184 146 L182 168 C182 176 118 176 118 168 L116 146 C108 138 96 126 96 100Z" fill={bone.url} />
      <g className={styles.pulse}>
        <circle cx="128" cy="104" r="16" fill="#1a0f22" />
        <circle cx="172" cy="104" r="16" fill="#1a0f22" />
        <circle cx="128" cy="104" r="8" fill="#22d3ee" opacity="0.8" filter={glow.url} />
        <circle cx="172" cy="104" r="8" fill="#f472b6" opacity="0.8" filter={glow.url} />
        <circle cx="128" cy="104" r="3" fill="#ffffff" />
        <circle cx="172" cy="104" r="3" fill="#ffffff" />
      </g>
      <path d="M150 120 l-7 14 h14z" fill="#1a0f22" />
      <path d="M126 150 h48 M134 144 v14 M142 144 v14 M150 144 v14 M158 144 v14 M166 144 v14" stroke="#1a0f22" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M124 66 q26 -16 52 0" fill="none" stroke="#f472b6" strokeWidth="3" strokeLinecap="round" />
      <circle cx="150" cy="58" r="4" fill="#22d3ee" />
      <g className={styles.orbit}>
        {marigold(64, 70, 1.1, "a")}
        {marigold(238, 132, 1, "b")}
        {marigold(232, 50, 0.7, "c")}
        {marigold(70, 160, 0.8, "d")}
      </g>
    </>
  );
}

function navidad(r: Ref): ReactNode {
  const glow = r("glow");
  const ball = r("ball");
  const flakes = [
    [50, 30, 2.4],
    [90, 70, 1.6],
    [230, 40, 2],
    [260, 100, 1.4],
    [40, 120, 1.8],
    [210, 160, 1.6],
    [120, 24, 1.4],
  ];
  return (
    <>
      <defs>
        <Glow r={r} blur={8} />
        <Soft r={r} />
        <Shade r={r} name="ball" light="#ff8a8a" base="#d81b2c" dark="#4a0710" />
      </defs>
      <Backdrop r={r} colors={["#0d3324", "#08141a"]} cy={30} />
      <path d="M20 26 C80 40 140 30 200 18 C230 12 260 14 290 20" fill="none" stroke="#14532d" strokeWidth="14" strokeLinecap="round" />
      <path d="M40 30 l-6 12 M70 34 l-4 14 M110 34 l2 14 M160 28 l4 14 M210 18 l6 12 M250 16 l4 14" stroke="#166534" strokeWidth="6" strokeLinecap="round" />
      <g className={styles.swing}>
        <path d="M150 26 V64" stroke="#e5e7eb" strokeWidth="1.6" />
        <rect x="140" y="60" width="20" height="12" rx="3" fill="#d4a017" />
        <circle cx="150" cy="122" r="52" fill="#ff3b4e" opacity="0.35" filter={glow.url} />
        <circle cx="150" cy="122" r="50" fill={ball.url} />
        <path d="M104 110 q46 18 92 0" fill="none" stroke="#fde68a" strokeWidth="3" opacity="0.9" />
        <path d="M108 134 q42 14 84 0" fill="none" stroke="#fde68a" strokeWidth="2" opacity="0.6" />
        <ellipse cx="132" cy="100" rx="14" ry="9" fill="#ffffff" opacity="0.65" transform="rotate(-30 132 100)" />
      </g>
      <g fill="#f0f9ff" className={styles.snow}>
        {flakes.map(([x, y, rr]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={rr} />
        ))}
      </g>
    </>
  );
}

function anoNuevo(r: Ref): ReactNode {
  const glow = r("glow");
  const burst = (cx: number, cy: number, radius: number, color: string, core: string, key: string, delay: string) => (
    <g key={key} className={styles.burst} style={{ animationDelay: delay }}>
      {Array.from({ length: 16 }, (_, i) => {
        const a = (i / 16) * Math.PI * 2;
        const x1 = cx + Math.cos(a) * radius * 0.3;
        const y1 = cy + Math.sin(a) * radius * 0.3;
        const x2 = cx + Math.cos(a) * radius;
        const y2 = cy + Math.sin(a) * radius;
        return (
          <g key={i}>
            <path d={`M${x1} ${y1} L${x2} ${y2}`} stroke={color} strokeWidth="6" strokeLinecap="round" opacity="0.55" filter={glow.url} />
            <path d={`M${x1} ${y1} L${x2} ${y2}`} stroke={core} strokeWidth="2" strokeLinecap="round" />
            <circle cx={x2} cy={y2} r="2.6" fill={core} />
          </g>
        );
      })}
      <circle cx={cx} cy={cy} r={radius * 0.18} fill="#ffffff" opacity="0.8" filter={glow.url} />
    </g>
  );
  return (
    <>
      <defs>
        <Glow r={r} blur={5} />
      </defs>
      <Backdrop r={r} colors={["#1e1b4b", "#0a0a1e"]} cy={30} />
      {burst(110, 84, 58, "#facc15", "#fef9c3", "a", "0s")}
      {burst(214, 62, 40, "#22d3ee", "#e0f7ff", "b", "-0.5s")}
      {burst(206, 150, 30, "#f472b6", "#fde4f2", "c", "-0.9s")}
      <path d="M60 220 Q100 170 110 100" fill="none" stroke="#fde68a" strokeWidth="1.6" strokeDasharray="2 6" opacity="0.6" />
    </>
  );
}

function sanValentin(r: Ref): ReactNode {
  const glow = r("glow");
  const heart = r("heart");
  const shape = "M150 178 C110 150 82 124 82 94 C82 72 98 56 118 56 C132 56 144 64 150 76 C156 64 168 56 182 56 C202 56 218 72 218 94 C218 124 190 150 150 178Z";
  const small = (x: number, y: number, s: number, key: string) => (
    <path key={key} d={shape} fill="#fb7185" opacity="0.85" transform={`translate(${x} ${y}) scale(${s}) translate(-150 -117)`} />
  );
  return (
    <>
      <defs>
        <Glow r={r} blur={9} />
        <Soft r={r} />
        <Shade r={r} name="heart" light="#ffc2d1" base="#ef2b5b" dark="#5c0a24" />
      </defs>
      <Backdrop r={r} colors={["#4a0f2e", "#170a16"]} cy={45} />
      <Floor r={r} cx={150} cy={192} rx={60} />
      <path d="M56 152 L240 70" stroke="#fcd34d" strokeWidth="3" strokeLinecap="round" />
      <path d="M240 70 l-14 -2 l6 12z" fill="#fcd34d" />
      <g className={styles.beat}>
        <path d={shape} fill="#ff4d7a" opacity="0.45" filter={glow.url} />
        <path d={shape} fill={heart.url} />
        <ellipse cx="116" cy="84" rx="14" ry="8" fill="#ffffff" opacity="0.6" transform="rotate(-35 116 84)" />
      </g>
      <path d="M56 152 L118 124" stroke="#fcd34d" strokeWidth="3" strokeLinecap="round" />
      <path d="M56 152 l-10 -10 m10 10 l-14 2 m24 -6 l-10 -10 m10 10 l-14 2" stroke="#fde68a" strokeWidth="2" strokeLinecap="round" />
      <g className={styles.rise}>
        {small(236, 140, 0.18, "a")}
        {small(70, 60, 0.14, "b")}
        {small(250, 40, 0.1, "c")}
      </g>
    </>
  );
}

function none(r: Ref): ReactNode {
  return (
    <>
      <Backdrop r={r} colors={["#1b2333", "#0b0f18"]} />
      <circle cx="150" cy="104" r="44" fill="none" stroke="#64748b" strokeWidth="3" strokeDasharray="6 8" />
      <path d="M132 86 L168 122 M168 86 L132 122" stroke="#94a3b8" strokeWidth="5" strokeLinecap="round" />
    </>
  );
}

const SEASONS: Record<string, (r: Ref) => ReactNode> = {
  halloween,
  dia_de_muertos: diaDeMuertos,
  navidad,
  ano_nuevo: anoNuevo,
  san_valentin: sanValentin,
};

/**
 * La ilustración de un toque de temporada (calabaza, calavera, esfera de Navidad, fuegos
 * artificiales, corazón), con luz y sombra para que tenga volumen. Se anima solo cuando `active`.
 */
export function SeasonEmblem({ season, active = false, className }: Props) {
  const base = useId().replace(/:/g, "");
  const r: Ref = (name) => ({ id: `${base}-${name}`, url: `url(#${base}-${name})` });
  const draw = (season && SEASONS[season]) || none;
  return (
    <svg viewBox="0 0 300 220" preserveAspectRatio="xMidYMid slice" className={`${styles.emblem} ${active ? styles.active : ""} ${className ?? ""}`} aria-hidden="true">
      {draw(r)}
    </svg>
  );
}
