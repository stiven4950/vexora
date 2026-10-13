"""Efectos de gestos con significado (docs/criterio_de_analisis.md, P4).

- throw_fx, disparado por `throw`:
  - Carga (del inicio del evento a la suelta): una bola de energía crece y late en la mano.
  - Suelta (después de `end_frame`), una de `style.shapes` por activación:
    - `orb`: la bola sale volando en la dirección del lanzamiento con estela y revienta en
      chispas diminutas.
    - `ray`: un rayo sale de la mano en esa dirección y se apaga.
    - `burst`: explosión de partículas en el punto de suelta.
  Conviene un `trigger.hold` de ~0,7 s para que la suelta tenga tiempo de verse.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import MotionEvent
from vfxglow.analysis.touch import _people, fingertips
from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import neon_layers

THROW_SHAPES = ("orb", "ray", "burst")
# Bola: radio máximo en torsos. Vuelo: distancia (torsos) y duración (s). Estallido: duración.
ORB_RADIUS = 0.09
FLIGHT = 2.2
FLIGHT_S = 0.35
BURST_S = 0.35
RAY_S = 0.45
SPARKS = 18


def _circle(center: np.ndarray, radius: float, points: int = 28) -> np.ndarray:
    theta = np.linspace(0.0, 2.0 * np.pi, points)
    return center + np.stack([np.cos(theta), np.sin(theta)], axis=1) * radius


def _orb(center: np.ndarray, radius: float, color: np.ndarray, envelope: float, line: float, layer: np.ndarray) -> list:
    """Bola de energía: relleno de color, centro blanco y aro de neón."""
    fill_polygon(layer, _circle(center, radius * 1.3), color, 0.5 * envelope, 1.2, feather=radius * 0.6)
    fill_polygon(layer, _circle(center, radius * 0.55), np.ones(3, np.float32), 0.85 * envelope, 1.0, feather=radius * 0.3)
    return neon_layers(_circle(center, radius), color, line, envelope)


def _sparks(center: np.ndarray, radius: float, progress: float, color: np.ndarray, envelope: float, rng: np.random.Generator, objects: list[str] | None = None) -> list:
    """Chispas diminutas que salen en todas direcciones y se apagan; con `objects` (temporada),
    objetos de la época en su lugar (menos y más grandes)."""
    strokes = []
    fade = envelope * (1.0 - progress)
    if objects:
        from vfxglow.engine.season import object_outline

        for k, angle in enumerate(rng.uniform(0, 2 * np.pi, 7)):
            direction = np.array([np.cos(angle), np.sin(angle)])
            pos = center + direction * radius * (0.25 + 0.75 * progress)
            for curve in object_outline(objects[k % len(objects)], pos, radius * 0.09, progress, k):
                strokes += neon_layers(curve, color, 1.5, fade)
        return strokes
    for angle, speed in zip(rng.uniform(0, 2 * np.pi, SPARKS), rng.uniform(0.6, 1.0, SPARKS)):
        direction = np.array([np.cos(angle), np.sin(angle)])
        head = center + direction * radius * speed * (0.3 + 0.7 * progress)
        tail = head - direction * radius * 0.25 * (1.0 - progress)
        strokes += neon_layers(np.stack([tail, head]), color, 1.4, fade)
    return strokes


def draw_throw_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or event is None or event.name != "throw" or track is None:
        return
    width = layer.shape[1]
    torso = torso_pixels(points, height)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    seed = zlib.crc32(f"{style.seed_offset}:throw:{event.start_frame}".encode()) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    names = [n for n in style.shapes if n in THROW_SHAPES] or list(THROW_SHAPES)
    shape = names[int(rng.integers(len(names)))]
    fps = runtime.fps
    strokes: list = []
    if frame_index <= event.end_frame:
        # Carga: la bola crece en la mano y late.
        person = next((p for p in _people(track) if p.person_id == event.target.split(":")[0]), None)
        tips = fingertips(person, event.kind, width, height) if person is not None else []
        if not tips:
            return
        grow = (frame_index - event.start_frame) / max(event.end_frame - event.start_frame, 1)
        pulse = 1.0 + 0.12 * np.sin(frame_index * 0.9)
        radius = ORB_RADIUS * torso * (0.35 + 0.65 * np.clip(grow, 0.0, 1.0)) * pulse
        strokes += _orb(np.mean(tips, axis=0), radius, color, envelope, line, layer)
    else:
        start = event_point(event, points, width, height)
        if start is None:
            return
        direction = np.array([np.cos(np.radians(event.direction_deg)), np.sin(np.radians(event.direction_deg))])
        elapsed = (frame_index - event.end_frame) / fps
        if shape == "orb":
            if elapsed <= FLIGHT_S:
                u = elapsed / FLIGHT_S
                head = start + direction * FLIGHT * torso * u
                trail = np.stack([start + direction * FLIGHT * torso * max(u - 0.35, 0.0), head])
                strokes += neon_layers(trail, color, line * 1.5, envelope)
                strokes += _orb(head, ORB_RADIUS * torso, color, envelope, line, layer)
            elif elapsed <= FLIGHT_S + BURST_S:
                end = start + direction * FLIGHT * torso
                strokes += _sparks(end, torso * 0.6, (elapsed - FLIGHT_S) / BURST_S, color, envelope, rng, style.objects)
        elif shape == "ray":
            if elapsed <= RAY_S:
                u = elapsed / RAY_S
                reach = 3.5 * torso * min(u / 0.3, 1.0)
                fade = envelope * (1.0 - max(u - 0.3, 0.0) / 0.7)
                strokes += neon_layers(np.stack([start, start + direction * reach]), color, line * 2.0, fade)
        elif elapsed <= BURST_S * 1.5:
            strokes += _sparks(start, torso * 0.8, elapsed / (BURST_S * 1.5), color, envelope, rng, style.objects)
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)


POP_S = 0.4


def draw_pop_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Pisotón (`stomp`): un globo se infla bajo el pie mientras baja y revienta al pisar, con
    chispas y ráfagas de aire (video_33 seg. 28,2)."""
    style = runtime.effect.style
    if envelope <= 0 or event is None or event.name != "stomp":
        return
    width = layer.shape[1]
    ground = event_point(event, points, width, height)
    if ground is None:
        return
    torso = torso_pixels(points, height)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    radius = 0.16 * torso
    strokes: list = []
    if frame_index <= event.end_frame:
        grow = np.clip((frame_index - event.start_frame) / max(event.end_frame - event.start_frame, 1), 0.0, 1.0)
        r = radius * (0.4 + 0.6 * grow)
        center = ground - np.array([0.0, r * 0.9])
        balloon = _circle(center, r)
        balloon[:, 0] = center[0] + (balloon[:, 0] - center[0]) * 0.9
        strokes += neon_layers(balloon, color, line, envelope)
        knot = np.array([center + [0, r], center + [-r * 0.12, r * 1.18], center + [r * 0.12, r * 1.18], center + [0, r]])
        strokes += neon_layers(knot, color, line * 0.8, envelope)
        shine = _circle(center + np.array([-r * 0.35, -r * 0.35]), r * 0.18, 10)[:6]
        strokes += neon_layers(shine, WHITE, line * 0.7, envelope)
    else:
        u = (frame_index - event.end_frame) / max(POP_S * runtime.fps, 1.0)
        if u > 1.0:
            return
        center = ground - np.array([0.0, radius * 0.9])
        rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:pop:{event.end_frame}".encode()) & 0xFFFFFFFF)
        fade = envelope * (1.0 - u)
        for angle in np.linspace(0, 2 * np.pi, 10, endpoint=False) + rng.uniform(0, 0.4):
            direction = np.array([np.cos(angle), np.sin(angle)])
            inner = center + direction * radius * (0.9 + 1.2 * u)
            strokes += neon_layers(np.stack([inner, inner + direction * radius * 0.45]), color, line, fade)
        # Ráfagas de aire: arcos cortos que se abren a los lados.
        for side in (-1.0, 1.0):
            arc = np.linspace(-0.6, 0.6, 8)
            reach = radius * (1.4 + 1.6 * u)
            strokes += neon_layers(np.stack([center + np.array([side * reach * np.cos(a), reach * np.sin(a) * 0.5]) for a in arc]), WHITE, line * 0.7, fade)
        strokes += _sparks(center, radius * 2.5, u, color, envelope, rng, style.objects)
    stroke_batch(layer, strokes, style.hdr_gain)


WHITE = np.array([1.0, 1.0, 1.0], dtype=np.float32)


# ----- gestos sostenidos -----


def event_point(event: MotionEvent, points, width: int, height: int) -> np.ndarray | None:
    """Dónde ocurrió el evento: su posición o, en la copia para la pareja (sin posición), la
    articulación de su objetivo."""
    if event.position is not None:
        return np.array(event.position, dtype=np.float64) * [width, height]
    return points.get(event.target)


def _person_points(points, event: MotionEvent | None):
    person = event.target.split(":")[0] if event is not None and event.target.startswith("person_") else None
    prefix = f"{person}:" if person else ""
    # Con una sola persona los puntos no llevan prefijo.
    return lambda name: points.get(f"{prefix}{name}", points.get(name))


def _heart(center: np.ndarray, size: float) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * np.pi, 48)
    x = 16 * np.sin(t) ** 3 / 17
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)) / 17
    return center + np.stack([x, y], axis=1) * size


def draw_heart_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Corazón con las manos: un corazón late entre las manos y, al soltar, sube y se apaga."""
    style = runtime.effect.style
    if envelope <= 0 or event is None:
        return
    get = _person_points(points, event)
    torso = torso_pixels(points, height)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    wrists = [get("left_wrist"), get("right_wrist")]
    if frame_index <= event.end_frame and all(w is not None for w in wrists):
        center = (wrists[0] + wrists[1]) / 2 - np.array([0.0, 0.12 * torso])
        runtime.anchor_point = center
        beat = 1.0 + 0.15 * max(np.sin(frame_index * 0.6), 0.0)
        strokes = neon_layers(_heart(center, 0.22 * torso * beat), color, line, envelope)
    else:
        center = runtime.anchor_point if runtime.anchor_point is not None else np.array(event.position or (0.5, 0.5)) * [layer.shape[1], height]
        rise = (frame_index - event.end_frame) / max(runtime.fps * 0.6, 1.0)
        center = center - np.array([0.0, rise * torso])
        strokes = neon_layers(_heart(center, 0.22 * torso * (1.0 + 0.3 * rise)), color, line, envelope * max(1.0 - rise, 0.0))
        for k, dx in enumerate((-0.35, 0.35)):
            strokes += neon_layers(_heart(center + np.array([dx * torso, 0.25 * torso * (k + 1) * (1 - rise)]), 0.07 * torso), color, line * 0.7, envelope * max(1.0 - rise, 0.0))
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_point_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Señalar: un rayo con punta de flecha sale del índice hacia donde apunta y deja un impacto."""
    style = runtime.effect.style
    if envelope <= 0 or event is None or event.kind not in ("left", "right") or track is None:
        return
    width = layer.shape[1]
    person = next((p for p in _people(track) if p.person_id == event.target.split(":")[0]), None)
    tips = fingertips(person, event.kind, width, height) if person is not None else []
    get = _person_points(points, event)
    elbow = get(f"{event.kind}_elbow")
    if not tips or elbow is None:
        return
    tip = max(tips, key=lambda t: float(np.linalg.norm(t - elbow)))
    direction = (tip - elbow) / max(float(np.linalg.norm(tip - elbow)), 1e-6)
    torso = torso_pixels(points, height)
    grow = min((frame_index - event.start_frame) / max(runtime.fps * 0.25, 1.0), 1.0)
    end = tip + direction * 2.5 * torso * grow
    side = np.array([-direction[1], direction[0]])
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    strokes = neon_layers(np.stack([tip, end]), color, line * 1.4, envelope)
    head = [end - direction * 0.15 * torso + side * 0.08 * torso, end, end - direction * 0.15 * torso - side * 0.08 * torso]
    strokes += neon_layers(np.array(head), color, line, envelope)
    if grow >= 1.0:
        rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:point:{event.start_frame}".encode()) & 0xFFFFFFFF)
        strokes += _sparks(end, torso * 0.35, ((frame_index - event.start_frame) % 12) / 12, color, envelope, rng)
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_confetti_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Brazos arriba: confeti que cae y fuegos artificiales que estallan sobre la cabeza."""
    style = runtime.effect.style
    if envelope <= 0 or event is None:
        return
    get = _person_points(points, event)
    nose = get("nose")
    if nose is None:
        return
    torso = torso_pixels(points, height)
    origin = nose - np.array([0.0, 0.7 * torso])
    elapsed = (frame_index - event.start_frame) / runtime.fps
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:confetti:{event.start_frame}".encode()) & 0xFFFFFFFF)
    strokes = []
    for k in range(3):  # tres fuegos escalonados
        burst = elapsed - k * 0.25
        if 0 <= burst <= 0.6:
            center = origin + np.array([(k - 1) * 0.6 * torso, -0.2 * torso * k])
            color = np.asarray(style.colors[k % len(style.colors)], dtype=np.float32)
            strokes += _sparks(center, torso * 0.7, burst / 0.6, color, envelope, rng)
    for k in range(28):  # confeti: papelitos que caen girando
        x = origin[0] + rng.uniform(-1.4, 1.4) * torso
        fall = (elapsed * rng.uniform(0.6, 1.2) + rng.uniform(0, 0.4)) * torso * 1.2
        y = origin[1] - 0.3 * torso + fall
        angle = rng.uniform(0, np.pi) + elapsed * rng.uniform(3, 8)
        piece = np.array([[np.cos(angle), np.sin(angle)], [-np.cos(angle), -np.sin(angle)]]) * 0.03 * torso + [x, y]
        color = np.asarray(style.colors[k % len(style.colors)], dtype=np.float32)
        strokes += neon_layers(piece, color, 2.0, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_sound_waves(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Mano en el oído: ondas de sonido ")))" que salen de la oreja hacia afuera de la cara."""
    style = runtime.effect.style
    if envelope <= 0 or event is None:
        return
    get = _person_points(points, event)
    ears = [e for e in (get("left_ear"), get("right_ear")) if e is not None]
    nose = get("nose")
    if not ears or nose is None:
        return
    target = event_point(event, points, layer.shape[1], height)
    if target is None:
        target = nose
    ear = min(ears, key=lambda e: float(np.linalg.norm(e - target)))
    out = (ear - nose) / max(float(np.linalg.norm(ear - nose)), 1e-6)
    angle = np.arctan2(out[1], out[0])
    torso = torso_pixels(points, height)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    strokes = []
    for k in range(3):
        phase = ((frame_index - event.start_frame) / (runtime.fps * 0.5) + k / 3) % 1.0
        radius = (0.12 + 0.45 * phase) * torso
        arc = np.linspace(angle - 0.6, angle + 0.6, 12)
        wave = ear + np.stack([np.cos(arc), np.sin(arc)], axis=1) * radius
        strokes += neon_layers(wave, color, line, envelope * (1.0 - phase))
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_whirl_fx(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Giro sobre sí mismo: anillos de torbellino que suben girando alrededor del cuerpo."""
    style = runtime.effect.style
    if envelope <= 0:
        return
    get = _person_points(points, event)
    top, feet = get("nose"), [p for p in (get("left_ankle"), get("right_ankle")) if p is not None]
    shoulders = [p for p in (get("left_shoulder"), get("right_shoulder")) if p is not None]
    if top is None or not feet or len(shoulders) < 2:
        return
    bottom = np.mean(feet, axis=0)
    width = float(np.linalg.norm(shoulders[0] - shoulders[1]))
    strokes = []
    for k in range(5):
        u = ((frame_index * 0.04) + k / 5) % 1.0
        center = bottom + (top - bottom) * u
        radius = width * (1.1 - 0.4 * u)
        spin = frame_index * 0.5 + k
        theta = np.linspace(spin, spin + np.pi * 1.3, 18)
        arc = center + np.stack([np.cos(theta) * radius, np.sin(theta) * radius * 0.22], axis=1)
        color = np.asarray(style.colors[k % len(style.colors)], dtype=np.float32)
        strokes += neon_layers(arc, color, 2.0, envelope * (1.0 - 0.5 * u))
    stroke_batch(layer, strokes, style.hdr_gain)
