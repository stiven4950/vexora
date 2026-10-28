import { useId, type ReactNode } from "react";

import { Backdrop, Glow, type Ref } from "./StyleEmblem";
import styles from "./StyleEmblem.module.css";

interface Props {
  kind: "fuego" | "rayo";
  /** Id del look (director/looks.py: FIRE_STYLES, BOLT_STYLES). */
  look: string;
  active?: boolean;
  className?: string;
}

const FLAME = "M150 22 C178 64 208 88 202 136 C198 170 176 190 150 192 C124 190 102 172 100 140 C98 110 118 98 124 72 C134 94 140 100 146 98 C140 72 140 46 150 22Z";
const CORE = "M152 92 C168 118 178 132 174 158 C171 176 162 186 150 186 C136 186 126 176 126 160 C126 144 137 138 139 122 C145 132 150 134 153 132 C149 118 148 104 152 92Z";

/** Una llama con brillo, cuerpo en degradado y núcleo (los looks "calientes"). */
function hotFlame(r: Ref, glow: string, body: [string, string, string], core: [string, string], backdrop: [string, string]): ReactNode {
  const fill = r("body");
  const heart = r("core");
  return (
    <>
      <defs>
        <Glow r={r} blur={9} />
        <linearGradient id={fill.id} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor={body[0]} />
          <stop offset="0.5" stopColor={body[1]} />
          <stop offset="1" stopColor={body[2]} />
        </linearGradient>
        <linearGradient id={heart.id} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor={core[0]} />
          <stop offset="1" stopColor={core[1]} />
        </linearGradient>
      </defs>
      <Backdrop r={r} colors={backdrop} cy={75} />
      <ellipse cx="150" cy="196" rx="100" ry="14" fill={glow} opacity="0.4" filter={r("glow").url} />
      <g className={styles.flicker}>
        <path d={FLAME} fill={glow} opacity="0.8" filter={r("glow").url} />
        <path d={FLAME} fill={fill.url} />
        <path d={CORE} fill={heart.url} />
      </g>
    </>
  );
}

/** El fuego de anime (video_51): amarillo plano y opaco, con huecos; `core` le pone núcleo blanco. */
function celFlame(r: Ref, core: boolean): ReactNode {
  return (
    <>
      <Backdrop r={r} colors={["#3a2606", "#140d08"]} cy={70} />
      <g className={styles.flicker}>
        <path d={`${FLAME} M136 128 c6 -10 16 -8 16 2 c0 8 -10 12 -16 -2z M162 70 c4 -6 10 -4 10 2 c0 6 -6 8 -10 -2z M118 156 c4 -6 10 -4 10 2 c0 6 -6 8 -10 -2z`} fill="#ffd23f" fillRule="evenodd" stroke="#7a3d00" strokeWidth="3" strokeLinejoin="round" />
        {core && <path d={CORE} fill="#ffffff" transform="translate(150 186) scale(0.7) translate(-150 -186)" />}
      </g>
    </>
  );
}

// Llama en bloques (16 x 14): 0 vacío, 1 naranja oscuro, 2 naranja, 3 amarillo, 4 blanco.
const PIXELS = [
  "0000000110000000",
  "0000001221000000",
  "0000012221000000",
  "0000122332100000",
  "0001223332210000",
  "0012233332210100",
  "0012333443221210",
  "0122334443322210",
  "0122334444332210",
  "0122334444332210",
  "0012233443322100",
  "0012223333222100",
  "0001222222221000",
  "0000111111110000",
];
const PIXEL_COLORS = ["", "#b3300a", "#ff6a14", "#ffc42e", "#fff7d6"];

function pixelFlame(r: Ref): ReactNode {
  const size = 12;
  const left = 150 - (16 * size) / 2;
  const top = 196 - PIXELS.length * size;
  return (
    <>
      <defs>
        <Glow r={r} blur={8} />
      </defs>
      <Backdrop r={r} colors={["#2e1406", "#120a08"]} cy={75} />
      <rect x={left + 2 * size} y={top + 2 * size} width={12 * size} height={11 * size} fill="#ff6a14" opacity="0.35" filter={r("glow").url} />
      <g className={styles.flicker} shapeRendering="crispEdges">
        {PIXELS.flatMap((row, y) =>
          [...row].map((cell, x) =>
            cell === "0" ? null : <rect key={`${x}-${y}`} x={left + x * size} y={top + y * size} width={size} height={size} fill={PIXEL_COLORS[Number(cell)]} />,
          ),
        )}
      </g>
    </>
  );
}

/** Un rayo quebrado; `ribbon` lo dibuja como cinta ancha con lazo, `branches` le suma ramas finas. */
function bolt(r: Ref, glow: string, core: string, edge: string, backdrop: [string, string], opts: { ribbon?: boolean; branches?: number; sparks?: boolean }): ReactNode {
  const main = "M70 28 L132 92 L112 104 L182 160 L164 170 L236 206";
  const branches = ["M132 92 L168 70 L196 76", "M112 104 L82 120 L66 150", "M182 160 L214 140 L240 146", "M150 120 L176 104", "M164 170 L136 188"].slice(0, opts.branches ?? 2);
  return (
    <>
      <defs>
        <Glow r={r} blur={7} />
      </defs>
      <Backdrop r={r} colors={backdrop} cx={40} cy={30} />
      <g fill="none" strokeLinecap="round" strokeLinejoin="round" className={styles.flash}>
        <path d={main} stroke={glow} strokeWidth={opts.ribbon ? 26 : 16} opacity="0.65" filter={r("glow").url} />
        {opts.ribbon && <path d={main} stroke={edge} strokeWidth="12" />}
        <path d={main} stroke={core} strokeWidth={opts.ribbon ? 5 : 3.4} />
        {branches.map((d) => (
          <g key={d}>
            <path d={d} stroke={glow} strokeWidth="8" opacity="0.5" filter={r("glow").url} />
            <path d={d} stroke={edge} strokeWidth="2" />
          </g>
        ))}
        {opts.ribbon && <path d="M236 206 c26 -10 34 -40 10 -50 c-20 -8 -36 14 -18 26" stroke={edge} strokeWidth="5" />}
      </g>
      {opts.sparks && (
        <g fill={core} className={styles.embers}>
          <circle cx="96" cy="60" r="3" />
          <circle cx="208" cy="128" r="2.4" />
          <circle cx="150" cy="196" r="2" />
          <circle cx="60" cy="96" r="2" />
        </g>
      )}
    </>
  );
}

const classicFire = (r: Ref) => hotFlame(r, "#ff7a00", ["#ff5a00", "#ffb000", "#fff3c4"], ["#ffd27a", "#ffffff"], ["#3a1206", "#140a10"]);
const cyanBolt = (r: Ref) => bolt(r, "#0ea5e9", "#ffffff", "#5be7ff", ["#082f49", "#06101e"], { ribbon: true, sparks: true });

const FIRE: Record<string, (r: Ref) => ReactNode> = {
  clasico: classicFire,
  plano: (r) => celFlame(r, false),
  mixto: (r) => celFlame(r, true),
  azul: (r) => hotFlame(r, "#2563eb", ["#1d4ed8", "#60a5fa", "#e0f2fe"], ["#bfdbfe", "#ffffff"], ["#0b1e46", "#080c1a"]),
  verde: (r) => hotFlame(r, "#16a34a", ["#15803d", "#4ade80", "#dcfce7"], ["#bbf7d0", "#ffffff"], ["#0b3018", "#08140c"]),
  pixel: pixelFlame,
};

const BOLT: Record<string, (r: Ref) => ReactNode> = {
  cian: cyanBolt,
  blanco: (r) => bolt(r, "#6b8cff", "#ffffff", "#dbe6ff", ["#1a1f4a", "#0a0c1e"], { branches: 5, sparks: true }),
  violeta: (r) => bolt(r, "#7c22e6", "#fbe7ff", "#c084fc", ["#2a0f4a", "#100a1e"], { ribbon: true, sparks: true }),
  rojo: (r) => bolt(r, "#dc1414", "#ffe8e0", "#ff4d3a", ["#3a0808", "#14080a"], { ribbon: true, branches: 3, sparks: true }),
  fuego: (r) => bolt(r, "#f05a0a", "#fff1cc", "#ff9a2e", ["#3a1606", "#140a08"], { branches: 2 }),
};

/** La ilustración de un look de fuego o de rayo: la llama o el rayo tal como lo pinta ese look. */
export function LookEmblem({ kind, look, active = false, className }: Props) {
  const base = useId().replace(/:/g, "");
  const r: Ref = (name) => ({ id: `${base}-${name}`, url: `url(#${base}-${name})` });
  const draw = (kind === "fuego" ? FIRE[look] : BOLT[look]) ?? (kind === "fuego" ? classicFire : cyanBolt);
  return (
    <svg viewBox="0 0 300 220" preserveAspectRatio="xMidYMid slice" className={`${styles.emblem} ${active ? styles.active : ""} ${className ?? ""}`} aria-hidden="true">
      {draw(r)}
    </svg>
  );
}
