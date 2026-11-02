"""Familia de ojos: una base común (iris, párpado, fases, reacciones) y variantes con personalidad.

Todas las variantes comparten el seguimiento de los ojos (engine/face_glow.py `Face`), las señales de la
cara (engine/face_signals.py) y las cuatro fases de un efecto:

1. Entrada: el iris se enciende y lo de alrededor crece (ENTRY_END).
2. Activo: el dibujo principal sigue los ojos.
3. Reacción: en cualquier momento, según la tabla de la variante (abajo).
4. Salida: se suelta en polvo (engine/dissolve.py `melt`), desde EXIT_AT.

Comportamientos que una variante asigna a una señal (`EyeVariant.reactions`):

- compress: se encoge con el párpado de ese ojo (al cerrar los ojos).
- grow: crece con los ojos muy abiertos.
- flare: más brillo y alcance con la señal (mirada fija, ceño).
- fade: menos brillo con la cara relajada.
- trail: copias del iris que se quedan atrás cuando la cabeza gira rápido.
- follow: lo que sale del ojo apunta hacia donde mira.
- burst: un flanco (guiño, abrir los ojos, salto de mirada) suelta partículas o reinicia un barrido.

Variantes (`style.shapes`):

- eyes_fire: anillo ámbar en el iris y llamas finas que suben del párpado.
- eyes_galaxy: el iris es un disco de noche con estrellas que giran; una constelación en la sien.
- eyes_storm: iris blanco y cian con arcos eléctricos cortos que saltan del párpado.
- eyes_void: anillo violeta de borde brillante y volutas que se enroscan hacia el ojo.
- eyes_feline: el contorno del ojo, una pupila vertical que se angosta y bigotes de luz.
- eyes_scanner: una retícula sobre el iris, un barrido que recorre el ojo y líneas de datos en la sien.

Las líneas del iris y del párpado se devuelven siempre en el mismo orden (iris derecho, iris izquierdo,
párpados, el resto): así la continuidad entre efectos (engine/bodyglow.py) transforma ojo en ojo.

Variaciones: cada aparición sortea sus perillas (KNOBS) con una semilla de la forma, la persona y el
momento; el catálogo puede limitarlas con `style.variants`. El mismo proyecto vuelve a dibujar igual.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import MELT_AT, fine, melt
from vfxglow.engine.face_glow import Face, _seed
from vfxglow.engine.face_signals import FaceSignals, signals
from vfxglow.engine.firebend import DIE_START, GROW_END, living_ribbon
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
EYES = ("eyes_fire", "eyes_galaxy", "eyes_storm", "eyes_void", "eyes_feline", "eyes_scanner")
# Fases: hasta dónde entra y desde dónde se suelta en polvo.
ENTRY_END = 0.12
EXIT_AT = MELT_AT
# Radio del iris (unidades de cara, la distancia entre los ojos).
IRIS = 0.11
# Perillas de variación y sus valores; `palette`: los colores propios de la variante o los del capítulo.
KNOBS: dict[str, tuple] = {
    "intensity": (0.75, 1.0, 1.3),
    "speed": (0.6, 0.85, 1.0, 1.3),
    "density": (0.6, 1.0, 1.5),
    "trail": (0.0, 0.5, 1.0),
    "stroke": (1.0, 1.6),
    "motion": (0, 1, 2),
    "palette": ("theme", "theme", "chapter"),
}
# Constelación de la galaxia, junto al ojo (x hacia afuera, y hacia abajo, unidades de cara).
CONSTELLATION = ((0.36, -0.26), (0.47, -0.34), (0.59, -0.37), (0.69, -0.32), (0.73, -0.21), (0.62, -0.17))
# Estela: la cabeza debe girar al menos esto (grados por segundo) y cuántas copias deja como máximo.
TRAIL_TURN = 40.0
TRAIL_COPIES = 5
# Partículas de un flanco: cuántas (por densidad 1), cuánto viven (cuadros de 30 fps) y su velocidad.
BURST = 12
BURST_LIFE = 26
BURST_SPEED = 0.05


@dataclass
class Eye:
    """Un ojo visible, en píxeles: el iris, su radio, el párpado y los ejes de la cara."""

    side: str
    out: float  # -1 hacia la derecha de la persona, 1 hacia su izquierda
    center: np.ndarray
    radius: float
    lid: np.ndarray | None
    across: np.ndarray
    down: np.ndarray
    unit: float

    def ring(self, radius: float, n: int = 28, start: float = 0.0, span: float = TAU) -> np.ndarray:
        t = start + np.linspace(0.0, span, n)
        return self.center + np.outer(np.cos(t), self.across) * radius + np.outer(np.sin(t), self.down) * radius

    def at(self, x: float, y: float) -> np.ndarray:
        """Un punto junto al ojo: x hacia afuera de la cara, y hacia abajo (unidades de cara)."""
        return self.center + self.across * self.out * x * self.unit + self.down * y * self.unit


@dataclass
class Mods:
    """Lo que las reacciones le hacen al dibujo de un ojo en este cuadro."""

    size: float = 1.0
    glow: float = 1.0
    reach: float = 1.0
    aim: np.ndarray = field(default_factory=lambda: np.zeros(2))  # hacia dónde mira, en píxeles por unidad


@dataclass
class Ctx:
    face: Face
    sig: FaceSignals
    u: float
    stage: str
    t: float  # avance dentro de la fase, 0-1
    frame_index: int
    runtime: object
    layer: np.ndarray
    alpha: float
    seed: int
    knobs: dict
    main: np.ndarray
    accent: np.ndarray
    st: dict
    iris: list = field(default_factory=list)
    lids: list = field(default_factory=list)
    extra: list = field(default_factory=list)

    @property
    def width(self) -> float:
        return max(1.0, 0.008 * self.face.unit) * float(self.knobs["stroke"])

    def dot(self, at: np.ndarray, size: float, tint, alpha: float) -> None:
        if alpha > 0.0:
            splat(self.layer, float(at[0]), float(at[1]), size * self.face.unit + 0.6, np.asarray(tint, np.float32), self.alpha * alpha, self.runtime.kernels)


@dataclass(frozen=True)
class EyeVariant:
    main: tuple[float, float, float]
    accent: tuple[float, float, float]
    draw: Callable[[Ctx, Eye, Mods], None]
    reactions: dict[str, str]  # señal → comportamiento
    burst_on: str | None = None  # flanco que suelta partículas: wink, eyes_opened, gaze_jump


def phase(u: float) -> tuple[str, float]:
    """(fase, avance dentro de ella): entry, active o exit."""
    if u < ENTRY_END:
        return "entry", u / ENTRY_END
    if u < EXIT_AT:
        return "active", (u - ENTRY_END) / (EXIT_AT - ENTRY_END)
    return "exit", (u - EXIT_AT) / (1.0 - EXIT_AT)


def pick_knobs(shape: str, person: str, start: int, allowed: dict) -> dict:
    """Las perillas de esta aparición: una semilla por perilla, la forma, la persona y el momento."""
    knobs = {}
    for name, values in KNOBS.items():
        options = [v for v in allowed.get(name, values) if v is not None] or list(values)
        rng = np.random.default_rng(zlib.crc32(f"{shape}:{person}:{start}:{name}".encode()))
        knobs[name] = options[int(rng.integers(0, len(options)))]
    return knobs


def _mods(variant: EyeVariant, sig: FaceSignals, eye: Eye, face: Face) -> Mods:
    mods = Mods()
    lid = sig.blink_r if eye.side == "right" else sig.blink_l
    for signal, behavior in variant.reactions.items():
        if behavior == "compress":
            mods.size *= 1.0 - 0.75 * min(lid * 1.3, 1.0)
        elif behavior == "grow":
            mods.size *= 1.0 + 0.5 * float(np.clip(sig.wide / 0.25, 0.0, 1.0))
        elif behavior == "flare":
            level = sig.stare if signal == "stare" else float(np.clip(sig.frown / 0.5, 0.0, 1.0))
            mods.glow *= 1.0 + 0.7 * level
            mods.reach *= 1.0 + 0.6 * level
        elif behavior == "fade":
            mods.glow *= 1.0 - 0.55 * sig.relaxed
        elif behavior == "follow":
            mods.aim = (face.ux * sig.gaze[0] - face.uy * sig.gaze[1]) / face.unit
    return mods


def _eyes(face: Face) -> list[Eye]:
    across, down = face.ux / face.unit, face.uy / face.unit
    found = []
    for side, out in (("right", -1.0), ("left", 1.0)):
        if face.visible(side):
            center = face.at(f"{side}_iris", (0.5 * out, 0.0))
            found.append(Eye(side, out, center, IRIS * face.unit, face.feature(f"{side}_eye"), across, down, face.unit))
    return found


def _burst(ctx: Ctx, eyes: list[Eye], variant: EyeVariant) -> None:
    """Partículas que suelta un flanco y su vida."""
    sig = ctx.sig
    edge = variant.burst_on
    fired = []
    if edge == "wink" and sig.wink:
        fired = [eye for eye in eyes if eye.side == sig.wink]
    elif edge == "eyes_opened" and sig.eyes_opened:
        fired = eyes
    elif edge == "gaze_jump" and ctx.st.get("jump") == ctx.frame_index:
        fired = eyes
    rng = np.random.default_rng([ctx.seed, ctx.frame_index])
    for eye in fired if ctx.stage != "exit" else []:
        for _ in range(int(BURST * float(ctx.knobs["density"]))):
            a = rng.uniform(0.0, TAU)
            direction = eye.across * np.cos(a) + eye.down * np.sin(a) - eye.down * 0.6
            ctx.st.setdefault("sparks", []).append({"at": eye.center.copy(), "vel": direction * rng.uniform(0.5, 1.0), "born": ctx.frame_index, "tint": ctx.accent if rng.random() < 0.5 else ctx.main})
    kept = []
    for spark in ctx.st.get("sparks", []):
        age = (ctx.frame_index - spark["born"]) / BURST_LIFE
        if not 0.0 <= age < 1.0:
            continue
        kept.append(spark)
        at = spark["at"] + spark["vel"] * age * BURST_LIFE * BURST_SPEED * ctx.face.unit * float(ctx.knobs["speed"])
        ctx.dot(at, 0.014, spark["tint"], (1.0 - age) ** 1.5)
    ctx.st["sparks"] = kept


def _trail(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    """Copias del iris donde estuvo hace unos cuadros, si la cabeza gira rápido."""
    history = ctx.st.setdefault(f"history:{eye.side}", [])
    history.append(eye.center.copy())
    del history[: -TRAIL_COPIES - 1]
    copies = int(round(TRAIL_COPIES * float(ctx.knobs["trail"])))
    turning = float(np.clip((abs(ctx.sig.yaw_rate) - TRAIL_TURN) / TRAIL_TURN, 0.0, 1.0))
    if copies <= 0 or turning <= 0.0:
        return
    for k, center in enumerate(reversed(history[:-1][-copies:])):
        ghost = center + (eye.ring(eye.radius * mods.size) - eye.center)
        fine([ghost], ctx.main, ctx.alpha * turning * 0.5 * (1.0 - (k + 1) / (copies + 1)), ctx.layer, width=ctx.width)


# ----- variantes -----


def _fire(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    grow = _ease(_seg(ctx.u, 0.0, ENTRY_END))
    radius = eye.radius * mods.size
    ctx.iris.append((eye.ring(radius), ctx.main * mods.glow))
    fill_polygon(ctx.layer, eye.ring(radius * 0.8), ctx.accent, ctx.alpha * 0.35 * grow * mods.glow * min(mods.size, 1.0), 1.0, feather=1.5)
    if eye.lid is None or len(eye.lid) < 4 or mods.size < 0.3:
        return
    upper = eye.lid[: len(eye.lid) // 2 + 1]
    life = GROW_END * grow if ctx.stage != "exit" else DIE_START + (1.0 - DIE_START) * ctx.t
    tongues = 3 if float(ctx.knobs["density"]) < 1.2 else 4
    for k in range(tongues):
        root = upper[int((k + 0.5) / tongues * (len(upper) - 1))]
        reach = (0.32 + 0.1 * (k % 2)) * eye.unit * mods.reach * mods.size * float(ctx.knobs["intensity"])
        q = np.linspace(0.0, 1.0, 16)
        sway = np.sin(q * 4.0 - ctx.frame_index * 0.25 * float(ctx.knobs["speed"]) + k * 1.7) * 0.18 * reach * q
        spine = root + np.outer(-q * reach, eye.down) + np.outer(sway + q * 0.25 * reach * eye.out, eye.across)
        widths = (0.004 + 0.032 * q**0.6 * (1.0 - q)) * eye.unit
        st = ctx.st.setdefault(f"tongue:{eye.side}:{k}", {})
        living_ribbon(ctx.layer, spine, widths, life, st, ctx.frame_index, ctx.main, ctx.alpha * 0.8 * mods.glow, None, grow_from_end=False, tongues=6.0, phase=float(k))


def _galaxy(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    grow = _ease(_seg(ctx.u, 0.0, ENTRY_END))
    radius = eye.radius * mods.size * 1.1
    fill_polygon(ctx.layer, eye.ring(radius), ctx.accent * 0.35, ctx.alpha * 0.5 * grow, 1.0, feather=2.0)
    ctx.iris.append((eye.ring(radius), ctx.accent * mods.glow))
    rng = np.random.default_rng(ctx.seed + (0 if eye.side == "right" else 7))
    stars = int(9 * float(ctx.knobs["density"]))
    turn = ctx.frame_index * 0.04 * float(ctx.knobs["speed"]) * (1.0 if int(ctx.knobs["motion"]) != 1 else -1.0)
    drift = mods.aim * 0.35 * radius
    for k in range(stars):
        r = radius * np.sqrt(rng.uniform(0.05, 0.85))
        a = rng.uniform(0.0, TAU) + turn * (1.4 - r / radius)
        at = eye.center + (eye.across * np.cos(a) + eye.down * np.sin(a)) * r + drift
        ctx.dot(at, 0.008 + 0.006 * (k % 3 == 0), (1.0, 1.0, 1.0), grow * mods.glow * (0.6 + 0.4 * np.sin(ctx.frame_index * 0.2 + k)))
    # Una constelación chica en la sien: estrellas unidas por un hilo tenue que se traza de a poco.
    points = np.array([eye.at(x, y) for x, y in CONSTELLATION])
    joined = int(np.ceil(_seg(ctx.u, ENTRY_END * 0.5, ENTRY_END * 2.5) * (len(points) - 1)))
    if joined:
        ctx.extra.append((points[: joined + 1], ctx.main * 0.45))
    for k, at in enumerate(points[: joined + 1]):
        ctx.dot(at, 0.009, (1.0, 1.0, 1.0), grow * (0.65 + 0.35 * np.sin(ctx.frame_index * 0.15 + k * 2.0)))


def _storm(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    radius = eye.radius * mods.size
    ctx.iris.append((eye.ring(radius), ctx.main * mods.glow))
    ctx.dot(eye.center, 0.035 * mods.size, (0.9, 1.0, 1.0), mods.glow)
    if mods.size < 0.3:
        return
    # Los arcos cambian de forma cada dos cuadros, como un chispazo.
    rng = np.random.default_rng([ctx.seed, eye.side == "left", ctx.frame_index // 2])
    count = int(3 * float(ctx.knobs["density"])) + 1
    for k in range(count):
        a = rng.uniform(-1.3, 0.35)  # hacia la sien y arriba: nunca cruzan el ojo
        direction = eye.across * eye.out * np.cos(a) + eye.down * np.sin(a)
        normal = np.array([-direction[1], direction[0]])
        length = rng.uniform(0.14, 0.26) * eye.unit * mods.reach * float(ctx.knobs["intensity"])
        q = np.linspace(0.0, 1.0, 7)
        jag = np.concatenate([[0.0], rng.uniform(-0.25, 0.25, 6)]) * 0.3 * length
        start = eye.center + direction * eye.unit * 0.24
        ctx.extra.append((start + np.outer(q * length, direction) + np.outer(jag, normal), ctx.accent * mods.glow))


def _void(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    radius = eye.radius * mods.size * 1.15
    ctx.iris.append((eye.ring(radius), ctx.main * mods.glow * 1.3))
    ctx.extra.append((eye.ring(radius * 0.72), ctx.accent * 0.55 * mods.glow))
    wisps = int(3 * float(ctx.knobs["density"])) + 1
    spin = ctx.frame_index * 0.05 * float(ctx.knobs["speed"])
    for k in range(wisps):
        a0 = k * TAU / wisps + spin
        q = np.linspace(0.0, 1.0, 18)
        r = radius * (1.2 + 0.85 * (1.0 - q) * mods.reach * mods.size)
        a = a0 + 1.8 * (1.0 - q)
        curl = eye.center + np.outer(np.cos(a) * r, eye.across) + np.outer(np.sin(a) * r, eye.down)
        ctx.extra.append((curl, ctx.accent * mods.glow * 0.7))


def _feline(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    if eye.lid is not None and len(eye.lid) > 4:
        ctx.lids.append((np.vstack([eye.lid, eye.lid[:1]]), ctx.main * mods.glow))
    tall = eye.radius * 1.35 * mods.size
    narrow = 0.38 - 0.26 * float(np.clip(ctx.sig.wide / 0.25, 0.0, 1.0))
    center = eye.center + mods.aim * 0.4 * eye.radius
    t = np.linspace(-1.0, 1.0, 15)
    half = np.sqrt(np.clip(1.0 - t**2, 0.0, 1.0)) * narrow * eye.radius
    side_a = center + np.outer(t * tall, eye.down) + np.outer(half, eye.across)
    side_b = center + np.outer(t * tall, eye.down) - np.outer(half, eye.across)
    ctx.iris.append((np.vstack([side_a, side_b[::-1], side_a[:1]]), ctx.accent * mods.glow))
    grow = _ease(_seg(ctx.u, 0.0, ENTRY_END + 0.08))
    for lift in (-0.05, 0.03, 0.11):  # bigotes desde el costado de la nariz
        root = ctx.face.place([(0.2 * eye.out, 0.38 + lift)])[0]
        tip = ctx.face.place([((0.22 + 0.45 * grow * float(ctx.knobs["intensity"])) * eye.out, 0.34 + lift * 2.0)])[0]
        bend = (root + tip) / 2 - eye.down * 0.03 * eye.unit
        ctx.extra.append((np.array([root, bend, tip]), ctx.main * 0.7))


def _scanner(ctx: Ctx, eye: Eye, mods: Mods) -> None:
    radius = eye.radius * 1.5 * mods.size
    ctx.iris.append((eye.ring(radius, 32), ctx.main * mods.glow))
    for k in range(4):  # las marcas de la retícula
        a = k * TAU / 4 + 0.25 * np.pi * (int(ctx.knobs["motion"]) == 2)
        d = eye.across * np.cos(a) + eye.down * np.sin(a)
        ctx.extra.append((np.array([eye.center + d * radius * 0.75, eye.center + d * radius * 1.3]), ctx.main * mods.glow))
    since = ctx.frame_index - ctx.st.get("jump", -10_000)
    sweep_frames = 20 / float(ctx.knobs["speed"])
    if since < sweep_frames:  # el barrido después de un salto de mirada
        y = (since / sweep_frames * 2.0 - 1.0) * radius
        line = eye.center + eye.down * y + np.outer(np.linspace(-1.2, 1.2, 2) * radius, eye.across)
        ctx.extra.append((line, ctx.accent * 1.4))
    rng = np.random.default_rng([ctx.seed, ctx.frame_index // 6, eye.side == "left"])
    for k in range(3):  # líneas de datos que cambian de largo
        start = eye.at(0.42, -0.12 + k * 0.1)
        length = rng.uniform(0.12, 0.35) * eye.unit * mods.reach
        ctx.extra.append((np.array([start, start + eye.across * eye.out * length]), ctx.accent * 0.8))


VARIANTS: dict[str, EyeVariant] = {
    "eyes_fire": EyeVariant((1.0, 0.55, 0.12), (1.0, 0.25, 0.04), _fire, {"blink": "compress", "stare": "flare", "yaw": "trail", "relaxed": "fade"}),
    "eyes_galaxy": EyeVariant((0.55, 0.45, 1.0), (0.25, 0.15, 0.9), _galaxy, {"gaze": "follow", "blink": "compress"}, burst_on="wink"),
    "eyes_storm": EyeVariant((0.85, 0.97, 1.0), (0.3, 0.8, 1.0), _storm, {"frown": "flare", "blink": "compress", "yaw": "trail"}, burst_on="eyes_opened"),
    "eyes_void": EyeVariant((0.75, 0.35, 1.0), (0.45, 0.1, 0.85), _void, {"wide": "grow", "blink": "compress", "relaxed": "fade"}),
    "eyes_feline": EyeVariant((1.0, 0.75, 0.2), (0.4, 1.0, 0.35), _feline, {"blink": "compress", "gaze": "follow"}),
    "eyes_scanner": EyeVariant((0.2, 1.0, 0.85), (0.6, 1.0, 1.0), _scanner, {"stare": "flare", "relaxed": "fade"}, burst_on="gaze_jump"),
}


def eye_family(shape: str, body, frame, scale, frame_index: int, runtime, layer, color, alpha: float, event) -> list:
    variant = VARIANTS[shape]
    face = Face(body, scale)
    u = _phase(runtime, event)
    stage, t = phase(u)
    start = event.start_frame if event is not None else 0
    knobs = pick_knobs(shape, body.prefix, start, runtime.effect.style.variants)
    sig = signals(runtime, frame_index, body.prefix)
    chapter = knobs["palette"] == "chapter"
    main = np.asarray(color if chapter else variant.main, np.float32)
    # Lo que se dibuja directo (rellenos, puntos, llamas) se apaga al soltarse; las líneas se vuelven polvo.
    direct = alpha * float(knobs["intensity"]) * (1.0 - _ease(t) if stage == "exit" else 1.0)
    ctx = Ctx(face, sig, u, stage, t, frame_index, runtime, layer, direct, _seed(shape, body, event), knobs, main, np.asarray(variant.accent, np.float32),
              runtime.swoosh.setdefault(f"_eyes:{shape}:{start}:{body.prefix}", {}))
    # Salto de mirada: lo crudo se aleja de lo suavizado (uno cada medio segundo como mucho).
    if float(np.abs(sig.gaze_raw - sig.gaze).max()) > 0.2 and frame_index - ctx.st.get("jump", -10_000) > 15:
        ctx.st["jump"] = frame_index
    eyes = _eyes(face)
    for eye in eyes:
        mods = _mods(variant, sig, eye, face)
        if stage == "entry":
            mods.size *= 0.4 + 0.6 * _ease(t)
        variant.draw(ctx, eye, mods)
        if "trail" in variant.reactions.values():
            _trail(ctx, eye, mods)
    _burst(ctx, eyes, variant)
    # El iris y el párpado los pinta el motor (y los transforma la continuidad); lo de alrededor es
    # fino y con poco halo, como todo lo delgado sobre la cara.
    power = alpha * float(knobs["intensity"])
    pairs = lambda items: [(curve, np.asarray(tint, np.float32)) for curve, tint in items]  # noqa: E731
    for curve, tint in melt(pairs(ctx.extra), u, face, layer, main, power, runtime.kernels, ctx.seed + 1, start=EXIT_AT):
        fine([curve], tint, ctx.alpha if stage != "exit" else power, layer, width=ctx.width)
    return melt(pairs(ctx.iris + ctx.lids), u, face, layer, main, power, runtime.kernels, ctx.seed, start=EXIT_AT)
