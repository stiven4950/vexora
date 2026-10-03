"""Catálogo de estrategias. Cada una declara qué señales necesita y se expande a efectos.

El director elige combinaciones por beat. El motor solo ve el Effect Script resultante.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vfxglow.analysis.beats import cut_frames
from vfxglow.analysis.schema import MotionBrief
from vfxglow.director.schema import (
    Effect,
    EffectRender,
    EffectScript,
    EffectStyle,
    EffectTarget,
    EffectTime,
    EffectTrigger,
    Grade,
)

PALETTES = {
    "person_0": [(1.0, 0.48, 0.08)],
    "person_1": [(0.35, 0.72, 1.0)],
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Choice(_Strict):
    beat: int = 0
    strategy: str
    accents: list[str] = Field(default_factory=list)
    glyph: str = ""
    intensity: float = 1.0
    actor: str | None = None


class StrategyPlan(_Strict):
    title: str = "Dirección por beats"
    theme: str = "mixed"
    seed: int = 1
    choices: list[Choice]


CATALOG: dict[str, str] = {
    "material_contour": "Contorno de la mancha de pintura activa. Se apaga cuando la mancha desaparece.",
    "tool_tip_flame": "Llama pequeña en la punta de la herramienta mientras toca el rostro.",
    "feature_lights": "Luces puntuales en ojos, nariz y boca, salvo donde el plano ya brilla.",
    "impact_accent": "Ráfaga de estrellas y zigzags en el punto de contacto.",
    "charge_up": "Orbe en el puño del atacante antes del golpe.",
    "debris_fall": "Chispas que caen después de un golpe fuerte.",
    "limb_trace": "Trazos alrededor de las piernas en las esquivas.",
    "character_overlay": "Dibujo de personaje anclado a la cabeza.",
    "symbol_react": "Símbolo que interpreta el gesto.",
    "motion_smear": "Arco grueso en un barrido rápido del brazo.",
    "silhouette_trace": "Contorno de neón de la persona.",
    "beat_grade": "Atenúa el plano y lo tiñe durante el beat.",
    "eye_rings": "Anillos discontinuos que giran sobre cada iris y cambian de color; se apagan al parpadear.",
    "face_linework": "Delineado de neón de cejas, ojos, labios, nariz y óvalo que se traza y se queda siguiendo la cara.",
    "drawing": "Dibujo propio del director, trazo a trazo, anclado a la cara, el cuerpo o una mano.",
}

FACE_STRATEGIES = {"eye_rings", "face_linework"}


def describe() -> str:
    return "\n".join(f"- {name}: {text}" for name, text in CATALOG.items())


def applicable(brief: MotionBrief) -> list[str]:
    names = set(CATALOG)
    events = {event.name for event in brief.events}
    if "person_contact" not in events:
        names -= {"impact_accent", "charge_up", "debris_fall"}
    if "tool_touch" not in events and not any(beat.kind.startswith("paint") for beat in brief.beats):
        names -= {"material_contour", "tool_tip_flame"}
    if len(brief.people) < 2:
        names -= {"impact_accent", "charge_up", "debris_fall"}
    if "right_iris" not in brief.anchors:
        names -= FACE_STRATEGIES
    return sorted(names)


def expand(plan: StrategyPlan, brief: MotionBrief) -> EffectScript:
    """Une las elecciones de beats contiguos que no cruzan un corte."""
    chosen: list[str] = []
    for choice in plan.choices:
        for name in [choice.strategy, *choice.accents]:
            if name in CATALOG and name not in chosen:
                chosen.append(name)
    if not chosen:
        chosen = ["impact_accent"] if "impact_accent" in applicable(brief) else ["symbol_react"]
    glyph = next((choice.glyph for choice in plan.choices if choice.glyph), "heart")
    return _script(plan.title, plan.theme, plan.seed, chosen, glyph, brief.video.frame_count)


def preset_script(name: str, frame_count: int) -> EffectScript:
    if name == "fight_comic":
        names = ["charge_up", "impact_accent", "debris_fall", "limb_trace"]
        return _script("Fight Comic", "fight_comic", 21, names, "burst", frame_count)
    if name == "doodle_dance":
        names = ["character_overlay", "symbol_react", "motion_smear", "silhouette_trace", "beat_grade"]
        return _script("Doodle Dance", "doodle_dance", 27, names, "cloud", frame_count)
    if name == "paint_reveal":
        names = ["material_contour", "tool_tip_flame", "feature_lights"]
        return _script("Paint Reveal", "paint_reveal", 11, names, "star", frame_count)
    if name == "face_neon":
        names = ["face_linework", "eye_rings", "tool_tip_flame"]
        return _script("Face Neon", "face_neon", 13, names, "star", frame_count)
    raise KeyError(name)


def _script(title: str, theme: str, seed: int, names: list[str], glyph: str, frame_count: int) -> EffectScript:
    effects: list[Effect] = []
    for name in names:
        effects.extend(_expand_one(name, glyph))
    return EffectScript(
        title=title,
        theme=theme,
        seed=seed,
        grade=Grade(),
        effects=effects[:12],
    )


def _expand_one(name: str, glyph: str) -> list[Effect]:
    if name == "material_contour":
        return [_effect("paint_contour", "contour", "contour", "paint_contour", colors=[(1.0, 0.72, 0.15)], dash=8)]
    if name == "tool_tip_flame":
        return [
            _effect(
                "brush_flame",
                "tip_flame",
                "event_point",
                "tool_touch",
                colors=[(1.0, 0.82, 0.25)],
                triggers=[_trigger("tool_touch", hold=4)],
            )
        ]
    if name == "feature_lights":
        return [
            _effect(f"light_{part}", "feature_light", "joint", part, colors=[(1.0, 0.45, 0.15)], thickness=0.03)
            for part in ("left_eye", "right_eye", "nose", "mouth")
        ]
    if name == "impact_accent":
        return [
            _effect(
                f"hit_{actor[-1]}",
                "impact_accent",
                "event_point",
                "contact",
                colors=PALETTES[actor],
                actor=actor,
                boil=3,
                triggers=[_trigger("person_contact", hold=14, attacker=actor)],
            )
            for actor in ("person_0", "person_1")
        ]
    if name == "charge_up":
        return [
            _effect(
                f"charge_{actor[-1]}",
                "charge",
                "joint",
                f"{actor}:right_wrist",
                colors=PALETTES[actor],
                actor=actor,
                group="interaction",
                triggers=[_trigger("fast_swing", joint=f"{actor}:right_wrist", hold=8)],
            )
            for actor in ("person_0", "person_1")
        ]
    if name == "debris_fall":
        return [
            _effect(
                "debris",
                "sparks",
                "event_point",
                "contact",
                colors=[(1.0, 0.6, 0.2)],
                group="particles",
                triggers=[_trigger("person_contact", hold=16, min_speed=0.25)],
            )
        ]
    if name == "limb_trace":
        return [
            _effect(
                f"legs_{side}",
                "trail",
                "joint",
                f"{side}_ankle",
                colors=[(0.55, 0.85, 1.0)],
                boil=2,
                triggers=[_trigger("fast_swing", joint=f"{side}_ankle", hold=10)],
            )
            for side in ("left", "right")
        ]
    if name == "character_overlay":
        return [
            _effect(
                "character",
                "glyph",
                "joint",
                "nose",
                colors=[(0.75, 0.35, 1.0)],
                glyph="horns",
                boil=3,
                triggers=[_trigger("raise_hand", hold=12)],
            )
        ]
    if name == "symbol_react":
        return [
            _effect("symbol_cloud", "glyph", "joint", "nose", colors=[(0.45, 0.9, 1.0)], glyph=glyph or "cloud", boil=3, triggers=[_trigger("raise_hand", hold=10)]),
            _effect("symbol_wink", "glyph", "joint", "nose", colors=[(0.4, 1.0, 0.55)], glyph="wink", boil=3, triggers=[_trigger("hand_open", hold=10)]),
            _effect("symbol_heart", "glyph", "joint", "nose", colors=[(1.0, 0.35, 0.7)], glyph="heart_broken", boil=3, triggers=[_trigger("arms_crossed", hold=12)]),
        ]
    if name == "motion_smear":
        return [
            _effect(
                f"smear_{side}",
                "smear",
                "joint",
                f"{side}_wrist",
                colors=[(0.4, 0.85, 1.0)],
                thickness=0.12,
                triggers=[_trigger("fast_swing", joint=f"{side}_wrist", hold=6)],
            )
            for side in ("left", "right")
        ]
    if name == "eye_rings":
        effect = _effect("eye_rings", "eye_rings", "face_region", "eyes", colors=[(0.3, 0.9, 1.0), (1.0, 0.35, 0.85), (1.0, 0.8, 0.2)], thickness=0.06)
        effect.style.hue_speed = 0.015
        effect.style.spin = 0.5
        effect.style.hdr_gain = 1.6
        effect.render.persistence = 0.0
        effect.render.glow_layers = 1
        return [effect]
    if name == "face_linework":
        effect = _effect("face_lines", "face_linework", "face_region", "brows,eyes,lips,nose,oval", colors=[(0.2, 0.85, 1.0), (0.85, 0.3, 1.0)], thickness=0.035, boil=3)
        effect.style.draw_on = 30
        effect.style.hue_speed = 0.004
        effect.style.hdr_gain = 1.1
        effect.render.persistence = 0.0
        effect.render.glow_layers = 1
        return [effect]
    if name == "silhouette_trace":
        return [_effect("silhouette", "silhouette", "mask", "person", colors=[(0.55, 1.0, 0.85)], thickness=0.02)]
    if name == "beat_grade":
        return [
            _effect(
                "grade_beat",
                "grade",
                "mask",
                "person",
                colors=[(0.45, 0.25, 0.85)],
                group="grade",
                blend="multiply",
                intensity=0.7,
            )
        ]
    return []


def _trigger(event: str, joint: str | None = None, hold: int = 8, attacker: str | None = None, min_speed: float = 0.0) -> EffectTrigger:
    return EffectTrigger(
        event=event,
        joint=joint,
        hold=hold,
        cooldown=4,
        fade_in=1,
        fade_out=5,
        min_speed=min_speed,
        attacker=attacker,
    )


def _effect(
    effect_id: str,
    kind: str,
    target_kind: str,
    target_id: str,
    colors: list[tuple[float, float, float]],
    triggers: list[EffectTrigger] | None = None,
    actor: str | None = None,
    glyph: str = "",
    boil: int = 0,
    dash: float = 0.0,
    group: str = "glow",
    blend: str = "add",
    thickness: float = 0.05,
    intensity: float = 1.0,
) -> Effect:
    return Effect(
        id=effect_id,
        type=kind,  # type: ignore[arg-type]
        target=EffectTarget(kind=target_kind, id=target_id),  # type: ignore[arg-type]
        time=EffectTime(start_frame=0, end_frame=-1, fade_in=2, fade_out=4),
        style=EffectStyle(colors=colors, thickness=thickness, hdr_gain=2.4, boil_frames=boil, glyph=glyph, dash=dash, intensity=intensity),
        render=EffectRender(blend=blend, group=group, motion_blur=0.15, persistence=0.35 if kind != "grade" else 0.0, glow_layers=2),  # type: ignore[arg-type]
        triggers=triggers or [],
        actor=actor,
    )


def cuts_of(brief: MotionBrief) -> list[int]:
    return cut_frames(brief.beats)
