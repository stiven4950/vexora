"""Restricciones entre el guion y el render.

El director propone; esta capa decide cuánto se dibuja cada efecto en cada fotograma según
lo que el análisis sabe del plano. Una regla puede vetar (ganancia 0) o atenuar, nunca
encender algo que el guion no pidió. Las reglas viven aquí y no dentro de cada efecto.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vfxglow.director.schema import Effect
from vfxglow.engine.anchors import PointSet

# Efectos que se dibujan sobre la malla facial y heredan su fundido cuando se sostiene.
FACE_TYPES = frozenset({"eye_rings", "face_linework", "drawing"})


@dataclass(frozen=True)
class FrameState:
    """Lo que el motor sabe del fotograma antes de dibujar."""

    # 1 con malla presente; baja hacia 0 mientras se sostiene la última malla válida.
    face_fade: float = 1.0
    # Rasgos que ya brillan en el plano (p. ej. lentes blancos): {"eyes", "nose", ...}.
    bright: frozenset[str] = field(default_factory=frozenset)


def gain_for(effect: Effect, state: FrameState, points: PointSet, min_confidence: float = 0.0) -> float:
    """Multiplicador de ganancia de `effect` en este fotograma, en [0, 1]."""
    if effect.type == "feature_light" and _already_bright(effect.target.id, state.bright):
        return 0.0
    gain = 1.0
    if is_face_effect(effect):
        gain *= state.face_fade
    if min_confidence > 0 and effect.target.id in points:
        conf = points.confidence(effect.target.id)
        if conf < min_confidence:
            gain *= max(conf, 0.0) / min_confidence
    return gain


def is_face_effect(effect: Effect) -> bool:
    if effect.type not in FACE_TYPES:
        return False
    return effect.type != "drawing" or effect.style.drawing is None or effect.style.drawing.space == "face"


def _already_bright(name: str, bright: frozenset[str]) -> bool:
    """Una luz encima de un rasgo que ya brilla lo tapa en vez de realzarlo."""
    return name in bright or (name.endswith("eye") and "eyes" in bright)
