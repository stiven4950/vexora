"""Símbolos de luz sobre el rostro y la cabeza, con la base de la familia de ojos (engine/eye_family.py):
las mismas fases, perillas de variación y señales de la cara (engine/face_signals.py).

- third_eye: un ojo de luz vertical en la frente, con doble contorno, iris de rayos grabados y un bindi. Se abre con las cejas (medidas contra lo habitual de
  esa cara: en facil_1 las cejas en reposo ya marcan 0,5-0,7), parpadea con los ojos de verdad y, al
  levantar las cejas de golpe, suelta rayos cortos.
- rune_shift: runas en la frente y las mejillas que se reorganizan: sus trazos viajan hasta formar
  otra runa al parpadear, al girar rápido la cabeza o cada tanto. Se apagan con la cara relajada.
- light_crown: una diadema de luz en perspectiva sobre la cabeza, inclinada con ella. Las puntas crecen con la sonrisa
  y las cejas, y un brillo recorre la banda. Va sobre el pelo: no tapa la cara.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.geom import catmull_rom
from vfxglow.engine.dissolve import fine, melt
from vfxglow.engine.eye_family import ENTRY_END, EXIT_AT, phase, pick_knobs
from vfxglow.engine.face_glow import _RUNES, Face, _seed
from vfxglow.engine.face_signals import signals
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
SYMBOLS = ("third_eye", "rune_shift", "light_crown")
THEMES = {
    "third_eye": ((0.8, 0.5, 1.0), (1.0, 0.85, 0.35)),
    "rune_shift": ((0.35, 0.9, 1.0), (0.85, 1.0, 1.0)),
    "light_crown": ((1.0, 0.8, 0.3), (1.0, 0.95, 0.75)),
}
# Cejas: cuánto sobre lo habitual abre del todo el tercer ojo, a qué ritmo se aprende lo habitual
# (por paso de 30 fps) y desde qué apertura un salto suelta rayos.
BROWS_FULL = 0.2
BROWS_LEARN = 0.02
RAYS_AT = 0.6
RAYS = 8
RAYS_LIFE = 18
# Tercer ojo: dónde va (unidades de cara, sobre la línea de los ojos), su alto y su ancho abierto.
THIRD_EYE_Y = -0.8
THIRD_EYE_TALL = 0.21
THIRD_EYE_WIDE = 0.11
# Runas: dónde van (x, y, tamaño), cada cuánto cambian solas (cuadros de 30 fps) y cuánto tarda el cambio.
RUNE_SPOTS = ((0.0, -0.78, 0.26), (-0.62, 0.55, 0.18), (0.62, 0.55, 0.18))
RUNE_EVERY = 45
RUNE_MORPH = 10
RUNE_POINTS = 12
RUNE_TURN = 60.0
# Corona: cuánto sobre la frente va su banda, su medio ancho, cuánto baja al frente (perspectiva),
# hasta qué ángulo alrededor de la cabeza se ve, el alto del filete y las puntas (ángulo y alto, en
# unidades de cara; el medio ancho de cada una en radianes).
CROWN_LIFT = 0.42
CROWN_WIDTH = 0.82
CROWN_DIP = 0.1
CROWN_REACH = 1.25
CROWN_RIM = 0.07
CROWN_PEAKS = (-0.9, -0.45, 0.0, 0.45, 0.9)
CROWN_HEIGHTS = (0.22, 0.36, 0.55, 0.36, 0.22)
CROWN_PEAK_HALF = 0.17


def _brows(runtime, st: dict, frame_index: int, sig) -> float:
    """Las cejas sobre lo habitual de esta cara, 0-1."""
    from vfxglow.engine.face_glow import steps

    base = st.setdefault("brows_base", sig.brows)
    if st.get("brows_frame") != frame_index:
        st["brows_frame"] = frame_index
        st["brows_base"] = base + (sig.brows - base) * (1.0 - (1.0 - BROWS_LEARN) ** steps(runtime))
    return float(np.clip((sig.brows - st["brows_base"]) / BROWS_FULL, 0.0, 1.0))


def _almond(center: np.ndarray, across: np.ndarray, down: np.ndarray, tall: float, wide: float) -> np.ndarray:
    """Un ojo vertical de puntas afiladas (dos arcos)."""
    t = np.linspace(-1.0, 1.0, 25)
    half = (1.0 - t**2) * wide
    side_a = center + np.outer(t * tall, down) + np.outer(half, across)
    side_b = center + np.outer(t * tall, down) - np.outer(half, across)
    return np.vstack([side_a, side_b[::-1], side_a[:1]])


def _third_eye(face: Face, ctx: dict, lines: list) -> None:
    """Dos contornos de almendra (el de afuera tenue), un iris con rayos grabados y pupila vertical,
    un rombo debajo y un punto arriba, como un bindi."""
    sig, st, u, knobs = ctx["sig"], ctx["st"], ctx["u"], ctx["knobs"]
    main, accent, layer, alpha = ctx["main"], ctx["accent"], ctx["layer"], ctx["alpha"]
    raised = _brows(ctx["runtime"], st, ctx["frame_index"], sig)
    entry = _ease(_seg(u, 0.0, ENTRY_END * 1.5))
    opened = entry * (0.6 + 0.4 * raised) * (1.0 - min(sig.blink * 1.2, 1.0))
    center = face.place([(0.0, THIRD_EYE_Y)])[0]
    across, down = face.ux / face.unit, face.uy / face.unit
    tall, wide = THIRD_EYE_TALL * face.unit, THIRD_EYE_WIDE * face.unit
    lines.append((_almond(center, across, down, tall * 1.28 * entry + 1.0, wide * 1.55 * entry), main * 0.45))
    lines.append((_almond(center, across, down, tall * max(entry, 0.05), wide * max(opened, 0.05)), main))
    if opened > 0.15:
        r = min(wide * opened, tall * 0.42) * 0.8
        ring = np.linspace(0.0, TAU, 28)
        circle = lambda radius: center + (np.outer(np.cos(ring), across) + np.outer(np.sin(ring), down)) * radius  # noqa: E731
        fill_polygon(layer, circle(r), accent, alpha * 0.12 * opened, 1.0, feather=1.2)
        lines.append((circle(r), accent))
        for k in range(8 if r > 6.0 else 0):  # los rayos grabados del iris (si caben: si no, son un manchón)
            a = TAU * k / 8 + ctx["frame_index"] * 0.01 * float(knobs["speed"])
            d = across * np.cos(a) + down * np.sin(a)
            lines.append((np.array([center + d * r * 0.55, center + d * r * 0.9]), accent * 0.7))
        lines.append((_almond(center, across, down, r * 0.75, r * 0.16), main))  # la pupila
    gem = center + down * tall * 1.62  # el rombo de abajo y el punto de arriba
    size = 0.045 * face.unit * entry
    lines.append((np.array([gem - down * size, gem + across * size * 0.6, gem + down * size, gem - across * size * 0.6, gem - down * size]), accent))
    top = center - down * tall * 1.55
    splat(layer, float(top[0]), float(top[1]), 0.016 * face.unit * entry + 0.5, accent, alpha * entry, ctx["runtime"].kernels)
    if raised > RAYS_AT and st.get("raised", 1.0) <= RAYS_AT and ctx["stage"] == "active":
        st["rays"] = ctx["frame_index"]
    st["raised"] = raised
    age = (ctx["frame_index"] - st.get("rays", -10_000)) / RAYS_LIFE
    if 0.0 <= age < 1.0:  # rayos finos que se abren hacia afuera y se apagan
        for k in range(RAYS):
            a = TAU * k / RAYS + 0.2
            d = across * np.cos(a) * 1.3 + down * np.sin(a)
            start, reach = 0.32 + 0.4 * age, 0.12 + 0.25 * float(knobs["intensity"]) * (1.0 - age)
            ray = np.array([center + d * start * face.unit, center + d * (start + reach) * face.unit])
            fine([ray], accent, alpha * (1.0 - age), layer, width=ctx["width"])


def _morph_strokes(a: list, b: list, t: float) -> list[np.ndarray]:
    """Los trazos de la runa `a` viajando hasta los de `b`: el que sobra se encoge a su centro."""
    def resample(stroke) -> np.ndarray:
        stroke = np.asarray(stroke, dtype=np.float64)
        seg = np.linalg.norm(np.diff(stroke, axis=0), axis=1)
        acc = np.concatenate([[0.0], np.cumsum(seg)])
        q = np.linspace(0.0, acc[-1], RUNE_POINTS)
        return np.stack([np.interp(q, acc, stroke[:, 0]), np.interp(q, acc, stroke[:, 1])], axis=1)

    out = []
    for k in range(max(len(a), len(b))):
        src = resample(a[k]) if k < len(a) else np.repeat(resample(b[k]).mean(axis=0, keepdims=True), RUNE_POINTS, axis=0)
        dst = resample(b[k]) if k < len(b) else np.repeat(resample(a[k]).mean(axis=0, keepdims=True), RUNE_POINTS, axis=0)
        out.append(src + (dst - src) * t)
    return out


def _rune_shift(face: Face, ctx: dict, lines: list) -> None:
    sig, st, frame_index = ctx["sig"], ctx["st"], ctx["frame_index"]
    every = RUNE_EVERY / float(ctx["knobs"]["speed"])
    since = frame_index - st.get("changed", frame_index)
    st.setdefault("changed", frame_index)
    st.setdefault("glyph", 0)
    if ctx["stage"] == "active" and since >= RUNE_MORPH and (sig.blink_start or abs(sig.yaw_rate) > RUNE_TURN or since >= every):
        st["previous"], st["glyph"], st["changed"] = st["glyph"], st["glyph"] + 1, frame_index
        since = 0
    t = _ease(min(since / RUNE_MORPH, 1.0)) if "previous" in st else 1.0
    write = _seg(ctx["u"], 0.0, ENTRY_END * 2.0)
    tint = ctx["main"] * (1.0 - 0.5 * sig.relaxed)
    across, down = face.ux / face.unit, face.uy / face.unit
    for k, (x, y, size) in enumerate(RUNE_SPOTS):
        if (k == 1 and not face.visible("right")) or (k == 2 and not face.visible("left")):
            continue
        new = _RUNES[(ctx["seed"] + k + st["glyph"]) % len(_RUNES)]
        old = _RUNES[(ctx["seed"] + k + st.get("previous", st["glyph"])) % len(_RUNES)]
        center = face.place([(x, y)])[0]
        for stroke in _morph_strokes(old, new, t):
            curve = center + np.outer((stroke[:, 0] - 0.5) * size * face.unit, across) + np.outer((stroke[:, 1] - 0.5) * size * face.unit, down)
            keep = max(int(np.ceil(len(curve) * write)), 1 if write > 0 else 0)
            if keep >= 2:
                lines.append((curve[:keep], tint))
        if 0.0 < t < 1.0:  # la chispa del cambio
            splat(ctx["layer"], float(center[0]), float(center[1]), 0.04 * face.unit * np.sin(np.pi * t) + 0.6, ctx["accent"], ctx["alpha"], ctx["runtime"].kernels)


def _crown(face: Face, ctx: dict, lines: list) -> None:
    """Una diadema de joyería en perspectiva: la banda sigue la curva de la cabeza (doble filete y
    perlas), las puntas son arcos ojivales que se angostan hacia los costados, la central lleva una gota
    y todas rematan en una estrella de cuatro puntas o una perla."""
    sig, knobs = ctx["sig"], ctx["knobs"]
    top_x, top_y = face.local("forehead_top", (0.0, -1.1))
    y0 = top_y - CROWN_LIFT
    raised = _brows(ctx["runtime"], ctx["st"], ctx["frame_index"], sig)
    entry = _ease(_seg(ctx["u"], 0.0, ENTRY_END * 1.5))
    lift = entry * (0.8 + 0.3 * float(np.clip(sig.smile / 0.5, 0.0, 1.0)) + 0.2 * raised) * float(knobs["intensity"])

    def at(theta, height) -> np.ndarray:
        """Un punto de la corona: `theta` alrededor de la cabeza (0 al frente), `height` sobre la banda."""
        theta, height = np.asarray(theta, dtype=np.float64), np.asarray(height, dtype=np.float64)
        x = top_x + np.sin(theta) * CROWN_WIDTH
        y = y0 + CROWN_DIP * np.cos(theta) - height
        return face.place(np.stack(np.broadcast_arrays(x, y), axis=-1).reshape(-1, 2))

    main, accent = ctx["main"], ctx["accent"]
    around = np.linspace(-CROWN_REACH, CROWN_REACH, 41)
    lines.append((at(around, 0.0), main))
    lines.append((at(around, CROWN_RIM), main * 0.55))
    for theta in np.linspace(-CROWN_REACH * 0.92, CROWN_REACH * 0.92, 15):  # las perlas de la banda
        bead = at(theta, CROWN_RIM / 2)[0]
        splat(ctx["layer"], float(bead[0]), float(bead[1]), 0.011 * face.unit * np.cos(theta) + 0.5, accent, ctx["alpha"] * 0.8 * entry, ctx["runtime"].kernels)
    outline = []
    for k, (theta, tall) in enumerate(zip(CROWN_PEAKS, CROWN_HEIGHTS)):
        h, half = tall * lift, CROWN_PEAK_HALF
        base = CROWN_RIM
        # Arco ojival: sale abierto del pie, se cierra a media altura y sube a la punta.
        control = [(-half, 0.0), (-half * 0.72, 0.28), (-half * 0.28, 0.66), (0.0, 1.0), (half * 0.28, 0.66), (half * 0.72, 0.28), (half, 0.0)]
        pts = np.array([at(theta + dx, base + dy * h)[0] for dx, dy in control])
        peak = catmull_rom(pts, 6)
        outline.append(peak)
        lines.append((peak, main))
        tip = at(theta, base + h)[0]
        if k == len(CROWN_PEAKS) // 2:  # la gota de la punta central y la estrella
            drop = catmull_rom(np.array([at(theta + dx * 0.55, base + dy * h)[0] for dx, dy in ((0.0, 0.62), (half * 0.42, 0.3), (0.0, 0.16), (-half * 0.42, 0.3), (0.0, 0.62))]), 6)
            fill_polygon(ctx["layer"], drop, accent, ctx["alpha"] * 0.35 * entry, 1.0, feather=1.0)
            lines.append((drop, accent))
            twinkle = 0.55 + 0.45 * np.sin(ctx["frame_index"] * 0.18 * float(knobs["speed"]))
            arm = 0.09 * face.unit * twinkle * entry
            across, up = face.ux / face.unit, -face.uy / face.unit
            star = tip + up * arm * 0.9
            lines.append((np.array([star - up * arm, star + up * arm]), accent))
            lines.append((np.array([star - across * arm * 0.6, star + across * arm * 0.6]), accent))
        else:  # una perla en la punta
            splat(ctx["layer"], float(tip[0]), float(tip[1]), 0.018 * face.unit * np.cos(theta) + 0.5, accent, ctx["alpha"] * entry, ctx["runtime"].kernels)
        if k < len(CROWN_PEAKS) - 1:  # un arco bajo entre una punta y la siguiente
            mid = (theta + CROWN_PEAKS[k + 1]) / 2
            gap = (CROWN_PEAKS[k + 1] - theta) / 2 - CROWN_PEAK_HALF
            arch = catmull_rom(np.array([at(mid + dx, base + dy * lift)[0] for dx, dy in ((-gap, 0.0), (-gap * 0.5, 0.07), (0.0, 0.1), (gap * 0.5, 0.07), (gap, 0.0))]), 5)
            lines.append((arch, main * 0.7))
    path = np.vstack(outline)  # un brillo que recorre las puntas
    run = (ctx["frame_index"] * 0.012 * float(knobs["speed"])) % 1.0
    shine = path[int(run * (len(path) - 1))]
    splat(ctx["layer"], float(shine[0]), float(shine[1]), 0.035 * face.unit + 0.6, accent, ctx["alpha"] * 0.8 * entry, ctx["runtime"].kernels)


DRAW = {"third_eye": _third_eye, "rune_shift": _rune_shift, "light_crown": _crown}


def face_symbol(shape: str, body, frame, scale, frame_index: int, runtime, layer, color, alpha: float, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    stage, t = phase(u)
    start = event.start_frame if event is not None else 0
    knobs = pick_knobs(shape, body.prefix, start, runtime.effect.style.variants)
    main, accent = (np.asarray(c, np.float32) for c in THEMES[shape])
    if knobs["palette"] == "chapter":
        main = np.asarray(color, np.float32)
    power = alpha * float(knobs["intensity"])
    ctx = {
        "sig": signals(runtime, frame_index, body.prefix), "st": runtime.swoosh.setdefault(f"_symbol:{shape}:{start}:{body.prefix}", {}),
        "u": u, "stage": stage, "frame_index": frame_index, "runtime": runtime, "layer": layer, "knobs": knobs, "seed": _seed(shape, body, event),
        "main": main, "accent": accent, "alpha": power * (1.0 - _ease(t) if stage == "exit" else 1.0),
        "width": max(1.0, 0.006 * face.unit) * float(knobs["stroke"]),
    }
    lines: list = []
    DRAW[shape](face, ctx, lines)
    left = melt(lines, u, face, layer, main, power, runtime.kernels, ctx["seed"], start=EXIT_AT)
    # Línea fina y nítida, con poco halo (con el neón del motor, las runas eran manchas). El motor la
    # pinta (curva, color, ancho): así la continuidad la transforma.
    ratio = (ctx["alpha"] if stage != "exit" else power) / max(alpha, 1e-6)
    return [(curve, np.asarray(tint, np.float32) * ratio, ctx["width"]) for curve, tint in left]
