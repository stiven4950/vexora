/**
 * Cambios pendientes del editor de efectos: lo que la persona hizo y todavía no se aplica.
 * Funciones puras: de aquí salen la vista previa en la línea de tiempo (qué se quitó, movió o
 * agregó), la lista de cambios para la API y el tiempo estimado de aplicarlos.
 */
import type { EditOp, EditorMoment, EditorTrack } from "./types";

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
