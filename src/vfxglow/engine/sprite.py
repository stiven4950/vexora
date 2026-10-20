"""sprite_fx: efectos diseñados afuera (After Effects, Blender, EmberGen...) que el motor coloca
donde y cuando la coreografía lo pide.

El efecto es una animación ya renderizada (`style.sprite`):

- una carpeta con una secuencia de PNG con transparencia (0001.png, 0002.png...), o
- un PNG suelto, o
- un video (.mp4, .mov, .webm). Si no trae canal alfa, el negro es transparente (la luz del
  efecto se suma, como en modo screen): sirve para los clips de partículas sobre fondo negro.

Rutas relativas a `configs/sprites/`. El motor:

- lo ancla al punto del evento (impacto, mano, pie) o, sin evento, a `target`;
- lo escala con el cuerpo: `style.size` = alto del sprite en torsos;
- lo reproduce desde que empieza la activación, a `sprite_fps` (o al fps del video); con
  `loop` en `style.shapes` se repite, si no se queda en el último cuadro mientras dure;
- con `orient` lo gira hacia la dirección del evento (un tajo, un lanzamiento) y con `tint` lo
  tiñe del color de la paleta (el capítulo de color).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from vfxglow.engine.anchors import resolve_anchor, torso_pixels

SPRITE_ROOT = Path("configs/sprites")
VIDEO_TYPES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
# Lado mayor con que se guardan en memoria los cuadros (se escalan al dibujar).
MAX_SIDE = 512


def resolve_sprite(name: str) -> Path:
    path = Path(name)
    if not path.is_absolute() and not path.exists():
        path = SPRITE_ROOT / name
    if not path.exists():
        raise FileNotFoundError(f"No existe el sprite {name} (se busca también en {SPRITE_ROOT}/)")
    return path


def _premultiplied(bgra: np.ndarray) -> np.ndarray:
    """BGRA uint8 → RGBA float32 lineal premultiplicado y achicado a MAX_SIDE."""
    scale = MAX_SIDE / max(bgra.shape[:2])
    if scale < 1:
        bgra = cv2.resize(bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    rgba = bgra[..., [2, 1, 0, 3]].astype(np.float32) / 255.0
    rgb = rgba[..., :3]
    rgba[..., :3] = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4) * rgba[..., 3:4]
    return rgba


def _with_alpha(image: np.ndarray) -> np.ndarray:
    """Sin canal alfa, el brillo hace de alfa: el negro desaparece."""
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return image
    alpha = image.max(axis=2)
    # El color se "des-premultiplica" para que al sumarse quede igual que el original.
    color = (image.astype(np.float32) * 255.0 / np.maximum(alpha[..., None], 1)).clip(0, 255).astype(np.uint8)
    return np.dstack([color, alpha])


@lru_cache(maxsize=16)
def load_sprite(name: str) -> tuple[tuple[np.ndarray, ...], float]:
    """Cuadros RGBA premultiplicados y fps propio (0 si es una secuencia o una imagen)."""
    path = resolve_sprite(name)
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in (".png", ".webp", ".tga", ".tif", ".tiff"))
        if not files:
            raise FileNotFoundError(f"La carpeta del sprite {path} no tiene imágenes")
        return tuple(_premultiplied(_with_alpha(cv2.imread(str(f), cv2.IMREAD_UNCHANGED))) for f in files), 0.0
    if path.suffix.lower() in VIDEO_TYPES:
        capture = cv2.VideoCapture(str(path))
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(_premultiplied(_with_alpha(frame)))
        capture.release()
        if not frames:
            raise ValueError(f"No se pudo leer el video del sprite {path}")
        return tuple(frames), fps
    return (_premultiplied(_with_alpha(cv2.imread(str(path), cv2.IMREAD_UNCHANGED))),), 0.0


def draw_sprite(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    if envelope <= 0 or not style.sprite:
        return
    frames, own_fps = load_sprite(style.sprite)
    target = runtime.effect.target
    # El punto del evento solo si el sprite lo pide (event_point); si pide una articulación, va ahí
    # aunque el gesto haya sido en otro lado.
    use_event = event is not None and runtime.anchor_point is not None and target.kind == "event_point"
    anchor = runtime.anchor_point if use_event else resolve_anchor(points, target.kind, target.id, runtime.anchor_point)
    if anchor is None:
        return
    # Cuadro de la animación desde el inicio de la activación.
    rate = style.sprite_fps or own_fps or runtime.fps
    elapsed = max(runtime.active_frames - 1, 0) / max(runtime.fps, 1.0)
    index = int(elapsed * rate)
    index = index % len(frames) if "loop" in style.shapes else min(index, len(frames) - 1)
    sprite = frames[index]
    torso = torso_pixels(points, height)
    scale = style.size * torso / sprite.shape[0]
    angle = -event.direction_deg if event is not None and "orient" in style.shapes else 0.0
    center = (sprite.shape[1] / 2.0, sprite.shape[0] / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, scale)
    matrix[:, 2] += np.asarray(anchor, dtype=np.float64) - np.array(center)
    h, w = layer.shape[:2]
    # Solo la caja que ocupa el sprite: transformar a pantalla completa es lo caro.
    corners = cv2.transform(np.array([[[0, 0], [sprite.shape[1], 0], [0, sprite.shape[0]], [sprite.shape[1], sprite.shape[0]]]], dtype=np.float64), matrix)[0]
    x0, y0 = np.floor(corners.min(axis=0)).astype(int)
    x1, y1 = np.ceil(corners.max(axis=0)).astype(int)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return
    matrix[:, 2] -= (x0, y0)
    placed = cv2.warpAffine(sprite, matrix, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    rgb, alpha = placed[..., :3], placed[..., 3]
    if "tint" in style.shapes:
        color = np.asarray(style.colors[0], dtype=np.float32)
        luma = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        rgb = luma[..., None] * color
    region = layer[y0:y1, x0:x1]
    region[..., :3] += rgb * np.float32(style.hdr_gain * envelope)
    region[..., 3] = 1.0 - (1.0 - region[..., 3]) * (1.0 - alpha * envelope)
