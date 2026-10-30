"""Qué efectos van sobre la cara (pedido del usuario): con un rostro especial puesto (las máscaras de
terror, engine/horror_masks.py) no se pone nada más sobre la cara. La coreografía rechaza esas
opciones mientras dura la máscara (director/choreography.py) y el motor apaga las que ya estaban
encendidas cuando llega (engine/engine.py).
"""

from __future__ import annotations

from vfxglow.engine.costumes import FACE, HEAD
from vfxglow.engine.face_glow import FACE_GLOW
from vfxglow.engine.hand_props import DRINKS, SMOKES
from vfxglow.engine.horror_masks import HORROR_MASKS

# Tipos de efecto que siempre dibujan sobre la cara.
FACE_TYPES = ("face_toon", "eyewear", "face_linework", "eye_rings", "decal")
# Adornos que dibujan sobre la cara (o la tapan): los del catálogo cara menos los que giran
# alrededor de la cabeza, disfraces, caras de personaje, ojos encendidos, lo que va a la boca y el
# número del conteo.
FACE_SHAPES = (
    frozenset(FACE_GLOW) - {"rune_orbit"}
    | set(FACE) | set(HEAD)
    | {"venom", "iron_man", "devil_eyes", "heart_eyes", "glow_eyes", "lion_roar", "avatar_mark", "finger_number"}
    | set(DRINKS) | set(SMOKES)
)


def is_special(effect) -> bool:
    """Un rostro especial: una máscara de terror (dict del catálogo o Effect)."""
    return any(shape in HORROR_MASKS for shape in _shapes(effect))


def on_face(effect) -> bool:
    """El efecto dibuja sobre la cara (sin contar los rostros especiales)."""
    kind = effect.get("type") if isinstance(effect, dict) else effect.type
    if kind in FACE_TYPES:
        return True
    return kind == "adornment" and any(shape in FACE_SHAPES for shape in _shapes(effect))


def _shapes(effect) -> list[str]:
    if isinstance(effect, dict):
        return list(effect.get("style", {}).get("shapes") or [])
    return list(effect.style.shapes or [])
