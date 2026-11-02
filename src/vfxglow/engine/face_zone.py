"""Qué efectos van sobre la cara (pedido del usuario): con un rostro especial puesto (las máscaras de
terror, engine/horror_masks.py) no se pone nada más sobre la cara. La coreografía rechaza esas
opciones mientras dura la máscara (director/choreography.py) y el motor apaga las que ya estaban
encendidas cuando llega (engine/engine.py).

Con un efecto a la vez (`one_at_a_time`), la cobertura (`coverage`) deja que un efecto periférico
acompañe al principal de la cara.
"""

from __future__ import annotations

from vfxglow.engine.costumes import FACE, HEAD
from vfxglow.engine.eye_family import EYES
from vfxglow.engine.face_creatures import CREATURES
from vfxglow.engine.face_glow import FACE_GLOW
from vfxglow.engine.face_moods import MOODS
from vfxglow.engine.face_wounds import WOUNDS
from vfxglow.engine.hand_props import DRINKS, SMOKES
from vfxglow.engine.head_beasts import HEAD_BEASTS
from vfxglow.engine.horror_masks import HORROR_MASKS
from vfxglow.engine.living_fx import ON_THE_FACE

# Tipos de efecto que siempre dibujan sobre la cara.
FACE_TYPES = ("face_toon", "eyewear", "face_linework", "eye_rings", "decal")
# Adornos que dibujan sobre la cara (o la tapan): los del catálogo cara menos los que giran
# alrededor de la cabeza, disfraces, caras de personaje, ojos encendidos, lo que va a la boca y el
# número del conteo.
FACE_SHAPES = (
    frozenset(FACE_GLOW) - {"rune_orbit"}
    | set(FACE) | set(HEAD)
    | {"venom", "iron_man", "devil_eyes", "heart_eyes", "glow_eyes", "lion_roar", "avatar_mark", "finger_number"}
    | set(DRINKS) | set(SMOKES) | set(CREATURES) | set(WOUNDS) | set(MOODS) | set(HEAD_BEASTS) | set(ON_THE_FACE) | set(EYES)
)


# Cobertura de la cara (pedido del usuario): un solo efecto principal sobre la cara, y con él puede
# convivir uno periférico (lo que rodea la cabeza sin tapar ojos ni boca). Lo que cubre toda la cara
# (alta) no admite nada al lado. Lo que no está en ninguna lista cuenta como "medium" (principal).
PERIPHERAL = frozenset(
    {"rune_orbit", "face_emanate", "head_echo", "emotion_burst", "shock_burst", "skeleton_dance", "raven", "fairies"}
)
# Pasan por encima de los rasgos, así que son principales: la lluvia de destellos cae sobre la cara
# (facil_1, fotograma 600: tapaba el ojo junto a Cleopatra) y el remolino cruza por delante de ojos y
# boca en media vuelta (facil_1, fotograma 265, sobre los ojos de galaxia).
LOW = frozenset({"brow_lines", "cheek_glow", "smile_sparks", "eye_sparks", "glint", "stars", "exclaim", "question", "face_sparkle_rain", "face_swirl"})
HIGH = frozenset(HORROR_MASKS) | {"blink_mask", "face_mesh_live", "face_crystal", "caricature"} | set(FACE)
RANK = {"peripheral": 0, "low": 1, "medium": 2, "high": 3}


def coverage(effect) -> str:
    """Cuánto de la cara tapa un efecto (dict del catálogo o Effect): peripheral, low, medium o high.
    Con varias formas sorteables, la que más tapa."""
    kind = effect.get("type") if isinstance(effect, dict) else effect.type
    shapes = _shapes(effect)
    if kind == "face_toon" and "caricature" in shapes or any(shape in HIGH for shape in shapes):
        return "high"
    if kind == "adornment" and shapes and all(shape in PERIPHERAL for shape in shapes):
        return "peripheral"
    if kind == "adornment" and shapes and all(shape in LOW or shape in PERIPHERAL for shape in shapes):
        return "low"
    return "medium"


def fits_beside(new: str, others: list[str]) -> bool:
    """Si un efecto de cobertura `new` puede encenderse junto a los que ya están (`others`): un
    principal (low/medium) con un periférico, nunca dos de una misma clase ni nada con uno alto."""
    if not others:
        return True
    if new == "high" or "high" in others:
        return False
    if new == "peripheral":
        return "peripheral" not in others
    return all(other == "peripheral" for other in others)


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
