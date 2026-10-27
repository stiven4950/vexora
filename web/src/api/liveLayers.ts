/**
 * Vista en vivo del editor: de los cambios pendientes a lo que dibuja cada baldosa del mosaico de
 * capas (src/vfxglow/composite/atlas.py; la mezcla, en components/editor/LayerCanvas.tsx).
 *
 * Se ve al instante, sin volver a dibujar: apagar una pista, quitar un momento, el color, la
 * intensidad y el tamaño. Mover o agregar no (el efecto seguiría a otra pose del cuerpo): esos
 * cambios se marcan como aproximados y se ven con "Vista previa" o al aplicar.
 */
import type { Pending } from "./editing";
import type { EditorTrack } from "./types";

/** La distribución del mosaico (AtlasLayout en composite/atlas.py). Coordenadas en píxeles del mosaico. */
export interface LayerTile {
  key: string;
  c: [number, number];
  a: [number, number] | null;
  /** Centro de la energía por fotograma, en milésimas del cuadro: [x0, y0, x1, y1, ...]; -1 = nada. */
  centers: number[];
}

export interface LayerLayout {
  version: number;
  encoding: string;
  fps: number;
  frames: number;
  width: number;
  height: number;
  tile: [number, number];
  plate: [number, number, number, number];
  tracks: LayerTile[];
  rest: LayerTile | null;
}

/** Lo que se aplica a una baldosa. `hidden`: tramos (segundos) en que no se dibuja (momentos quitados). */
export interface TileLive {
  tile: LayerTile;
  gain: number;
  size: number;
  /** Color elegido como en director/edits.py `_hex` (0-1, sin pasar a lineal), o null. */
  tint: [number, number, number] | null;
  hidden: [number, number][];
}

export interface LiveState {
  tiles: TileLive[];
  /** Pistas con cambios que la vista en vivo no puede mostrar tal cual (mover, agregar, pistas sin baldosa). */
  approximate: string[];
}

/** Lo que dura encendido un efecto después de su momento (estelas, fundidos). */
const TAIL_S = 0.5;

export function hexToRgb(hex: string): [number, number, number] | null {
  const text = hex.trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(text)) return null;
  return [0, 2, 4].map((i) => parseInt(text.slice(i, i + 2), 16) / 255) as [number, number, number];
}

/** `ranges` menos `keep` (tramos ordenados o no). */
export function subtract(ranges: [number, number][], keep: [number, number][]): [number, number][] {
  let out = ranges.map((r) => [...r] as [number, number]);
  for (const [k0, k1] of keep) {
    out = out.flatMap(([a, b]) => {
      if (k1 <= a || k0 >= b) return [[a, b] as [number, number]];
      const parts: [number, number][] = [];
      if (k0 > a) parts.push([a, k0]);
      if (k1 < b) parts.push([k1, b]);
      return parts;
    });
  }
  return out;
}

export function liveState(layout: LayerLayout, tracks: EditorTrack[], pending: Pending): LiveState {
  const own = new Set(layout.tracks.map((t) => t.key));
  const approximate = new Set<string>();
  const byKey = new Map(tracks.map((t) => [t.key, t]));

  const tileFor = (tile: LayerTile): TileLive => {
    const track = byKey.get(tile.key);
    const change = pending.tracks[tile.key] ?? {};
    const removed: [number, number][] = [];
    const kept: [number, number][] = [];
    for (const moment of track?.moments ?? []) {
      const edit = pending.moments[moment.id];
      const moved = edit && !edit.removed && (edit.start !== undefined || edit.end !== undefined);
      if (edit?.removed || moved) removed.push([moment.start, moment.end + TAIL_S]);
      else kept.push([moment.start, moment.end]);
      if (moved && track) approximate.add(track.label);
    }
    return {
      tile,
      gain: change.off ? 0 : (change.intensity ?? 1),
      size: change.size ?? 1,
      tint: change.color ? hexToRgb(change.color) : null,
      hidden: subtract(removed, kept),
    };
  };

  const tiles = layout.tracks.map(tileFor);
  if (layout.rest) tiles.push({ tile: layout.rest, gain: 1, size: 1, tint: null, hidden: [] });

  // Lo que no tiene baldosa propia (va en "rest") no se puede apagar ni teñir por separado.
  for (const track of tracks) {
    if (own.has(track.key)) continue;
    const touched = pending.tracks[track.key] || track.moments.some((m) => pending.moments[m.id]);
    if (touched) approximate.add(track.label);
  }
  for (const add of pending.added) approximate.add(byKey.get(add.track)?.label ?? add.track);
  return { tiles, approximate: [...approximate] };
}

/** Si la baldosa se dibuja en el instante `t` (segundos). */
export function visibleAt(live: TileLive, t: number): boolean {
  return live.gain > 0 && !live.hidden.some(([a, b]) => t >= a && t < b);
}

/** El centro (0-1) de la baldosa en el fotograma `frame`; el del cuadro si no hay nada dibujado. */
export function centerAt(tile: LayerTile, frame: number): [number, number] {
  const i = Math.max(0, Math.min(frame, tile.centers.length / 2 - 1)) * 2;
  const x = tile.centers[i];
  const y = tile.centers[i + 1];
  return x === undefined || y === undefined || x < 0 ? [0.5, 0.5] : [x / 1000, y / 1000];
}
