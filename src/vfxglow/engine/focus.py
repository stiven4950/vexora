"""Nada compite con el protagonista (docs/criterio_de_analisis.md, P1).

Cada efecto dibuja sobre una región (brazo, piernas, cabeza, torso, el objeto). Si el guion trae
la línea de atención, un efecto cuya región no es protagonista en ese momento se apaga con un
fundido corto, y vuelve cuando su región recupera el foco. Los efectos sin región clara (rayos
entre personas, partículas globales) no se tocan, y `style.focus: false` desactiva la regla en
un efecto concreto.
"""

from __future__ import annotations

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect

# Fotogramas del fundido al perder o recuperar el foco.
FADE = 4

_HEAD_ADORN = {"cap", "cowboy_hat", "top_hat", "fedora", "party_hat", "witch_hat", "santa_hat", "flower_crown", "headphones", "halo", "crown"}
_CHEST_ADORN = {"necklace", "chain", "chest_stars", "belt", "metal_jacket"}
_LEG_ADORN = {"knee_dots", "ankle_bands"}
_BODY_PARTS = {
    "left_arm": {"left_arm"},
    "right_arm": {"right_arm"},
    "arms": {"left_arm", "right_arm"},
    "hands": {"left_arm", "right_arm"},
    "legs": {"legs"},
    "feet": {"legs"},
    "torso": {"torso"},
    "head": {"head"},
}


def _joint_region(joint: str) -> str | None:
    if joint.startswith(("left_wrist", "left_elbow", "left_hand", "left_index", "left_thumb")):
        return "left_arm"
    if joint.startswith(("right_wrist", "right_elbow", "right_hand", "right_index", "right_thumb")):
        return "right_arm"
    if any(part in joint for part in ("ankle", "knee", "heel", "foot")):
        return "legs"
    if any(part in joint for part in ("nose", "eye", "ear", "mouth", "face")):
        return "head"
    if any(part in joint for part in ("shoulder", "hip", "torso", "chest")):
        return "torso"
    return None


def effect_regions(effect: Effect, event: MotionEvent | None) -> set[str] | None:
    """Regiones sobre las que dibuja el efecto; None = sin región (no se regula)."""
    kind = effect.type
    if kind == "wings":
        return {"left_arm", "right_arm"}
    if kind == "footprints":
        return {"legs"}
    if kind == "heart_fx":
        return {"left_arm", "right_arm"}
    if kind == "point_fx":
        return {f"{event.kind}_arm"} if event is not None and event.kind in ("left", "right") else None
    if kind in ("confetti_fx", "sound_waves"):
        return {"head"}
    if kind in ("foot_paint", "pop_fx"):
        return {"legs"}
    if kind.startswith("prop_"):
        return {"prop"}
    if kind == "throw_fx":
        # La mano que lanza puede llevar el objeto (lanzar la gorra): vale cualquiera de los dos.
        return {f"{event.kind}_arm", "prop"} if event is not None and event.kind in ("left", "right") else None
    if kind in ("face_toon", "eyewear"):
        return {"head"}
    if kind == "adornment":
        shapes = set(effect.style.shapes)
        regions = set()
        if shapes & _HEAD_ADORN:
            regions.add("head")
        if shapes & _CHEST_ADORN:
            regions.add("torso")
        if shapes & _LEG_ADORN:
            regions.add("legs")
        return regions or None
    if kind in ("body_glow", "limb_rings"):
        part = event.kind if event is not None and event.kind in _BODY_PARTS else effect.target.id
        return _BODY_PARTS.get(part)
    if kind in ("swoosh", "droplets", "arm_outline"):
        regions = {_joint_region(joint.strip()) for joint in effect.target.id.split(",")}
        regions.discard(None)
        if event is not None:
            limb = _joint_region(event.target.rsplit(":", 1)[-1])
            if limb is not None:
                return {limb}
        return regions or None
    return None


def focus_gain(runtime, effect: Effect, event: MotionEvent | None, focus: set[str]) -> float:
    """Ganancia 0-1 del efecto según el foco, con fundido de FADE fotogramas."""
    regions = effect_regions(effect, event)
    wanted = 1.0 if regions is None or not focus or regions & focus else 0.0
    step = 1.0 / FADE
    if wanted > runtime.focus_level:
        runtime.focus_level = min(wanted, runtime.focus_level + step)
    else:
        runtime.focus_level = max(wanted, runtime.focus_level - step)
    return runtime.focus_level
