"""El mini yo: una copia diminuta de la cara, hecha de luz, flota junto a la cabeza.

Sale de la misma malla facial, así que repite cada gesto sin que nadie lo programe: boca, cejas, ojos,
giro. No deforma ni reemplaza a la persona (son líneas). Lo diminuto va con poco halo. Al final salta
hacia la cámara y se deshace en polvo.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _seg
from vfxglow.engine.dissolve import disintegrate, fine
from vfxglow.engine.raster import splat

CHAINS = ("face_oval", "right_eye", "left_eye", "right_brow", "left_brow", "lips_outer", "lips_inner", "nose_bridge", "nose_base")
HOLO = np.array([0.45, 0.9, 1.0], np.float32)
# Tamaño respecto a la cara real, tope respecto al ancho del cuadro y distancia a la cabeza.
RATIO = 0.36
MAX_WIDTH = 0.2
BESIDE = 2.0
# Sigue a la cabeza con retraso (fracción por cuadro de 30 fps): se nota que flota.
FOLLOW = 0.14
BOB = 0.1
JUMP_AT = 0.84
MESH_EVERY = 9


def mini_me(face, u: float, frame_index: int, runtime, layer, color, alpha: float, seed: int) -> list:
    height, width = layer.shape[:2]
    chains = [line for line in (face.feature(name) for name in CHAINS) if line is not None and len(line) >= 2]
    if not chains:
        return []
    oval = chains[0]
    head = (oval.min(axis=0) + oval.max(axis=0)) / 2.0
    ratio = min(RATIO, MAX_WIDTH * width / max(float(np.ptp(oval[:, 0])), 1.0))
    half = np.ptp(oval, axis=0) * ratio / 2.0
    st = runtime.swoosh.setdefault(f"_mini:{seed}", {})
    if "side" not in st:  # del lado con más lugar
        st["side"] = -1.0 if float(head[0]) > width / 2.0 else 1.0
    margin = half + 0.03 * width
    wanted = head + np.array([st["side"] * BESIDE * face.unit, -0.9 * face.unit])
    wanted = np.clip(wanted, margin, np.array([width, height]) - margin)
    old = st.get("at")
    st["at"] = wanted if old is None else old + (wanted - old) * FOLLOW
    at = st["at"] + np.array([0.0, np.sin(frame_index * 0.09) * BOB * face.unit])
    grow = _ease(_seg(u, 0.0, 0.14))
    jump = _ease(_seg(u, JUMP_AT, 1.0))
    size = ratio * grow * (1.0 + 2.4 * jump)
    at = at + (np.array([width / 2.0, height * 0.55]) - at) * jump
    tint = np.asarray(color, np.float32) * 0.35 + HOLO * 0.65
    curves = [at + (line - head) * size for line in chains]
    if jump > 0.0:
        left = disintegrate([(c, tint) for c in curves], jump, face.unit, layer, alpha, runtime.kernels, seed)
        fine([c for c, _ in left], tint, alpha, layer, width=1.2)
        return []
    fine(curves, tint, alpha, layer, width=1.1)
    names = sorted(k for k in face.points if k.startswith("face_") and k[5:].isdigit())
    for name in names[::MESH_EVERY]:  # la malla: puntos, que siguen la forma sin llenar de líneas
        p = at + (face.points[name] - head) * size
        splat(layer, float(p[0]), float(p[1]), 1.2, tint, alpha * 0.55, runtime.kernels)
    # La barra de escaneo que baja por la cabeza diminuta y el zócalo del que se proyecta.
    y = float(at[1]) + half[1] * grow * np.sin(frame_index * 0.12)
    fine([np.array([[at[0] - half[0] * grow, y], [at[0] + half[0] * grow, y]])], tint, alpha * 0.45, layer, width=1.0)
    t = np.linspace(0.0, 2.0 * np.pi, 32)
    base = at + np.array([0.0, half[1] * grow * 1.25])
    fine([base + np.stack([np.cos(t) * half[0] * 0.8, np.sin(t) * half[0] * 0.16], axis=1)], tint, alpha * 0.8, layer, width=1.0)
    return []
