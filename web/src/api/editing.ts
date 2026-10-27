/**
 * Cambios pendientes del editor de efectos: lo que la persona hizo y todavía no se aplica.
 * Funciones puras: de aquí salen la vista previa en la línea de tiempo (qué se quitó, movió o
 * agregó), la lista de cambios para la API y el tiempo estimado de aplicarlos.
 */
import type { EditOp, EditorMoment, EditorOption, EditorTrack } from "./types";

export interface MomentChange {
  removed?: boolean;
  start?: number;
  end?: number;
}

export interface TrackChange {
  off?: boolean;
  color?: string;
  intensity?: number;
  size?: number;
}

export interface Added {
  key: string;
  option: string;
  action: string;
  track: string;
  /** Elemento de la opción (para dibujar la pista nueva si todavía no existe). */
  element?: string | null;
  start: number;
  end: number;
}

export interface Pending {
  moments: Record<string, MomentChange>;
  tracks: Record<string, TrackChange>;
  added: Added[];
}

export const EMPTY: Pending = { moments: {}, tracks: {}, added: [] };

/** Cómo se ve un momento con los cambios pendientes. */
export interface ShownMoment extends EditorMoment {
  state: "same" | "removed" | "moved" | "added";
  /** Dónde estaba antes de moverlo. */
  was?: { start: number; end: number };
}

/** Los efectos permanentes (always:<figura>) duran todo el video: solo se apagan o se estilizan. */
export const isPermanent = (key: string): boolean => key.startsWith("always:");

/** Icono y color de una pista nueva, según su elemento. */
const ELEMENT_LOOK: Record<string, { icon: string; color: string }> = {
  fuego: { icon: "flame", color: "#f59e0b" },
  agua: { icon: "drop", color: "#1e90ff" },
  aire: { icon: "wind", color: "#7dd3fc" },
  rayo: { icon: "bolt", color: "#a855f7" },
  tierra: { icon: "mountain", color: "#a8a29e" },
};
const OTHER_LOOK = { icon: "sparkles", color: "#22d3ee" };

/** Las pistas con las filas nuevas: una opción agregada cuya pista no existe todavía crea una fila pendiente. */
export function withPending(tracks: EditorTrack[], pending: Pending): EditorTrack[] {
  const known = new Set(tracks.map((t) => t.key));
  const extra: EditorTrack[] = [];
  for (const add of pending.added) {
    if (known.has(add.track)) {
      const row = extra.find((t) => t.key === add.track);
      if (row) {
        row.start = Math.min(row.start, add.start);
        row.end = Math.max(row.end, add.end);
      }
      continue;
    }
    known.add(add.track);
    const look = (add.element && ELEMENT_LOOK[add.element]) || OTHER_LOOK;
    extra.push({ key: add.track, label: add.track, icon: look.icon, color: look.color, element: add.element ?? null, start: add.start, end: add.end, moments: [] });
  }
  return extra.length ? [...tracks, ...extra] : tracks;
}

const ELEMENT_ORDER: [string | null, string][] = [
  ["fuego", "Fuego"],
  ["agua", "Agua"],
  ["aire", "Viento"],
  ["rayo", "Rayo"],
  ["tierra", "Tierra"],
  [null, "Otros efectos"],
];

/** Las opciones para agregar, agrupadas por elemento y filtradas por nombre (`label` traduce el nombre interno). */
export function groupOptions(options: EditorOption[], query: string, label: (name: string) => string): { element: string | null; title: string; options: EditorOption[] }[] {
  const needle = query.trim().toLowerCase();
  const known = new Set(ELEMENT_ORDER.map(([e]) => e));
  return ELEMENT_ORDER.map(([element, title]) => ({
    element,
    title,
    options: options
      .filter((o) => (known.has(o.element) ? o.element : null) === element)
      .filter((o) => !needle || label(o.option).toLowerCase().includes(needle))
      .sort((a, b) => label(a.option).localeCompare(label(b.option), "es")),
  })).filter((g) => g.options.length > 0);
}

export function shownMoments(track: EditorTrack, pending: Pending): ShownMoment[] {
  const off = pending.tracks[track.key]?.off ?? false;
  const shown: ShownMoment[] = track.moments.map((moment) => {
    const change = pending.moments[moment.id];
    if (off || change?.removed) return { ...moment, state: "removed" };
    if (change && (change.start !== undefined || change.end !== undefined)) {
      return { ...moment, start: change.start ?? moment.start, end: change.end ?? moment.end, state: "moved", was: { start: moment.start, end: moment.end } };
    }
    return { ...moment, state: "same" };
  });
  for (const add of pending.added.filter((a) => a.track === track.key)) {
    shown.push({ id: add.key, start: add.start, end: add.end, choice: add.option, action: add.action, person: null, note: "", state: "added" });
  }
  return shown.sort((a, b) => a.start - b.start);
}

/** La lista de cambios que entiende la API, en un orden que siempre se puede aplicar. */
export function buildEdits(pending: Pending, tracks: EditorTrack[]): EditOp[] {
  const ops: EditOp[] = [];
  const off = new Set(Object.entries(pending.tracks).filter(([, c]) => c.off).map(([key]) => key));
  for (const key of off) ops.push({ op: "track_off", track: key });
  for (const track of tracks) {
    if (off.has(track.key)) continue;
    if (isPermanent(track.key)) continue; // los permanentes no se mueven ni se quitan
    for (const moment of track.moments) {
      const change = pending.moments[moment.id];
      if (!change) continue;
      if (change.removed) ops.push({ op: "remove", moment: moment.id });
      else if (change.start !== undefined || change.end !== undefined)
        ops.push({ op: "move", moment: moment.id, start: round(change.start ?? moment.start), end: round(change.end ?? moment.end) });
    }
  }
  for (const add of pending.added) {
    if (!off.has(add.track)) ops.push({ op: "add", option: add.option, action: add.action, track: add.track, start: round(add.start), end: round(add.end) });
  }
  for (const [key, change] of Object.entries(pending.tracks)) {
    if (change.off || (change.color === undefined && change.intensity === undefined && change.size === undefined)) continue;
    ops.push({ op: "style", track: key, color: change.color, intensity: change.intensity, size: change.size });
  }
  return ops;
}

export const countChanges = (pending: Pending): number =>
  Object.values(pending.moments).filter((c) => c.removed || c.start !== undefined || c.end !== undefined).length +
  Object.values(pending.tracks).filter((c) => c.off || c.color !== undefined || c.intensity !== undefined || c.size !== undefined).length +
  pending.added.length;

/** Segundos de video que hay que volver a dibujar (aproximado: el servidor lo calcula exacto),
 * con el calentamiento de 2 s que se dibuja antes; los cambios de estilo cubren su pista entera. */
export function redrawSeconds(pending: Pending, tracks: EditorTrack[], duration: number): number {
  const spans: [number, number][] = [];
  for (const track of tracks) {
    const change = pending.tracks[track.key];
    if (change && (change.off || change.color !== undefined || change.intensity !== undefined || change.size !== undefined)) spans.push([track.start, track.end]);
    for (const moment of track.moments) {
      const m = pending.moments[moment.id];
      if (!m) continue;
      spans.push([moment.start, moment.end]);
      if (m.start !== undefined || m.end !== undefined) spans.push([m.start ?? moment.start, m.end ?? moment.end]);
    }
  }
  for (const add of pending.added) spans.push([add.start, add.end]);
  if (spans.length === 0) return 0;
  const from = Math.max(Math.min(...spans.map(([a]) => a)) - 2, 0);
  const to = Math.min(Math.max(...spans.map(([, b]) => b)) + 0.5, duration);
  return Math.min(to - from, duration);
}

const round = (value: number): number => Math.round(value * 100) / 100;
