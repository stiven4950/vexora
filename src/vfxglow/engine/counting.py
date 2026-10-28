"""Contar con los dedos (adorno `type: adornment`, `style.shapes: [finger_number]`).

unpair_dance, seg. 15,9-19,5 y 29,2-31,6 (docs/referencias/unpair_dance.md): la persona cuenta con
los dedos y el número aparece en neón sobre la cara (sobre la mascarilla), siguiendo el conteo.

- Entrada: un swoosh pequeño sale de entre las manos y sube a la cara, donde se vuelve el número.
- El número cambia cuando cambia el conteo (`finger_count`, `detail` = "conteo=cuadro:n,..."); en
  cada cambio, unas rayas "≡" de transición y rayitas de vibración junto a las puntas de los dedos.
- Fijado a mano (sin conteo detectado), cuenta solo del 1 al 5.

Los números son trazos a mano alzada en una caja de 1 x 1 (x a la derecha, y hacia abajo).
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.energy_pass import _travel
from vfxglow.geom import catmull_rom

COUNTING = ("finger_number",)
# Alto del número en distancias entre orejas (o en anchos de hombros si no hay orejas).
DIGIT_HEIGHT = 0.55
# Fotogramas de la transición "≡" y de las rayitas de vibración después de cada cambio.
SWAP_FRAMES = 3
SHAKE_FRAMES = 7
# Fotogramas del swoosh de entrada, de las manos a la cara.
INTRO_FRAMES = 7
# Fijado a mano: un número cada tantos fotogramas.
AUTO_STEP = 12


def _oval(cx: float, cy: float, rx: float, ry: float, n: int = 20) -> list[tuple[float, float]]:
    t = np.linspace(0, 2 * np.pi, n)
    return list(zip(cx + rx * np.sin(t), cy - ry * np.cos(t)))


_DIGITS: dict[str, list[list[tuple[float, float]]]] = {
    "0": [_oval(0.5, 0.5, 0.36, 0.5)],
    "1": [[(0.25, 0.25), (0.55, 0.0), (0.55, 1.0)], [(0.3, 1.0), (0.8, 1.0)]],
    "2": [[(0.12, 0.25), (0.3, 0.03), (0.7, 0.03), (0.88, 0.25), (0.8, 0.48), (0.1, 1.0), (0.9, 1.0)]],
    "3": [[(0.12, 0.08), (0.85, 0.05), (0.45, 0.45), (0.82, 0.58), (0.88, 0.8), (0.6, 1.0), (0.12, 0.93)]],
    "4": [[(0.7, 1.0), (0.7, 0.0), (0.05, 0.68), (0.95, 0.68)]],
    "5": [[(0.85, 0.0), (0.22, 0.0), (0.16, 0.45), (0.6, 0.38), (0.9, 0.62), (0.76, 0.94), (0.12, 0.95)]],
    "6": [[(0.8, 0.05), (0.42, 0.1), (0.14, 0.55), (0.2, 0.9), (0.55, 1.0), (0.86, 0.8), (0.8, 0.55), (0.45, 0.45), (0.15, 0.6)]],
    "7": [[(0.1, 0.0), (0.9, 0.0), (0.4, 1.0)]],
    "8": [_oval(0.5, 0.26, 0.28, 0.25), _oval(0.5, 0.73, 0.36, 0.27)],
    "9": [[(0.85, 0.42), (0.5, 0.55), (0.15, 0.35), (0.3, 0.04), (0.7, 0.02), (0.86, 0.3), (0.8, 1.0)]],
}


def _steps(event) -> list[tuple[int, int]]:
    detail = event.detail if event is not None and event.detail else ""
    if not detail.startswith("conteo="):
        return []
    out = []
    for item in detail.removeprefix("conteo=").split(","):
        frame, _, n = item.partition(":")
        if frame.strip().lstrip("-").isdigit() and n.strip().isdigit():
            out.append((int(frame), int(n)))
    return out


def current_count(event, frame_index: int, active_frames: int) -> tuple[int, int]:
    """(número a mostrar, fotogramas desde el último cambio)."""
    steps = _steps(event)
    if not steps:  # fijado a mano: cuenta solo
        return 1 + (active_frames // AUTO_STEP) % 5, active_frames % AUTO_STEP
    shown = [(f, n) for f, n in steps if f <= frame_index] or steps[:1]
    frame, n = shown[-1]
    return n, max(frame_index - frame, 0)


def _number(text: str, center: np.ndarray, height: float, across: np.ndarray, down: np.ndarray) -> list[np.ndarray]:
    width = height * 0.62
    gap = width * 0.25
    total = len(text) * width + (len(text) - 1) * gap
    lines = []
    for k, char in enumerate(text):
        left = -total / 2 + k * (width + gap)
        for stroke in _DIGITS.get(char, []):
            local = np.array(stroke, dtype=np.float64)
            pts = center + np.outer(left + local[:, 0] * width, across) + np.outer((local[:, 1] - 0.5) * height, down)
            lines.append(catmull_rom(pts, 4) if len(pts) > 2 else pts)
    return lines


def _face(body, scale: float) -> tuple[np.ndarray, float] | None:
    nose = body.get("nose")
    if nose is None:
        return None
    ears = body.get("left_ear"), body.get("right_ear")
    size = float(np.linalg.norm(ears[0] - ears[1])) if ears[0] is not None and ears[1] is not None else 0.0
    return nose, max(size, 0.35 * scale)


def _tips(body) -> list[tuple[np.ndarray, np.ndarray]]:
    """(punta, dirección del dedo) de cada dedo visible de las dos manos."""
    out = []
    for side in ("left", "right"):
        for finger, joint in (("thumb", "ip"), ("index", "pip"), ("middle", "pip"), ("ring", "pip"), ("pinky", "pip")):
            tip, base = body.get(f"{side}_{finger}_tip"), body.get(f"{side}_{finger}_{joint}")
            if tip is not None and base is not None and float(np.linalg.norm(tip - base)) > 1e-3:
                out.append((tip, (tip - base) / float(np.linalg.norm(tip - base))))
    return out


def finger_number(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    found = _face(body, scale)
    if found is None:
        return []
    nose, size = found
    _center, across, down = frame
    height = DIGIT_HEIGHT * size
    spot = nose + down * height * 0.15  # sobre la mascarilla, entre la nariz y la boca
    age = runtime.active_frames
    if age < INTRO_FRAMES:  # el swoosh sube de entre las manos a la cara
        hands = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
        if hands:
            start = np.mean(hands, axis=0)
            path = np.linspace(start, spot, 30)
            return _travel(path, (age + 1) / INTRO_FRAMES, scale * 0.6, layer, color, alpha, runtime.kernels)
    n, since = current_count(event, frame_index, age)
    lines: list[np.ndarray] = []
    if since < SWAP_FRAMES and age >= INTRO_FRAMES + SWAP_FRAMES:  # "≡": el número que cambia
        slide = (since + 1) / SWAP_FRAMES
        for k in (-1, 0, 1):
            y = spot + down * k * height * 0.22
            lines.append(np.array([y - across * height * 0.35 * slide, y + across * height * 0.35 * slide]))
    else:
        lines += _number(str(n), spot, height, across, down)
    if since < SHAKE_FRAMES:  # rayitas de vibración junto a las puntas de los dedos
        for tip, along in _tips(body):
            side = np.array([-along[1], along[0]])
            for sign in (1.0, -1.0):
                base = tip + side * sign * 0.05 * scale
                lines.append(np.array([base - along * 0.03 * scale, base + along * 0.03 * scale]))
    return lines
