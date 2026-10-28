import { useId, type ReactNode } from "react";

import styles from "./StyleEmblem.module.css";

interface Props {
  /** Nombre del catálogo (configs/catalogs/<nombre>.yaml). */
  style: string;
  /** Anima el emblema (estilo elegido o con el cursor encima). */
  active?: boolean;
  className?: string;
}

/** Ids únicos por emblema: varios en la misma página no comparten degradados ni filtros. */
export type Ref = (name: string) => { id: string; url: string };

/** Fondo oscuro teñido con el color del estilo, desde `cx`/`cy` (en %). */
export function Backdrop({ r, colors, cx = 50, cy = 45 }: { r: Ref; colors: [string, string]; cx?: number; cy?: number }) {
  const bg = r("bg");
  return (
    <>
      <radialGradient id={bg.id} cx={`${cx}%`} cy={`${cy}%`} r="85%">
        <stop offset="0" stopColor={colors[0]} />
        <stop offset="0.6" stopColor={colors[1]} />
        <stop offset="1" stopColor="#05070c" />
      </radialGradient>
      <rect width="300" height="220" fill={bg.url} />
    </>
  );
}

export function Glow({ r, blur }: { r: Ref; blur: number }) {
  return (
    <filter id={r("glow").id} x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation={blur} />
    </filter>
  );
}

/** Figura de pictograma (cabeza y trazos gruesos): `limbs` son polilíneas "x,y x,y ...". */
function Figure({ head, limbs, stroke, width }: { head: [number, number]; limbs: string[]; stroke: string; width: number }) {
  return (
    <g fill="none" stroke={stroke} strokeWidth={width} strokeLinecap="round" strokeLinejoin="round">
      <circle cx={head[0]} cy={head[1]} r={width * 0.85} fill={stroke} stroke="none" />
      {limbs.map((points) => (
        <polyline key={points} points={points} />
      ))}
    </g>
  );
}

function avatar(r: Ref): ReactNode {
  const glow = r("glow");
  const ring = r("ring");
  const kick = { head: [134, 62] as [number, number], limbs: ["138,74 146,110", "140,82 112,72 96,82", "140,84 166,70 184,52", "146,110 128,138 120,164", "146,110 182,98 214,82"] };
  return (
    <>
      <defs>
        <Glow r={r} blur={7} />
        <linearGradient id={ring.id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff1c2" />
          <stop offset="0.45" stopColor="#ffb000" />
          <stop offset="1" stopColor="#ff4d00" />
        </linearGradient>
      </defs>
      <Backdrop r={r} colors={["#4a1a06", "#160a0c"]} cy={50} />
      <text x="26" y="52" fill="#fff" opacity="0.18" fontSize="40" fontWeight="700">
        火
      </text>
      <g className={styles.spin}>
        <path d="M150 34 A70 70 0 0 1 220 104" fill="none" stroke="#ff7a00" strokeWidth="16" opacity="0.6" filter={glow.url} />
        <path d="M150 34 A70 70 0 0 1 220 104" fill="none" stroke={ring.url} strokeWidth="6" strokeLinecap="round" />
        <path d="M150 174 A70 70 0 0 1 80 104" fill="none" stroke="#ff7a00" strokeWidth="16" opacity="0.6" filter={glow.url} />
        <path d="M150 174 A70 70 0 0 1 80 104" fill="none" stroke={ring.url} strokeWidth="6" strokeLinecap="round" />
      </g>
      <g filter={glow.url} opacity="0.8">
        <Figure {...kick} stroke="#ff8a1f" width={13} />
      </g>
      <Figure {...kick} stroke="#1a0b06" width={9} />
    </>
  );
}

function fuego(r: Ref): ReactNode {
  const glow = r("glow");
  const flame = r("flame");
  const core = r("core");
  const outer = "M150 26 C176 66 204 88 198 134 C194 166 174 184 150 186 C126 184 106 168 104 138 C102 110 120 98 126 74 C135 94 141 100 146 98 C140 74 140 50 150 26Z";
  return (
    <>
      <defs>
        <Glow r={r} blur={9} />
        <linearGradient id={flame.id} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#ff5a00" />
          <stop offset="0.5" stopColor="#ffb000" />
          <stop offset="1" stopColor="#fff3c4" />
        </linearGradient>
        <linearGradient id={core.id} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor="#ffd27a" />
          <stop offset="1" stopColor="#ffffff" />
        </linearGradient>
      </defs>
      <Backdrop r={r} colors={["#3a1206", "#140a10"]} cy={75} />
      <ellipse cx="150" cy="190" rx="110" ry="14" fill="#ff6a00" opacity="0.35" filter={glow.url} />
      <g className={styles.flicker}>
        <path d={outer} fill="#ff7a00" opacity="0.8" filter={glow.url} />
        <path d={outer} fill={flame.url} />
        <path d="M152 92 C166 116 176 128 172 152 C169 170 161 180 150 180 C137 180 128 170 128 155 C128 140 138 134 140 120 C146 130 150 132 153 130 C149 118 148 104 152 92Z" fill={core.url} />
      </g>
      <g fill="#ffcf6a" className={styles.embers}>
        <circle cx="88" cy="96" r="2.4" />
        <circle cx="212" cy="70" r="2" />
        <circle cx="222" cy="122" r="1.6" />
        <circle cx="76" cy="140" r="1.6" />
        <circle cx="196" cy="40" r="1.4" />
      </g>
    </>
  );
}

function agua(r: Ref): ReactNode {
  const glow = r("glow");
  const water = r("water");
  const whip = "M54 150 C84 92 132 176 160 112 C182 62 236 74 240 112 C243 140 214 152 196 138";
  return (
    <>
      <defs>
        <Glow r={r} blur={7} />
        <linearGradient id={water.id} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#1e6bff" />
          <stop offset="0.6" stopColor="#38bdf8" />
          <stop offset="1" stopColor="#cffafe" />
        </linearGradient>
      </defs>
      <Backdrop r={r} colors={["#0b2f5e", "#081428"]} cy={55} />
      <path d={whip} fill="none" stroke="#1e90ff" strokeWidth="26" strokeLinecap="round" opacity="0.5" filter={glow.url} />
      <path d={whip} fill="none" stroke={water.url} strokeWidth="14" strokeLinecap="round" />
      <path d={whip} fill="none" stroke="#ffffff" strokeWidth="3" strokeLinecap="round" strokeDasharray="26 34" opacity="0.85" className={styles.flow} />
      <g fill="#bae6fd">
        <circle cx="74" cy="96" r="5" />
        <circle cx="62" cy="116" r="3" />
        <circle cx="214" cy="164" r="4" />
        <circle cx="232" cy="176" r="2.4" />
        <circle cx="126" cy="64" r="2.6" />
      </g>
    </>
  );
}

function rayo(r: Ref): ReactNode {
  const glow = r("glow");
  return (
    <>
      <defs>
        <Glow r={r} blur={6} />
      </defs>
      <Backdrop r={r} colors={["#1b1446", "#0b0b22"]} cx={60} cy={35} />
      <g fill="none" strokeLinejoin="round" strokeLinecap="round" className={styles.flash}>
        <path d="M60 186 L104 140 L94 130 L150 86 L140 76 L206 24 M150 86 L188 94 L230 70 M104 140 L82 110 L60 102 M140 76 L118 44" stroke="#a855f7" strokeWidth="12" opacity="0.7" filter={glow.url} />
        <path d="M60 186 L104 140 L94 130 L150 86 L140 76 L206 24" stroke="#c4f1ff" strokeWidth="4" />
        <path d="M150 86 L188 94 L230 70 M104 140 L82 110 L60 102 M140 76 L118 44" stroke="#7dd3fc" strokeWidth="2.2" />
      </g>
      <circle cx="60" cy="186" r="16" fill="#a855f7" opacity="0.6" filter={glow.url} />
      <circle cx="60" cy="186" r="5" fill="#ffffff" />
    </>
  );
}

function tierra(r: Ref): ReactNode {
  const glow = r("glow");
  // Una roca facetada: contorno y dos caras más claras.
  const rock = (x: number, y: number, s: number, tone: string, key: string) => (
    <g key={key} transform={`translate(${x} ${y}) scale(${s})`}>
      <path d="M-18 -6 L-6 -20 L14 -16 L22 2 L10 20 L-12 18 Z" fill={tone} />
      <path d="M-6 -20 L14 -16 L6 0 L-18 -6 Z" fill="#f5f5f4" opacity="0.55" />
      <path d="M6 0 L22 2 L10 20 Z" fill="#000" opacity="0.25" />
    </g>
  );
  return (
    <>
      <defs>
        <Glow r={r} blur={8} />
      </defs>
      <Backdrop r={r} colors={["#3b2f26", "#14110f"]} cy={60} />
      <ellipse cx="150" cy="104" rx="96" ry="30" fill="none" stroke="#d6d3d1" strokeWidth="1.5" strokeDasharray="4 8" opacity="0.45" />
      <ellipse cx="150" cy="150" rx="70" ry="10" fill="#a8a29e" opacity="0.3" filter={glow.url} />
      <g className={styles.orbit}>
        {rock(62, 100, 0.8, "#a8a29e", "a")}
        {rock(238, 108, 0.7, "#78716c", "b")}
        {rock(192, 70, 0.55, "#d6d3d1", "c")}
      </g>
      <g className={styles.bob}>{rock(150, 100, 2.1, "#8f8a85", "main")}</g>
      <g fill="#e7e5e4" opacity="0.6">
        <circle cx="100" cy="160" r="2" />
        <circle cx="206" cy="156" r="1.6" />
        <circle cx="130" cy="170" r="1.4" />
      </g>
    </>
  );
}

function viento(r: Ref): ReactNode {
  const glow = r("glow");
  const ribbons = ["M40 140 C90 100 150 170 200 120 C236 84 210 52 182 66 C160 78 172 104 196 100", "M56 104 C100 76 140 116 190 92", "M70 172 C120 150 170 186 236 150"];
  return (
    <>
      <defs>
        <Glow r={r} blur={6} />
      </defs>
      <Backdrop r={r} colors={["#0e3442", "#0a1620"]} cy={50} />
      {ribbons.map((d, i) => (
        <g key={d}>
          <path d={d} fill="none" stroke="#7dd3fc" strokeWidth={i === 0 ? 14 : 9} strokeLinecap="round" opacity="0.35" filter={glow.url} />
          <path d={d} fill="none" stroke={i === 0 ? "#f0f9ff" : "#bae6fd"} strokeWidth={i === 0 ? 3.4 : 2.2} strokeLinecap="round" strokeDasharray={i === 0 ? "60 22" : "34 18"} className={styles.flow} opacity={i === 0 ? 1 : 0.8} />
        </g>
      ))}
    </>
  );
}

function baile(r: Ref): ReactNode {
  const glow = r("glow");
  const pose = { head: [150, 46] as [number, number], limbs: ["150,60 146,112", "148,70 120,52 104,30", "148,70 178,80 196,58", "146,112 124,140 128,176", "146,112 172,132 196,146"] };
  return (
    <>
      <defs>
        <Glow r={r} blur={7} />
      </defs>
      <Backdrop r={r} colors={["#2d1150", "#110a24"]} cy={45} />
      <g className={styles.pulse}>
        <g filter={glow.url} opacity="0.9">
          <Figure {...pose} stroke="#22d3ee" width={16} />
        </g>
        <Figure {...pose} stroke="#a5f3fc" width={11} />
        <Figure {...pose} stroke="#140a26" width={6} />
      </g>
      <path d="M96 140 C110 120 128 150 142 128" fill="none" stroke="#f472b6" strokeWidth="3" strokeLinecap="round" />
      <g fill="#f472b6">
        <path d="M218 54 l0 -22 l14 -4 l0 22" fill="none" stroke="#f472b6" strokeWidth="2.6" />
        <circle cx="214" cy="56" r="5" />
        <circle cx="228" cy="52" r="5" />
        <path d="M82 70 c-6 -8 -18 -2 -12 8 l12 10 l12 -10 c6 -10 -6 -16 -12 -8z" opacity="0.85" />
      </g>
    </>
  );
}

function pelea(r: Ref): ReactNode {
  const glow = r("glow");
  const rays = Array.from({ length: 10 }, (_, i) => {
    const a = (i / 10) * Math.PI * 2;
    return `M${150 + Math.cos(a) * 16} ${104 + Math.sin(a) * 16} L${150 + Math.cos(a) * (i % 2 ? 42 : 58)} ${104 + Math.sin(a) * (i % 2 ? 42 : 58)}`;
  });
  return (
    <>
      <defs>
        <Glow r={r} blur={6} />
      </defs>
      <Backdrop r={r} colors={["#3a0f3a", "#120a1c"]} cy={50} />
      <path d="M30 160 C70 150 110 128 140 106" fill="none" stroke="#f472b6" strokeWidth="12" strokeLinecap="round" opacity="0.6" filter={glow.url} />
      <path d="M30 160 C70 150 110 128 140 106" fill="none" stroke="#fbcfe8" strokeWidth="3.5" strokeLinecap="round" />
      <path d="M270 58 C232 70 190 88 160 102" fill="none" stroke="#facc15" strokeWidth="12" strokeLinecap="round" opacity="0.55" filter={glow.url} />
      <path d="M270 58 C232 70 190 88 160 102" fill="none" stroke="#fef9c3" strokeWidth="3.5" strokeLinecap="round" />
      <g className={styles.burst}>
        <g stroke="#fde68a" strokeWidth="3" strokeLinecap="round" filter={glow.url}>
          {rays.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>
        <g stroke="#ffffff" strokeWidth="1.6" strokeLinecap="round">
          {rays.map((d) => (
            <path key={d} d={d} />
          ))}
        </g>
        <circle cx="150" cy="104" r="14" fill="#ffffff" />
      </g>
      <path d="M226 150 l4 10 l10 4 l-10 4 l-4 10 l-4 -10 l-10 -4 l10 -4z" fill="#f472b6" />
      <path d="M72 62 l3 7 l7 3 l-7 3 l-3 7 l-3 -7 l-7 -3 l7 -3z" fill="#facc15" />
    </>
  );
}

/** Dos katanas cruzadas; `flames` pinta lenguas de fuego a lo largo de las hojas. */
function blades(r: Ref, colors: [string, string], cores: [string, string], backdrop: [string, string], flames: boolean): ReactNode {
  const glow = r("glow");
  const tongues = [0.3, 0.5, 0.7].flatMap((t) => [
    [86 + (232 - 86) * t, 174 + (34 - 174) * t],
    [214 + (68 - 214) * t, 174 + (34 - 174) * t],
  ]);
  return (
    <>
      <defs>
        <Glow r={r} blur={7} />
      </defs>
      <Backdrop r={r} colors={backdrop} cy={50} />
      <g strokeLinecap="round" className={flames ? styles.flicker : styles.shine}>
        <path d="M70 190 L232 34" stroke={colors[0]} strokeWidth="16" opacity="0.55" filter={glow.url} />
        <path d="M230 190 L68 34" stroke={colors[1]} strokeWidth="16" opacity="0.5" filter={glow.url} />
        <path d="M86 174 L232 34" stroke={cores[0]} strokeWidth="4" />
        <path d="M214 174 L68 34" stroke={cores[1]} strokeWidth="4" />
      </g>
      {flames && (
        <g className={styles.flicker} fill="#ff8a1f">
          {tongues.map(([x, y]) => (
            <path key={`${x}-${y}`} d={`M${x} ${y} c-8 -10 -4 -22 6 -30 c-2 10 6 14 4 24 c-2 6 -6 8 -10 6z`} opacity="0.9" />
          ))}
        </g>
      )}
      <g stroke="#94a3b8" strokeWidth="6" strokeLinecap="round">
        <path d="M62 198 L86 174 M74 162 L98 186" />
        <path d="M238 198 L214 174 M226 162 L202 186" />
      </g>
      <circle cx="150" cy="111" r="24" fill="#ffffff" opacity="0.35" filter={glow.url} className={styles.glint} />
    </>
  );
}

const STANDING = { head: [150, 40] as [number, number], limbs: ["150,54 150,112", "150,66 124,92 116,120", "150,66 176,92 184,120", "150,112 134,150 130,186", "150,112 166,150 170,186"] };

function bodyAura(r: Ref): ReactNode {
  const glow = r("glow");
  return (
    <>
      <defs>
        <Glow r={r} blur={10} />
      </defs>
      <Backdrop r={r} colors={["#2a1458", "#0e0a24"]} cy={50} />
      <g className={styles.pulse}>
        <g filter={glow.url} opacity="0.75">
          <Figure {...STANDING} stroke="#8b5cf6" width={34} />
        </g>
        <g opacity="0.55">
          <Figure {...STANDING} stroke="#22d3ee" width={22} />
        </g>
      </g>
      <Figure {...STANDING} stroke="#0d0a1c" width={12} />
    </>
  );
}

function doodleDance(r: Ref): ReactNode {
  const pose = { head: [150, 44] as [number, number], limbs: ["150,58 148,112", "150,70 122,56 108,34", "150,70 180,64 200,44", "148,112 128,144 120,180", "148,112 174,138 182,176"] };
  return (
    <>
      <Backdrop r={r} colors={["#3b1036", "#140a1c"]} cy={45} />
      <Figure {...pose} stroke="#0d0a14" width={10} />
      <g fill="none" stroke="#fdf4ff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className={styles.pulse}>
        <path d="M70 60 l8 -16 l8 16 l-18 -10 h20 z" />
        <path d="M222 96 c10 -10 24 0 14 10 c-8 8 -20 -2 -12 -8" />
        <path d="M64 128 l10 -8 l10 8 l10 -8 l10 8" stroke="#f472b6" />
        <path d="M206 150 q14 -18 28 0 t28 0" stroke="#facc15" />
        <circle cx="230" cy="40" r="7" stroke="#22d3ee" />
      </g>
    </>
  );
}

function faceNeon(r: Ref): ReactNode {
  const glow = r("glow");
  const face = "M150 30 C190 30 206 64 204 100 C202 140 178 172 150 176 C122 172 98 140 96 100 C94 64 110 30 150 30Z";
  return (
    <>
      <defs>
        <Glow r={r} blur={6} />
      </defs>
      <Backdrop r={r} colors={["#3a0f30", "#120a1a"]} cy={45} />
      <path d={face} fill="#140a16" stroke="#f472b6" strokeWidth="10" opacity="0.6" filter={glow.url} />
      <path d={face} fill="none" stroke="#fbcfe8" strokeWidth="2.4" />
      <g fill="none" strokeLinecap="round" className={styles.shine}>
        <path d="M108 92 h84" stroke="#22d3ee" strokeWidth="12" opacity="0.5" filter={glow.url} />
        <path d="M112 86 q19 -12 34 0 q-15 14 -34 0 M154 86 q19 -12 34 0 q-15 14 -34 0" stroke="#a5f3fc" strokeWidth="3" />
        <path d="M128 138 q22 14 44 0" stroke="#f472b6" strokeWidth="3" />
        <path d="M118 112 l-10 14 M182 112 l10 14" stroke="#f9a8d4" strokeWidth="2.4" />
      </g>
    </>
  );
}

function faceRunes(r: Ref): ReactNode {
  const glow = r("glow");
  const runes = ["M0 -10 v20 M0 -10 l8 8 M0 0 l8 8", "M-6 -10 l12 20 M6 -10 l-12 20", "M0 -10 v20 M-8 -4 h16", "M-6 10 v-20 l12 10 l-12 10", "M-8 -10 l8 20 l8 -20"];
  const ring = runes.map((d, i) => {
    const a = (i / runes.length) * Math.PI * 2 - Math.PI / 2;
    return { d, x: 150 + Math.cos(a) * 82, y: 104 + Math.sin(a) * 62 };
  });
  return (
    <>
      <defs>
        <Glow r={r} blur={6} />
      </defs>
      <Backdrop r={r} colors={["#2b2410", "#100e0a"]} cy={50} />
      <ellipse cx="150" cy="104" rx="40" ry="52" fill="#0f0d09" stroke="#fbbf24" strokeWidth="2" opacity="0.8" />
      <path d="M134 96 h10 M156 96 h10 M150 104 v14 M140 128 h20" stroke="#fde68a" strokeWidth="2.4" strokeLinecap="round" />
      <g className={styles.spin}>
        <ellipse cx="150" cy="104" rx="82" ry="62" fill="none" stroke="#fbbf24" strokeWidth="1.2" strokeDasharray="3 7" opacity="0.6" />
        {ring.map(({ d, x, y }) => (
          <g key={d} transform={`translate(${x} ${y})`} fill="none" strokeLinecap="round">
            <path d={d} stroke="#f59e0b" strokeWidth="8" opacity="0.55" filter={glow.url} />
            <path d={d} stroke="#fef3c7" strokeWidth="2.6" />
          </g>
        ))}
      </g>
    </>
  );
}

function fightComic(r: Ref): ReactNode {
  const spikes = Array.from({ length: 14 }, (_, i) => {
    const a = (i / 14) * Math.PI * 2;
    const radius = i % 2 ? 46 : 78;
    return `${150 + Math.cos(a) * radius * 1.25},${100 + Math.sin(a) * radius}`;
  }).join(" ");
  return (
    <>
      <Backdrop r={r} colors={["#3a1010", "#140a0c"]} cy={50} />
      <g fill="#fca5a5" opacity="0.18">
        {Array.from({ length: 48 }, (_, i) => (
          <circle key={i} cx={20 + (i % 12) * 24} cy={22 + Math.floor(i / 12) * 48} r={3 + (i % 3)} />
        ))}
      </g>
      <g className={styles.burst}>
        <polygon points={spikes} fill="#ef4444" stroke="#0b0b0b" strokeWidth="5" strokeLinejoin="round" />
        <polygon points={spikes} fill="#facc15" transform="translate(150 100) scale(0.78) translate(-150 -100)" />
        <text x="150" y="114" textAnchor="middle" fontSize="40" fontWeight="900" fill="#111" stroke="#fff" strokeWidth="1.5" fontStyle="italic">
          POW!
        </text>
      </g>
    </>
  );
}

function neonJoints(r: Ref): ReactNode {
  const glow = r("glow");
  const joints: [number, number][] = [
    [150, 40], [150, 66], [124, 92], [116, 120], [176, 92], [184, 120], [150, 112], [134, 150], [130, 186], [166, 150], [170, 186],
  ];
  return (
    <>
      <defs>
        <Glow r={r} blur={5} />
      </defs>
      <Backdrop r={r} colors={["#0b2a3a", "#0a1020"]} cy={50} />
      <Figure {...STANDING} stroke="#22d3ee" width={3} />
      <g className={styles.pulse}>
        {joints.map(([x, y], i) => (
          <g key={`${x}-${y}`}>
            <circle cx={x} cy={y} r="9" fill={i % 2 ? "#e879f9" : "#22d3ee"} opacity="0.7" filter={glow.url} />
            <circle cx={x} cy={y} r="3.4" fill="#ffffff" />
          </g>
        ))}
      </g>
    </>
  );
}

function paintReveal(r: Ref): ReactNode {
  const paint = r("paint");
  const stroke = "M44 150 C90 90 140 170 186 104 C210 70 240 80 258 60";
  return (
    <>
      <defs>
        <linearGradient id={paint.id} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#ec4899" />
          <stop offset="0.5" stopColor="#f97316" />
          <stop offset="1" stopColor="#facc15" />
        </linearGradient>
      </defs>
      <Backdrop r={r} colors={["#2e1430", "#120a14"]} cy={55} />
      <path d={stroke} fill="none" stroke={paint.url} strokeWidth="30" strokeLinecap="round" opacity="0.95" />
      <path d={stroke} fill="none" stroke="#ffffff" strokeWidth="3" strokeLinecap="round" strokeDasharray="18 40" opacity="0.55" className={styles.flow} />
      <g fill={paint.url}>
        <circle cx="70" cy="70" r="6" />
        <circle cx="96" cy="176" r="4" />
        <circle cx="232" cy="128" r="7" />
        <circle cx="250" cy="150" r="3" />
        <circle cx="160" cy="58" r="3.5" />
      </g>
    </>
  );
}

const EMBLEMS: Record<string, (r: Ref) => ReactNode> = {
  avatar,
  fuego,
  agua,
  rayo,
  tierra,
  viento,
  baile,
  pelea,
  espadas_neon: (r) => blades(r, ["#33ffd9", "#d9ff26"], ["#e6fffb", "#fbffe0"], ["#0d2a2c", "#081418"], false),
  espadas_fuego: (r) => blades(r, ["#ff6a00", "#ffb000"], ["#fff1d6", "#fff7e0"], ["#3a1406", "#150b0c"], true),
  // Presets fijos (configs/presets/).
  body_aura: bodyAura,
  doodle_dance: doodleDance,
  face_neon: faceNeon,
  face_runes: faceRunes,
  fight_comic: fightComic,
  neon_joints: neonJoints,
  paint_reveal: paintReveal,
  avatar_fire: avatar,
  avatar_storm: avatar,
};

/** Para un estilo sin emblema propio (uno nuevo que aún no tiene): destellos neutros. */
function generic(r: Ref): ReactNode {
  const glow = r("glow");
  const star = "M150 54 l12 34 l34 12 l-34 12 l-12 34 l-12 -34 l-34 -12 l34 -12z";
  return (
    <>
      <defs>
        <Glow r={r} blur={8} />
      </defs>
      <Backdrop r={r} colors={["#123446", "#0a1220"]} />
      <path d={star} fill="#22d3ee" opacity="0.6" filter={glow.url} />
      <path d={star} fill="#e0f7ff" className={styles.pulse} />
    </>
  );
}

/**
 * El emblema ilustrado de un estilo del Estudio: una figura propia por catálogo (fuego, agua, rayo,
 * espadas…) sobre un fondo teñido con su color. Se anima solo cuando `active`.
 */
export function StyleEmblem({ style, active = false, className }: Props) {
  const base = useId().replace(/:/g, "");
  const r: Ref = (name) => ({ id: `${base}-${name}`, url: `url(#${base}-${name})` });
  const draw = EMBLEMS[style] ?? generic;
  return (
    <svg viewBox="0 0 300 220" preserveAspectRatio="xMidYMid slice" className={`${styles.emblem} ${active ? styles.active : ""} ${className ?? ""}`} aria-hidden="true">
      {draw(r)}
    </svg>
  );
}
