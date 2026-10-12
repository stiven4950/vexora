"""Comprueba que el guion solo pide efectos, anclas y eventos que el motor sabe resolver."""

from __future__ import annotations

from vfxglow.analysis.names import CHAINS, FACE_REGIONS, known_joint_names
from vfxglow.director.schema import EVENT_NAMES, SUPPORTED_TYPES, EffectScript

INTERACTION_TYPES = {"cracks", "ripples", "sparks", "flame_burst", "spark_dashes", "clash", "stars", "ground_burst", "ground_cloud", "floor_streak"}
# Siguen a cada persona presente y cortan su estela solos: pueden cruzar un corte.
JOINT_LIST_TYPES = {"swoosh", "droplets", "arm_outline"}
# Se redibujan con los datos de cada fotograma (hoja, silueta): un corte de plano no los rompe.
FRAME_DATA_TYPES = {"blade_glow", "blade_echo", "body_outline", "eyewear", "body_glow", "adornment", "prop_outline", "prop_spring", "prop_rings", "prop_doodle", "face_toon", "throw_fx", "limb_rings"}
# Siguen a la cara o al cuerpo y se vuelven a trazar en cada corte, así que pueden cruzarlo.
REDRAW_TYPES = {"eye_rings", "face_linework", "drawing"}
MAX_STROKES = 24
MAX_VARIANTS = 4
MAX_POINTS = 600


class ScriptError(ValueError):
    pass


def validate_script(
    script: EffectScript,
    anchors: set[str] | None = None,
    cuts: list[int] | None = None,
    max_effects: int = 12,
) -> None:
    """`max_effects` frena a un director LLM; un catálogo genera un efecto por opción usada."""
    if not script.effects:
        raise ScriptError("El guion no contiene efectos.")
    if len(script.effects) > max_effects:
        raise ScriptError(f"El guion supera el máximo de {max_effects} efectos.")
    ids: set[str] = set()
    known = known_joint_names() | set(CHAINS) | set(FACE_REGIONS) | {"person", "person_0"}
    if anchors:
        known |= anchors
    for effect in script.effects:
        if effect.id in ids:
            raise ScriptError(f"Identificador de efecto repetido: {effect.id}")
        ids.add(effect.id)
        if effect.type not in SUPPORTED_TYPES:
            raise ScriptError(f"Tipo de efecto desconocido: {effect.type}")
        if effect.type in REDRAW_TYPES:
            _check_face_effect(effect)
        elif effect.type in {"eyewear", "intent_mark", "blade_glow", "blade_echo", "body_outline", "body_glow", "adornment", "prop_outline", "prop_spring", "prop_rings", "prop_doodle", "face_toon", "throw_fx", "limb_rings"}:
            pass  # se ancla a los ojos de cada persona; no hay ancla que validar
        elif effect.type in JOINT_LIST_TYPES:
            # Lista de articulaciones; se aplica a cada persona presente.
            for joint in (token.strip() for token in effect.target.id.split(",") if token.strip()):
                _check_target(joint, "joint", known)
        else:
            _check_target(effect.target.id, effect.target.kind, known)
        if effect.type in {"droplets", "eyewear", "intent_mark"} or (effect.type == "blade_glow" and effect.style.shapes != ["drop"]):
            if effect.type == "blade_glow":
                from vfxglow.engine.sword import BLADE_MATERIALS as SHAPES
            elif effect.type == "droplets":
                from vfxglow.engine.burst import SHAPES
            elif effect.type == "eyewear":
                from vfxglow.engine.eyewear import SHAPES
            else:
                from vfxglow.engine.marks import SHAPES

            unknown = [name for name in effect.style.shapes if name not in SHAPES]
            if unknown or not effect.style.shapes:
                raise ScriptError(f"{effect.id}: forma de partícula desconocida {unknown}. Usa {', '.join(SHAPES)}.")
        if effect.target.kind == "event_point" and not effect.triggers:
            raise ScriptError(f"{effect.id}: event_point necesita al menos un trigger.")
        if effect.type in INTERACTION_TYPES and effect.target.kind not in {"event_point", "object", "joint"}:
            raise ScriptError(f"{effect.id}: {effect.type} se ancla a event_point, object o joint.")
        if effect.type == "lightning" and effect.target.secondary:
            _check_target(effect.target.secondary, "joint", known)
        if effect.time.end_frame >= 0 and effect.time.end_frame < effect.time.start_frame:
            raise ScriptError(f"{effect.id}: el fotograma final es anterior al inicial.")
        if not effect.style.colors:
            raise ScriptError(f"{effect.id}: la paleta está vacía.")
        if effect.style.intensity < 0:
            raise ScriptError(f"{effect.id}: la intensidad no puede ser negativa.")
        if not 0.0 <= effect.render.persistence < 1.0:
            raise ScriptError(f"{effect.id}: persistence debe estar en [0, 1).")
        if effect.style.glyph:
            _check_glyph(effect.id, effect.style.glyph)
        if cuts and not effect.triggers and effect.type not in REDRAW_TYPES | JOINT_LIST_TYPES | FRAME_DATA_TYPES:
            end = effect.time.end_frame
            for cut in cuts:
                if effect.time.start_frame < cut <= end:
                    raise ScriptError(f"{effect.id}: el efecto cruza el corte del fotograma {cut}.")
        for trigger in effect.triggers:
            if trigger.event not in EVENT_NAMES:
                raise ScriptError(f"{effect.id}: evento desconocido '{trigger.event}'.")
            if trigger.joint is not None and not _known_anchor(trigger.joint, known):
                raise ScriptError(f"{effect.id}: articulación desconocida en trigger '{trigger.joint}'.")
            if trigger.hold < 0 or trigger.cooldown < 0:
                raise ScriptError(f"{effect.id}: hold y cooldown no pueden ser negativos.")
    _check_grades(script)
    _check_actor_colors(script)


def _check_target(name: str, kind: str, known: set[str]) -> None:
    if kind == "mask" and name in {"person", "person_0", "person_1"}:
        return
    if kind in {"object", "event_point", "contour"}:
        return
    if _known_anchor(name, known):
        return
    raise ScriptError(f"Ancla desconocida: {name}")


def _known_anchor(name: str, known: set[str]) -> bool:
    if name in known or name.startswith("face") or name.startswith("object"):
        return True
    if name in {"mouth", "head_top", "paint_contour", "contact", "person", "eye_glint"}:
        return True
    if name.startswith("blade_") and name.endswith(("_tip", "_hilt")):
        return True
    if name.startswith("person_") and ":" in name:
        joint = name.split(":", 1)[1]
        return joint in known or joint in known_joint_names()
    return False


def _check_face_effect(effect) -> None:
    from vfxglow.analysis.names import FACE_FEATURE_GROUPS, FACE_FEATURES
    from vfxglow.engine.glyphs import _path_d

    if effect.type == "face_linework":
        allowed = set(FACE_FEATURES) | set(FACE_FEATURE_GROUPS) | {"all", "face", ""}
        unknown = [token.strip() for token in effect.target.id.split(",") if token.strip() not in allowed]
        if unknown:
            raise ScriptError(f"{effect.id}: rasgo desconocido {unknown[0]}. Usa {', '.join(sorted(allowed - {''}))}.")
    if effect.type != "drawing":
        return
    drawing = effect.style.drawing
    if drawing is None or not drawing.strokes:
        raise ScriptError(f"{effect.id}: drawing necesita style.drawing.strokes.")
    if len(drawing.variants) > MAX_VARIANTS:
        raise ScriptError(f"{effect.id}: como máximo {MAX_VARIANTS} variantes.")
    total = 0
    for strokes in [drawing.strokes, *drawing.variants]:
        if len(strokes) > MAX_STROKES:
            raise ScriptError(f"{effect.id}: como máximo {MAX_STROKES} trazos por variante.")
        for d in strokes:
            pts = _path_d(d)
            if len(pts) < 2:
                raise ScriptError(f"{effect.id}: trazo ilegible '{d[:40]}'. Usa M, L, C o Z.")
            if abs(pts).max() > 4.0:
                raise ScriptError(f"{effect.id}: coordenadas fuera de [-4, 4] en '{d[:40]}'.")
            total += len(pts)
    if total > MAX_POINTS:
        raise ScriptError(f"{effect.id}: el dibujo supera {MAX_POINTS} puntos.")


def _check_glyph(effect_id: str, glyph: str) -> None:
    from vfxglow.engine.glyphs import resolve_glyph, validate_svg

    if glyph.strip().startswith("<"):
        if not validate_svg(glyph):
            raise ScriptError(f"{effect_id}: el SVG compuesto no pasa el validador.")
        return
    if resolve_glyph(glyph) is None:
        raise ScriptError(f"{effect_id}: glifo desconocido '{glyph}'.")


def _check_grades(script: EffectScript) -> None:
    grades = [effect for effect in script.effects if effect.type == "grade"]
    for index, left in enumerate(grades):
        for right in grades[index + 1 :]:
            if _overlaps(left, right):
                raise ScriptError("beat_grade solo puede aplicarse una vez por beat.")


def _overlaps(left, right) -> bool:
    if left.triggers or right.triggers:
        return False
    left_end = left.time.end_frame if left.time.end_frame >= 0 else 10**9
    right_end = right.time.end_frame if right.time.end_frame >= 0 else 10**9
    return left.time.start_frame <= right_end and right.time.start_frame <= left_end


def _check_actor_colors(script: EffectScript) -> None:
    seen: dict[str, tuple[float, float, float]] = {}
    for effect in script.effects:
        if not effect.actor or not effect.style.colors:
            continue
        color = effect.style.colors[0]
        previous = seen.get(effect.actor)
        if previous is not None and previous != color:
            raise ScriptError(f"El color de {effect.actor} cambia entre efectos.")
        seen[effect.actor] = color
