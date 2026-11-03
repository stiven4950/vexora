"""Delinear la ropa (estilo desfile, docs/referencias/video_46.md): los trazos de la prenda que da
analysis/garment.py, en neón con el color del outfit.

- garment_lines: al empezar el outfit (la toma) elige sus trazos: los que más aparecen y más contraste
  tienen en esa toma (así son los mismos de principio a fin): el calzado y el bolso, un par de
  fronteras (prenda contra piel o contra el calzado) y unos pocos bordes de adentro (costuras,
  solapas, franjas). Cuántos, según la perilla `density`. Entra completo en el corte, sigue la tela
  cuadro a cuadro y en los últimos cuadros se parte en guiones (la salida de la referencia).
- garment_zones: zonas de la prenda pintadas con luz (video_55): el turno pasa de una zona a otra
  (torso, mangas, piernas, bolso); la de turno se tiñe suave con el color del outfit y un brillo la
  cruza en diagonal como un reflejo en la tela, con destellos donde toca el borde.
- garment_reveal: el estreno de un outfit nuevo (video_55, 1,9-2,7 s): un barrido de luz blanca cruza
  la prenda, la deja entera teñida del color del outfit con su silueta delineada y se desvanece hacia
  los trazos. No en el outfit con el que empieza el video (ahí no hay cambio).
- garment_ecg: una onda tipo electrocardiograma que cruza el pantalón a la altura de la cadera
  (video_55, 2,4-3,5 s): varias hebras con picos que corren de lado a lado, recortadas a la prenda.
"""

from __future__ import annotations

import zlib

import cv2
import numpy as np

from vfxglow.engine.eye_family import pick_knobs
from vfxglow.engine.hand_props import _dashed
from vfxglow.engine.raster import fill_polygon, splat

GARMENT_FX = ("garment_lines", "garment_zones", "garment_reveal", "garment_ecg")
# Cuántos trazos de cada clase elige un outfit (con la perilla `density`: 0,6, 1 o 1,5) y en cuántos de
# los cuadros de la toma tiene que aparecer uno para contar.
PICK = {"accessory": 4, "border": 2, "inner": 3}
PRESENCE = 0.3
# Un trazo que falta unos cuadros se sostiene donde estaba (la máscara parpadea).
HOLD_FRAMES = 3
# La salida: los últimos cuadros de la toma se parte en guiones de este largo (fracción del alto).
EXIT_FRAMES = 6
DASH = 0.03


def _choose(strokes_by_frame: dict, start: int, end: int, density: float, seed: int) -> set[int]:
    """Los trazos de este outfit: por clase, los que más aparecen por su contraste medio."""
    frames = [f for f in range(start, end + 1) if f in strokes_by_frame]
    strokes_by_frame = {f: strokes_by_frame[f]["strokes"] if isinstance(strokes_by_frame[f], dict) else strokes_by_frame[f] for f in frames}
    if not frames:
        return set()
    seen: dict[int, list] = {}
    for f in frames:
        for stroke in strokes_by_frame[f]:
            seen.setdefault(stroke["id"], []).append(stroke)
    rng = np.random.default_rng(seed)
    chosen: set[int] = set()
    for kind, count in PICK.items():
        candidates = []
        for sid, rows in seen.items():
            if rows[0]["kind"] != kind or len(rows) < PRESENCE * len(frames):
                continue
            # Un poco de azar para que dos outfits parecidos no elijan igual (con semilla: repetible).
            candidates.append((len(rows) / len(frames) * float(np.mean([r["score"] for r in rows])) * rng.uniform(0.85, 1.15), sid))
        take = max(int(round(count * density)), 1 if kind != "inner" else 0)
        chosen |= {sid for _, sid in sorted(candidates, reverse=True)[:take]}
    return chosen


def garment_lines(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    strokes_by_frame = getattr(runtime, "garment", None) or {}
    if not strokes_by_frame or event is None:
        return []
    height, width = runtime.frame_shape
    knobs = pick_knobs(shape, body.prefix, event.start_frame, runtime.effect.style.variants)
    # Los trazos se eligen por toma: un outfit puede tener varias (capas que se suman con un corte) y
    # al cortar los trazos son otros. El color y la salida siguen siendo del outfit.
    take = max(getattr(runtime, "take_start", event.start_frame), event.start_frame)
    take_end = min(getattr(runtime, "next_cut", None) or event.end_frame + 1, event.end_frame + 1) - 1
    st = runtime.swoosh.setdefault(f"_garment:{event.start_frame}:{take}", {"last": {}})
    if "ids" not in st:
        seed = zlib.crc32(f"garment:{take}:{runtime.effect.id}".encode())
        st["ids"] = _choose(strokes_by_frame, take, take_end, float(knobs["density"]), seed)
    for stroke in (strokes_by_frame.get(frame_index) or {}).get("strokes", []):
        if stroke["id"] in st["ids"]:
            st["last"][stroke["id"]] = (frame_index, np.asarray(stroke["points"], dtype=np.float64) * [width, height])
    live = [curve for seen, curve in st["last"].values() if frame_index - seen <= HOLD_FRAMES]
    # El calzado: lo que queda abajo del todo (se pinta en arcoíris si el outfit es holográfico).
    marked = [(curve, curve[:, 1].mean() > SHOE_LINE * height) for curve in live]
    left = event.end_frame - frame_index
    if left < EXIT_FRAMES:  # la salida: se parte en guiones
        keep = max(left, 0) / EXIT_FRAMES
        marked = [(piece, shoe) for curve, shoe in marked for piece in _dashed(curve, keep, DASH * height)]
    marked = [(curve, shoe) for curve, shoe in marked if len(curve) >= 2]
    tint = np.asarray(color, np.float32)
    holo = runtime.effect.style.variants.get("holo")
    rng = np.random.default_rng(zlib.crc32(f"holo:{event.start_frame}:{runtime.effect.id}".encode()))
    if not (bool(holo[0]) if holo else rng.random() < HOLO_CHANCE):
        return [(curve, tint) for curve, _shoe in marked]
    # Holográfico (video_55): cada línea en su color y, a los lados, una copia roja y otra azul corridas
    # unos píxeles (separación de color); el calzado, en arcoíris que corre a lo largo.
    shift = HOLO_SHIFT * height
    out = []
    for curve, shoe in marked:
        out += _rainbow(curve, frame_index) if shoe else [(curve, tint)]
        out += [(curve + [-shift, 0.0], RED * 0.6), (curve + [shift, 0.0], BLUE * 0.6)]
    return out


HOLO_CHANCE = 0.35
HOLO_SHIFT = 0.003
SHOE_LINE = 0.82
RED = np.array([1.0, 0.1, 0.1], np.float32)
BLUE = np.array([0.15, 0.35, 1.0], np.float32)
RAINBOW_PIECES = 7


def _rainbow(curve: np.ndarray, frame_index: int) -> list:
    """La línea partida en tramos de colores del arcoíris que corren a lo largo."""
    out = []
    n = len(curve)
    for k in range(RAINBOW_PIECES):
        a, b = k * (n - 1) // RAINBOW_PIECES, (k + 1) * (n - 1) // RAINBOW_PIECES + 1
        hue = ((k / RAINBOW_PIECES + frame_index * 0.03) % 1.0) * 179
        rgb = cv2.cvtColor(np.uint8([[[hue, 220, 255]]]), cv2.COLOR_HSV2RGB)[0, 0] / 255.0
        if b - a >= 2:
            out.append((curve[a:b], np.asarray(rgb, np.float32) * 1.2))
    return out


# Zonas: cuánto dura el turno de cada una (s), el fundido entre turnos (fracción del turno), en cuántos
# cuadros de la toma tiene que aparecer una zona para entrar en la ronda, el tinte y el brillo.
ZONE_TURN_S = 0.9
ZONE_FADE = 0.3
ZONE_PRESENCE = 0.5
ZONE_TINT = 0.3
SHEEN_WIDTH = 0.09
SHEEN_GAIN = 1.1
ZONE_ORDER = ("torso", "sleeve_right", "leg_left", "bag", "sleeve_left", "leg_right")


def _zone_order(rows: dict, start: int, end: int, seed: int) -> list[str]:
    """Las zonas que entran en la ronda (las que se ven casi toda la toma), en un orden con semilla
    que empieza siempre por la más grande de las que estén (el torso, si está)."""
    frames = [f for f in range(start, end + 1) if f in rows]
    present = [z for z in ZONE_ORDER if frames and sum(z in (rows[f].get("zones") or {}) for f in frames) >= ZONE_PRESENCE * len(frames)]
    if len(present) <= 2:
        return present
    rest = present[1:]
    np.random.default_rng(seed).shuffle(rest)
    return present[:1] + rest


def _sheen(layer: np.ndarray, poly: np.ndarray, angle: float, center: float, tint, alpha: float) -> tuple[np.ndarray, np.ndarray] | None:
    """Un brillo en banda que cruza la zona en la dirección `angle`; `center` de 0 a 1 es dónde va la
    banda. Devuelve (la dirección, el borde de la banda) para los destellos."""
    lo = np.floor(poly.min(axis=0)).astype(int) - 2
    hi = np.ceil(poly.max(axis=0)).astype(int) + 3
    h, w = layer.shape[:2]
    x0, y0, x1, y1 = max(lo[0], 0), max(lo[1], 0), min(hi[0], w), min(hi[1], h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    mask = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.fillPoly(mask, [np.round(poly - [x0, y0]).astype(np.int32)], 1.0, lineType=cv2.LINE_AA)
    mask = cv2.GaussianBlur(mask, (0, 0), 1.5)
    direction = np.array([np.cos(angle), np.sin(angle)])
    yy, xx = np.mgrid[y0:y1, x0:x1]
    proj = xx * direction[0] + yy * direction[1]
    span = poly @ direction
    s = (proj - span.min()) / max(float(np.ptp(span)), 1.0)
    band = np.exp(-(((s - center) / SHEEN_WIDTH) ** 2)).astype(np.float32) * mask * np.float32(alpha)
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += np.asarray(tint, np.float32) * band[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - band)
    return direction, span


def garment_zones(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    rows = getattr(runtime, "garment", None) or {}
    if not rows or event is None:
        return []
    height, width = runtime.frame_shape
    fps = getattr(runtime, "fps", 30.0) or 30.0
    st = runtime.swoosh.setdefault(f"_zones:{event.start_frame}", {"last": {}})
    seed = zlib.crc32(f"zones:{event.start_frame}:{runtime.effect.id}".encode())
    if "order" not in st:
        st["order"] = _zone_order(rows, event.start_frame, event.end_frame, seed)
    for name, pts in ((rows.get(frame_index) or {}).get("zones") or {}).items():
        st["last"][name] = (frame_index, np.asarray(pts, dtype=np.float64) * [width, height])
    if not st["order"]:
        return []
    turn = ZONE_TURN_S * fps
    clock = (frame_index - event.start_frame) / turn
    k, t = int(clock), clock - int(clock)
    tint = np.asarray(color, np.float32)
    shine = tint * 0.35 + 0.65  # el brillo, casi blanco con el color del outfit
    lines = []
    rng = np.random.default_rng([seed, k])
    for step, weight in ((k, min(t / ZONE_FADE, 1.0) if k else 1.0), (k - 1, max(1.0 - t / ZONE_FADE, 0.0))):
        if step < 0 or weight <= 0.0:
            continue
        name = st["order"][step % len(st["order"])]
        seen, poly = st["last"].get(name, (-10_000, None))
        if poly is None or frame_index - seen > 3 or len(poly) < 3:
            continue
        # Un tinte suave, sin borde: las fronteras entre zonas las pone la pose y no existen en la tela.
        fill_polygon(layer, poly, tint, alpha * ZONE_TINT * weight, 1.0, feather=0.012 * height)
        if step == k:  # el brillo cruza la zona en este turno
            angle = np.radians(60.0 + 60.0 * rng.random()) * (1 if rng.random() < 0.5 else -1)
            center = -0.15 + 1.3 * t
            found = _sheen(layer, poly, angle, center, shine, alpha * SHEEN_GAIN * weight)
            if found is not None:  # destellos donde la banda toca el borde
                direction, span = found
                s = (span - span.min()) / max(float(np.ptp(span)), 1.0)
                for idx in np.argsort(np.abs(s - center))[:2]:
                    at = poly[idx]
                    arm = 0.012 * height
                    lines += [(np.array([at - [arm, 0], at + [arm, 0]]), shine), (np.array([at - [0, arm * 1.6], at + [0, arm * 1.6]]), shine)]
                    splat(layer, float(at[0]), float(at[1]), 0.004 * height + 1.0, shine, alpha, runtime.kernels)
    return lines


# Revelado: cuánto tarda el barrido, cuánto dura la prenda entera teñida y su fundido de salida (s);
# brillo del barrido y del tinte.
REVEAL_WIPE_S = 0.3
REVEAL_HOLD_S = 0.4
REVEAL_FADE_S = 0.35
REVEAL_FLASH = 1.4
REVEAL_TINT = 0.5


def _garment_mask(polys: list[np.ndarray], shape: tuple[int, int]) -> tuple[np.ndarray, int, int] | None:
    """La prenda entera (todas sus zonas) como máscara de su recuadro: (máscara, x0, y0)."""
    if not polys:
        return None
    pts = np.vstack(polys)
    h, w = shape
    x0, y0 = max(int(pts[:, 0].min()) - 3, 0), max(int(pts[:, 1].min()) - 3, 0)
    x1, y1 = min(int(pts[:, 0].max()) + 4, w), min(int(pts[:, 1].max()) + 4, h)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(mask, [np.round(p - [x0, y0]).astype(np.int32) for p in polys], 255, lineType=cv2.LINE_AA)
    return mask, x0, y0


def garment_reveal(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    rows = getattr(runtime, "garment", None) or {}
    if not rows or event is None or event.start_frame == 0:
        return []
    fps = getattr(runtime, "fps", 30.0) or 30.0
    t = (frame_index - event.start_frame) / fps
    if t > REVEAL_WIPE_S + REVEAL_HOLD_S + REVEAL_FADE_S:
        return []
    height, width = runtime.frame_shape
    zones = ((rows.get(frame_index) or {}).get("zones") or {})
    # Solo la ropa (torso, mangas, piernas): el bolso y el calzado tienen sus propios trazos.
    polys = [np.asarray(pts, dtype=np.float64) * [width, height] for name, pts in zones.items() if name.split("_")[0] in ("torso", "sleeve", "leg")]
    found = _garment_mask(polys, layer.shape[:2])
    if found is None:
        return []
    mask, x0, y0 = found
    weight = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 2.0)
    tint = np.asarray(color, np.float32)
    yy, xx = np.mgrid[y0 : y0 + mask.shape[0], x0 : x0 + mask.shape[1]]
    s = (xx - x0) / max(mask.shape[1], 1) * 0.6 + (yy - y0) / max(mask.shape[0], 1) * 0.4  # en diagonal, de arriba a la izquierda
    wipe = float(np.clip(t / REVEAL_WIPE_S, 0.0, 1.0))
    fade = 1.0 - float(np.clip((t - REVEAL_WIPE_S - REVEAL_HOLD_S) / REVEAL_FADE_S, 0.0, 1.0))
    covered = (s <= wipe * 1.05).astype(np.float32)
    front = np.exp(-(((s - wipe) / 0.06) ** 2)).astype(np.float32) if wipe < 1.0 else 0.0
    energy = weight * (covered * REVEAL_TINT * fade + front * REVEAL_FLASH) * np.float32(alpha)
    shine = tint * 0.3 + 0.7  # el frente del barrido, casi blanco
    paint = (tint[None, None, :] * (covered * REVEAL_TINT * fade)[..., None] + shine[None, None, :] * (front * REVEAL_FLASH if wipe < 1.0 else 0.0)[..., None] if wipe < 1.0 else tint[None, None, :] * (REVEAL_TINT * fade))
    dst = layer[y0 : y0 + mask.shape[0], x0 : x0 + mask.shape[1]]
    dst[..., :3] += paint * (weight * np.float32(alpha))[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - np.clip(energy, 0.0, 1.0))
    if wipe < 1.0 or fade <= 0.0:
        return []
    # Estrenada: la silueta de la prenda (no las fronteras entre zonas, que pone la pose).
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return [(c[:, 0, :].astype(np.float64) + [x0, y0], (tint * 0.4 + 0.6) * fade) for c in contours if len(c) > 20]


# Onda: a qué altura de las piernas va (fracción desde la cadera), cuántas hebras, alto de los picos
# (fracción del alto del cuadro) y a qué velocidad corren (fracción del ancho por cuadro de 30 fps).
WAVE_AT = 0.22
WAVE_STRANDS = 3
WAVE_PEAK = 0.06
WAVE_SPEED = 0.02
WAVE_POINTS = 90


def garment_ecg(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    rows = getattr(runtime, "garment", None) or {}
    if not rows or event is None:
        return []
    height, width = runtime.frame_shape
    zones = ((rows.get(frame_index) or {}).get("zones") or {})
    legs = [np.asarray(zones[k], dtype=np.float64) * [width, height] for k in ("leg_left", "leg_right") if k in zones]
    found = _garment_mask(legs, layer.shape[:2])
    if found is None:
        return []
    mask, x0, y0 = found
    pts = np.vstack(legs)
    top, bottom = pts[:, 1].min(), pts[:, 1].max()
    y = top + WAVE_AT * (bottom - top)
    row = int(np.clip(y - y0, 0, mask.shape[0] - 1))
    inside = np.nonzero(mask[row] > 0)[0]
    if len(inside) < 4:
        return []
    xa, xb = x0 + inside.min(), x0 + inside.max()
    tint = np.asarray(color, np.float32)
    rng = np.random.default_rng(zlib.crc32(f"wave:{event.start_frame}".encode()))
    spikes = rng.uniform(0.3, 1.0, 24) * np.where(rng.random(24) < 0.5, 1.0, -0.6)
    fps = getattr(runtime, "fps", 30.0) or 30.0
    run = (frame_index - event.start_frame) * WAVE_SPEED * 30.0 / fps
    out = []
    for k in range(WAVE_STRANDS):
        q = np.linspace(0.0, 1.0, WAVE_POINTS)
        phase = (q * 6.0 + run * 6.0 + k * 0.37) % 1.0
        idx = ((q * 6.0 + run * 6.0 + k * 0.37).astype(int) + k * 5) % len(spikes)
        # Un pico afilado por tramo, como el trazo de un electrocardiograma.
        bump = np.exp(-(((phase - 0.5) / 0.08) ** 2)) * spikes[idx]
        curve = np.stack([xa + q * (xb - xa), y + k * 0.012 * height - bump * WAVE_PEAK * height], axis=1)
        xs = np.clip(np.round(curve[:, 0] - x0).astype(int), 0, mask.shape[1] - 1)
        ys = np.clip(np.round(curve[:, 1] - y0).astype(int), 0, mask.shape[0] - 1)
        keep = mask[ys, xs] > 0
        start = None
        for i, flag in enumerate(np.append(keep, False)):  # los tramos que caen sobre el pantalón
            if flag and start is None:
                start = i
            elif not flag and start is not None:
                if i - start >= 3:
                    out.append((curve[start:i], tint * (1.0 - 0.25 * k)))
                start = None
    return out
