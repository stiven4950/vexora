"""Brazo musculoso: contorno de neón del brazo extendido durante un golpe recto.

Se dibuja el borde de un brazo exagerado (hombro, bíceps abultado, codo estrecho, antebrazo,
muñeca y puño redondeado) sobre la cadena hombro-codo-muñeca, abierto en el hombro como si
saliera del cuerpo, con guiones de velocidad detrás del puño.

Solo aparece si el brazo está extendido (codo casi recto), apunta más hacia los lados que
hacia abajo (un brazo colgando también está recto) y la muñeca acaba de moverse rápido. Se
decide una vez por golpe con `style.chance`.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.analysis.schema import FrameRecord
from vfxglow.engine.anchors import joint_speed, torso_pixels
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import neon_layers, swoosh_keys
from vfxglow.geom import catmull_rom, normals

# Ángulo mínimo del codo (grados) y proporción horizontal mínima del brazo.
MIN_ELBOW = 150.0
MIN_LEVEL = 0.8
# Histéresis: un brazo que ya se dibuja sigue mientras esté razonablemente recto.
KEEP_ELBOW = 135.0
KEEP_LEVEL = 0.6
# Fotogramas de fundido de entrada: una aparición de un solo fotograma apenas se ve.
FADE_IN = 3
# Caída por fotograma de la actividad: un golpe sostenido se mantiene dibujado.
RELEASE = 0.9
# Perfil del medio ancho a lo largo del brazo (fracción de su longitud -> torsos).
PROFILE_T = np.array([0.0, 0.25, 0.47, 0.65, 0.85, 0.95, 1.0])
PROFILE_W = np.array([0.11, 0.16, 0.075, 0.12, 0.065, 0.1, 0.06])


def arm_chain(points: dict[str, np.ndarray], key: str) -> np.ndarray | None:
    """Hombro, codo y muñeca de la misma persona y lado que `key` (…:left_wrist)."""
    prefix, _, joint = key.rpartition(":")
    side = joint.split("_", 1)[0]
    names = [f"{side}_shoulder", f"{side}_elbow", f"{side}_wrist"]
    chain = [points.get(f"{prefix}:{name}" if prefix else name) for name in names]
    if any(point is None for point in chain):
        return None
    return np.stack(chain)


def is_punch_pose(chain: np.ndarray, min_elbow: float = MIN_ELBOW, min_level: float = MIN_LEVEL) -> bool:
    shoulder, elbow, wrist = chain
    upper, lower = shoulder - elbow, wrist - elbow
    norms = float(np.linalg.norm(upper) * np.linalg.norm(lower))
    if norms < 1e-6:
        return False
    angle = float(np.degrees(np.arccos(np.clip(upper @ lower / norms, -1.0, 1.0))))
    reach = wrist - shoulder
    return angle >= min_elbow and abs(reach[0]) >= min_level * abs(reach[1])


def draw_arm_outline(runtime, track: FrameRecord | None, points: dict[str, np.ndarray], frame_index: int, height: int, envelope: float, layer: np.ndarray) -> None:
    effect = runtime.effect
    style = effect.style
    torso = torso_pixels(points, height)
    joints = [token.strip() for token in effect.target.id.split(",") if token.strip()]
    activity: dict[str, float] = runtime.swoosh_activity
    strokes = []
    for key, person in swoosh_keys(track, joints):
        chain = arm_chain(points, key)
        speed = joint_speed(track, key) if chain is not None else 0.0
        floor = max(style.min_speed, 1e-6)
        target = float(np.clip((speed - floor) / floor, 0.0, 1.0))
        active = max(target, activity.get(key, 0.0) * RELEASE)
        activity[key] = active
        drawn = runtime.limb_frames.get(key, 0)
        if active < 0.05:
            runtime.swoosh_stroke.pop(key, None)
            runtime.limb_frames.pop(key, None)
            continue
        start = runtime.swoosh_stroke.setdefault(key, frame_index)
        seed = zlib.crc32(f"{style.seed_offset}:{key}:{start}".encode()) & 0xFFFFFFFF
        pose_ok = chain is not None and (
            is_punch_pose(chain, KEEP_ELBOW, KEEP_LEVEL) if drawn else is_punch_pose(chain)
        )
        if not pose_ok or envelope <= 0 or float(np.random.default_rng(seed).random()) >= style.chance:
            runtime.limb_frames.pop(key, None)
            continue
        drawn += 1
        runtime.limb_frames[key] = drawn
        active *= min(1.0, drawn / FADE_IN)
        wobble = np.random.default_rng(seed + frame_index // max(style.boil_frames, 1))
        color = np.asarray(style.colors[person % len(style.colors)], dtype=np.float32)
        width = max(1.2, style.thickness * torso)
        outline, dashes = muscle_arm(chain, torso * style.size * 2.0, wobble)
        strokes += neon_layers(outline, color, width, active * envelope)
        for dash in dashes:
            strokes += neon_layers(dash, color, width * 0.7, active * envelope * 0.8)
    stroke_batch(layer, strokes, style.hdr_gain)


def muscle_arm(chain: np.ndarray, scale: float, rng: np.random.Generator) -> tuple[np.ndarray, list[np.ndarray]]:
    """Contorno abierto en el hombro y guiones de velocidad. `scale` convierte el perfil a píxeles."""
    elbow, wrist = chain[1], chain[2]
    forward = wrist - elbow
    forward = forward / max(float(np.linalg.norm(forward)), 1e-6)
    spine = catmull_rom(np.vstack([chain, wrist + forward * scale * 0.12]), samples_per_seg=10)
    seg = np.linalg.norm(np.diff(spine, axis=0), axis=1)
    t = np.concatenate([[0.0], np.cumsum(seg)]) / max(float(seg.sum()), 1e-6)
    half = np.interp(t, PROFILE_T, PROFILE_W) * scale * (1 + rng.normal(0, 0.05, len(t)))
    nrm = normals(spine)
    left = spine + nrm * half[:, None]
    right = spine - nrm * half[:, None]
    tip, side = spine[-1], nrm[-1]
    angles = np.linspace(0.0, np.pi, 10)
    cap = tip + (np.cos(angles)[:, None] * side + np.sin(angles)[:, None] * forward) * half[-1]
    outline = np.vstack([left, cap, right[::-1]])
    dashes = []
    for index, at in enumerate((0.6, 0.72, 0.84)):
        point = np.interp(at, t, spine[:, 0]), np.interp(at, t, spine[:, 1])
        base = np.array(point) + side * np.interp(at, t, half) * (1.8 if index % 2 == 0 else -1.8)
        dashes.append(np.array([base - forward * scale * 0.25, base - forward * scale * 0.08]))
    return outline, dashes
