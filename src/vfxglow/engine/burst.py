"""Impactos en line-art de neón: llamarada, chispas en guiones y gotas.

Todo se dibuja como contorno o trazo fino (no manchas difusas), igual que el swoosh:

- flame_burst: en cada contacto, lenguas de fuego contorneadas que nacen del punto del
  golpe, crecen deprisa, se enroscan y se apagan. Color del atacante, con alguna lengua del
  color del rival para que las dos energías se mezclen.
- spark_dashes: guiones cortos que salen disparados del contacto y caen con gravedad.
- droplets: en algunos puñetazos rápidos el puño suelta partículas contorneadas. Cada golpe
  elige una forma de `style.shapes`: gota (cae como lluvia), anillo y hoja de fuego (suben
  como brasas), rizo (deriva girando) o guion (sale disparado).

Las tres usan el torso como unidad de tamaño, así que no dependen de la resolución.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np

from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.engine.anchors import joint_speed, resolve_anchor, torso_pixels
from vfxglow.engine.raster import fill_polygon, stroke_batch
from vfxglow.engine.swoosh import focused, neon_layers, swoosh_keys
from vfxglow.engine.firebend import other_element_active

TAU = 2.0 * np.pi
# Fracción de la vida de la llamarada en la que alcanza su tamaño completo.
GROW = 0.3
# Gotas en pantalla a la vez y nuevas por fotograma: pocas y pequeñas para no saturar el plano.
DROPLET_LIMIT = 40
DROPLETS_PER_FRAME = 2
BIG_EVERY = 4
BIG_PER_STROKE = 4
# Topes de tamaño como fracción de la altura del cuadro (llamarada y partícula).
MAX_BURST = 0.12
MAX_BIT = 0.012
SPARK_LIMIT = 80


@dataclass
class Bit:
    """Partícula de line-art: gota, anillo, hoja, rizo o guion."""

    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    color: int
    shape: str = "dash"
    gravity: float = 1.0
    spin: float = 1.0


# Forma -> (gravedad relativa: negativa sube, fracción de la velocidad de la mano que hereda).
# Corchea doble (♫): dos cabezas unidas por una barra (video_34, seg. 5,3-6,1).
SHAPES_EXTRA = ("beamed",)
SHAPES: dict[str, tuple[float, float]] = {
    "beamed": (0.0, 0.0),
    "drop": (1.0, 0.55),
    "ring": (-0.12, 0.3),
    "leaf": (-0.25, 0.3),
    "curl": (-0.1, 0.35),
    "dash": (0.5, 0.9),
    "heart": (-0.15, 0.3),
    "note": (-0.18, 0.35),
    # Objetos de temporada (engine/season.py): murciélagos y fantasmas suben, calabazas caen.
    "bat": (-0.35, 0.45),
    "pumpkin": (0.6, 0.5),
    "ghost": (-0.4, 0.25),
    "skull": (0.4, 0.45),
    "marigold": (-0.05, 0.3),
    "flake": (0.12, 0.2),
    "ornament": (0.7, 0.4),
    "star": (-0.2, 0.3),
    "spider": (0.8, 0.3),
}


def person_index(person_id: str | None) -> int:
    if not person_id:
        return 0
    tail = person_id.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _palette(style, index: int) -> np.ndarray:
    return np.asarray(style.colors[index % len(style.colors)], dtype=np.float32)


def _neon(curve: np.ndarray, color: np.ndarray, width: float, alpha: float) -> list:
    return neon_layers(curve, color, width, alpha)


# ----- llamarada -----


def draw_flame_burst(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is None or envelope <= 0 or event is None:
        return
    key = (event.start_frame, event.target)
    if runtime.burst_key != key:
        # Nueva activación: otra forma de llamarada, fija para toda su vida.
        runtime.burst_key = key
        runtime.burst_seed = zlib.crc32(f"{style.seed_offset}:{event.start_frame}:{event.target}".encode()) & 0xFFFFFFFF
    torso = torso_pixels(points, height)
    # En primeros planos el torso es enorme; el tope evita que la llamarada tape el cuadro.
    radius = min(style.size * torso, MAX_BURST * height)
    grow = float(np.clip(runtime.active_frames / max(effect.triggers[0].hold * GROW, 1.0), 0.0, 1.0)) if effect.triggers else 1.0
    grow = 1.0 - (1.0 - grow) ** 2
    # Line boil: la forma tiembla cada `boil_frames` sin cambiar de identidad.
    boil = frame_index // max(style.boil_frames, 1)
    rng = np.random.default_rng(runtime.burst_seed)
    jitter = np.random.default_rng(runtime.burst_seed + boil * 7919)
    own = person_index(event.attacker)
    rival = person_index(event.receiver) if event.receiver else own + 1
    width = max(1.2, style.thickness * torso)
    hold = effect.triggers[0].hold if effect.triggers else 14
    age = float(np.clip(runtime.active_frames / max(hold, 1), 0.0, 1.0))
    # Las piezas se separan del golpe y suben mientras viven, como brasas que se dispersan.
    drift = radius * 0.5 * age
    rise = np.array([0.0, -radius * 0.45 * age])
    count = 4 + int(rng.integers(0, 3))
    base = float(rng.uniform(0, TAU))
    strokes = []
    for index in range(count):
        angle = base + index * TAU / count + float(rng.normal(0, 0.3))
        direction = np.array([np.cos(angle), np.sin(angle)])
        # Cada lengua nace lejos del centro: pétalos separados, no una maraña sobre el golpe.
        start = origin + direction * (radius * float(rng.uniform(0.22, 0.42)) + drift) + rise
        length = radius * float(rng.uniform(0.35, 0.65)) * grow
        curl = float(rng.choice([-1.0, 1.0]) * rng.uniform(0.4, 1.1))
        tongue = flame_tongue(start, angle, length, length * 0.17, curl, jitter)
        color = _palette(style, rival if index % 3 == 2 else own)
        strokes += _neon(tongue, color, width, envelope)
    # Óvalos sueltos alrededor del golpe.
    theta = np.linspace(0, TAU, 22)
    for _ in range(2):
        angle = float(rng.uniform(0, TAU))
        center = origin + np.array([np.cos(angle), np.sin(angle)]) * radius * float(rng.uniform(0.5, 0.9)) * (0.7 + 0.3 * grow) + rise
        size = radius * float(rng.uniform(0.1, 0.18)) * grow
        tilt = float(rng.uniform(0, np.pi))
        ellipse = np.stack([np.cos(theta) * size, np.sin(theta) * size * 0.65], axis=1)
        rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
        strokes += _neon(center + (ellipse * (1 + jitter.normal(0, 0.05, (22, 1)))) @ rot.T, _palette(style, own), width * 0.8, envelope)
    strokes += micro_sparks(runtime, origin, torso, key, frame_index)
    stroke_batch(layer, strokes, style.hdr_gain)


def flame_tongue(origin: np.ndarray, angle: float, length: float, width: float, curl: float, rng: np.random.Generator) -> np.ndarray:
    """Contorno cerrado de una lengua de fuego: base ancha junto al golpe, punta que se enrosca."""
    s = np.linspace(0.0, 1.0, 18)
    bend = angle + curl * s**2
    radial = 0.12 * length + 0.88 * length * s
    spine = origin + np.stack([np.cos(bend), np.sin(bend)], axis=1) * radial[:, None]
    tangent = np.gradient(spine, axis=0)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-6)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    half = width * np.sin(np.pi * np.clip(s * 0.9 + 0.1, 0, 1)) ** 0.7 * (1 - s) ** 0.35
    half = half * (1 + rng.normal(0, 0.08, len(s)))
    left = spine + normal * half[:, None]
    right = spine - normal * half[:, None]
    return np.vstack([left, right[::-1], left[:1]])


# ----- chispas -----


def draw_spark_dashes(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    effect = runtime.effect
    style = effect.style
    torso = torso_pixels(points, height)
    bits: list[Bit] = runtime.bits
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if event is not None and origin is not None and envelope > 0 and runtime.burst_key != (event.start_frame, event.target):
        runtime.burst_key = (event.start_frame, event.target)
        rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:{event.start_frame}".encode()) & 0xFFFFFFFF)
        color = person_index(event.attacker)
        for _ in range(min(14, SPARK_LIMIT - len(bits))):
            angle = float(rng.uniform(0, TAU))
            speed = torso * float(rng.uniform(0.05, 0.12)) * style.size * 2
            life = float(rng.uniform(8, 16))
            bits.append(Bit(float(origin[0]), float(origin[1]), np.cos(angle) * speed, np.sin(angle) * speed - torso * 0.02, life, life, torso * 0.04, color))
    _step(bits, gravity=torso * 0.006, drag=0.06)
    width = max(1.0, style.thickness * torso * 0.7)
    strokes = []
    for bit in bits:
        tail = np.array([bit.x - bit.vx * 1.6, bit.y - bit.vy * 1.6])
        strokes += _neon(np.array([tail, [bit.x, bit.y]]), _palette(style, bit.color), width, bit.life / bit.max_life)
    stroke_batch(layer, strokes, style.hdr_gain)


# ----- gotas -----


# Chorro (style.stream): una figura cada STREAM_EVERY fotogramas por mano mientras dure el momento
# (video_34, seg. 5,2-6,9 y 19-21: notas y corazones). Las primeras salen pequeñas y las
# siguientes cada vez más grandes (STREAM_RAMP_S); cada una se queda en el camino de la mano y se
# encoge hasta desaparecer.
STREAM_EVERY = 3
STREAM_RAMP_S = 0.5


def _stream(runtime, points, key: str, person: int, point: np.ndarray, velocity, elapsed: int, torso: float, height: int) -> None:
    style = runtime.effect.style
    every = 4 if any(s in ("note", "beamed") for s in style.shapes) else STREAM_EVERY
    if elapsed < 0 or elapsed % every or len(runtime.bits) >= DROPLET_LIMIT:
        return
    prefix = key.rsplit(":", 1)[0] + ":" if ":" in key else ""
    center = points.get(f"{prefix}mid_shoulder")
    out = point - center if center is not None else np.array([0.0, -1.0])
    out = out / max(float(np.linalg.norm(out)), 1e-6)
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:{key}:{elapsed}".encode()) & 0xFFFFFFFF)
    shapes = [name for name in style.shapes if name in SHAPES] or ["drop"]
    shape = shapes[int(rng.integers(0, len(shapes)))]
    gravity, inherit = SHAPES[shape]
    # Corazones: suben hasta los hombros. Notas: quedan casi quietas donde pasó la mano, y al
    # barrer la mano forman la fila (seg. 5,9).
    drift = np.array([0.0, -torso * 0.004]) + rng.normal(0, torso * 0.002, 2)
    life = float(rng.uniform(18, 24))
    ramp = 0.35 + 0.65 * min(elapsed / max(STREAM_RAMP_S * runtime.fps, 1.0), 1.0)
    size = min(torso * style.size * 0.1 * ramp, MAX_BIT * height * max(style.size, 1.0))
    # Sin gravedad: la deriva ya dice hacia dónde van (la de la forma las haría subir o caer).
    runtime.bits.append(Bit(float(point[0]), float(point[1]), float(drift[0]), float(drift[1]), life, life, size, person, shape, 0.0, float(rng.choice([-1.0, 1.0]))))


def draw_droplets(runtime, track: FrameRecord | None, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None = None) -> None:
    """Partículas que suelta una mano rápida. Disparadas por un evento, solo las suelta la persona
    (o la extremidad) del evento."""
    effect = runtime.effect
    style = effect.style
    torso = torso_pixels(points, height)
    bits: list[Bit] = runtime.bits
    joints = [token.strip() for token in effect.target.id.split(",") if token.strip()]
    stream = style.stream and event is not None
    for key, person in swoosh_keys(track, joints):
        point = points.get(key)
        velocity = points.get(f"vel:{key}")
        if stream:
            if point is not None and envelope > 0 and focused(event, key):
                _stream(runtime, points, key, person, point, velocity, frame_index - event.start_frame, torso, height)
            continue
        fast = point is not None and velocity is not None and joint_speed(track, key) >= style.min_speed
        if not fast or not focused(event, key):
            runtime.swoosh_stroke.pop(key, None)
            continue
        # Un golpe empieza cuando la mano supera el umbral; ahí se decide si suelta partículas
        # y de qué forma, una sola para todo el golpe.
        start = runtime.swoosh_stroke.setdefault(key, frame_index)
        seed = zlib.crc32(f"{style.seed_offset}:{key}:{start}".encode()) & 0xFFFFFFFF
        chooser = np.random.default_rng(seed)
        if float(chooser.random()) >= style.chance or envelope <= 0:
            continue
        if event is None and other_element_active(frame_index):
            continue  # las brasas de fuego de siempre no salen durante un rayo o un viento (glowing/video_51)
        shapes = [name for name in style.shapes if name in SHAPES] or ["drop"]
        shape = shapes[int(chooser.integers(0, len(shapes)))]
        gravity, inherit = SHAPES[shape]
        rng = np.random.default_rng(seed + frame_index)
        count = DROPLETS_PER_FRAME
        if style.size > 1.0:
            # Figuras grandes (notas, corazones): pocas y espaciadas, como una ráfaga de 3-4 por
            # mano y golpe, no una nube.
            elapsed = frame_index - start
            if elapsed % BIG_EVERY or elapsed >= BIG_EVERY * BIG_PER_STROKE:
                continue
            count = 1
        for _ in range(min(count, DROPLET_LIMIT - len(bits))):
            spread = rng.normal(0, torso * 0.025, 2)
            life = float(rng.uniform(14, 26))
            # El tope crece con `size` (notas y corazones grandes, como en video_34).
            size = min(torso * style.size * float(rng.uniform(0.05, 0.1)), MAX_BIT * height * max(style.size, 1.0))
            spin = float(rng.choice([-1.0, 1.0]))
            bits.append(
                Bit(
                    float(point[0]),
                    float(point[1]),
                    float(velocity[0] * inherit + spread[0]),
                    float(velocity[1] * inherit + spread[1]),
                    life,
                    life,
                    size,
                    person,
                    shape,
                    gravity,
                    spin,
                )
            )
    _step(bits, gravity=torso * 0.012, drag=0.03)
    width = max(1.0, style.thickness * torso * 0.7)
    strokes = []
    for bit in bits:
        fade = min(1.0, 2.5 * bit.life / bit.max_life)
        if style.stream:
            # Se encoge al envejecer (no se desvanece de golpe).
            fade = 1.0
            full = bit.size
            bit.size = full * max(bit.life / bit.max_life, 0.0) ** 0.7
        lines = bit_outline(bit)
        if style.stream:
            bit.size = full
        for line in lines:
            if style.stream and (bit.shape == "heart" or (bit.shape in ("beamed", "note") and len(line) > 4)):
                # Corazones del chorro: rellenos de blanco con halo del color (video_34, seg. 20).
                fill_polygon(layer, line, np.ones(3, np.float32), fade * 0.9 * max(envelope, 0.0), 1.0, feather=1.5)
            strokes += _neon(line, _palette(style, bit.color), width, fade)
    stroke_batch(layer, strokes, style.hdr_gain * max(envelope, 0.0))


def bit_outline(bit: Bit) -> list[np.ndarray]:
    """Polilíneas de una partícula según su forma."""
    center = np.array([bit.x, bit.y])
    velocity = np.array([bit.vx, bit.vy])
    age = 1.0 - bit.life / max(bit.max_life, 1e-6)
    if bit.shape == "drop":
        return [teardrop(center, velocity, bit.size)]
    if bit.shape == "ring":
        theta = np.linspace(0, TAU, 16)
        tilt = bit.spin * (0.6 + age * 1.5)
        ellipse = np.stack([np.cos(theta), np.sin(theta) * 0.65], axis=1) * bit.size * 1.3
        rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
        return [center + ellipse @ rot.T]
    if bit.shape == "leaf":
        # Hoja de fuego pequeña, apuntando hacia arriba; rng fijo para que no parpadee.
        return [flame_tongue(center, -np.pi / 2 + bit.spin * 0.3, bit.size * 3.5, bit.size, bit.spin * 0.9, np.random.default_rng(0))]
    if bit.shape == "curl":
        theta = np.linspace(0, 2.5 * np.pi, 24)
        radius = bit.size * 1.6 * (1 - theta / (2.8 * np.pi))
        turn = bit.spin * (theta + age * 3.0)
        return [center + np.stack([np.cos(turn), np.sin(turn)], axis=1) * radius[:, None]]
    if bit.shape == "heart":
        t = np.linspace(0, TAU, 30)
        r = bit.size * 0.11
        return [center + np.stack([16 * np.sin(t) ** 3, -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))], axis=1) * r]
    if bit.shape == "beamed":
        r = bit.size
        heads = [center + np.array([dx * r, dy * r]) for dx, dy in ((0.0, 0.0), (2.6, -0.5))]
        ellipse = np.stack([np.cos(np.linspace(0, TAU, 14)), np.sin(np.linspace(0, TAU, 14)) * 0.7], axis=1) * r
        tops = [h + np.array([r, -3.0 * r]) for h in heads]
        beam = np.array([tops[0], tops[1], tops[1] + np.array([0.0, 0.7 * r]), tops[0] + np.array([0.0, 0.7 * r]), tops[0]])
        return [heads[0] + ellipse, heads[1] + ellipse, np.array([heads[0] + np.array([r, 0.0]), tops[0]]), np.array([heads[1] + np.array([r, 0.0]), tops[1]]), beam]
    if bit.shape == "note":
        r = bit.size
        head = center + np.stack([np.cos(np.linspace(0, TAU, 14)), np.sin(np.linspace(0, TAU, 14)) * 0.7], axis=1) * r
        stem_top = center + np.array([r, -3.2 * r])
        return [head, np.array([center + np.array([r, 0.0]), stem_top]), np.array([stem_top, stem_top + np.array([1.2 * r, 0.9 * r])])]
    from vfxglow.engine.season import OBJECTS, object_outline

    if bit.shape in OBJECTS:
        return object_outline(bit.shape, center, bit.size * 1.3, age, bit.spin)
    return [np.array([center - velocity * 1.6, center])]


def teardrop(center: np.ndarray, velocity: np.ndarray, radius: float) -> np.ndarray:
    """Contorno de gota: cabeza redonda hacia donde viaja y cola en punta detrás."""
    speed = float(np.linalg.norm(velocity))
    forward = velocity / speed if speed > 1e-6 else np.array([0.0, 1.0])
    side = np.array([-forward[1], forward[0]])
    angles = np.linspace(-0.62 * np.pi, 0.62 * np.pi, 14)
    head = center + (np.cos(angles)[:, None] * forward + np.sin(angles)[:, None] * side) * radius
    tail = center - forward * radius * (2.2 + min(speed / max(radius, 1e-6), 3.0) * 0.4)
    return np.vstack([tail, head, tail])


def _step(bits: list[Bit], gravity: float, drag: float) -> None:
    alive = []
    for bit in bits:
        bit.vx *= 1.0 - drag
        bit.vy = bit.vy * (1.0 - drag) + gravity * bit.gravity
        bit.x += bit.vx
        bit.y += bit.vy
        bit.life -= 1.0
        if bit.life > 0:
            alive.append(bit)
    bits[:] = alive


# ----- choque de energía -----


def draw_clash(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    """Energía liberada al chocar dos manos: rayos en zigzag de los dos colores y ondas rotas."""
    effect = runtime.effect
    style = effect.style
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is None or envelope <= 0 or event is None:
        return
    key = (event.start_frame, event.target)
    if runtime.burst_key != key:
        runtime.burst_key = key
        runtime.burst_seed = zlib.crc32(f"{style.seed_offset}:clash:{event.start_frame}".encode()) & 0xFFFFFFFF
    torso = torso_pixels(points, height)
    radius = min(style.size * torso, MAX_BURST * height)
    hold = effect.triggers[0].hold if effect.triggers else 12
    age = float(np.clip(runtime.active_frames / max(hold, 1), 0.0, 1.0))
    own = person_index(event.attacker)
    rival = person_index(event.receiver) if event.receiver else own + 1
    width = max(1.2, style.thickness * torso)
    # Los rayos se redibujan cada `boil_frames`: titilan como electricidad.
    flicker = np.random.default_rng(runtime.burst_seed + (frame_index // max(style.boil_frames, 1)) * 7919)
    strokes = []
    count = 6
    for index in range(count):
        angle = index * TAU / count + float(flicker.normal(0, 0.35))
        reach = radius * float(flicker.uniform(0.5, 1.0)) * (0.6 + 0.4 * (1 - age))
        bolt = zigzag(origin, angle, radius * 0.12, reach, flicker)
        strokes += _neon(bolt, _palette(style, own if index % 2 == 0 else rival), width * 0.8, envelope)
    # Ondas de choque: arcos rotos que se expanden y se apagan.
    shape = np.random.default_rng(runtime.burst_seed)
    for wave in range(2):
        r = radius * (0.35 + 0.9 * age + 0.3 * wave)
        start = float(shape.uniform(0, TAU))
        for arc in range(3):
            theta = np.linspace(start + arc * TAU / 3, start + arc * TAU / 3 + TAU / 5, 10)
            curve = origin + np.stack([np.cos(theta), np.sin(theta) * 0.8], axis=1) * r
            strokes += _neon(curve, _palette(style, own if wave == 0 else rival), width * 0.7, envelope * (1 - age))
    strokes += micro_sparks(runtime, origin, torso, key, frame_index)
    stroke_batch(layer, strokes, style.hdr_gain)


def zigzag(origin: np.ndarray, angle: float, start: float, reach: float, rng: np.random.Generator, steps: int = 6) -> np.ndarray:
    """Rayo quebrado desde `start` hasta `reach` en la dirección `angle`."""
    direction = np.array([np.cos(angle), np.sin(angle)])
    side = np.array([-direction[1], direction[0]])
    radial = np.linspace(start, reach, steps)
    offsets = rng.normal(0, (reach - start) * 0.12, steps)
    offsets[0] = offsets[-1] = 0.0
    return origin + radial[:, None] * direction + offsets[:, None] * side


# ----- rayos de los ojos -----

# Fases del rayo como fracción de su vida: los ojos se encienden, el rayo viaja, golpea.
BEAM_TRAVEL = (0.15, 0.4)


def actors(event: MotionEvent | None, track: FrameRecord | None) -> tuple[str | None, str | None]:
    """(atacante, rival). Si el evento no nombra al rival, es la otra persona del cuadro."""
    if event is None:
        return None, None
    attacker = event.attacker or (event.target.split(":", 1)[0] if ":" in event.target else None)
    receiver = event.receiver
    if receiver is None and track is not None:
        receiver = next((person.person_id for person in track.people if person.person_id != attacker), None)
    return attacker, receiver


def _person_part(points, person: str | None, names: tuple[str, ...]) -> np.ndarray | None:
    found = [points.get(f"{person}:{name}" if person else name) for name in names]
    found = [point for point in found if point is not None]
    return np.mean(found, axis=0) if found else None


def draw_beam(runtime, track: FrameRecord | None, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    """Rayo de los ojos del atacante a la cabeza del rival, que enciende fuego al llegar."""
    effect = runtime.effect
    style = effect.style
    if envelope <= 0 or event is None:
        return
    attacker, receiver = actors(event, track)
    eyes = _person_part(points, attacker, ("left_eye", "right_eye"))
    target = _person_part(points, receiver, ("nose",))
    if eyes is None or target is None:
        return
    key = (event.start_frame, event.target)
    if runtime.burst_key != key:
        runtime.burst_key = key
        runtime.burst_seed = zlib.crc32(f"{style.seed_offset}:beam:{event.start_frame}".encode()) & 0xFFFFFFFF
    torso = torso_pixels(points, height)
    hold = effect.triggers[0].hold if effect.triggers else 16
    age = float(np.clip(runtime.active_frames / max(hold, 1), 0.0, 1.0))
    own = person_index(attacker)
    rival = person_index(receiver)
    width = max(1.2, style.thickness * torso)
    flicker = np.random.default_rng(runtime.burst_seed + frame_index)
    strokes = []
    # Ojos encendidos: dos anillos pequeños que laten.
    eye_r = max(3.0, torso * 0.05) * (1.0 + 0.15 * np.sin(frame_index * 1.3))
    theta = np.linspace(0, TAU, 16)
    for name in ("left_eye", "right_eye"):
        eye = points.get(f"{attacker}:{name}" if attacker else name)
        if eye is not None:
            strokes += _neon(eye + np.stack([np.cos(theta), np.sin(theta)], axis=1) * eye_r, _palette(style, own), width * 0.7, envelope)
    start, arrive = BEAM_TRAVEL
    if age >= start:
        reach = float(np.clip((age - start) / max(arrive - start, 1e-6), 0.0, 1.0))
        tip = eyes + (target - eyes) * reach
        # Dos hilos casi paralelos que titilan: el rayo vibra.
        side = np.array([-(target - eyes)[1], (target - eyes)[0]])
        side /= max(float(np.linalg.norm(side)), 1e-6)
        for offset in (-1.0, 1.0):
            line = np.linspace(eyes, tip, 12) + side * width * offset * float(flicker.uniform(0.6, 1.6))
            line[1:-1] += flicker.normal(0, width * 0.5, (10, 2))
            strokes += _neon(line, _palette(style, own), width, envelope)
        if age >= arrive:
            # Al llegar: lenguas de fuego del color del rival en su cabeza.
            burn = float(np.clip((age - arrive) / 0.25, 0.0, 1.0))
            shape = np.random.default_rng(runtime.burst_seed)
            jitter = np.random.default_rng(runtime.burst_seed + (frame_index // max(style.boil_frames, 1)))
            radius = min(style.size * torso, MAX_BURST * height)
            for index in range(5):
                angle = -np.pi / 2 + float(shape.uniform(-1.2, 1.2))
                length = radius * float(shape.uniform(0.4, 0.75)) * burn
                tongue = flame_tongue(target, angle, length, length * 0.2, float(shape.choice([-1.0, 1.0])) * 0.7, jitter)
                strokes += _neon(tongue, _palette(style, rival), width, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


# ----- estrellas -----


def draw_stars(runtime, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event: MotionEvent | None) -> None:
    """Destellos de cuatro puntas alrededor del golpe: aparecen, titilan y se apagan."""
    effect = runtime.effect
    style = effect.style
    origin = resolve_anchor(points, effect.target.kind, effect.target.id, runtime.anchor_point)
    if origin is None or envelope <= 0 or event is None:
        return
    key = (event.start_frame, event.target)
    if runtime.burst_key != key:
        runtime.burst_key = key
        runtime.burst_seed = zlib.crc32(f"{style.seed_offset}:stars:{event.start_frame}".encode()) & 0xFFFFFFFF
    torso = torso_pixels(points, height)
    radius = min(style.size * torso, MAX_BURST * height)
    width = max(1.2, style.thickness * torso * 1.2)
    shape = np.random.default_rng(runtime.burst_seed)
    own = person_index(event.attacker)
    strokes = []
    for index in range(3 + int(shape.integers(0, 2))):
        angle = float(shape.uniform(0, TAU))
        center = origin + np.array([np.cos(angle), np.sin(angle)]) * radius * float(shape.uniform(0.2, 0.9))
        phase = float(shape.uniform(0, TAU))
        # Cada estrella entra con un pequeño retraso y titila a su ritmo.
        delay = index * 1.5
        grow = float(np.clip((runtime.active_frames - delay) / 3.0, 0.0, 1.0))
        twinkle = 0.75 + 0.25 * np.sin(frame_index * 1.1 + phase)
        size = radius * float(shape.uniform(0.35, 0.6)) * grow * twinkle
        if size < 1.0:
            continue
        color = _palette(style, own if index % 2 == 0 else own + 1)
        strokes += _neon(sparkle(center, size), color, width, envelope)
    strokes += micro_sparks(runtime, origin, torso, key, frame_index)
    stroke_batch(layer, strokes, style.hdr_gain)


def sparkle(center: np.ndarray, size: float) -> np.ndarray:
    """Estrella de cuatro puntas cóncava: brazos largos y finos en cruz, cintura estrecha."""
    angles = np.arange(8) * np.pi / 4
    radii = np.where(np.arange(8) % 2 == 0, size, size * 0.16)
    star = center + np.stack([np.sin(angles), -np.cos(angles)], axis=1) * radii[:, None]
    return np.vstack([star, star[:1]])


# ----- chispas diminutas -----

# Cantidad máxima en pantalla por efecto y ancho del trazo (px): finas como polvo de chispa.
MICRO_LIMIT = 160
MICRO_WIDTH = 0.9


def micro_sparks(runtime, origin: np.ndarray, torso: float, key: object, frame_index: int) -> list:
    """Lluvia de chispas muy pequeñas que sale del golpe al empezar cada impacto y cae."""
    style = runtime.effect.style
    if style.micro_sparks <= 0:
        return []
    micro: list[Bit] = runtime.micro
    if runtime.micro_key != key:
        runtime.micro_key = key
        rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:micro:{key}".encode()) & 0xFFFFFFFF)
        for _ in range(min(style.micro_sparks, MICRO_LIMIT - len(micro))):
            angle = float(rng.uniform(0, TAU))
            speed = torso * float(rng.uniform(0.03, 0.13))
            life = float(rng.uniform(5, 13))
            micro.append(
                Bit(float(origin[0]), float(origin[1]), np.cos(angle) * speed, np.sin(angle) * speed - torso * 0.015,
                    life, life, 0.0, int(rng.integers(0, 3)))
            )
    _step(micro, gravity=torso * 0.005, drag=0.1)
    strokes = []
    for bit in micro:
        fade = bit.life / bit.max_life
        tail = np.array([bit.x - bit.vx * 0.7, bit.y - bit.vy * 0.7])
        # Un tercio sale casi blanco: el destello caliente de la chispa.
        color = np.array([1.0, 0.95, 0.85], dtype=np.float32) if bit.color == 2 else _palette(style, bit.color)
        strokes += _neon(np.array([tail, [bit.x, bit.y]]), color, MICRO_WIDTH, fade)
    return strokes
