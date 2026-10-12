import type { Rgb } from "./types";

export const rgb = ([r, g, b]: Rgb, alpha = 1): string =>
  `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${alpha})`;

export const timecode = (seconds: number): string => {
  const s = Math.max(0, seconds);
  const minutes = Math.floor(s / 60);
  const rest = s - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${rest.toFixed(1).padStart(4, "0")}`;
};

export const ago = (epoch: number): string => {
  const diff = Date.now() / 1000 - epoch;
  if (diff < 60) return "hace un momento";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  return new Date(epoch * 1000).toLocaleDateString("es", { day: "numeric", month: "short" });
};

/** Nombres legibles de las acciones que detecta el análisis. */
export const ACTIONS: Record<string, string> = {
  fast_swing: "Golpe rápido",
  spotlight: "Protagonista",
  prop_transfer: "Pase de objeto",
  prop_spin: "Giro de objeto",
  prop_worn: "Se lo pone",
  face_touch: "Mano en la cara",
  throw: "Lanzamiento",
  neck_slash: "Ya valió",
  stomp: "Pisotón",
  step: "Paso",
  frenzy: "Baile intenso",
  beat: "Golpe musical",
  heart_hands: "Corazón",
  arms_up: "Brazos arriba",
  arms_open: "Brazos en cruz",
  point: "Señalar",
  hand_ear: "Mano al oído",
  cover_eyes: "Ojos tapados",
  spin_body: "Giro",
  person_contact: "Impacto",
  fist_clash: "Choque de puños",
  body_bump: "Choque de cuerpos",
  lull: "Pausa",
  intent: "Intención",
  intended_strike: "Golpe con intención",
  blade_swing: "Tajo",
  blade_ground: "Hoja al piso",
  flip: "Voltereta",
  tumble: "Giro",
  jump: "Salto",
  landing: "Aterrizaje",
  entrance: "Entrada",
};

export const actionLabel = (action: string): string => ACTIONS[action] ?? action.replaceAll("_", " ");
export const choiceLabel = (choice: string): string => choice.replaceAll("_", " ");

/** Color estable por acción para los marcadores de la línea de tiempo. */
export const actionHue = (action: string): number => {
  let hash = 0;
  for (const char of action) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
};
