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
- `fire_blast`, `fire_carpet`, `fire_halo` (glowing/video_51, docs/referencias/video_51.md): chorro
  de fuego desde el puño, alfombra de lenguas en el piso y aro grande alrededor del cuerpo.
- `fire_trail`: swoosh de fuego: la mano lleva la llama prendida y, al moverse, la estela de fuego
  la persigue por su recorrido (lo que queda atrás sube y se achica); al frenar se recoge.
- `fire_landing`: al caer al piso con el fuego en los pies, el fuego choca y se desbarata en el
  suelo (video_51, seg. 2,4-2,7); si no venía de los pies, el golpe de piso de siempre.
- `fire_orbit`: la mano pone el fuego a girar alrededor del cuerpo (en perspectiva), lo atrapa al
  completar la vuelta y, si estira el brazo o abre la mano, lo lanza como una explosión
  (video_51, seg. 4,0-4,7).
- `fire_carpet_end`: cierre con la alfombra: en los últimos segundos, solo si la persona lleva más
  de 2 s de frente (y no hay pared). Se usa en `always`.
- `fire_wall`: cierre: en el último tramo una pared de fuego sube desde el piso hasta llenar el
  cuadro, con la flecha y los ojos encendidos (seg. 14,4-16). Se usa en `always`: se cronometra
  sola con `runtime.frame_count` (`style.size` = segundos del cierre).
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

FIREBEND = ("fire_whip", "hand_fire", "candle", "floor_fire", "fire_ring", "avatar_mark", "body_blaze", "fire_wall", "fire_light", "fire_blast", "fire_carpet", "fire_halo", "fire_carpet_end", "fire_trail", "fire_landing", "fire_orbit")
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
# Intensidad general del fuego pintado (núcleo, borde y resplandor): 0,85 = un 15% menos.
FIRE_INTENSITY = 0.80
WHITE_HOT = np.array([1.0, 0.98, 0.9], np.float32) * 1.35  # apenas sobre 1: con más, el bloom engorda la forma
RIM = np.array([1.0, 0.78, 0.2], np.float32) * 1.6
NEAR_GLOW = np.array([1.0, 0.48, 0.04], np.float32)
FAR_GLOW = np.array([1.0, 0.26, 0.0], np.float32)
# Estilo cel (glowing/video_51): amarillo puro #FAF71C, plano y opaco, sin núcleo blanco.
CEL_YELLOW = np.array([0.955, 0.93, 0.011], np.float32)
# El estilo con que se dibuja el efecto en curso (style.look): hot, cel o mix. Lo fija
# draw_adornment antes de dibujar; cel() lo anota en el fuego del efecto.
LOOK = {"now": "hot"}


def set_look(look: str) -> None:
    LOOK["now"] = look if look in ("hot", "cel", "mix") else "hot"


def note_frame(frame_index: int) -> None:
    """El primer efecto de fuego de cada cuadro rota la lista de luces."""
    if frame_index != _LIGHTS["frame"]:
        if frame_index < _LIGHTS["frame"]:  # otro video o se volvió atrás
            _LIGHTS["now"] = []
        _LIGHTS["prev"], _LIGHTS["now"], _LIGHTS["frame"] = _LIGHTS["now"], [], frame_index


def _entry(layer) -> dict:
    """El fuego acumulado de la capa en este cuadro (lo pinta flush_fire)."""
    height, width = layer.shape[:2]
    entry = _FIELDS.get(id(layer))
    if entry is not None and entry["mask"].shape != (height, width):
        entry = None  # quedó de otra capa ya liberada que tenía la misma dirección de memoria
    if entry is None:
        entry = _FIELDS[id(layer)] = {"mask": np.zeros((height, width), np.float32), "field": None, "alpha": 0.0, "look": LOOK["now"]}
    return entry


def cel(layer, make, color, alpha: float, runtime=None, heat: float = 1.0, core: bool = True, mass: bool = False) -> None:
    """Suma una llama al fuego del efecto (make(1.0) da su contorno). `mass`: masa grande que se
    funde con las vecinas como líquido (bola de fuego, pared). Con `runtime`, además un resplandor
    tenue alrededor y la llama cuenta como luz para fire_light. (`core` queda por compatibilidad:
    el cuerpo ya es blanco entero.)"""
    if alpha <= 0:
        return
    height, width = layer.shape[:2]
    entry = _entry(layer)
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
    vel = out * speed + np.array([0.0, -0.006 * height], np.float32) + pool.get("inherit", np.zeros(2, np.float32))  # afuera, arriba y con el fuego
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
        # Las livianas flotan; las más grandes (trozos pesados) caen con gravedad.
        heavy = (pool["size"] > 0.0078 * height)[:, None]
        lift = np.where(heavy, np.array([0.0, 0.0016 * height], np.float32), np.array([0.0, -0.0012 * height], np.float32))
        pool["vel"] = vel * 0.9 + wobble * (0.0025 * height) + lift
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
    comma = pool.get("look", "hot") != "hot"
    if comma:  # estilo cel/mix: comas amarillas planas (video_51) en vez de rayitas
        colors = np.where((age < 0.6)[:, None], CEL_YELLOW * 1.1, colors)
    for p, v, c, s, a in zip(pos, vel, colors, pool["size"], shrink):
        if comma:
            poly = _comma(p - np.array([x0, y0], np.float32), v, max(s * a * 1.6, 1.5))
            cv2.fillPoly(canvas, [poly], (float(c[0]), float(c[1]), float(c[2])), cv2.LINE_AA)
            cv2.fillPoly(cover, [poly], float(a), cv2.LINE_AA)
            continue
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


def _comma(center: np.ndarray, vel: np.ndarray, radius: float) -> np.ndarray:
    """Una coma (medialuna con punta) que se curva según la velocidad de la brasa."""
    heading = float(np.arctan2(vel[1], vel[0])) if float(np.linalg.norm(vel)) > 1e-3 else -np.pi / 2
    a = heading + np.linspace(-1.6, 1.6, 9)
    outer = np.stack([np.cos(a), np.sin(a)], axis=1) * radius
    inner = np.stack([np.cos(a), np.sin(a)], axis=1) * radius * np.linspace(0.95, 0.35, 9)[:, None] - np.array([np.cos(heading), np.sin(heading)]) * radius * 0.35
    return np.round(np.vstack([outer, inner[::-1]]) + center).astype(np.int32)


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
    a = np.float32(min(entry["alpha"], 1.0) * FIRE_INTENSITY)
    look = entry.get("look", "hot")
    if look == "hot":
        rgb = WHITE_HOT * m[..., None] + RIM * band[..., None] + NEAR_GLOW * (near * 0.375)[..., None] + FAR_GLOW * (far * 0.3)[..., None]
        cover = np.clip(m + band + near * 0.3 + far * 0.2, 0.0, 1.0)
    else:
        m, body = _cel_body(m, look, frame_index, (x0, y0, x1, y1), (height, width))
        a = np.float32(min(entry["alpha"], 1.0))  # el plano no se atenúa: es opaco
        glow = 0.12 if look == "cel" else 0.3  # el cel casi no irradia: el brillo lo pone el tinte del cuadro
        rgb = body * m[..., None] + NEAR_GLOW * (near * glow)[..., None] + FAR_GLOW * (far * glow * 0.8)[..., None]
        cover = np.clip(m + near * glow * 0.8 + far * glow * 0.5, 0.0, 1.0)
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += rgb * a
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - cover * a)
    if embers is not None:
        # Heredan la mitad del movimiento del fuego que las suelta (el centro de la llama).
        ys_, xs_ = np.nonzero(m > 0.5)
        if len(xs_):
            center_now = np.array([xs_.mean() + x0, ys_.mean() + y0], np.float32)
            prev_c = embers.get("center")
            embers["center"] = center_now
            embers["inherit"] = (center_now - prev_c) * 0.5 if prev_c is not None and np.linalg.norm(center_now - prev_c) < 0.15 * height else np.zeros(2, np.float32)
        # Pocas: una brasa cada ~14.000 px de fuego por cuadro; al morir, tres veces más (se deshace).
        dying = u is not None and u > DIE_START
        rate = min(float(m.sum()) / 22000.0 * (3.0 if dying else 1.0), 4.0)
        embers["look"] = look
        emit_embers(embers, m, (x0, y0), frame_index, rate, height)
        draw_embers(layer, embers, frame_index, 1.0)


def _cel_body(m: np.ndarray, look: str, frame_index: int, box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Máscara y color del fuego plano (cel y mix). Cel: amarillo puro con huecos en lo ancho, por
    donde se ve el fondo (glowing/video_51). Mix: el mismo amarillo con el núcleo blanco de
    video_18 solo a lo largo del centro de las partes gruesas."""
    x0, y0, x1, y1 = box
    height, width = size
    dist = cv2.distanceTransform((m > 0.5).astype(np.uint8), cv2.DIST_L2, 3)
    if look == "cel":
        # Huecos: manchas del ruido que sube con el fuego, solo donde la llama es ancha.
        drift = _noise(height, width, frame_index, 41)[y0:y1, x0:x1]
        wide = np.clip((dist - 0.012 * height) / (0.008 * height), 0.0, 1.0)
        hole = np.clip((drift - 0.3) / 0.08, 0.0, 1.0) * wide
        return m * (1.0 - hole), np.broadcast_to(CEL_YELLOW, m.shape + (3,))
    local = cv2.dilate(dist, np.ones((25, 25), np.uint8))
    center = dist / np.maximum(local, 1.0)  # 1 sobre la línea central de cada parte
    # Solo en grosores medios (cintas, chorros, gotas): en las masas muy anchas (alfombra, pared)
    # un núcleo blanco grande se veía como plastilina.
    thick = np.clip((dist - 0.008 * height) / (0.008 * height), 0.0, 1.0) * np.clip((0.04 * height - dist) / (0.015 * height), 0.0, 1.0)
    core = (np.clip((center - 0.75) / 0.2, 0.0, 1.0) * thick)[..., None]  # una franja fina por el centro
    return m, CEL_YELLOW * (1.0 - core) + WHITE_HOT * core


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

    hook = LOOK["now"] != "hot"
    if hook:
        # Estilo cel/mix (video_51): lenguas más altas y afiladas que se inclinan hacia la cola,
        # todas hacia el mismo lado, como ganchos.
        flick = 1.0 + 1.5 * np.maximum(0.0, _smooth_noise(t * tongues * 2.4 - drift, phase + 1.0)) ** 2.5
        tangent = np.gradient(spine, axis=0)
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-6)

    def make(k: float):
        w = widths * k
        upper = spine + normal * (w * flick * up_notch)[:, None]
        if hook:
            upper = upper - tangent * (w * (flick - 1.0) * 0.9)[:, None]
        lower = spine - normal * (w * (0.7 + 0.3 * calm) * low_notch)[:, None]
        return np.vstack([upper, lower[::-1]])

    return make


# ----- física de la llama (docs/fisica_del_fuego.md) -----
#
# Cada llama anclada (a una mano, la cabeza, un hueso) tiene un estado: su dirección es un ángulo
# que sigue con un resorte amortiguado a la dirección que piden las fuerzas:
#   flotación (sube) + viento relativo (el aire que corta el ancla empuja la llama en contra de su
#   movimiento) + viento del ambiente (opcional).
# El resorte da inercia: al arrancar la llama se queda atrás, al frenar se pasa de largo, oscila y
# se asienta. La velocidad la estira y la afina; al frenar en seco se recoge (más corta y ancha).

BUOYANCY = 1.0      # cuánto tira hacia arriba
WIND_DRAG = 5.0     # cuánto la empuja el aire relativo (por ancho de hombros por cuadro)
SPRING = 0.32       # rigidez del resorte del ángulo
DAMPING = 0.7       # cuánto conserva de su giro por cuadro (menos = se asienta antes)
MAX_LEAN = 1.45     # inclinación máxima respecto de la vertical (rad, ~83°)
STRETCH = 2.5       # cuánto se estira con la velocidad
MAX_STRETCH = 1.7


CENTRIFUGAL = 6.0   # cuánto abre las llamas hacia afuera al girar alrededor del cuerpo
ATTRACT = 0.9       # cuánto se inclinan dos llamas cercanas una hacia la otra
MERGE_GAP = 0.35    # a menos de esto (anchos de hombros) dos llamas se funden en una
# Viento del ambiente (por ancho de hombros): (0, 0) sin viento; p. ej. (-0.6, 0) sopla a la izquierda.
AMBIENT_WIND = np.array([0.0, 0.0])


def flame_physics(
    st: dict,
    key: str,
    anchor: np.ndarray,
    scale: float,
    up: np.ndarray | None = None,
    wind: np.ndarray | None = None,
    pivot: np.ndarray | None = None,
    partner: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    """(dirección unitaria de la llama, factor de estiramiento) para la llama anclada en `anchor`.

    `st` guarda el estado entre cuadros; `key` distingue cada llama del efecto. `pivot`: el eje del
    cuerpo (la llama se abre hacia afuera si el ancla gira a su alrededor). `partner`: el ancla de
    otra llama cercana (se atraen cuando están a menos de un ancho de hombros)."""
    up = np.array([0.0, -1.0]) if up is None else up
    s = st.setdefault(key, {})
    prev = s.get("p")
    s["p"] = np.asarray(anchor, float).copy()
    vel = (s["p"] - prev) / max(scale, 1e-6) if prev is not None else np.zeros(2)
    if float(np.linalg.norm(vel)) > 1.5:  # salto del detector (no un movimiento real): se ignora
        vel = np.zeros(2)
    s["v"] = s.get("v", vel) * 0.5 + vel * 0.5  # velocidad suavizada
    force = up * BUOYANCY - s["v"] * WIND_DRAG + (AMBIENT_WIND if wind is None else wind)
    if pivot is not None:  # fuerza centrífuga: v_tangencial² / radio, hacia afuera del eje
        radial = (s["p"] - np.asarray(pivot, float)) / max(scale, 1e-6)
        radius = float(np.linalg.norm(radial))
        if radius > 0.5:  # solo con la mano lejos del eje (cerca, un temblor no es un giro)
            out = radial / radius
            tangential = s["v"] - out * float(np.dot(s["v"], out))
            force = force + out * CENTRIFUGAL * float(np.dot(tangential, tangential)) / radius
    if partner is not None:  # dos llamas cercanas se inclinan una hacia la otra
        gap = (np.asarray(partner, float) - s["p"]) / max(scale, 1e-6)
        dist = float(np.linalg.norm(gap))
        if MERGE_GAP <= dist < 1.0:  # más cerca que eso ya son una sola llama (ver _hand_fire)
            force = force + gap / dist * ATTRACT * (1.0 - dist)
    rest = float(np.arctan2(up[1], up[0]))
    target = float(np.arctan2(force[1], force[0]))
    target = rest + float(np.clip(np.angle(np.exp(1j * (target - rest))), -MAX_LEAN, MAX_LEAN))
    angle = s.get("a", target)
    spin = s.get("w", 0.0)
    spin = spin * DAMPING + float(np.angle(np.exp(1j * (target - angle)))) * SPRING
    angle += spin
    s["a"], s["w"] = angle, spin
    speed = float(np.linalg.norm(s["v"]))
    goal = 1.0 + min(speed * STRETCH, MAX_STRETCH - 1.0)
    # Frenada brusca: se recoge un instante (más corta) antes de volver a su largo.
    braking = max(s.get("speed", 0.0) - speed, 0.0)
    goal -= min(braking * 3.0, 0.35)
    s["speed"] = speed
    s["s"] = s.get("s", 1.0) * 0.6 + goal * 0.4
    return np.array([np.cos(angle), np.sin(angle)]), float(s["s"])


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


def flame_parts(base: np.ndarray, up: np.ndarray, tall: float, width: float, frame_index: int, seed: float = 0.0, trail: list | None = None, swoosh: float = 0.0) -> list[tuple[np.ndarray, np.ndarray]]:
    """Una llama completa como piezas (línea central, anchos): el cuerpo en forma de gota (base
    redonda) con bordes caóticos, a veces una lengüeta chica pegada al cuerpo, y un trocito suelto
    sobre la punta. Se dibujan juntas y nacen/mueren juntas (living_ribbon).

    `trail` (posiciones recientes del ancla, de la más vieja a la actual) y `swoosh` (0-1, según la
    velocidad): con la mano rápida el cuerpo se dobla siguiendo su recorrido, como una estela."""
    side = np.array([-up[1], up[0]])
    s = np.linspace(0, 1, 32)
    sway = _smooth_noise(s * 2.5 - frame_index * 0.09, seed) * 0.18 * tall * s ** 1.3
    spine = base + np.outer(s * tall, up) + np.outer(sway, side)
    if trail is not None and len(trail) >= 3 and swoosh > 0:
        # Estela: el punto s del cuerpo va hacia la posición que tenía el ancla hace s·n cuadros
        # (la llama queda tendida sobre el camino de la mano).
        path = np.asarray(trail[::-1], float)  # de la actual a la más vieja
        offsets = path - path[0]
        idx = np.clip(s * (len(path) - 1), 0, len(path) - 1)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, len(path) - 1)
        f = (idx - lo)[:, None]
        streak = base + (offsets[lo] * (1 - f) + offsets[hi] * f) * 2.2 + np.outer(s * tall * 0.35, up)
        w = np.clip(swoosh, 0.0, 1.0) * s[:, None] ** 0.6  # la base sigue en la mano
        spine = spine * (1 - w) + streak * w
    profile = flame_profile(s, width, seed, frame_index)
    # Bordes caóticos: mordiscos y bultos irregulares que se mueven (no un contorno liso).
    chaos = 1.0 + 0.22 * _smooth_noise(s * 9.0 - frame_index * 0.25, seed + 11.0) * np.clip(s * 2.5, 0, 1)
    parts = [(spine, profile * chaos)]
    rng = np.random.default_rng(int(abs(seed) * 1000) % 2**31)
    if rng.random() < 0.6 and swoosh < 0.5:  # una lengüeta chica, pegada al cuerpo (no una hoja)
        sign = rng.choice([-1.0, 1.0])
        at = rng.uniform(0.5, 0.65)
        k = int(at * 31)
        root = spine[k] + side * sign * profile[k] * 0.55
        d = up + side * sign * 0.3
        d /= float(np.linalg.norm(d))
        q = np.linspace(0, 1, 10)
        wob = _smooth_noise(q * 2.0 - frame_index * 0.12, seed + 7) * 0.08 * tall * q
        tongue = root + np.outer(q * tall * rng.uniform(0.18, 0.26), d) + np.outer(wob, np.array([-d[1], d[0]]))
        parts.append((tongue, width * 0.22 * np.sin(np.pi * np.clip(q * 0.9 + 0.1, 0, 1)) ** 0.6 * (1 - q) ** 0.6 + 0.4))
    tip = spine[-1] + up * tall * 0.1 + side * _smooth_noise(np.array([frame_index * 0.1]), seed + 9)[0] * 0.08 * tall
    q = np.linspace(0, 1, 10)
    wisp = tip + np.outer(q * tall * 0.14, up)
    parts.append((wisp, width * 0.15 * np.sin(np.pi * q) + 0.3))
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
    entry = _entry(layer)
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
        # Solo el tramo desde el último giro brusco (más de 100°): si la mano cambia de dirección
        # en medio del golpe, el látigo dibujaba un zigzag como una letra (seg. 10,4).
        steps_d = np.diff(spine, axis=0)
        norms = np.linalg.norm(steps_d, axis=1)
        for i in range(len(steps_d) - 1, 0, -1):
            a_, b_ = steps_d[i - 1], steps_d[i]
            if norms[i - 1] > 1 and norms[i] > 1 and float(np.dot(a_, b_)) / (norms[i - 1] * norms[i]) < -0.17:
                spine = spine[i:]
                break
        if len(spine) < 3 or float(np.linalg.norm(spine[-1] - spine[0])) < 0.25 * scale:  # casi quieta: sin látigo
            continue
        # Exagerado como en la referencia: el látigo dobla el recorrido real (desde la mano hacia
        # atrás) y la llama se adelanta a la mano, como si la lanzara.
        # El recorrido exagerado; si la persona ocupa poco del cuadro, más (el swoosh se ve en
        # proporción al cuadro, como en video_51).
        spine = spine[-1] + (spine - spine[-1]) * WHIP_SCALE * (1.4 if len(limbs) == 2 else 1.0) * (_unit(scale, layer) / scale)
        ahead = spine[-1] - spine[-3]
        spine = np.vstack([spine, spine[-1] + ahead * 0.8])
        # Medialuna como en la referencia: se arquea hacia el lado en que gira el golpe (aunque el
        # recorrido real sea casi recto), y se remuestrea a una curva suave de 40 puntos.
        chord = spine[-1] - spine[0]
        length = float(np.linalg.norm(chord))
        side = np.array([-chord[1], chord[0]]) / max(length, 1e-6)
        turn = st.setdefault("turn", float(np.sign(np.dot(spine[len(spine) // 2] - (spine[0] + spine[-1]) / 2, side)) or 1.0))  # fijo por golpe
        # Siempre una medialuna suave: curva de Bézier del inicio al fin del tramo, arqueada hacia el
        # lado del golpe. Con pocos puntos de recorrido, la curva anterior salía con esquinas ("A").
        unit = _unit(scale, layer)  # en proporción al cuadro si la persona ocupa poco (video_51)
        cap = (2.4 if len(limbs) == 2 else 1.8) * unit  # tope de largo (las patadas hacían barras)
        start, end = spine[0], spine[-1]
        if length > cap:
            start = end + (start - end) * (cap / length)
            length = cap
        control = (start + end) / 2 + side * 0.75 * length * turn
        q = np.linspace(0, 1, 40)[:, None]
        smooth = (1 - q) ** 2 * start + 2 * (1 - q) * q * control + q ** 2 * end
        q = q[:, 0]
        # Fina y en punta en la cola, ancha cerca de la mano y otra vez afilada en la cabeza.
        big = 1.5 if len(limbs) == 2 else 1.0  # con las dos manos, medialunas grandes (seg. 0,8)
        widths = (0.006 + 0.24 * big * np.sin(np.pi * q) ** 0.9 * q ** 0.9) * unit
        living_ribbon(layer, smooth, widths, u, st, frame_index, color, alpha, runtime)
        if u < DIE_START:
            shed(layer, smooth, widths, st, frame_index, scale, color, alpha)
        rim(layer, runtime, [point, smooth[len(smooth) // 2]], scale, color, alpha)
        splat(layer, float(point[0]), float(point[1]), 0.12 * scale, CORE * 1.4, alpha * 0.6, runtime.kernels)
    return []


TRAIL_FRAMES = 12  # cuadros del recorrido que forman la estela
TRAIL_EXAGGERATION = 1.5  # la estela, más larga que el recorrido real (como las de las referencias)
HANDS, FEET = ("left_wrist", "right_wrist"), ("left_ankle", "right_ankle")
FEET_EVENTS = ("flip", "tumble")  # dando volteretas la atención está en los pies
TRANSFER_FRAMES = 12  # lo que tarda el fuego en pasar de unas extremidades a otras
TRANSFER_WINDOW = 45  # cuadros: el fuego de antes solo se reutiliza si fue hace poco
TRANSFER_SWOOSH = 2.5  # unidades: más lejos que esto, el fuego viaja en un swoosh y no en trocitos
# Por persona: dónde estuvo el fuego la última vez: (extremidades, sus posiciones, cuadro).
_FIRE_LIMBS: dict = {}


def _limb_point(body, name: str) -> np.ndarray | None:
    """La posición de una extremidad del fuego (`head` es la cabeza: la nariz)."""
    return body.get("nose") if name == "head" else body.get(name)


def note_fire(body, names, frame_index: int) -> None:
    """Anota que el fuego está en estas extremidades (para el traspaso de lo que siga)."""
    where = {n: _limb_point(body, n) for n in names}
    _FIRE_LIMBS[getattr(body, "prefix", "") or "person"] = (tuple(names), {n: p.copy() for n, p in where.items() if p is not None}, frame_index)


def _limb_speed(body, names) -> float:
    points, prefix = getattr(body, "points", body), getattr(body, "prefix", "")
    vels = [points.get(f"vel:{prefix}{n}", points.get(f"vel:{n}")) for n in names]
    vels = [float(np.linalg.norm(v)) for v in vels if v is not None]
    return max(vels) if vels else 0.0


def _attention_limbs(body, event, st: dict) -> tuple[str, ...]:
    """Las extremidades que llevan el fuego: las del gesto si es de una mano o un pie; en
    volteretas, los pies; si no, el grupo (manos o pies) que más se mueve, con histéresis (no
    salta de uno a otro por un cuadro)."""
    joint = event.target.split(":")[-1] if event is not None else ""
    if joint.endswith(("_wrist", "_ankle")):
        return (joint,)
    if event is not None and event.name in FEET_EVENTS:
        return FEET
    if event is not None and event.kind in ("left", "right"):
        return (f"{event.kind}_wrist",)
    hands, feet = _limb_speed(body, HANDS), _limb_speed(body, FEET)
    group = st.get("group", "hands")
    if group == "hands" and feet > hands * 1.5 + 1.0:
        group = "feet"
    elif group == "feet" and hands > feet * 1.5 + 1.0:
        group = "hands"
    st["group"] = group
    return FEET if group == "feet" else HANDS


def _fire_trail(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    """Swoosh de fuego (como el swoosh del catálogo de peleas, pero de fuego): la llama está
    prendida en la mano (o el pie) desde el principio y, cuando se mueve, una estela de fuego la
    persigue por el recorrido: ancha en la extremidad, afinándose hacia la cola. Lo que queda atrás
    sube (el aire caliente) y se achica; si la extremidad frena, la estela se recoge en la llama.
    El fuego va en las extremidades donde está la atención (_attention_limbs) y, si venía de las
    otras (de una mano a la otra, de las manos a los pies), viaja hasta ellas (transfer_fire).
    La estela se corta en el último giro brusco (en un giro sobre sí mismo hacía un gancho o una V)
    y tiene un tope de largo."""
    center, across, down = frame
    up = -down
    att = _activation(runtime, event, "trail:attention", body)
    limbs = _attention_limbs(body, event, att)
    lit = transfer_fire(body, limbs, frame_index, scale, layer, color, alpha, runtime, att)
    unit = _unit(scale, layer)
    for k, name in enumerate(limbs):
        point = body.get(name)
        if point is None:
            continue
        grow = _ease(_seg(_phase(runtime, event), 0.0, 0.15)) * lit.get(name, 1.0)
        st = _activation(runtime, event, f"trail:{name}", body)
        hist = st.setdefault("hist", [])
        if hist and float(np.linalg.norm(point - hist[-1])) > 1.5 * scale:
            hist.clear()  # salto del detector: la estela empieza de nuevo
        for h in hist:  # lo que quedó atrás sube y se mece
            h += up * 0.025 * scale + across * _smooth_noise(np.array([frame_index * 0.2 + h[0] * 0.01]), 3.0)[0] * 0.01 * scale
        hist.append(np.asarray(point, dtype=np.float64).copy())
        del hist[:-TRAIL_FRAMES]
        lean, stretch = flame_physics(st, "phys", point, scale, up)
        pts = np.array(hist)
        steps = np.linalg.norm(np.diff(pts, axis=0), axis=1) / max(scale, 1e-6) if len(pts) > 1 else np.zeros(0)
        speed = float(steps[-3:].mean()) if len(steps) else 0.0
        # La llama de la extremidad, siempre prendida. Rápida, se achica y queda como la cabeza de
        # la estela (con su inercia apuntaba a donde iba antes del giro y formaba una V); al frenar
        # vuelve a crecer. Tamaños en `unit`: si la persona ocupa poco del cuadro, el fuego no se
        # achica con ella (video_51).
        moving = float(np.clip((speed - 0.04) / 0.12, 0.0, 1.0))
        half = 0.22 * unit * grow * (1.0 - 0.45 * moving)
        tall = 1.0 * unit * grow * (stretch * (1.0 - moving) + 0.35 * moving)
        base = point - up * half * 0.6
        for j, (spine, widths) in enumerate(flame_parts(base, lean, tall, half / np.sqrt(stretch), frame_index, k * 1.7 + 0.3)):
            cel(layer, ribbon(spine, widths, frame_index, 3.0, k * 1.7 + j), color, alpha, runtime if j == 0 else None)
        # La estela: solo si viene moviéndose; más larga cuanto más rápido.
        keep = int(np.clip(speed / 0.04, 0, len(pts)))  # quieta: no hay estela
        tail = pts[-keep:] if keep >= 3 else pts[:0]
        if len(tail) >= 3:
            # Desde la extremidad hacia atrás, hasta que el recorrido gire más de 75° en total (un
            # giro repartido en varios cuadros también cuenta): un arco suave queda entero, un
            # cambio de dirección no deja ganchos ni esquinas en V.
            d = np.diff(tail, axis=0)
            n = np.linalg.norm(d, axis=1)
            heading = np.arctan2(d[:, 1], d[:, 0])
            turned = 0.0
            for i in range(len(d) - 1, 0, -1):
                if n[i] > 1 and n[i - 1] > 1:
                    turned += abs(float(np.angle(np.exp(1j * (heading[i] - heading[i - 1])))))
                if turned > np.radians(75):
                    tail = tail[i:]
                    break
        if len(tail) >= 2:  # tope de largo, medido desde la extremidad hacia atrás
            seg = np.linalg.norm(np.diff(tail, axis=0), axis=1)
            far = np.cumsum(seg[::-1])
            cut = int(np.searchsorted(far, 2.2 * unit))
            tail = tail[max(len(tail) - 1 - cut - 1, 0):]
        if len(tail) < 3:
            continue
        q = np.linspace(0, 1, 24)
        idx = q * (len(tail) - 1)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, len(tail) - 1)
        f = (idx - lo)[:, None]
        spine = tail[lo] * (1 - f) + tail[hi] * f  # de la cola a la extremidad
        # Exagerada como en las referencias: el recorrido 1,5 veces más largo hacia atrás, con la
        # misma forma y la cabeza pegada a la extremidad.
        spine = spine[-1] + (spine - spine[-1]) * TRAIL_EXAGGERATION
        widths = (0.03 + 0.4 * q ** 1.2) * unit * grow  # fina en la cola, ancha en la extremidad
        cel(layer, ribbon(spine, widths, frame_index, 5.0, k * 2.3), color, alpha, runtime)
    return []


def transfer_fire(body, limbs, frame_index: int, scale: float, layer, color, alpha: float, runtime, st: dict) -> dict[str, float]:
    """Continuidad del fuego (glowing/video_51, seg. 0,5, 2,0 y 3,5): si hace poco el fuego estaba
    en otras extremidades (una mano, las manos, los pies, la cabeza), no aparece de la nada en
    estas: la llama de origen se achica y el fuego viaja en TRANSFER_FRAMES cuadros.

    - Cerca (de mano a mano, de la cabeza a la mano): se deshace en trocitos alargados que se
      enroscan como serpientes chicas alrededor del camino (en perspectiva: más chicos al pasar
      por detrás) y se vuelven a juntar en el destino.
    - Lejos (de las manos a los pies en una voltereta): se desintegra en el origen y un swoosh
      corto lo transporta, soltando trocitos.

    Devuelve, por extremidad, cuánto está prendido el fuego (0 mientras viaja hacia ella, 1 al
    llegar; la que ya lo tenía, 1)."""
    key = getattr(body, "prefix", "") or "person"
    last = _FIRE_LIMBS.get(key)
    if last is not None and (frame_index < last[2] or frame_index - last[2] > TRANSFER_WINDOW):
        last = None  # otro video, volvió atrás o fue hace mucho
    if "from" not in st:
        st["from"] = last[1] if last is not None and set(last[0]) != set(limbs) else None
        st["start"] = frame_index
    note_fire(body, limbs, frame_index)
    lit = {name: 1.0 for name in limbs}
    if not st["from"]:
        return lit
    p = (frame_index - st["start"]) / TRANSFER_FRAMES
    if p >= 1.0:
        return lit
    unit = _unit(scale, layer)
    sources = list(st["from"].values())
    for k, name in enumerate(limbs):
        target = _limb_point(body, name)
        if target is None:
            continue
        source = min(sources, key=lambda x: float(np.linalg.norm(x - target)))
        chord = target - source
        dist = float(np.linalg.norm(chord))
        if dist < 0.3 * unit:
            continue  # ya tenía el fuego (de las dos manos a una de ellas)
        lit[name] = float(np.clip((p - 0.75) / 0.25, 0.0, 1.0))
        side = np.array([-chord[1], chord[0]]) / max(dist, 1e-6)
        hips = body.mid("left_hip", "right_hip")
        if hips is not None and float(np.dot(side, source - hips)) < 0:
            side = -side  # combado hacia afuera del cuerpo, no por encima

        def path(t, source=source, chord=chord, side=side, dist=dist):
            t = np.asarray(t, dtype=np.float64)
            return source + np.outer(t, chord) + np.outer(np.sin(np.pi * t) * 0.3 * dist, side)

        if p < 0.3:  # la llama de origen se achica
            shrink = 1.0 - p / 0.3
            cel(layer, teardrop(source, np.array([0.0, -1.0]), 0.5 * unit * shrink, 0.12 * unit * shrink + 0.5, frame_index, 3.1 + k), color, alpha, runtime)
        if dist > TRANSFER_SWOOSH * unit:
            # Lejos: un swoosh corto lleva el fuego; la cabeza avanza y la cola la sigue.
            head = float(np.clip((p - 0.15) / 0.65, 0.0, 1.0))
            if head > 0.05:
                spine = path(np.linspace(max(head - 0.35, 0.0), head, 18))
                q = np.linspace(0, 1, 18)
                widths = (0.02 + 0.14 * q ** 1.2) * unit
                cel(layer, ribbon(spine, widths, frame_index, 5.0, 2.7 + k), color, alpha, runtime)
                shed(layer, spine, widths, st, frame_index, scale, color, alpha, 2.0)
            for i in range(5):  # al salir se desintegra: trocitos que se dispersan del origen
                t = float(np.clip(p / 0.4, 0.0, 1.0))
                if 0 < t < 1:
                    a = i * TAU / 5 + 0.7
                    out = np.array([np.cos(a), np.sin(a)])
                    cel(layer, teardrop(source + out * unit * 0.4 * t, -out, 0.1 * unit * (1 - t), 0.025 * unit + 0.5, frame_index, i * 1.3, 0.5), color, alpha, None)
            continue
        # Cerca: trocitos alargados que se enroscan alrededor del camino y se juntan al llegar.
        pieces = 9
        for i in range(pieces):
            t = float(np.clip((p - 0.12 - i * 0.04) / 0.55, 0.0, 1.0))
            if not 0.0 < t < 1.0:
                continue
            a = t * TAU * 1.5 + i * TAU / pieces
            radius = 1.4 * unit * np.sin(np.pi * t) * (0.6 + 0.4 * np.sin(i * 2.3))  # se dispersan alrededor del cuerpo y se juntan (video_51, seg. 0,5)
            depth = 0.7 + 0.3 * np.sin(a)  # por detrás, más chicos
            pos = path([t])[0] + side * np.cos(a) * radius
            ahead = path([min(t + 0.05, 1.0)])[0] + side * np.cos(a + 0.4) * radius - pos
            ahead /= max(float(np.linalg.norm(ahead)), 1e-6)
            # Alargados y apenas enroscados en la punta (con más vuelta se cerraban en bolitas).
            curl = 0.18 * (1 if i % 2 else -1)
            cel(layer, teardrop(pos, -ahead, 0.6 * unit * depth, 0.06 * unit * depth + 0.5, frame_index, i * 2.1 + k, curl), color, alpha * depth, None)
    return lit


def _hand_fire(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = -down
    note_fire(body, HANDS, frame_index)  # el fuego está en las manos (para el traspaso)
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2))
    sides = [event.kind] if event is not None and event.kind in ("left", "right") else ["left", "right"]
    for k, side in enumerate(sides):
        wrist = body.get(f"{side}_wrist")
        if wrist is None:
            continue
        st = _activation(runtime, event, f"hand:{side}", body)
        u = _phase(runtime, event)
        # Gota: base ancha y redonda que envuelve el puño, cuerpo que se angosta con bordes
        # caóticos (proporción ~2,3:1).
        tall, half = 1.15 * scale, 0.25 * scale
        other = body.get(f"{'right' if side == 'left' else 'left'}_wrist")
        if len(sides) == 2 and other is not None and float(np.linalg.norm(other - wrist)) < MERGE_GAP * scale:
            # Manos juntas: una sola gota que sale de entre las dos (no dos llamas encimadas).
            if side == "right":
                continue
            wrist, other, half = (wrist + other) / 2, None, half * 1.1
        base = wrist - up * half * 0.6
        # Física: viento relativo, inercia, estiramiento, centrífuga alrededor del cuerpo y atracción
        # hacia la otra llama cercana.
        lean, stretch = flame_physics(st, "phys", wrist, scale, up, pivot=center + down * 0.5 * scale, partner=other)
        trail = st.setdefault("trail", [])
        if trail and float(np.linalg.norm(base - trail[-1])) > 0.5 * scale:
            trail.clear()  # salto del detector: la estela empieza de nuevo
        trail.append(base.copy())
        del trail[:-8]
        speed = float(np.linalg.norm(st["phys"].get("v", np.zeros(2))))
        swoosh = float(np.clip((speed - 0.05) / 0.15, 0.0, 1.0))  # mano rápida: la llama se vuelve estela
        tall, half = tall * stretch, half / np.sqrt(stretch)
        for j, (spine, widths) in enumerate(flame_parts(base, lean, tall, half, frame_index, k * 1.7 + 0.3, trail, swoosh)):
            living_ribbon(layer, spine, widths, u, st.setdefault(f"part{j}", {}), frame_index, color, alpha, runtime if j == 0 else None, grow_from_end=False, tongues=3.0, phase=k * 1.7 + j)
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
    lean, stretch = flame_physics(_activation(runtime, event, "candle", body), "phys", base, scale, up)
    cel(layer, teardrop(base, lean, 1.1 * scale * size * stretch, 0.2 * scale * size / np.sqrt(stretch) + 1, frame_index), color, alpha, runtime)
    return []


# ----- formas de video_51: chorro, alfombra y aro grande -----


def _unit(scale: float, layer) -> float:
    """Unidad de las formas grandes: la escala del cuerpo, pero no menos del 7% del alto del
    cuadro. En video_51 la persona ocupa poco del cuadro (y agachada o de perfil sus hombros miden
    casi nada), y el fuego igual cruza la pantalla: se dibuja en proporción al cuadro."""
    return max(float(scale), 0.07 * layer.shape[0])


def _fire_blast(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    """Chorro de fuego desde el puño (video_51, seg. 3,0 y 3,6): sale en la dirección del
    antebrazo, se abre hacia la punta, sube un poco al final (el aire caliente) y termina en
    lenguas que se enroscan."""
    found = _wrist(body, event, scale)
    if found is None:
        return []
    name, wrist = found
    st = _activation(runtime, event, f"blast:{name}", body)
    elbow = body.get(name.replace("wrist", "elbow").replace("ankle", "knee"))
    if elbow is not None and float(np.linalg.norm(wrist - elbow)) > 0.2 * scale:
        aim = (wrist - elbow) / float(np.linalg.norm(wrist - elbow))
        old = st.get("aim")
        aim = aim if old is None else old * 0.7 + aim * 0.3  # el chorro sigue al brazo con inercia
        st["aim"] = aim / max(float(np.linalg.norm(aim)), 1e-6)
    aim = st.get("aim")
    if aim is None:
        return []
    u = _phase(runtime, event)
    scale = _unit(scale, layer)
    side = np.array([-aim[1], aim[0]])
    length = 3.8 * scale
    q = np.linspace(0, 1, 36)
    wave = _smooth_noise(q * 3.0 - frame_index * 0.2, 3.0) * 0.1 * length * q
    spine = wrist + np.outer(q * length, aim) + np.outer(wave, side) + np.outer(q ** 2 * 0.22 * length, [0.0, -1.0])
    widths = (0.04 + 0.7 * q ** 0.9 * (1.0 - 0.45 * q ** 4)) * scale
    living_ribbon(layer, spine, widths, u, st, frame_index, color, alpha, runtime, grow_from_end=False, tongues=6.0, phase=1.3)
    if u < DIE_START:
        grow = _ease_out(u / GROW_END)
        tip = spine[-1]
        for j, turn in enumerate((-0.9, -0.45, 0.0, 0.45, 0.9)):  # la punta se abre en abanico de lenguas
            d = aim * np.cos(turn) + side * np.sin(turn) + np.array([0.0, -0.5])
            d /= float(np.linalg.norm(d))
            base = tip - aim * 0.2 * length + side * (j - 2) * 0.28 * scale
            tall = (1.1 - 0.25 * abs(j - 2)) * scale * grow
            cel(layer, teardrop(base, d, tall, 0.17 * scale * grow + 0.5, frame_index, j * 2.1, 0.35 * np.sign(turn or 1.0)), color, alpha, runtime)
        shed(layer, spine, widths, st, frame_index, scale, color, alpha, 1.5)
    rim(layer, runtime, [wrist, spine[len(spine) // 3]], scale, color, alpha)
    return []


def _fire_carpet(body, scale, frame_index, runtime, layer, color, alpha, event, u: float | None = None, size: float = 1.0) -> list:
    """Alfombra de fuego en el piso (video_51, seg. 2,7): gotas gordas en gancho repartidas al azar
    sobre una elipse del piso alrededor de los pies, todas inclinadas hacia el mismo lado y más
    grandes cuanto más cerca de la cámara (más abajo en el cuadro). Al encimarse forman una masa
    irregular, y los espacios entre ellas son los huecos por donde se ve el piso."""
    floor = _floor(body, scale)
    feet = [p for p in (body.get(j) for j in ("left_ankle", "right_ankle")) if p is not None]
    if floor is None or not feet:
        return []
    st = _activation(runtime, event, "carpet", body)
    if "x" not in st:
        st["x"] = float(np.mean([f[0] for f in feet]))
        st["lean"] = 1.0 if (st["x"] < layer.shape[1] / 2) else -1.0  # hacia el centro del cuadro
    u = _phase(runtime, event) if u is None else u
    scale = _unit(scale, layer) * size
    grow = _ease_out(u / GROW_END) if u < DIE_START else 1.0
    rng = np.random.default_rng(int(st["x"]) * 7 + 3)
    count = 22
    # Puntos al azar en la elipse (más densos cerca de los pies), ordenados de atrás hacia adelante.
    r = np.sqrt(rng.random(count)) * (0.35 + 0.65 * grow)
    t = rng.uniform(0, TAU, count)
    xs = st["x"] + np.cos(t) * r * 4.6 * scale
    ys = floor + np.sin(t) * r * 1.0 * scale + 0.3 * scale
    for j in np.argsort(ys):
        depth = 0.75 + 0.45 * float(np.sin(t[j]) * r[j])  # adelante (más abajo), más grande
        near = 1.0 - float(r[j])
        tall = (2.6 + 3.8 * near) * depth * scale * grow * (0.6 + 0.6 * rng.random())
        tall *= 1.0 + 0.15 * _smooth_noise(np.array([frame_index * 0.12 + j * 1.7]), 5.0)[0]
        d = np.array([0.35 * st["lean"], -1.0])
        d /= float(np.linalg.norm(d))
        curl = (0.25 + 0.25 * rng.random()) * st["lean"]
        cel(layer, teardrop(np.array([xs[j], ys[j]]), d, tall, (0.3 + 0.18 * rng.random()) * depth * scale, frame_index, j * 1.1, curl), color, alpha, runtime, 0.4)
    return []


ORBIT_END = 0.55  # fracción de la vida en que el fuego termina la vuelta y vuelve a la mano
ARM_STRAIGHT = 0.85  # brazo estirado: muñeca-hombro más que esto del largo del brazo


def _arm_extended(body, side: str) -> bool:
    """Si el brazo está estirado (puñetazo o mano abierta hacia afuera): la muñeca lejos del
    hombro, casi el largo entero de brazo y antebrazo."""
    shoulder, elbow, wrist = (body.get(f"{side}_{j}") for j in ("shoulder", "elbow", "wrist"))
    if shoulder is None or elbow is None or wrist is None:
        return False
    length = float(np.linalg.norm(elbow - shoulder) + np.linalg.norm(wrist - elbow))
    return float(np.linalg.norm(wrist - shoulder)) > ARM_STRAIGHT * max(length, 1e-6)


def _fire_orbit(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    """El fuego que gira alrededor del cuerpo (video_51, seg. 4,0-4,7): sale de la mano y da una
    vuelta en elipse alrededor del torso, en perspectiva (por delante más grande y brillante, por
    detrás más chico y tenue), como una cola de trocitos que se persiguen. Al completar la vuelta
    vuelve a la mano (la atrapa) y queda una llama. Si después el brazo se estira (un puñetazo o
    la mano abierta hacia afuera), el fuego sale como una explosión en la dirección del antebrazo;
    si no, la llama se apaga en la mano."""
    center, across, down = frame
    up = -down
    found = _wrist(body, event, scale)
    if found is None:
        return []
    name, wrist = found
    side_name = name.split("_")[0]
    st = _activation(runtime, event, f"orbit:{name}", body)
    u = _phase(runtime, event)
    unit = _unit(scale, layer)
    hips = body.mid("left_hip", "right_hip")
    # A la altura del pecho (la referencia gira el fuego a la altura de los brazos).
    mid = center + ((hips - center) * 0.3 if hips is not None else down * 0.3 * scale)
    rx, ry = 1.4 * unit, 0.4 * unit  # la elipse, vista un poco desde arriba
    start = float(np.arctan2((wrist - mid)[1] / ry, (wrist - mid)[0] / rx))
    st.setdefault("a0", start)
    if u < ORBIT_END:
        k = _ease(u / ORBIT_END)
        head = st["a0"] + TAU * k  # la cabeza de la cola da una vuelta completa
        for i in range(8):
            a = head - i * 0.22
            depth = 0.5 + 0.5 * np.sin(a)  # 1 por delante (abajo de la elipse), 0 por detrás
            pos = mid + np.array([np.cos(a) * rx, np.sin(a) * ry])
            if k < 0.12:  # al salir, la cola nace desde la mano
                pos = wrist + (pos - wrist) * (k / 0.12)
            if k > 0.88:  # al volver, se cierra sobre la mano
                pos = pos + (wrist - pos) * ((k - 0.88) / 0.12)
            ahead = np.array([-np.sin(a) * rx, np.cos(a) * ry])
            ahead /= max(float(np.linalg.norm(ahead)), 1e-6)
            size = (0.75 - 0.06 * i) * unit * (0.55 + 0.45 * depth)
            cel(layer, teardrop(pos, -ahead, size, 0.18 * unit * (0.55 + 0.45 * depth) + 0.5, frame_index, i * 1.7, 0.25), color, alpha * (0.6 + 0.4 * depth), runtime if i == 0 else None)
        return []
    # La atrapó: la llama en la mano, hasta que el brazo se estira y la lanza.
    if not st.get("thrown") and _arm_extended(body, side_name):
        st["thrown"] = frame_index
    if st.get("thrown") is None:
        fade = 1.0 - _seg(u, 0.85, 1.0)
        cel(layer, teardrop(wrist, up, 0.8 * unit * fade, 0.2 * unit * fade + 0.5, frame_index, 2.2), color, alpha, runtime)
        return []
    # La explosión: el chorro desde el puño y un estallido de lenguas y brasas en la punta.
    age = frame_index - st["thrown"]
    _fire_blast(body, scale, frame_index, runtime, layer, color, alpha, event)
    blast = st.get("blast")
    if blast is None:
        elbow = body.get(f"{side_name}_elbow")
        aim = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6) if elbow is not None else across
        blast = st["blast"] = wrist + aim * 3.0 * unit
    burst = _ease(min(age / 5.0, 1.0)) * (1.0 - _seg(u, 0.9, 1.0))
    if burst > 0:
        for i in range(10):  # lenguas que se abren en todas direcciones
            a = i * TAU / 10 + 0.3
            d = np.array([np.cos(a), np.sin(a)])
            cel(layer, teardrop(blast + d * unit * 0.3 * burst, d, 0.9 * unit * burst, 0.16 * unit * burst + 0.5, frame_index, i * 1.1, 0.35), color, alpha, runtime if i == 0 else None)
    return []


LANDING_FEET_S = 1.0  # el fuego tenía que estar en los pies hace menos de esto


def _fire_landing(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    """El fuego que se desbarata al caer (video_51, seg. 2,4-2,7): si hace poco el fuego iba en los
    pies (una voltereta), al tocar el piso choca y se deshace en una alfombra chica de lenguas
    alrededor de los pies, que nace en 2-3 cuadros y muere enseguida en trozos (la vida del
    efecto). El fuego queda gastado: lo que siga no lo traspasa. Si no venía de los pies, el golpe
    de piso de siempre."""
    st = _activation(runtime, event, "landing", body)
    key = getattr(body, "prefix", "") or "person"
    if "feet" not in st:
        last = _FIRE_LIMBS.get(key)
        st["feet"] = bool(last is not None and any(n.endswith("_ankle") for n in last[0]) and 0 <= frame_index - last[2] <= runtime.fps * LANDING_FEET_S)
        if st["feet"]:
            _FIRE_LIMBS.pop(key, None)  # el fuego se gastó en el piso
    if not st["feet"]:
        from vfxglow.engine.fire_creatures import _fire_splash

        return _fire_splash(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return _fire_carpet(body, scale, frame_index, runtime, layer, color, alpha, event, size=0.8)


# Cierres del fuego en el piso: la pared (si se enciende) gana y la alfombra no sale.
_CLOSING: dict = {"wall": (0, -99)}  # (largo del video, último cuadro con pared): no se cruza entre videos
CARPET_FRONT_S = 2.0  # segundos seguidos de frente para que salga la alfombra del cierre
CARPET_WINDOW_S = 1.8  # solo en los últimos segundos del video (como la pared)...
CARPET_WINDOW_FRAC = 0.2  # ...y nunca más de esta fracción del video (en uno corto quedaba a la mitad)


def closing_frames(total: int, fps: float) -> int:
    """Cuadros del cierre del fuego en el piso (alfombra o pared) en un video de `total` cuadros."""
    return int(min(CARPET_WINDOW_S * fps, CARPET_WINDOW_FRAC * total))


def _carpet_end(body, scale, frame_index, runtime, layer, color, alpha) -> list:
    """La alfombra como cierre: cuenta cuántos cuadros seguidos la persona mira de frente y, en el
    tramo final (closing_frames), si esa racha pasa de CARPET_FRONT_S, nace desde el borde de
    abajo del cuadro, sube y queda encendida hasta el último cuadro (no muere)."""
    from vfxglow.engine.bodyglow import facing

    st = runtime.swoosh.setdefault("_carpetend", {})
    if st.get("frame") == frame_index:  # una sola alfombra por cuadro, aunque haya dos personas
        return []
    if st.get("frame") is not None and frame_index < st["frame"]:  # otro video o volvió atrás
        st.clear()
    if frame_index - st.get("frame", frame_index) > 3:  # sin persona varios cuadros: la racha se corta
        st["streak"] = 0
    st["frame"] = frame_index
    st["streak"] = st.get("streak", 0) + 1 if facing(body) == "front" else 0
    total = runtime.frame_count
    if total <= 0 or frame_index < total - closing_frames(total, runtime.fps):
        return []
    if "start" not in st:
        wall_total, wall_frame = _CLOSING["wall"]
        if st["streak"] < CARPET_FRONT_S * runtime.fps or (wall_total == total and wall_frame >= frame_index - 1):
            return []
        st["start"] = frame_index
    s = _ease(min((frame_index - st["start"]) / max(total - st["start"] - 1, 1), 1.0))
    height, width = layer.shape[:2]
    # Desde el borde de abajo del cuadro hacia arriba (no en el piso de la persona, que puede estar
    # a media altura): dos filas de lenguas en gancho a lo ancho, la de atrás más alta y fina.
    rise = height * (0.06 + 0.24 * s)
    base_y = height + 2
    lean = 1.0 if st.setdefault("lean", 1.0 if frame_index % 2 else -1.0) > 0 else -1.0
    rng = np.random.default_rng(29)
    for row, (lift, size, count) in enumerate(((0.35, 0.75, 8), (0.0, 1.0, 9))):
        for j in range(count):
            x = width * (j + 0.5 + rng.uniform(-0.25, 0.25)) / count
            tall = rise * size * rng.uniform(0.6, 1.0) * (0.9 + 0.12 * _smooth_noise(np.array([frame_index * 0.08 + j + row * 3]), 6.0)[0])
            d = np.array([0.35 * lean, -1.0])
            d /= float(np.linalg.norm(d))
            thin = min(tall * rng.uniform(0.25, 0.35), width / count * 0.6)
            curl = (0.25 + 0.25 * rng.random()) * lean
            cel(layer, teardrop(np.array([x, base_y - rise * lift]), d, tall, thin, frame_index, row * 11 + j * 1.3, curl), color, alpha, runtime, 0.6)
    band = np.array([[-0.05 * width, base_y - rise * 0.15], [1.05 * width, base_y - rise * 0.15], [1.05 * width, base_y + 2], [-0.05 * width, base_y + 2]])
    cel(layer, lambda k: band, color, alpha * 0.8, None, mass=True)  # la base, pegada al borde
    return []


def _fire_halo(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    """Aro grande de fuego alrededor del cuerpo (video_51, seg. 2,4): nace en un pie, sube por un
    lado, pasa sobre la cabeza y baja por el otro, abierto arriba de un lado; lenguas hacia afuera."""
    joints = [p for p in (body.get(j) for j in ("nose", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_ankle", "right_ankle")) if p is not None]
    if len(joints) < 3:
        return []
    st = _activation(runtime, event, "halo", body)
    u = _phase(runtime, event)
    # El centro del cuerpo, con inercia; el tamaño sale de la escala (en una voltereta la nariz y
    # los pies no dicen dónde está arriba).
    now = np.mean(joints, axis=0)
    st["mid"] = now if "mid" not in st else st["mid"] * 0.8 + now * 0.2
    mid = st["mid"]
    scale = _unit(scale, layer)
    ry = min(3.8 * scale, 0.33 * layer.shape[0])  # en video_51, un tercio del alto del cuadro
    rx = ry * 0.68
    turn = st.setdefault("turn", 1.0 if frame_index % 2 else -1.0)
    a = np.pi / 2 + turn * np.linspace(0.15, 0.15 + 1.7 * np.pi, 48)  # de abajo, 306° de vuelta
    spine = mid + np.stack([np.cos(a) * rx, np.sin(a) * ry], axis=1)
    q = np.linspace(0, 1, 48)
    widths = (0.03 + 0.6 * np.sin(np.pi * q) ** 0.7) * scale
    if float(np.mean(np.sum(_normals(spine) * (spine - mid), axis=1))) < 0:  # lenguas hacia afuera
        spine, widths = spine[::-1], widths[::-1]
        grow_from_end = True
    else:
        grow_from_end = False
    living_ribbon(layer, spine, widths, u, st, frame_index, color, alpha, runtime, grow_from_end=grow_from_end, tongues=8.0, phase=2.7)
    if u < DIE_START:
        shed(layer, spine, widths, st, frame_index, scale, color, alpha, 1.5)
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


def _arrow_path(body, frame, scale) -> tuple[np.ndarray, bool, float] | None:
    """La línea de la flecha de Aang sobre el cuerpo, de la frente hacia atrás: sube por la frente,
    pasa por la coronilla, baja por la nuca y sigue por la columna. Devuelve (puntos, si la punta
    de la frente se ve, ancho de la cabeza). De frente se ve el tramo de la frente a la coronilla;
    de perfil, el arco sobre la cabeza hasta la nuca; de espaldas, de la coronilla a la columna."""
    from vfxglow.engine.bodyglow import facing

    face = _face(body, frame, scale)
    if face is None:
        return None
    nose, r, up, across = face
    center, _across, down = frame
    ears = [e for e in (body.get("left_ear"), body.get("right_ear")) if e is not None]
    head = np.mean(ears, axis=0) if ears else nose - up * 0.1 * r
    hips = body.mid("left_hip", "right_hip")
    back = [center + down * 0.1 * scale]
    if hips is not None:
        back.append(center + (hips - center) * 0.8)  # hasta la parte baja de la espalda
    neck = center - down * 0.12 * scale
    crown = head + up * 0.95 * r
    side = facing(body)
    eyes = [body.get("left_eye"), body.get("right_eye")]
    if side == "front" and all(e is not None for e in eyes):
        # El eje de la cara sale de los ojos (no del torso, que se inclina): la punta, centrada
        # justo arriba de los ojos; la banda sube hasta la coronilla.
        mid, gap = (eyes[0] + eyes[1]) / 2, float(np.linalg.norm(eyes[0] - eyes[1]))
        face_up = np.array([eyes[1][1] - eyes[0][1], eyes[0][0] - eyes[1][0]]) / max(gap, 1e-6)
        if float(np.dot(face_up, mid - nose)) < 0:
            face_up = -face_up
        gap = max(gap, 0.3 * r)
        forehead = mid + face_up * 0.3 * gap
        q = np.linspace(0, 1, 12)[:, None]
        return forehead + face_up * 1.9 * gap * q, True, gap * 1.6
    if side == "front":
        forehead = nose + up * 0.55 * r
        q = np.linspace(0, 1, 12)[:, None]
        return forehead + (crown - forehead) * q, True, r
    if side == "back":
        nape = head - up * 0.35 * r
        pts = [crown, head + up * 0.4 * r, nape, neck] + back
        return _resample(np.array(pts), 40), False, r
    # De perfil: un arco desde la frente sobre el cráneo hasta la nuca, y la columna.
    ahead = nose - head
    ahead = ahead - up * float(np.dot(ahead, up))
    ahead = ahead / max(float(np.linalg.norm(ahead)), 1e-6)
    a = np.linspace(0.25, np.pi - 0.15, 16)  # de adelante (frente) a atrás (nuca), por arriba
    arc = head + np.outer(np.cos(a), ahead) * 0.9 * r + np.outer(np.sin(a), up) * 0.95 * r
    # La columna no: de perfil queda sobre el borde de la espalda y, dibujada por el centro del
    # torso, cruzaba el cuerpo. Termina en la nuca.
    pts = np.vstack([arc, [head - ahead * 0.75 * r - up * 0.45 * r]])
    return _resample(pts, 24), True, r


def _resample(pts: np.ndarray, n: int) -> np.ndarray:
    """La polilínea con `n` puntos a distancias iguales (curva suave para la banda)."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    d = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0, d[-1], n)
    return np.stack([np.interp(t, d, pts[:, 0]), np.interp(t, d, pts[:, 1])], axis=1)


def _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    found = _arrow_path(body, frame, scale)
    if found is None:
        return []
    path, tip, r = found
    # La flecha de Aang: una banda angosta que corre por el centro de la cabeza y la espalda y, en
    # la frente, termina en punta hacia la cara.
    normal = _normals(path)
    w = 0.1 * r
    band = np.vstack([path + normal * w, (path - normal * w)[::-1]])
    fill_polygon(layer, band, CORE, alpha, 1.6, feather=1.0)
    shapes = [band]
    if tip:
        forehead = path[0]
        ahead = path[1] - path[0]
        ahead = ahead / max(float(np.linalg.norm(ahead)), 1e-6)  # de la frente hacia la coronilla
        side = np.array([-ahead[1], ahead[0]])
        # Punta ancha (casi el ancho de la frente) apuntando a la cara, como en la referencia.
        head = np.array([forehead + ahead * 0.36 * r + side * 0.36 * r, forehead, forehead + ahead * 0.36 * r - side * 0.36 * r])
        fill_polygon(layer, head, CORE, alpha, 1.6, feather=1.0)
        shapes.append(head)
        warm(layer, forehead, 1.2 * r, np.asarray(color, np.float32), alpha * 0.25)
        _glowing_eyes(body, layer, r, alpha, runtime)
    else:
        warm(layer, path[len(path) // 3], 1.6 * r, np.asarray(color, np.float32), alpha * 0.35)
    return shapes


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
            for q in (0.6,):  # una llama por hueso (con tres se volvía una maraña)
                k += 1
                base = a_ + (b_ - a_) * q
                size = (0.45 + 0.35 * np.sin(k * 2.3) ** 2) * scale * grow
                lean, stretch = flame_physics(_activation(runtime, event, "blaze", body), f"bone{k}", base, scale, up)
                cel(layer, teardrop(base, lean, size * stretch, 0.13 * scale / np.sqrt(stretch), frame_index, k * 0.9), color, alpha, runtime, 0.5)
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
    length = min(int(max(runtime.effect.style.size, 0.5) * runtime.fps), closing_frames(total, runtime.fps))
    if total <= 0 or frame_index < total - length:
        return []
    if "front" not in st:
        # Solo si la persona mira de frente al empezar el cierre (la pared enmarca a quien mira a
        # cámara; de espaldas o de perfil no). Se decide una vez y se mantiene.
        from vfxglow.engine.bodyglow import facing

        st["front"] = facing(body) == "front"
    if not st["front"]:
        return []
    _CLOSING["wall"] = (total, frame_index)  # la alfombra del cierre cede
    s = _ease((frame_index - (total - length)) / max(length - 1, 1))
    height, width = layer.shape[:2]
    rise = height * (0.08 + 0.32 * s)  # hasta el 40% del cuadro: no tapa a la persona
    base_y = height + 2
    alpha = max(float(alpha), st.get("peak", 0.0))  # sin fundido al final: se notaban las piezas
    st["peak"] = alpha
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
# Tinte de capítulo (glowing/video_51): mientras hay un elemento en pantalla, todo el cuadro toma
# su color, como una gelatina sobre la luz. Medido como multiplicador lineal (RGB) de las partes
# claras del fondo (pared): el fuego deja el rojo y baja verde y azul; el rayo casi apaga el rojo.
ELEMENT_TINT = {
    "fire": np.array([1.0, 0.5, 0.26], np.float32),
    "bolt": np.array([0.18, 0.66, 1.05], np.float32),
}


def note_bolt(frame_index: int) -> None:
    """Un rayo dibujado en este cuadro: el plano se tiñe de cian (lo lee fire_light)."""
    _LIGHTS["bolt"] = frame_index


def bolt_active(frame_index: int) -> bool:
    """Si hubo un rayo en este cuadro o en el anterior (el capítulo es de rayo, no de fuego)."""
    return _LIGHTS.get("bolt", -99) >= frame_index - 1


def note_wind(frame_index: int) -> None:
    """Un viento dibujado en este cuadro (el capítulo es de aire, no de fuego)."""
    _LIGHTS["wind"] = frame_index


def other_element_active(frame_index: int) -> bool:
    """Si en este cuadro (o el anterior) hay rayo o viento: las brasas del fuego no salen."""
    return bolt_active(frame_index) or _LIGHTS.get("wind", -99) >= frame_index - 1


def _chapter_tint(st: dict, frame_index: int, fire: bool, strength: float) -> np.ndarray | None:
    """Multiplicador uniforme del cuadro según qué elementos hay: entra en ~3 cuadros y sale en
    ~8 (no parpadea entre un golpe y el siguiente)."""
    seen = {"fire": fire, "bolt": _LIGHTS.get("bolt", -99) >= frame_index - 1}
    mult = np.ones(3, np.float32)
    for kind, on in seen.items():
        p = st.get(kind, 0.0)
        p += ((1.0 if on else 0.0) - p) * (0.35 if on else 0.12)
        st[kind] = p
        mult *= 1.0 + np.float32(p * strength) * (ELEMENT_TINT[kind] - 1.0)
    return None if float(np.abs(mult - 1.0).max()) < 0.01 else mult


def _fire_light(runtime, layer, frame_index: int, alpha: float) -> list:
    st = runtime.swoosh.setdefault("_firelight", {})
    if st.get("frame") == frame_index:  # una vez por cuadro aunque haya dos personas
        return []
    st["frame"] = frame_index
    note_frame(frame_index)
    lights = _LIGHTS["prev"] + _LIGHTS["now"]
    # style.size: fuerza del tinte de capítulo (0 = solo la luz local, 1 = el de video_51).
    chapter = _chapter_tint(st, frame_index, bool(lights), float(runtime.effect.style.size))
    height, width = layer.shape[:2]
    if not lights:
        if chapter is not None:
            layer[..., :3] = chapter * np.float32(alpha)
            layer[..., 3] = np.float32(alpha)
        return []
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
    if chapter is None:
        layer[..., :3] = straight * cover
        layer[..., 3] = cover
        return []
    # Con tinte de capítulo la capa cubre todo: luz local (mezclada según su cobertura) por el tinte.
    a = np.float32(alpha)
    layer[..., :3] = (1.0 + (straight - 1.0) * cover) * chapter * a
    layer[..., 3] = a
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
    if shape == "fire_blast":
        return _fire_blast(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_carpet":
        return _fire_carpet(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_halo":
        return _fire_halo(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_orbit":
        return _fire_orbit(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_landing":
        return _fire_landing(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_trail":
        return _fire_trail(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_carpet_end":
        return _carpet_end(body, scale, frame_index, runtime, layer, color, alpha)
    return []
