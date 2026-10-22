"""Dibujos a mano alzada sobre el cuerpo (referencia video_34, docs/referencias/video_34.md).

Son adornos (`type: adornment`, `style.shapes`): cada uno se ancla a las articulaciones de la
persona del evento y escala con su ancho de hombros. Medidos sobre la referencia:

- head_ring: aro alrededor de la cabeza a la altura de la frente (0-2,5 s).
- heart_eyes: un corazón blanco relleno sobre cada ojo (0-2,5 s).
- lapel: el borde delantero del saco, del cuello a la cadera (0,5-1,5 s).
- wrist_ring: aro alrededor de la muñeca más alejada del cuerpo (1,0 s).
- hand_heart: corazón grande en la mano y dos pequeños que suben (1,0 s; 9,0 s; 19,5 s).
- rose: una rosa en la mano, a la altura del pecho, con su tallo (3,6-4,5 s).
- neck_ring: lazo alrededor del cuello (3,6-4,5 s).
- swirl: remolino que sale de la mano y se enrosca hacia afuera (4,0-4,5 s).
- big_note: una nota grande en la mano (6,5 s).
- shoulder_bolts: rayos que recorren hombros y brazos (7,5 s; 8,6 s; 11,0 s).
- head_bolts: rayos que se erizan sobre la cabeza (9,5 s; 18,1 s).
- hand_ring: aro de guiones que gira alrededor de la mano (12-14 s; 32 s).
- moon: luna creciente detrás de la cabeza (15,0 s; 16,4 s).
- chest_burst: la luz que estalla en el pecho al abrirse el saco (17,1 s).
- body_bolts: rayos por el cuerpo y bajando por una pierna (14,6-15,4 s; 17,6 s).
- foot_spark: destello y chispitas en la punta del pie que pisa (21,5-23 s).
- floor_arc: estela en arco sobre el piso que barre el pie (27,2 s).
- leg_line: una línea continua por el frente de la pierna, de la cadera al tobillo.
- leg_string: una tira, como un hilo, de la banda del tobillo hasta la mano del mismo lado, con
  una curva al final; sigue a la mano (33-34,8 s). Una por pierna.
- side_edges: los costados del saco de espaldas, de la axila al bajo (28,2 s; 30,1 s).
- shoulder_arcs: arcos que bajan por hombros y brazos de espaldas (28,7-29,6 s).
- foot_ring: aro en el piso alrededor del pie que se levanta (9,8-10,6 s).
- foot_bolts: rayos alrededor del pie (16,9-17,8 s).
- glow_eyes: ojos encendidos, dos destellos blancos con un resplandor del color sobre la cara (18 s).
- spin_arcs: dos arcos grandes que giran alrededor del cuerpo en un giro (31,0 s).

Los rayos cambian de forma cada BOLT_FRAMES fotogramas, como un dibujo animado a mano.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.characters import CHARACTERS, character
from vfxglow.engine.costumes import COSTUMES, costume
from vfxglow.engine.critters import CRITTERS, critter
from vfxglow.engine.fire_creatures import FIRE_CREATURES, fire_creature
from vfxglow.engine.firebend import FIREBEND, firebend
from vfxglow.engine.airbend import AIRBEND, airbend
from vfxglow.engine.earthbend import EARTHBEND, earthbend
from vfxglow.engine.waterbend import WATERBEND, waterbend
from vfxglow.engine.fist import FISTS, fist_effect
from vfxglow.engine.gun import GUNS, gun
from vfxglow.engine.hand_props import HAND_PROPS, hand_prop
from vfxglow.engine.stories import STORIES, story
from vfxglow.engine.dresses import DRESSES, dress
from vfxglow.engine.shoes import SHOES, shoe
from vfxglow.engine.duo_fx import DUO_FX, duo_fx
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
BOLT_FRAMES = 2
DOODLES = (
    "head_ring", "lapel", "wrist_ring", "hand_heart", "rose", "neck_ring", "swirl", "big_note",
    "shoulder_bolts", "head_bolts", "hand_ring", "moon", "chest_burst", "body_bolts", "foot_spark",
    "floor_arc", "leg_line", "leg_string", "side_edges", "shoulder_arcs", "heart_eyes", "spin_arcs", "glow_eyes",
    "foot_ring", "foot_bolts",
) + DUO_FX + COSTUMES + SHOES + DRESSES + CRITTERS + STORIES + GUNS + FISTS + HAND_PROPS + FIREBEND + FIRE_CREATURES + WATERBEND + AIRBEND + EARTHBEND + CHARACTERS
WHITE = np.array([1.0, 1.0, 1.0], np.float32)


def _ellipse(center, rx, ry, across, up, a0=0.0, a1=TAU, n=40) -> np.ndarray:
    t = np.linspace(a0, a1, n)
    return center + np.cos(t)[:, None] * across * rx + np.sin(t)[:, None] * up * ry


def _heart(center: np.ndarray, size: float) -> np.ndarray:
    t = np.linspace(0.0, TAU, 48)
    x = 16 * np.sin(t) ** 3 / 17
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)) / 17
    return center + np.stack([x, y], axis=1) * size


def zigzag(path: np.ndarray, amp: float, rng: np.random.Generator, step: float) -> np.ndarray:
    """Un rayo a lo largo de `path`: puntos cada `step` px desplazados de lado al azar."""
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    total = float(seg.sum())
    if total < 1.0:
        return path
    n = max(int(total / max(step, 1.0)), 3)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    u = np.linspace(0.0, total, n)
    pts = np.stack([np.interp(u, s, path[:, 0]), np.interp(u, s, path[:, 1])], axis=1)
    tangent = np.gradient(pts, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
    offset = rng.uniform(-amp, amp, n)
    offset[0] = offset[-1] = 0.0
    return pts + normal * offset[:, None]


def _bolt(path: np.ndarray, scale: float, rng: np.random.Generator, branches: int = 1) -> list[np.ndarray]:
    """Rayo con ramitas cortas que salen de puntos al azar, y hebras que se ramifican de ellas."""
    from vfxglow.engine.duo_fx import branched

    main = zigzag(path, 0.09 * scale, rng, 0.07 * scale)
    out = [main]
    for _ in range(branches + 2):
        k = int(rng.integers(1, max(len(main) - 1, 2)))
        angle = rng.uniform(0, TAU)
        out += branched(main[k], np.array([np.cos(angle), np.sin(angle)]), scale * rng.uniform(0.1, 0.2), rng, 1)
    for _ in range(0):
        k = int(rng.integers(1, max(len(main) - 1, 2)))
        angle = rng.uniform(0, TAU)
        tip = main[k] + np.array([np.cos(angle), np.sin(angle)]) * scale * rng.uniform(0.12, 0.25)
        out.append(zigzag(np.array([main[k], tip]), 0.03 * scale, rng, 0.04 * scale))
    return out


def _side_wrist(body, center: np.ndarray):
    """(lado, muñeca) de la mano más alejada del centro del pecho: la que hace el gesto."""
    best = None
    for side in ("left", "right"):
        wrist = body.get(f"{side}_wrist")
        if wrist is not None and (best is None or np.linalg.norm(wrist - center) > np.linalg.norm(best[1] - center)):
            best = (side, wrist)
    return best


# De perfil: cuánto tiene que adelantarse la nariz respecto al centro de los hombros (en anchos
# de hombros) para decir hacia qué lado mira la persona.
PROFILE_NOSE = 0.25


def far_side(body) -> str | None:
    """El lado del cuerpo que queda al fondo, de perfil ("left"/"right"), o None si está de frente o
    de espaldas. Mirando a la derecha de la imagen, el lado izquierdo queda lejos de la cámara (la
    profundidad de MediaPipe lo confirma en video_34, seg. 33-34: cadera izquierda más lejos)."""
    from vfxglow.engine.bodyglow import facing

    if facing(body) != "side":
        return None
    nose, a, b = body.get("nose"), body.get("left_shoulder"), body.get("right_shoulder")
    if nose is None or a is None or b is None:
        return None
    width = max(float(np.linalg.norm(a - b)), 1.0)
    ahead = float(nose[0] - (a[0] + b[0]) / 2) / max(width, body.scale * 0.5 if body.scale else 1.0)
    if abs(ahead) < PROFILE_NOSE * 0.5:
        return None
    return "left" if ahead > 0 else "right"


def _event_side(event) -> str | None:
    if event is None:
        return None
    for side in ("left", "right"):
        if side in event.target or event.kind == side:
            return side
    return None


def doodle(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event=None) -> list[np.ndarray]:
    if shape in CRITTERS:
        return critter(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event)
    if shape in STORIES:
        return story(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event)
    if shape in GUNS:
        return gun(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in FISTS:
        return fist_effect(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in HAND_PROPS:
        return hand_prop(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in FIREBEND:
        return firebend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in EARTHBEND:
        return earthbend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in AIRBEND:
        return airbend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in WATERBEND:
        return waterbend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in FIRE_CREATURES:
        return fire_creature(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in CHARACTERS:
        return character(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event)
    if shape in DRESSES:
        return dress(shape, body, frame, scale, frame_index, layer, color, alpha)
    if shape in SHOES:
        return shoe(shape, body, frame, scale, frame_index, layer, color, alpha)
    if shape in COSTUMES:
        from vfxglow.engine.bodyglow import facing

        return costume(shape, body, frame, scale, frame_index, layer, color, alpha, facing(body) == "back")
    if shape in DUO_FX:
        return duo_fx(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event)
    center, across, down = frame
    up = -down
    age = runtime.active_frames
    grow = float(np.clip(age / 6.0, 0.0, 1.0))
    rng = np.random.default_rng((seed + frame_index // BOLT_FRAMES) & 0xFFFFFFFF)
    hips = body.mid("left_hip", "right_hip")
    if shape in ("heart_eyes", "glow_eyes"):
        eyes = [body.get("left_eye"), body.get("right_eye")]
        nose = body.get("nose")
        if any(e is None for e in eyes):
            if nose is None:
                return []
            # Sin ojos en la pose: a los lados, un poco arriba de la nariz.
            eyes = [nose + up * 0.08 * scale + across * s * 0.09 * scale for s in (-1.0, 1.0)]
        size = max(0.06 * scale, float(np.linalg.norm(eyes[0] - eyes[1])) * 0.38)
        out = []
        if shape == "glow_eyes":
            face = (eyes[0] + eyes[1]) / 2
            splat(layer, float(face[0]), float(face[1]), 0.28 * scale, color * 1.2, alpha * 0.6, runtime.kernels)
            for eye in eyes:
                splat(layer, float(eye[0]), float(eye[1]), size * 0.6, WHITE * 1.2, alpha, runtime.kernels)
            return []
        for eye in eyes:
            heart = _heart(eye, size)
            fill_polygon(layer, heart, WHITE, alpha * 0.9, 1.0, feather=1.0)
            out.append(heart)
        return out
    if shape == "head_ring" and head is not None:
        return [_ellipse(head + up * 0.18 * scale, 0.36 * scale, 0.09 * scale, across, up)]
    if shape == "lapel" and hips is not None:
        side = 1.0 if (seed % 2) else -1.0
        collar = center + across * side * 0.18 * scale + up * 0.02 * scale
        bend = center + across * side * 0.36 * scale + down * float(np.linalg.norm(hips - center)) * 0.45
        hem = hips + across * side * 0.45 * scale + down * 0.14 * scale
        t = np.linspace(0, 1, 16)[:, None]
        curve = (1 - t) ** 2 * collar + 2 * (1 - t) * t * bend + t**2 * hem
        return [curve[: max(int(len(curve) * min(age / 8.0, 1.0)), 2)]]
    if shape in ("wrist_ring", "hand_heart", "rose", "swirl", "big_note", "hand_ring"):
        side = _event_side(event)
        picked = (side, body.get(f"{side}_wrist")) if side and body.get(f"{side}_wrist") is not None else _side_wrist(body, center)
        if picked is None:
            return []
        side, wrist = picked
        elbow = body.get(f"{side}_elbow")
        along = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6) if elbow is not None else down
        hand = wrist + along * 0.08 * scale
        if shape == "wrist_ring":
            normal = np.array([-along[1], along[0]])
            return [_ellipse(wrist, 0.16 * scale, 0.05 * scale, normal, along)]
        if shape == "hand_ring":
            spin = frame_index * 0.35
            r = 0.2 * scale
            dashes = [_ellipse(hand, r, r, across, up, spin + k * TAU / 5, spin + k * TAU / 5 + TAU / 8, 8) for k in range(5)]
            return dashes + [_ellipse(hand, r * 0.55, r * 0.55, across, up, -spin, -spin + TAU * 0.6, 16)]
        if shape == "hand_heart":
            size = 0.3 * scale * (0.6 + 0.4 * grow)
            lift = up * 0.02 * scale * age
            main = _heart(hand + lift * 0.3 + up * 0.1 * scale, size)
            fill_polygon(layer, main, WHITE * 1.5, alpha * 0.9, 1.0, feather=2.0)
            out = [main]
            for k, (dx, delay) in enumerate(((-0.3, 4), (0.35, 8))):
                if age > delay:
                    rise = (age - delay) * 0.025 * scale
                    out.append(_heart(hand + across * dx * scale + up * (0.15 * scale + rise), size * (0.3 + 0.1 * k)))
            splat(layer, float(hand[0]), float(hand[1]), size * 1.2, color * 1.2, alpha * 0.5, runtime.kernels)
            return out
        if shape == "big_note":
            size = 0.6 * scale * (0.6 + 0.4 * grow)
            head_n = hand + up * 0.05 * scale
            stem_top = head_n + across * 0.07 * size / 0.3 + up * size * 1.3
            note = _ellipse(head_n, 0.09 * size / 0.3, 0.065 * size / 0.3, across, up)
            flag = np.array([stem_top, stem_top + across * size * 0.35 - up * size * 0.25, stem_top + across * size * 0.3 - up * size * 0.55])
            return [note, np.array([head_n + across * 0.08 * size / 0.3, stem_top]), flag]
        if shape == "rose":
            # La flor a la altura del pecho, sobre la mano; el tallo baja a la mano.
            bloom = center + down * 0.2 * scale + (hand - center) * 0.4 + up * 0.3 * scale
            t = np.linspace(0, TAU * 2.2, 40)
            r = (0.05 + 0.07 * t / (TAU * 2.2)) * scale
            spiral = bloom + np.stack([np.cos(t) * r, np.sin(t) * r * 0.8], axis=1)
            cup = _ellipse(bloom, 0.17 * scale, 0.15 * scale, across, up, np.pi * 1.05, np.pi * 1.95, 14)
            petals = [bloom + across * s * 0.15 * scale + up * 0.03 * scale + _ellipse(np.zeros(2), 0.07 * scale, 0.1 * scale, across, up)[:22] for s in (-1, 1)]
            stem = np.array([bloom - up * 0.1 * scale, (bloom + hand) / 2 + across * 0.03 * scale, hand])
            leaf = np.array([(bloom + hand) / 2, (bloom + hand) / 2 + across * 0.1 * scale + up * 0.04 * scale, (bloom + hand) / 2 + across * 0.02 * scale - up * 0.03 * scale])
            return [spiral, cup, *petals, stem, leaf]
        if shape == "swirl":
            # Remolino: sube desde la mano, abriéndose hacia afuera, y se enrosca (seg. 4,0-4,5).
            outward = (hand - center) / max(float(np.linalg.norm(hand - center)), 1e-6)
            out_dir = up * 0.8 + outward * 0.6
            out_dir = out_dir / max(float(np.linalg.norm(out_dir)), 1e-6)
            t = np.linspace(0, 1, 60)[: max(int(60 * min(age / 5.0, 1.0)), 3)]
            spine = hand[None, :] + out_dir[None, :] * (t[:, None] * 0.9 * scale)
            normal = np.array([-out_dir[1], out_dir[0]])
            loops = np.sin(t * TAU * 2.5)[:, None] * normal * 0.18 * scale * (0.4 + t[:, None]) + np.cos(t * TAU * 2.5)[:, None] * out_dir * 0.1 * scale
            return [spine + loops]
    if shape == "spin_arcs" and hips is not None:
        chest = center + (hips - center) * 0.35
        r = 0.95 * scale
        spin = age * 0.35
        return [_ellipse(chest, r, r * 1.15, across, up, spin + k * np.pi, spin + k * np.pi + 1.6, 24) for k in range(2)]
    if shape == "neck_ring":
        neck = center + up * 0.08 * scale
        return [_ellipse(neck, 0.24 * scale, 0.09 * scale, across, up)]
    if shape == "shoulder_bolts":
        # Por encima de los hombros y bajando hasta el codo (no el brazo entero, seg. 7,5).
        path = []
        for side in ("left", "right"):
            chain = [body.get(f"{side}_elbow"), body.get(f"{side}_shoulder")]
            chain = [p + up * 0.05 * scale for p in chain if p is not None]
            path.append(chain if side == "left" else chain[::-1])
        line = np.array(path[0] + [center + up * 0.1 * scale] + path[1]) if path[0] or path[1] else None
        return _bolt(line, scale, rng, 2) if line is not None and len(line) >= 2 else []
    if shape == "head_bolts" and head is not None:
        out = []
        for k in range(4):
            angle = np.pi * (0.15 + 0.7 * k / 3)
            base = head + (across * np.cos(angle) + up * np.sin(angle)) * 0.28 * scale
            tip = base + (across * np.cos(angle) + up * np.sin(angle)) * 0.22 * scale
            out.append(zigzag(np.array([base, tip]), 0.04 * scale, rng, 0.04 * scale))
        return out
    if shape == "moon" and head is not None:
        # Creciente detrás de la cabeza (seg. 15 y 16,4).
        # Hacia el lado de afuera del cuadro (A, a la derecha, a los 15 s; B, a la izquierda, a los 16,4).
        side = 1.0 if (head[0] > layer.shape[1] / 2) == (across[0] > 0) else -1.0
        r = 0.5 * scale
        c = head + across * side * 0.3 * scale + up * 0.08 * scale
        outer = _ellipse(c, r, r, across, up, -np.pi / 2 - 1.2, np.pi / 2 + 1.2, 40) if side > 0 else _ellipse(c, r, r, across, up, np.pi / 2 - 1.2 + np.pi, np.pi * 1.5 + 1.2 + np.pi, 40)
        inner_c = c - across * side * 0.18 * scale
        inner = _ellipse(inner_c, r * 0.85, r * 0.85, across, up, -np.pi / 2 - 1.0, np.pi / 2 + 1.0, 30) if side > 0 else _ellipse(inner_c, r * 0.85, r * 0.85, across, up, np.pi / 2 - 1.0 + np.pi, np.pi * 1.5 + 1.0 + np.pi, 30)
        # Media luna rellena de blanco (el disco menos otro corrido hacia la cara).
        disc = _ellipse(c, r, r, across, up, 0, TAU, 48)
        bite = _ellipse(inner_c, r * 0.85, r * 0.85, across, up, 0, TAU, 48)
        # Blanca (como en la referencia), con un halo suave del color de la persona.
        fill_polygon(layer, disc, WHITE * 1.05, alpha * 0.9, 1.0, feather=3.0, holes=[bite])
        mid = c + across * side * r * 0.5
        splat(layer, float(mid[0]), float(mid[1]), r * 0.9, color * 0.8, alpha * 0.35, runtime.kernels)
        return []
    if shape == "chest_burst" and hips is not None:
        chest = center + (hips - center) * 0.3
        pulse = 0.85 + 0.15 * np.sin(frame_index * 0.7)
        splat(layer, float(chest[0]), float(chest[1]), 0.35 * scale * pulse, WHITE * 1.8, alpha, runtime.kernels)
        splat(layer, float(chest[0]), float(chest[1]), 0.6 * scale * pulse, color * 1.4, alpha * 0.6, runtime.kernels)
        out = []
        for side in (-1.0, 1.0):
            edge = np.array([center + across * side * 0.12 * scale, hips + across * side * 0.3 * scale + down * 0.1 * scale])
            out += _bolt(edge, scale * 0.7, rng, 1)
        return out
    if shape == "body_bolts" and hips is not None:
        side = "left" if (seed % 2) else "right"
        knee, ankle = body.get(f"{side}_knee"), body.get(f"{side}_ankle")
        out = []
        shoulder = body.get(f"{'right' if side == 'left' else 'left'}_shoulder")
        if shoulder is not None:
            out += _bolt(np.array([shoulder, center + down * 0.2 * scale, hips]), scale, rng, 2)
        if knee is not None:
            # Hasta la rodilla: en la referencia los rayos se quedan en el cuerpo (seg. 14,5).
            out += _bolt(np.array([body.get(f"{side}_hip") if body.get(f"{side}_hip") is not None else hips, knee]), scale, rng, 1)
        return out
    if shape == "leg_string":
        # Del tobillo (encima de la banda) a la mano del mismo lado, como un hilo que la mano
        # sostiene: curva en S suave, que se dibuja de abajo hacia arriba.
        out = []
        reveal = min((age + 1) / 6.0, 1.0)
        far = far_side(body)
        for side in ("left", "right"):
            ankle, knee, wrist = body.get(f"{side}_ankle"), body.get(f"{side}_knee"), body.get(f"{side}_wrist")
            if ankle is None or wrist is None:
                continue
            start = ankle + up * 0.16 * scale
            span = wrist - start
            if float(np.linalg.norm(span)) < 0.3 * scale:
                continue
            side_dir = np.array([-span[1], span[0]]) / max(float(np.linalg.norm(span)), 1e-6)
            # La tira pasa por delante de la rodilla y llega a la mano por fuera.
            bow = 0.12 * scale * (1.0 if (side_dir @ across) >= 0 else -1.0)
            c1 = start + span * 0.35 + side_dir * bow
            c2 = start + span * 0.75 - side_dir * bow * 0.6
            if knee is not None:
                c1 = (c1 + knee + across * 0.04 * scale) / 2
            t = np.linspace(0, 1, 40)[:, None]
            curve = (1 - t) ** 3 * start + 3 * (1 - t) ** 2 * t * c1 + 3 * (1 - t) * t**2 * c2 + t**3 * wrist
            # Rizo en la mano (seg. 34,0).
            direction = (curve[-1] - curve[-4]) / max(float(np.linalg.norm(curve[-1] - curve[-4])), 1e-6)
            normal = np.array([-direction[1], direction[0]])
            hook_t = np.linspace(0, np.pi * 1.1, 10)
            hook = wrist + (direction[None, :] * np.sin(hook_t)[:, None] + normal[None, :] * (1 - np.cos(hook_t))[:, None]) * 0.05 * scale
            curve = np.vstack([curve, hook[1:]])
            curve = curve[: max(int(len(curve) * reveal), 2)]
            if side == far:
                # Perspectiva: la tira de la pierna de atrás queda al otro lado del cuerpo; solo se
                # ve lo que sale de la silueta (P6: las partes tapadas no se dibujan).
                from vfxglow.engine.duo_fx import body_mask, visible

                mask = body_mask(body, layer.shape[:2], scale)
                out += [curve[a:b] for a, b in visible(curve, -np.ones(len(curve)), mask)]
            else:
                out.append(curve)
        return out
    if shape in ("foot_spark", "floor_arc", "leg_line", "foot_ring", "foot_bolts"):
        side = _event_side(event)
        if side is None:
            ankles = {s: body.get(f"{s}_ankle") for s in ("left", "right")}
            seen = {s: a for s, a in ankles.items() if a is not None}
            if not seen:
                return []
            # La pierna de adelante: el tobillo más bajo en el cuadro.
            side = max(seen, key=lambda s: seen[s][1])
        ankle, toe, knee, hip = (body.get(f"{side}_{n}") for n in ("ankle", "foot_index", "knee", "hip"))
        foot = toe if toe is not None else ankle
        if foot is None:
            return []
        if shape == "foot_spark":
            from vfxglow.engine.burst import sparkle

            # Resplandor en la punta del pie (seg. 21,5-23: ~0,1 hombros de blanco y halo).
            splat(layer, float(foot[0]), float(foot[1]), 0.1 * scale, WHITE * 1.5, alpha, runtime.kernels)
            splat(layer, float(foot[0]), float(foot[1]), 0.22 * scale, color * 1.3, alpha * 0.6, runtime.kernels)
            sparks = []
            for k in range(4):
                angle = rng.uniform(0, TAU)
                pos = foot + np.array([np.cos(angle), np.sin(angle) * 0.6]) * scale * rng.uniform(0.1, 0.25)
                sparks.append(sparkle(pos, 0.04 * scale))
            return sparks
        if shape == "foot_ring":
            return [_ellipse(foot + down * 0.02 * scale, 0.32 * scale, 0.08 * scale, across, up)]
        if shape == "foot_bolts":
            out = []
            for k in range(3):
                angle = rng.uniform(0, TAU)
                tip = foot + np.array([np.cos(angle), np.sin(angle) * 0.5]) * scale * rng.uniform(0.2, 0.35)
                out.append(zigzag(np.array([foot + up * 0.05 * scale, tip]), 0.05 * scale, rng, 0.05 * scale))
            return out
        if shape == "floor_arc":
            ground = foot + down * 0.04 * scale
            sweep = min(age / 8.0, 1.0)
            a1 = np.pi * (0.1 + 0.9 * sweep)
            arc = _ellipse(ground + across * 0.45 * scale, 0.75 * scale, 0.12 * scale, across, up, np.pi + 0.2, np.pi + 0.2 + a1, 30)
            return [arc]
        if shape == "leg_line" and hip is not None and knee is not None and ankle is not None:
            # Una curva suave de la cadera al tobillo que pasa cerca de la rodilla (no quebrada).
            forward = across * (0.05 * scale)
            t = np.linspace(0, 1, 30)[:, None]
            control = 2 * knee - (hip + ankle) / 2
            control = (control + (hip + ankle) / 2) / 2 + (knee - (hip + ankle) / 2) * 0.5
            line = (1 - t) ** 2 * hip + 2 * (1 - t) * t * control + t**2 * (ankle - (ankle - knee) * 0.05) + forward
            return [line[: max(int(len(line) * min(age / 6.0, 1.0)), 2)]]
        return []
    if shape == "side_edges" and hips is not None:
        out = []
        for s in (-1.0, 1.0):
            top = center + across * s * 0.48 * scale + down * 0.22 * scale
            bottom = hips + across * s * 0.42 * scale + down * 0.18 * scale
            mid = (top + bottom) / 2 + across * s * 0.05 * scale
            t = np.linspace(0, 1, 14)[:, None]
            out.append((1 - t) ** 2 * top + 2 * (1 - t) * t * mid + t**2 * bottom)
        return out
    if shape == "shoulder_arcs":
        out = []
        for side in ("left", "right"):
            shoulder, elbow = body.get(f"{side}_shoulder"), body.get(f"{side}_elbow")
            if shoulder is None or elbow is None:
                continue
            outward = (shoulder - center) / max(float(np.linalg.norm(shoulder - center)), 1e-6)
            top = center + (shoulder - center) * 0.55 + up * 0.08 * scale
            peak = shoulder + outward * 0.1 * scale + up * 0.06 * scale
            low = elbow + outward * 0.08 * scale
            t = np.linspace(0, 1, 16)[:, None]
            out.append((1 - t) ** 2 * top + 2 * (1 - t) * t * peak + t**2 * low)
        return out
    return []


def doodle_seed(style_offset: int, key) -> int:
    return zlib.crc32(f"{style_offset}:doodle:{key}".encode()) & 0xFFFFFFFF
