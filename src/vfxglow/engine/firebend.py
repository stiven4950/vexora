"""Fuego de maestro fuego, estilo anime (adornos `type: adornment`, `style.shapes`).

Leído de glowing/video_18.mp4 (docs/referencias/video_18.md): el fuego sale de lo que hace el
cuerpo y se dibuja plano, en tres capas anidadas (borde naranja, cuerpo amarillo, núcleo casi
blanco) con lenguas definidas, no como un brillo difuso.

- `fire_whip`: látigo de fuego con la forma de la trayectoria reciente de la mano (o del pie).
- `hand_fire`: llamas que suben de las manos.
- `candle`: una sola llama que sale de las manos juntas y se achica de a poco (seg. 6-7,6).
- `floor_fire`: fuego a ras del piso: charco bajo la mano o el pie apoyado, o una raya que crece
  por donde barre (seg. 2, 5,2, 9,2-10,8).
- `fire_ring`: un aro de fuego que gira alrededor de la mano (seg. 8).
- la calavera, el ave, el dragón y la cara que echa fuego están en engine/fire_creatures.py.
- `avatar_mark`: la flecha de Avatar en la frente y los ojos encendidos (seg. 0 y 15).
- `body_blaze`: el cuerpo arde: llamas que trepan por brazos y piernas y alas de fuego (seg. 11,2).
- `fire_wall`: cierre: en el último tramo una pared de fuego sube desde el piso hasta llenar el
  cuadro, con la flecha y los ojos encendidos (seg. 14,4-16). Se usa en `always`: se cronometra
  sola con `runtime.frame_count` (`style.size` = segundos del cierre).
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

FIREBEND = ("fire_whip", "hand_fire", "candle", "floor_fire", "fire_ring", "avatar_mark", "body_blaze", "fire_wall", "fire_light")
MID = np.array([1.0, 0.66, 0.1], np.float32)
# La luz que el fuego echa sobre el escenario: naranja profundo (con más verde, al sumarse sobre el
# cuadro y el bloom, se iba al amarillo).
GLOW = np.array([1.0, 0.22, 0.0], np.float32)
CORE = np.array([1.0, 0.97, 0.78], np.float32)


_WARM: dict[int, np.ndarray] = {}


def warm(layer, center: np.ndarray, radius: float, color: np.ndarray, alpha: float) -> None:
    """Resplandor radial que llega a cero en el borde (el de `splat` corta en ~8% y, grande, se
    veía como un recuadro naranja)."""
    r = int(min(max(radius, 2.0), 1600))
    r = max(8, r // 24 * 24) if r > 32 else r  # radios redondeados: pocos núcleos en memoria
    kernel = _WARM.get(r)
    if kernel is None:
        if len(_WARM) > 48:
            _WARM.clear()
        axis = np.arange(-r, r + 1, dtype=np.float32) / r
        xx, yy = np.meshgrid(axis, axis)
        kernel = np.clip(1.0 - (xx * xx + yy * yy), 0.0, 1.0) ** 2
        _WARM[r] = kernel
    height, width = layer.shape[:2]
    x0, y0 = int(round(center[0])) - r, int(round(center[1])) - r
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = kernel.shape[1] - max(0, x0 + kernel.shape[1] - width), kernel.shape[0] - max(0, y0 + kernel.shape[0] - height)
    if sx0 >= sx1 or sy0 >= sy1:
        return
    dst = layer[y0 + sy0 : y0 + sy1, x0 + sx0 : x0 + sx1]
    weight = kernel[sy0:sy1, sx0:sx1] * np.float32(alpha)
    dst[..., :3] += np.asarray(color, np.float32) * weight[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - weight)


# ----- cómo se pinta el fuego -----
#
# Medido en la referencia (glowing/video_18, seg. 3,5): el cuerpo de la llama es BLANCO casi puro
# (saturación 9/255), con un borde amarillo fino y suave, y alrededor un resplandor que va de
# amarillo a naranja y tiñe todo el cuadro. No hay borde naranja duro.
#
# Cada llama suma su contorno a una máscara nítida del efecto (sin desenfocar: bordes limpios, con
# los cortes dentados de su geometría). Las masas grandes (bola de fuego, pared) suman además a un
# campo suave que se corta con un umbral (se funden como líquido). Al final del efecto, por cuadro
# (flush_fire), la máscara se pinta blanca y se le agrega el borde amarillo y el resplandor.

_FIELDS: dict[int, dict] = {}
# Luces de fuego del cuadro (para fire_light, que tiñe el plano): las del cuadro anterior y las de este.
_LIGHTS: dict = {"frame": -1, "now": [], "prev": []}
WHITE_HOT = np.array([1.0, 0.98, 0.9], np.float32) * 1.35  # apenas sobre 1: con más, el bloom engorda la forma
RIM = np.array([1.0, 0.78, 0.2], np.float32) * 1.6
NEAR_GLOW = np.array([1.0, 0.48, 0.04], np.float32)
FAR_GLOW = np.array([1.0, 0.26, 0.0], np.float32)


def note_frame(frame_index: int) -> None:
    """El primer efecto de fuego de cada cuadro rota la lista de luces."""
    if frame_index != _LIGHTS["frame"]:
        if frame_index < _LIGHTS["frame"]:  # otro video o se volvió atrás
            _LIGHTS["now"] = []
        _LIGHTS["prev"], _LIGHTS["now"], _LIGHTS["frame"] = _LIGHTS["now"], [], frame_index


def cel(layer, make, color, alpha: float, runtime=None, heat: float = 1.0, core: bool = True, mass: bool = False) -> None:
    """Suma una llama al fuego del efecto (make(1.0) da su contorno). `mass`: masa grande que se
    funde con las vecinas como líquido (bola de fuego, pared). Con `runtime`, además un resplandor
    tenue alrededor y la llama cuenta como luz para fire_light. (`core` queda por compatibilidad:
    el cuerpo ya es blanco entero.)"""
    if alpha <= 0:
        return
    height, width = layer.shape[:2]
    entry = _FIELDS.get(id(layer))
    if entry is None:
        entry = _FIELDS[id(layer)] = {"mask": np.zeros((height, width), np.float32), "field": None, "alpha": 0.0}
    entry["alpha"] = max(entry["alpha"], float(alpha))
    poly = make(1.0)
    if poly is None or len(poly) < 3:
        return
    pts = [np.round(poly).astype(np.int32)]
    if mass:
        if entry["field"] is None:
            entry["field"] = np.zeros((height, width), np.float32)
        blob = np.zeros((height, width), np.uint8)
        cv2.fillPoly(blob, pts, 255, lineType=cv2.LINE_AA)
        entry["field"] += blob.astype(np.float32) * np.float32(min(alpha, 1.0) / 255.0)
    else:
        shape = np.zeros((height, width), np.uint8)
        cv2.fillPoly(shape, pts, 255, lineType=cv2.LINE_AA)
        # Lo que se apaga se adelgaza (no se vuelve transparente): solo cuenta lo que pasa el umbral.
        np.maximum(entry["mask"], np.clip((shape.astype(np.float32) / 255.0) * (0.4 + 0.6 * min(alpha, 1.0)), 0, 1), out=entry["mask"])
    if runtime is not None and heat > 0:
        lo, hi = poly.min(axis=0), poly.max(axis=0)
        size = float(np.linalg.norm(hi - lo))
        mid = (lo + hi) / 2
        warm(layer, mid, max(size * 2.4, 0.45 * height), GLOW * 0.55, alpha * 0.07 * heat)  # ancha pero transparente
        _LIGHTS["now"].append((mid, size, float(alpha) * heat))


_NOISE: dict = {}


def _noise(height: int, width: int, frame_index: int, seed: int) -> np.ndarray:
    """Ruido suave en [-1, 1] del tamaño del cuadro que sube con el tiempo (el fuego asciende)."""
    key = (height, width, seed)
    tex = _NOISE.get(key)
    if tex is None:
        rng = np.random.default_rng(seed)
        tall = height * 2
        tex = np.zeros((tall, width), np.float32)
        for cell, weight in ((max(height // 14, 8), 0.65), (max(height // 40, 4), 0.35)):  # dos octavas
            small = rng.uniform(-1, 1, (tall // cell + 2, width // cell + 2)).astype(np.float32)
            tex += cv2.resize(small, (width, tall), interpolation=cv2.INTER_CUBIC) * weight
        _NOISE[key] = tex
    shift = int(frame_index * height * 0.012) % height  # sube ~1,2% del cuadro por fotograma
    return tex[height - shift : 2 * height - shift]


# ----- brasas: partículas que suelta el fuego -----
#
# Nacen en el borde de la llama (muchas más cuando muere y se deshace), salen hacia afuera y
# arriba con turbulencia y frenado, y su color depende de la edad: blanco-amarillo al nacer,
# naranja a media vida, rojo al apagarse, mientras se achican. Se dibujan como rayitas
# orientadas por su velocidad (no puntos redondos).

EMBER_LIFE = (10, 22)  # cuadros de vida (mínimo, máximo)
EMBER_MAX = 260
_EMBER_RAMP = np.array([
    [1.0, 0.88, 0.45],   # nace amarilla
    [1.0, 0.6, 0.1],
    [1.0, 0.4, 0.04],    # media vida: naranja
    [0.8, 0.15, 0.02],   # se apaga rojiza
], np.float32)


def _ember_color(age: np.ndarray) -> np.ndarray:
    x = np.clip(age, 0.0, 1.0) * (len(_EMBER_RAMP) - 1)
    i = np.minimum(np.floor(x).astype(int), len(_EMBER_RAMP) - 2)
    f = (x - i)[:, None]
    return _EMBER_RAMP[i] * (1 - f) + _EMBER_RAMP[i + 1] * f


def emit_embers(pool: dict, mask: np.ndarray, box: tuple[int, int], frame_index: int, rate: float, height: int) -> None:
    """Siembra brasas en el borde de `mask` (recorte con esquina `box` = (x0, y0))."""
    if rate <= 0:
        return
    edge = cv2.morphologyEx((mask > 0.5).astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(edge)
    if len(xs) == 0:
        return
    rng = np.random.default_rng(frame_index * 7919 + len(xs))
    count = int(min(rng.poisson(rate), 40))
    if count == 0:
        return
    pick = rng.integers(0, len(xs), count)
    x0, y0 = box
    pos = np.stack([xs[pick] + x0, ys[pick] + y0], axis=1).astype(np.float32)
    center = np.array([xs.mean() + x0, ys.mean() + y0], np.float32)
    out = pos - center
    out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-3)
    speed = rng.uniform(0.004, 0.012, count)[:, None] * height
    vel = out * speed + np.array([0.0, -0.006 * height], np.float32)  # afuera y arriba
    new = {
        "pos": pos,
        "vel": vel.astype(np.float32),
        "born": np.full(count, frame_index, np.float32),
        "life": rng.integers(EMBER_LIFE[0], EMBER_LIFE[1], count).astype(np.float32),
        "size": rng.uniform(0.004, 0.009, count).astype(np.float32) * height,
    }
    if "pos" not in pool:
        pool.update(new)
    else:
        for k in new:
            pool[k] = np.concatenate([pool[k], new[k]])[-EMBER_MAX:]


def draw_embers(layer, pool: dict, frame_index: int, alpha: float) -> None:
    """Mueve las brasas un cuadro y las dibuja como rayitas que cambian de color con la edad."""
    if "pos" not in pool or len(pool["pos"]) == 0:
        return
    if pool.get("frame") is not None and frame_index < pool["frame"]:  # volvió atrás: se olvida
        pool.clear()
        return
    if pool.get("frame") != frame_index:  # se mueven una vez por cuadro
        pool["frame"] = frame_index
        age = (frame_index - pool["born"]) / pool["life"]
        alive = age < 1.0
        for k in ("pos", "vel", "born", "life", "size"):
            pool[k] = pool[k][alive]
        if len(pool["pos"]) == 0:
            return
        pos, vel = pool["pos"], pool["vel"]
        height = layer.shape[0]
        # Turbulencia: ruido coherente según la posición y el tiempo (se curvan, no tiemblan).
        wobble = np.stack([
            _smooth_noise(pos[:, 1] / (0.05 * height) + frame_index * 0.15, 1.0),
            _smooth_noise(pos[:, 0] / (0.05 * height) - frame_index * 0.15, 2.0) * 0.5,
        ], axis=1).astype(np.float32)
        pool["vel"] = vel * 0.9 + wobble * (0.0025 * height) + np.array([0.0, -0.0012 * height], np.float32)
        pool["pos"] = pos + pool["vel"]
    pos, vel = pool["pos"], pool["vel"]
    age = (frame_index - pool["born"]) / pool["life"]
    colors = _ember_color(age)
    shrink = np.clip(1.0 - age, 0.0, 1.0) ** 0.6
    height, width = layer.shape[:2]
    lo = np.floor(pos.min(axis=0) - 12).astype(int)
    hi = np.ceil(pos.max(axis=0) + 12).astype(int)
    x0, y0 = max(lo[0], 0), max(lo[1], 0)
    x1, y1 = min(hi[0], width), min(hi[1], height)
    if x0 >= x1 or y0 >= y1:
        return
    canvas = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
    cover = np.zeros((y1 - y0, x1 - x0), np.float32)
    for p, v, c, s, a in zip(pos, vel, colors, pool["size"], shrink):
        tail = p - v * 1.6  # rayita orientada por la velocidad
        p0 = (int(round(tail[0] - x0)), int(round(tail[1] - y0)))
        p1 = (int(round(p[0] - x0)), int(round(p[1] - y0)))
        thick = max(int(round(s * a)), 1)
        bright = float(a) * 1.25
        cv2.line(canvas, p0, p1, (float(c[0]) * bright, float(c[1]) * bright, float(c[2]) * bright), thick, cv2.LINE_AA)
        cv2.line(cover, p0, p1, float(a), thick, cv2.LINE_AA)
    a = np.float32(min(alpha, 1.0))
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += canvas * a
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - np.clip(cover, 0, 1) * a)


def flush_fire(layer, frame_index: int, u: float | None = None, st: dict | None = None, embers: dict | None = None) -> None:
    """Pinta el fuego acumulado del efecto: cuerpo blanco, borde amarillo y resplandor de color.
    Con `u` (vida del efecto), lo que no trae vida propia muere igual que las cintas: se vacía
    desde el centro en trozos, con la opacidad que tuvo (no se vuelve transparente)."""
    entry = _FIELDS.pop(id(layer), None)
    if entry is None:
        return
    if st is not None and u is not None and not entry.get("alive"):
        st["peak"] = max(st.get("peak", 0.0), entry["alpha"])
        if u >= DIE_START:
            entry["alpha"] = st["peak"]
    mask = entry["mask"]
    height, width = mask.shape
    if entry["field"] is not None:  # las masas: campo suave cortado con un umbral, con el borde comido
        field = cv2.GaussianBlur(entry["field"], (0, 0), max(0.008 * height, 1.0))
        field = field - _noise(height, width, frame_index, 23) * 0.18
        x = np.clip((field - 0.45) / 0.12, 0.0, 1.0)
        np.maximum(mask, x * x * (3 - 2 * x), out=mask)
    ys, xs = np.nonzero(mask > 0.02)
    if len(xs) == 0:
        if embers is not None:  # sin fuego, las brasas que quedan siguen su vida
            draw_embers(layer, embers, frame_index, 1.0)
        return
    pad = int(0.14 * height)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, width)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, height)
    m = mask[y0:y1, x0:x1]
    if st is not None and u is not None and not entry.get("alive") and u > DIE_START:
        die = float(np.clip((u - DIE_START) / (1.0 - DIE_START), 0.0, 1.0))
        m = erode(m, (m > 0.5).astype(np.uint8), die, int(st.setdefault("seed", frame_index % 97)), (x0, y0, x1, y1), (height, width))
    # Borde amarillo corto y bien difuminado (seg. 3,17): una caída suave justo afuera del blanco.
    rim_blur = cv2.GaussianBlur(m, (0, 0), max(0.005 * height, 1.0))
    band = np.clip(rim_blur * (1.0 - m) * 1.6, 0.0, 1.0) * 0.64  # 15% y luego 25% más suave que al principio
    near = cv2.GaussianBlur(m, (0, 0), max(0.014 * height, 1.0)) * (1.0 - m)
    small = cv2.resize(m, (max((x1 - x0) // 4, 1), max((y1 - y0) // 4, 1)), interpolation=cv2.INTER_AREA)
    far = cv2.resize(cv2.GaussianBlur(small, (0, 0), max(0.045 * height / 4, 1.0)), (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
    a = np.float32(min(entry["alpha"], 1.0))
    rgb = WHITE_HOT * m[..., None] + RIM * band[..., None] + NEAR_GLOW * (near * 0.375)[..., None] + FAR_GLOW * (far * 0.3)[..., None]
    cover = np.clip(m + band + near * 0.3 + far * 0.2, 0.0, 1.0)
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += rgb * a
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - cover * a)
    if embers is not None:
        # Pocas: una brasa cada ~14.000 px de fuego por cuadro; al morir, tres veces más (se deshace).
        dying = u is not None and u > DIE_START
        rate = min(float(m.sum()) / 14000.0 * (3.0 if dying else 1.0), 6.0)
        emit_embers(embers, m, (x0, y0), frame_index, rate, height)
        draw_embers(layer, embers, frame_index, 1.0)


def erode(shape: np.ndarray, binary: np.ndarray, die: float, seed: int, box: tuple[int, int, int, int], size: tuple[int, int]) -> np.ndarray:
    """La muerte de una llama: se vacía desde el centro y el borde que queda se parte en tramos.
    `shape` es la máscara (0-1) del recuadro `box` (x0, y0, x1, y1) de un cuadro de `size` (alto, ancho)."""
    if die <= 0:
        return shape
    x0, y0, x1, y1 = box
    height, width = size
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 5)
    local = cv2.dilate(dist, np.ones((25, 25), np.uint8))
    center = dist / np.maximum(local, 1.0)  # 1 en el centro de cada parte, 0 en su borde
    coarse = _noise(height, width, 0, 31 + seed)[y0:y1, x0:x1]
    fine = _fine_noise(height, width, 57 + seed)[y0:y1, x0:x1]
    field = center + 0.35 * coarse + 0.55 * fine  # el ruido fino parte el borde en tramos
    limit = 1.3 - 1.9 * die  # sube el umbral: primero cae el centro, al final el borde
    return shape * np.clip((limit - field) / 0.08, 0.0, 1.0)


def _fine_noise(height: int, width: int, seed: int) -> np.ndarray:
    """Ruido fijo de grano mediano en [-1, 1] (celdas de ~1,5% del alto): corta los bordes en tramos."""
    key = ("fine", height, width, seed)
    tex = _NOISE.get(key)
    if tex is None:
        rng = np.random.default_rng(seed)
        cell = max(height // 65, 4)
        small = rng.uniform(-1, 1, (height // cell + 2, width // cell + 2)).astype(np.float32)
        tex = cv2.resize(small, (width, height), interpolation=cv2.INTER_CUBIC)
        _NOISE[key] = tex
    return tex


def _smooth_noise(x: np.ndarray, seed: float) -> np.ndarray:
    """Ruido 1D suave y coherente en [-1, 1] (valores al azar en una grilla, interpolados con
    curva suave): reemplaza al seno, cuyo patrón el ojo detecta."""
    i = np.floor(x).astype(np.int64)
    f = x - i
    f = f * f * (3 - 2 * f)

    def value(k):
        return np.sin(k * 127.1 + seed * 311.7) * 43758.5453 % 1.0 * 2 - 1

    return value(i) * (1 - f) + value(i + 1) * f


def _normals(spine: np.ndarray) -> np.ndarray:
    tangent = np.gradient(spine, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    return normal / np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)


def ribbon(spine: np.ndarray, widths: np.ndarray, frame_index: int, tongues: float = 4.0, phase: float = 0.0):
    """make(k) de una cinta de fuego por `spine` (de la cola a la cabeza), con lenguas que
    corren por el borde exterior."""
    if len(spine) < 3:
        return lambda k: None
    normal = _normals(spine)
    t = np.linspace(0, 1, len(spine))
    drift = frame_index * 0.12  # el ruido corre por la cinta con el tiempo, sin parpadear
    flick = 1.0 + 0.75 * np.maximum(0.0, _smooth_noise(t * tongues * 1.6 - drift, phase + 1.0)) ** 2
    calm = 1.0 + 0.2 * _smooth_noise(t * tongues * 1.1 - drift, phase + 2.0)
    # Cortes dentados: muescas en V, afiladas, en lugares fijos de la cinta (viajan con ella).
    teeth = len(spine) / 2.5

    def notch(seed):
        f = (t * teeth + seed) % 1.0
        return 1.0 - 0.38 * np.clip(1.0 - f / 0.14, 0.0, 1.0) * (np.sin((np.floor(t * teeth + seed)) * 12.9898 + seed) > 0.1)

    up_notch, low_notch = notch(phase * 0.37 + 0.2), notch(phase * 0.73 + 0.6)

    def make(k: float):
        w = widths * k
        upper = spine + normal * (w * flick * up_notch)[:, None]
        lower = spine - normal * (w * (0.7 + 0.3 * calm) * low_notch)[:, None]
        return np.vstack([upper, lower[::-1]])

    return make


ROUND_BASE = 0.3  # fracción del largo que ocupa la base redonda


def flame_profile(s: np.ndarray, width: float, seed: float = 0.0, frame_index: int = 0) -> np.ndarray:
    """Ancho (medio) de una llama a lo largo de s (0 la base, 1 la punta), como en las llamas
    animadas de referencia (SVG "flame animation"): la base es media circunferencia ancha y
    redonda, y desde ahí el cuerpo se angosta hasta la punta con bultos suaves que se mueven."""
    b = ROUND_BASE
    bottom = np.sqrt(np.clip(1.0 - ((b - s) / b) ** 2, 0.0, 1.0))
    body = np.clip((1.0 - s) / (1.0 - b), 0.0, 1.0) ** 1.1
    bumps = 1.0 + 0.16 * _smooth_noise(s * 5.0 - frame_index * 0.1, seed + 4.0)
    return width * np.where(s < b, bottom, body * bumps) + 0.5


def teardrop(base: np.ndarray, up: np.ndarray, length: float, width: float, frame_index: int, seed: float = 0.0, curl: float = 0.0):
    """make(k) de una llama que sube desde `base` en la dirección `up` y se mece. `curl` (en
    vueltas, con signo para el lado) enrosca la punta en un gancho, como las llamas de anime."""
    side = np.array([-up[1], up[0]])
    s = np.linspace(0, 1, 26 if curl else 18)
    sway = _smooth_noise(s * 2.5 - frame_index * 0.08, seed) * 0.2 * length * s  # se mece sin patrón
    if curl:
        # El rumbo gira cada vez más hacia la punta: la llama sube y se enrosca sobre sí misma.
        angle = curl * TAU * np.clip((s - 0.45) / 0.55, 0.0, 1.0) ** 1.6
        step = np.stack([np.cos(angle), np.sin(angle)], axis=1)  # (adelante, de lado)
        ds = np.gradient(s) * length
        local = np.cumsum(step * ds[:, None], axis=0)
        spine = base + np.outer(local[:, 0], up) + np.outer(local[:, 1] + sway * 0.5, side)
        return ribbon(spine, flame_profile(s, width, seed, frame_index), frame_index, 2.0, seed)
    spine = base + np.outer(s * length, up) + np.outer(sway, side)
    return ribbon(spine, flame_profile(s, width, seed, frame_index), frame_index, 2.0, seed)


def flame_parts(base: np.ndarray, up: np.ndarray, tall: float, width: float, frame_index: int, seed: float = 0.0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Una llama completa como piezas (línea central, anchos): el cuerpo de base redonda, una o
    dos lenguas laterales que salen de su mitad hacia afuera y arriba, y un trocito suelto sobre la
    punta. Se dibujan juntas y nacen/mueren juntas (living_ribbon)."""
    side = np.array([-up[1], up[0]])
    s = np.linspace(0, 1, 28)
    sway = _smooth_noise(s * 2.5 - frame_index * 0.09, seed) * 0.22 * tall * s ** 1.3
    spine = base + np.outer(s * tall, up) + np.outer(sway, side)
    parts = [(spine, flame_profile(s, width, seed, frame_index))]
    rng = np.random.default_rng(int(abs(seed) * 1000) % 2**31)
    for k, at in enumerate((0.45, 0.62)[: 1 + int(rng.random() < 0.7)]):
        sign = rng.choice([-1.0, 1.0]) if k == 0 else -parts_sign
        parts_sign = sign
        root = spine[int(at * 27)] + side * sign * flame_profile(np.array([at]), width, seed, frame_index)[0] * 0.7
        d = up + side * sign * 0.75
        d /= float(np.linalg.norm(d))
        q = np.linspace(0, 1, 12)
        wob = _smooth_noise(q * 2.0 - frame_index * 0.12, seed + 7 + k) * 0.15 * tall * q
        t_len = tall * rng.uniform(0.28, 0.4)
        tongue = root + np.outer(q * t_len, d) + np.outer(wob, np.array([-d[1], d[0]]))
        parts.append((tongue, width * 0.32 * np.sin(np.pi * np.clip(q * 0.95 + 0.05, 0, 1)) ** 0.6 * (1 - q) ** 0.5 + 0.4))
    tip = spine[-1] + up * tall * 0.12 + side * _smooth_noise(np.array([frame_index * 0.1]), seed + 9)[0] * 0.08 * tall
    q = np.linspace(0, 1, 10)
    wisp = tip + np.outer(q * tall * 0.18, up)
    parts.append((wisp, width * 0.18 * np.sin(np.pi * q) + 0.3))
    return parts


# ----- la vida de una llama: nacer, sostenerse y morir (docs/referencias/video_18_fuego.md) -----
#
# Medido en la referencia: nace en 2-3 cuadros (la punta adelante, el cuerpo detrás), se sostiene
# 3-6 y muere en 3-5 sin volverse transparente: se vacía por dentro, el centro desaparece primero y
# quedan tramos finos del borde que se afinan y se apagan.

GROW_END = 0.2   # fracción de la vida en que termina de nacer
DIE_START = 0.6  # desde aquí se congela y se erosiona


def _ease_out(x: float) -> float:
    x = float(np.clip(x, 0.0, 1.0))
    return 1.0 - (1.0 - x) ** 3


def living_ribbon(layer, spine: np.ndarray, widths: np.ndarray, u: float, st: dict, frame_index: int, color, alpha: float, runtime=None, grow_from_end: bool = True, tongues: float = 3.0, phase: float = 0.0) -> None:
    """Dibuja una cinta de fuego según su momento de vida `u` (0 al nacer, 1 al apagarse).

    `spine` va de la cola a la cabeza. Con `grow_from_end`, nace en la cabeza (la mano) y la punta
    avanza hacia la cola; si no, nace en la cola. Al empezar a morir, la forma se congela en `st`."""
    if len(spine) < 3 or alpha <= 0:
        return
    # Al morir no se vuelve transparente: se erosiona con la opacidad que tuvo (el fundido de
    # salida del motor no cuenta).
    st["peak"] = max(st.get("peak", 0.0), float(alpha))
    if u >= DIE_START:
        alpha = st["peak"]
    if u >= DIE_START and "frozen" in st:
        spine, widths = st["frozen"]
    elif u >= DIE_START:
        st["frozen"] = (spine.copy(), widths.copy())
    grow = _ease_out(u / GROW_END)
    n = len(spine)
    keep = max(int(np.ceil(n * max(grow, 0.08))), 3)
    if grow_from_end:
        part, part_w = spine[n - keep :], widths[n - keep :]
        # El cuerpo crece detrás de la punta que avanza: la punta (el inicio del tramo) es fina.
        taper_in = np.clip(np.linspace(0.0, 1.0, keep) * 3.0, 0.15, 1.0) if grow < 1 else 1.0
    else:
        part, part_w = spine[:keep], widths[:keep]
        taper_in = np.clip(np.linspace(1.0, 0.0, keep) * 3.0, 0.15, 1.0) if grow < 1 else 1.0
    part_w = part_w * (0.55 + 0.45 * grow) * taper_in
    poly = ribbon(part, part_w, frame_index, tongues, phase)(1.0)
    if poly is None or len(poly) < 3:
        return
    height, width = layer.shape[:2]
    pad = 4
    lo = np.floor(poly.min(axis=0)).astype(int) - pad
    hi = np.ceil(poly.max(axis=0)).astype(int) + pad
    x0, y0 = max(lo[0], 0), max(lo[1], 0)
    x1, y1 = min(hi[0], width), min(hi[1], height)
    if x0 >= x1 or y0 >= y1:
        return
    mask = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(mask, [np.round(poly - [x0, y0]).astype(np.int32)], 255, lineType=cv2.LINE_AA)
    shape = mask.astype(np.float32) / 255.0
    die = float(np.clip((u - DIE_START) / (1.0 - DIE_START), 0.0, 1.0))
    if die > 0:
        shape = erode(shape, mask, die, int(st.setdefault("seed", frame_index % 97)), (x0, y0, x1, y1), (height, width))
    entry = _FIELDS.get(id(layer))
    if entry is None:
        entry = _FIELDS[id(layer)] = {"mask": np.zeros((height, width), np.float32), "field": None, "alpha": 0.0}
    entry["alpha"] = max(entry["alpha"], float(alpha))
    entry["alive"] = True  # ya trae su propia vida: flush_fire no lo vuelve a erosionar
    np.maximum(entry["mask"][y0:y1, x0:x1], shape, out=entry["mask"][y0:y1, x0:x1])
    if runtime is not None and die < 0.8:
        size = float(np.linalg.norm(hi - lo))
        mid = (lo + hi) / 2
        fade = 1.0 - die
        warm(layer, mid, max(size * 2.4, 0.45 * height), GLOW * 0.55, alpha * 0.07 * fade)
        _LIGHTS["now"].append((mid, size, float(alpha) * fade))


# ----- lo que tienen todos los fuegos: escamas, tramos cortados y el borde del cuerpo iluminado -----


def pieces(spine: np.ndarray, widths: np.ndarray, seed: int, gap: float = 0.05) -> list[tuple[np.ndarray, np.ndarray]]:
    """La cinta partida en 2-3 tramos con huecos (el fuego de la referencia se corta), cada uno
    con su propio grosor que se afina en las puntas del corte."""
    rng = np.random.default_rng(seed)
    cuts = sorted(rng.uniform(0.25, 0.75, size=int(rng.integers(1, 3))))
    n = len(spine)
    out, start = [], 0
    for c in [*cuts, 1.0 + gap]:
        end = min(int((c - gap / 2) * n), n)
        if end - start >= 3:
            seg_w = widths[start:end] * np.sin(np.linspace(0.15, np.pi - 0.15, end - start)) ** 0.25
            out.append((spine[start:end], seg_w))
        start = int((c + gap / 2) * n)
    return out


def shed(layer, spine: np.ndarray, widths: np.ndarray, st: dict, frame_index: int, scale: float, color, alpha: float, rate: float = 1.0) -> None:
    """Escamas de fuego que se desprenden del borde de la llama: medialunas que salen, giran y
    se apagan en ~10 cuadros."""
    flakes = st.setdefault("flakes", [])
    rng = np.random.default_rng(frame_index * 31 + len(flakes))
    if len(spine) >= 3 and rng.random() < 0.8 * rate:
        normal = _normals(spine)
        for _ in range(1 + int(rng.random() < 0.5 * rate)):
            i = int(rng.integers(len(spine) // 3, len(spine)))
            side = rng.choice([-1.0, 1.0])
            pos = spine[i] + normal[i] * widths[i] * side
            vel = normal[i] * side * rng.uniform(0.02, 0.05) * scale + np.array([0.0, -0.015 * scale])
            flakes.append([pos.copy(), vel, frame_index, rng.uniform(0.04, 0.08) * scale, rng.uniform(0, TAU)])
    keep = []
    for flake in flakes:
        pos, vel, born, size, spin = flake
        age = frame_index - born
        if age > 10:
            continue
        keep.append(flake)
        at = pos + vel * age
        fade = 1.0 - age / 10.0
        a = spin + age * 0.4
        arc = np.linspace(a, a + 2.4, 10)  # una medialuna: dos arcos de distinto radio
        outer = at + np.stack([np.cos(arc), np.sin(arc)], axis=1) * size * fade
        inner = at + np.stack([np.cos(arc[::-1]), np.sin(arc[::-1])], axis=1) * size * fade * 0.6 + np.array([np.cos(a + 1.2), np.sin(a + 1.2)]) * size * 0.25
        crescent = np.vstack([outer, inner])
        fill_polygon(layer, crescent, MID, alpha * fade, 1.4, feather=0.8)
    st["flakes"] = keep


def rim(layer, runtime, sources: list[np.ndarray], scale: float, color, alpha: float, reach: float = 1.3) -> None:
    """El borde del cuerpo cercano al fuego, iluminado con una línea muy fina que se apaga con la
    distancia (sobre la silueta real del segmentador)."""
    outlines = getattr(runtime, "silhouettes", None) or []
    if not outlines or not sources:
        return
    src = np.array(sources, dtype=np.float64)
    radius = reach * scale
    height, width = layer.shape[:2]
    glow = np.zeros((height, width), np.float32)
    for outline in outlines:
        d = np.min(np.linalg.norm(outline[:, None, :] - src[None, :, :], axis=2), axis=1)
        weight = np.clip(1.0 - d / radius, 0.0, 1.0) ** 1.5
        pts = np.round(outline).astype(np.int32)
        for i in range(len(pts)):
            w = (weight[i] + weight[(i + 1) % len(pts)]) / 2
            if w > 0.05:
                cv2.line(glow, tuple(pts[i]), tuple(pts[(i + 1) % len(pts)]), float(w), 1, cv2.LINE_AA)
    if glow.max() <= 0:
        return
    glow *= np.float32(alpha)
    tint = np.asarray(color, np.float32) * 0.5 + MID * 0.5
    layer[..., :3] += tint * 1.6 * glow[..., None]
    layer[..., 3] = 1.0 - (1.0 - layer[..., 3]) * (1.0 - glow)


def _floor(body, scale: float) -> float | None:
    feet = [p for p in (body.get(j) for j in ("left_ankle", "right_ankle", "left_heel", "right_heel", "left_foot_index", "right_foot_index")) if p is not None]
    return max(p[1] for p in feet) + 0.02 * scale if feet else None


def _wrist(body, event, scale) -> tuple[str, np.ndarray] | None:
    """La extremidad del evento (muñeca o tobillo) o, sin ella, la mano más rápida."""
    if event is not None:
        joint = event.target.split(":")[-1]
        if not joint.endswith(("_wrist", "_ankle")) and event.kind in ("left", "right"):
            joint = f"{event.kind}_wrist"
        if joint.endswith(("_wrist", "_ankle")) and body.get(joint) is not None:
            return joint, body.get(joint)
    best, speed = None, -1.0
    for name in ("left_wrist", "right_wrist"):
        point = body.get(name)
        if point is None:
            continue
        vel = body.points.get(f"vel:{body.prefix}{name}")
        v = float(np.linalg.norm(vel)) if vel is not None else 0.0
        if v > speed:
            best, speed = (name, point), v
    return best


# ----- látigo, llamas en las manos, vela -----


TWO_HANDED = ("arms_open", "arms_up", "jump", "landing", "spin_body")
WHIP_SCALE = 2.6


def _fire_whip(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    if event is not None and (event.kind == "both" or event.name in TWO_HANDED):
        limbs = [(n, body.get(n)) for n in ("left_wrist", "right_wrist") if body.get(n) is not None]
    else:
        found = _wrist(body, event, scale)
        limbs = [found] if found is not None else []
    for name, point in limbs:
        st = _activation(runtime, event, f"whip:{name}", body)
        trail = st.setdefault("trail", [])
        trail.append(point.copy())
        del trail[:-16]
        u = _phase(runtime, event)
        if u >= DIE_START and "frozen" in st:  # muriendo: se deshace donde quedó
            living_ribbon(layer, st["frozen"][0], st["frozen"][1], u, st, frame_index, color, alpha, runtime)
            continue
        if len(trail) < 3:
            continue
        spine = np.array(trail)
        if float(np.linalg.norm(spine[-1] - spine[0])) < 0.25 * scale:  # casi quieta: sin látigo
            continue
        # Exagerado como en la referencia: el látigo dobla el recorrido real (desde la mano hacia
        # atrás) y la llama se adelanta a la mano, como si la lanzara.
        spine = spine[-1] + (spine - spine[-1]) * WHIP_SCALE * (1.4 if len(limbs) == 2 else 1.0)
        ahead = spine[-1] - spine[-3]
        spine = np.vstack([spine, spine[-1] + ahead * 0.8])
        # Medialuna como en la referencia: se arquea hacia el lado en que gira el golpe (aunque el
        # recorrido real sea casi recto), y se remuestrea a una curva suave de 40 puntos.
        chord = spine[-1] - spine[0]
        length = float(np.linalg.norm(chord))
        side = np.array([-chord[1], chord[0]]) / max(length, 1e-6)
        turn = st.setdefault("turn", float(np.sign(np.dot(spine[len(spine) // 2] - (spine[0] + spine[-1]) / 2, side)) or 1.0))  # fijo por golpe
        q0 = np.linspace(0, 1, len(spine))
        spine = spine + np.outer(np.sin(np.pi * q0) * 0.38 * length * turn, side)
        for _ in range(3):  # suavizado 1-2-1 que conserva los extremos
            spine[1:-1] = spine[:-2] * 0.25 + spine[1:-1] * 0.5 + spine[2:] * 0.25
        q = np.linspace(0, 1, 40)
        steps = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(spine, axis=0), axis=1))])
        steps /= max(steps[-1], 1e-6)
        smooth = np.stack([np.interp(q, steps, spine[:, 0]), np.interp(q, steps, spine[:, 1])], axis=1)
        # Fina y en punta en la cola, ancha cerca de la mano y otra vez afilada en la cabeza.
        big = 1.5 if len(limbs) == 2 else 1.0  # con las dos manos, medialunas grandes (seg. 0,8)
        widths = (0.006 + 0.24 * big * np.sin(np.pi * q) ** 0.9 * q ** 0.9) * scale
        living_ribbon(layer, smooth, widths, u, st, frame_index, color, alpha, runtime)
        if u < DIE_START:
            shed(layer, smooth, widths, st, frame_index, scale, color, alpha)
        rim(layer, runtime, [point, smooth[len(smooth) // 2]], scale, color, alpha)
        splat(layer, float(point[0]), float(point[1]), 0.12 * scale, CORE * 1.4, alpha * 0.6, runtime.kernels)
    return []


def _hand_fire(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = -down
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2))
    sides = [event.kind] if event is not None and event.kind in ("left", "right") else ["left", "right"]
    for k, side in enumerate(sides):
        wrist = body.get(f"{side}_wrist")
        if wrist is None:
            continue
        st = _activation(runtime, event, f"hand:{side}", body)
        u = _phase(runtime, event)
        flame = teardrop(wrist, up, 0.85 * scale, 0.2 * scale, frame_index, k * 1.7)
        # Base ancha y redonda en la mano, cuerpo que se angosta, lenguas laterales y un trocito
        # suelto arriba (proporción ~2:1, no una aguja).
        tall, half = 1.45 * scale, 0.2 * scale
        base = wrist - up * half * 0.6  # la base redonda envuelve el puño
        for j, (spine, widths) in enumerate(flame_parts(base, up, tall, half, frame_index, k * 1.7 + 0.3)):
            living_ribbon(layer, spine, widths, u, st.setdefault(f"part{j}", {}), frame_index, color, alpha, runtime if j == 0 else None, grow_from_end=False, tongues=3.0, phase=k * 1.7 + j)
        del flame
        flame_spine = np.array([wrist + up * 0.85 * scale * grow * s for s in np.linspace(0, 1, 8)])
        shed(layer, flame_spine, np.full(8, 0.12 * scale), st, frame_index, scale, color, alpha, 0.6)
        rim(layer, runtime, [wrist], scale, color, alpha, 1.0)
    return []


def _candle(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = -down
    wrists = [body.get("left_wrist"), body.get("right_wrist")]
    if any(w is None for w in wrists):
        return []
    base = (wrists[0] + wrists[1]) / 2
    u = _phase(runtime, event)
    size = _ease(_seg(u, 0.0, 0.15)) * (1.0 - 0.65 * _seg(u, 0.15, 1.0))  # nace grande y se achica
    cel(layer, teardrop(base, up, 1.1 * scale * size, 0.2 * scale * size + 1, frame_index), color, alpha, runtime)
    return []


# ----- piso y aro -----


def _floor_fire(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    floor = _floor(body, scale)
    if floor is None:
        return []
    joints = [p for p in (body.get(j) for j in ("left_wrist", "right_wrist", "left_ankle", "right_ankle")) if p is not None]
    if not joints:
        return []
    low = max(joints, key=lambda p: p[1])  # la extremidad más cerca del piso
    st = _activation(runtime, event, "floor", body)
    st["x0"] = min(st.get("x0", low[0]), low[0])
    st["x1"] = max(st.get("x1", low[0]), low[0])
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2))
    x0, x1 = st["x0"] - 0.35 * scale, st["x1"] + 0.35 * scale
    xs = np.linspace(x0, x1, 60)
    edge = np.minimum(np.linspace(0, 1, 60) * 3, 1) ** 0.7 * np.minimum(np.linspace(1, 0, 60) * 3, 1) ** 0.7
    w = 0.16 * scale
    lick = 0.35 + 0.65 * np.clip(
        0.55 * np.sin(xs / w - frame_index * 0.55) + 0.35 * np.sin(xs / (w * 0.43) + frame_index * 0.8 + 1.3) + 0.25 * np.sin(xs / (w * 2.3) - frame_index * 0.3), -1, 1) ** 2
    lean = np.sin(xs / (w * 1.7) + frame_index * 0.4) * 0.12 * scale  # las lenguas se mecen de lado

    def make(k: float):
        h = 0.42 * scale * grow * edge * lick * k
        top = np.stack([xs + lean * (h / max(h.max(), 1e-6)), floor - h], axis=1)
        return np.vstack([top, [[x1, floor], [x0, floor]]])

    cel(layer, make, color, alpha, runtime, 1.4)
    return []


def _fire_ring(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    found = _wrist(body, event, scale)
    if found is None:
        return []
    _, point = found
    u = _phase(runtime, event)
    r = 0.38 * scale * _ease(_seg(u, 0.0, 0.25))
    a0 = frame_index * 0.35
    a = np.linspace(a0, a0 + TAU * 0.8, 36)  # un aro abierto que gira
    spine = point + np.stack([np.cos(a), np.sin(a)], axis=1) * r
    widths = 0.06 * scale * np.sin(np.linspace(0.05, np.pi - 0.05, 36)) + 0.5
    cel(layer, ribbon(spine, widths, frame_index, 5.0), color, alpha, runtime)
    return []


# ----- la cara: calavera y estado Avatar -----


def _face(body, frame, scale):
    center, across, down = frame
    nose = body.get("nose")
    if nose is None:
        return None
    ears = [body.get("left_ear"), body.get("right_ear")]
    width = float(np.linalg.norm(ears[0] - ears[1])) if all(e is not None for e in ears) else 0.0
    return nose, max(width * 0.75, 0.28 * scale), -down, across


def _glowing_eyes(body, layer, r, alpha, runtime) -> None:
    for name in ("left_eye", "right_eye"):
        eye = body.get(name)
        if eye is not None:
            splat(layer, float(eye[0]), float(eye[1]), 0.16 * r, WHITE * 2.2, alpha, runtime.kernels)


def _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = _face(body, frame, scale)
    if face is None:
        return []
    nose, r, up, across = face
    forehead = nose + up * 0.55 * r
    top = nose + up * 1.25 * r
    # La flecha de Aang: una banda que baja por la cabeza y termina en punta sobre la frente.
    shaft = np.array([top + across * 0.07 * r, forehead + up * 0.18 * r + across * 0.07 * r, forehead + up * 0.18 * r - across * 0.07 * r, top - across * 0.07 * r])
    head = np.array([forehead + up * 0.2 * r + across * 0.2 * r, forehead, forehead + up * 0.2 * r - across * 0.2 * r])
    fill_polygon(layer, shaft, CORE, alpha, 1.6, feather=1.0)
    fill_polygon(layer, head, CORE, alpha, 1.6, feather=1.0)
    warm(layer, forehead, 1.6 * r, np.asarray(color, np.float32), alpha * 0.45)
    _glowing_eyes(body, layer, r, alpha, runtime)
    return [shaft, head]


# ----- el cuerpo arde, y el cierre -----


def _body_blaze(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = np.array([0.0, -1.0])  # el fuego sube hacia arriba de la imagen, sin importar la pose
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.3))
    chains = [(f"{s}_{a}", f"{s}_{b}", f"{s}_{c}") for s in ("left", "right") for a, b, c in (("shoulder", "elbow", "wrist"), ("hip", "knee", "ankle"))]
    k = 0
    for names in chains:
        pts = [body.get(n) for n in names]
        if any(p is None for p in pts):
            continue
        for a_, b_ in ((pts[0], pts[1]), (pts[1], pts[2])):
            for q in (0.2, 0.6, 0.95):  # tres llamas por hueso, de distinto tamaño
                k += 1
                base = a_ + (b_ - a_) * q
                size = (0.45 + 0.35 * np.sin(k * 2.3) ** 2) * scale * grow
                cel(layer, teardrop(base, up, size, 0.13 * scale, frame_index, k * 0.9), color, alpha, runtime, 0.5)
    for s in (-1, 1):  # alas de fuego sobre los hombros
        shoulder = body.get("left_shoulder" if (s < 0) == (across[0] > 0) else "right_shoulder")
        if shoulder is None:
            continue
        d = up + np.array([s * 0.9, 0.0])
        cel(layer, teardrop(shoulder, d / float(np.linalg.norm(d)), 1.5 * scale * grow, 0.35 * scale, frame_index, s), color, alpha, runtime)
    return []


def _fire_wall(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    st = runtime.swoosh.setdefault("_firewall", {})
    if st.get("frame") == frame_index:  # una sola pared por cuadro, aunque haya dos personas
        return []
    st["frame"] = frame_index
    total = runtime.frame_count
    length = int(max(runtime.effect.style.size, 0.5) * runtime.fps)
    if total <= 0 or frame_index < total - length:
        return []
    s = _ease((frame_index - (total - length)) / max(length - 1, 1))
    height, width = layer.shape[:2]
    rise = height * (0.1 + 0.5 * s)
    base_y = height + 2
    # Como en la referencia (seg. 15,4): llamas blancas separadas, con huecos naranjas entre ellas
    # (el resplandor), sobre una base baja; no un bloque. Las de atrás más altas y finas.
    band = np.array([[-0.05 * width, base_y - rise * 0.12], [1.05 * width, base_y - rise * 0.12], [1.05 * width, base_y + 2], [-0.05 * width, base_y + 2]])
    cel(layer, lambda k: band, color, alpha * 0.8, runtime, 2.0, core=False, mass=True)
    rng = np.random.default_rng(18)
    for j in range(7):  # pocas y separadas: entre una y otra queda el resplandor naranja
        x = width * (j + 0.5 + rng.uniform(-0.15, 0.15)) / 7
        tall = rise * rng.uniform(0.55, 1.0) * (0.85 + 0.2 * _smooth_noise(np.array([frame_index * 0.06 + j]), 3.0)[0])
        lean = np.array([_smooth_noise(np.array([frame_index * 0.05 + j * 1.7]), 5.0)[0] * 0.4, -1.0])
        thin = min(tall * rng.uniform(0.22, 0.3), width / 7 * 0.55)  # base ancha
        # Se enroscan en la punta, alternando el lado y con distinta vuelta (no pasto recto).
        curl = (0.35 + 0.2 * rng.random() + 0.08 * _smooth_noise(np.array([frame_index * 0.05 + j]), 9.0)[0]) * (1 if j % 2 else -1)
        cel(layer, teardrop(np.array([x, base_y - rise * 0.06]), lean / float(np.linalg.norm(lean)), tall, thin, frame_index, j * 1.3, curl), color, alpha * 0.85, runtime, 1.5)
    return _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha * min(s * 3, 1.0), event)


# Luz del fuego sobre el plano (se mezcla multiplicando, antes del fuego): cerca de las llamas
# sube el rojo y baja el azul conservando la textura (la ropa y el piso se tiñen de naranja con
# sus arrugas y sombras); lejos, con mucho fuego en pantalla, el cuadro se oscurece un poco para
# que el fuego resalte (lo que el animador hace al subexponer el plano).
LIGHT_TINT = np.array([1.6, 0.74, 0.32], np.float32)
LIGHT_DARK = 0.74


def _fire_light(runtime, layer, frame_index: int, alpha: float) -> list:
    st = runtime.swoosh.setdefault("_firelight", {})
    if st.get("frame") == frame_index:  # una vez por cuadro aunque haya dos personas
        return []
    st["frame"] = frame_index
    note_frame(frame_index)
    lights = _LIGHTS["prev"] + _LIGHTS["now"]
    if not lights:
        return []
    height, width = layer.shape[:2]
    step = 8  # la luz es suave: se calcula a 1/8 y se agranda
    gy, gx = np.mgrid[0:height:step, 0:width:step].astype(np.float32)
    light = np.zeros(gx.shape, np.float32)
    amount = 0.0
    for mid, size, a in lights:
        r = max(size * 3.0, 0.9 * height)  # la referencia tiñe casi todo el cuadro mientras hay fuego
        d2 = ((gx - mid[0]) ** 2 + (gy - mid[1]) ** 2) / (r * r)
        light += np.clip(1.0 - d2, 0.0, 1.0) ** 2 * np.float32(a)
        amount += size * a
    light = cv2.resize(np.clip(light, 0.0, 1.0), (width, height), interpolation=cv2.INTER_LINEAR)
    cover = np.float32(min(amount / (0.5 * height), 1.0) * 0.45 * alpha)
    straight = LIGHT_DARK * (1.0 - light)[..., None] + LIGHT_TINT * light[..., None]
    layer[..., :3] = straight * cover
    layer[..., 3] = cover
    return []


def firebend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    note_frame(frame_index)
    if shape == "fire_light":
        return _fire_light(runtime, layer, frame_index, alpha)
    if shape == "fire_whip":
        return _fire_whip(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "hand_fire":
        return _hand_fire(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "candle":
        return _candle(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "floor_fire":
        return _floor_fire(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_ring":
        return _fire_ring(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "avatar_mark":
        return _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "body_blaze":
        return _body_blaze(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_wall":
        return _fire_wall(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
