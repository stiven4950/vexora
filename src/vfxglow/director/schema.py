"""Guion de efectos. El director lo emite; el motor solo acepta este contrato."""

from __future__ import annotations

from typing import Literal

from vfxglow.analysis.schema import AttentionSpan, MotionEvent
from pydantic import BaseModel, ConfigDict, Field

EffectType = Literal[
    "ribbon",
    "trail",
    "particles",
    "aura",
    "stroke",
    "lightning",
    "decal",
    "distortion",
    "cracks",
    "ripples",
    "charge",
    "sparks",
    "glyph",
    "impact_accent",
    "smear",
    "silhouette",
    "grade",
    "contour",
    "tip_flame",
    "feature_light",
    "eye_rings",
    "face_linework",
    "drawing",
    "swoosh",
    "flame_burst",
    "spark_dashes",
    "droplets",
    "clash",
    "arm_outline",
    "beam",
    "stars",
    "eyewear",
    "intent_mark",
    "body_glow",
    "adornment",
    "blade_glow",
    "blade_echo",
    "body_outline",
    "ground_burst",
    "ground_cloud",
    "floor_streak",
    "prop_outline",
    "prop_spring",
    "prop_rings",
    "prop_doodle",
    "face_toon",
    "throw_fx",
    "limb_rings",
    "foot_paint",
    "prop_swoosh",
    "pop_fx",
    "closing_stars",
    "disco_fx",
    "beat_pulse",
    "equalizer",
    "heart_fx",
    "point_fx",
    "confetti_fx",
    "sound_waves",
    "whirl_fx",
    "mirror_ball",
]
TargetKind = Literal["joint", "chain", "face_region", "mask", "object", "event_point", "contour"]
BlendMode = Literal["add", "screen", "over", "multiply", "tint"]
LayerGroup = Literal["grade", "glow", "particles", "interaction", "lightning"]

EVENT_NAMES: tuple[str, ...] = (
    "fast_swing",
    "impact",
    "foot_strike",
    "hand_contact",
    "object_contact",
    "held_object",
    "turn",
    "jump",
    "hand_open",
    "hand_closed",
    "arms_crossed",
    "raise_hand",
    "still",
    "person_contact",
    "tool_touch",
    "strike_windup",
    "strike_recoil",
    "fist_clash",
    "body_bump",
    "lull",
    "intent",
    "intended_strike",
    "blade_swing",
    "blade_ground",
    "flip",
    "landing",
    "entrance",
    "tumble",
    "spotlight",
    "prop_transfer",
    "prop_worn",
    "prop_spin",
    "face_touch",
    "throw",
    "neck_slash",
    "stomp",
    "frenzy",
    "beat",
    "heart_hands",
    "arms_up",
    "arms_open",
    "point",
    "hand_ear",
    "cover_eyes",
    "spin_body",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EffectTarget(_Strict):
    kind: TargetKind
    id: str
    secondary: str | None = None
    space: Literal["image"] = "image"


class EffectTime(_Strict):
    start_frame: int = 0
    end_frame: int = -1
    fade_in: int = 6
    fade_out: int = 8


class NoiseParams(_Strict):
    scale: float = 48.0
    speed: float = 0.8
    octaves: int = 3
    amplitude: float = 0.35


class LightningParams(_Strict):
    branches: int = 3
    branch_depth: int = 2
    branch_angle: float = 28.0
    jitter: float = 0.22
    reseed_every: int = 4
    tail_frames: int = 6
    sparks: int = 6
    reach: float = 1.4


class Drawing(_Strict):
    """Dibujo del director en un espacio que sigue a la cara, el cuerpo o una mano.

    Cada trazo es un `d` de SVG (M, L, C, Z) en unidades del espacio. Se traza en
    orden durante `style.draw_on` fotogramas. `variants` alterna juegos de trazos
    completos cada `variant_every` fotogramas (aleteo, llama).
    """

    space: Literal["face", "body", "left_hand", "right_hand"] = "face"
    strokes: list[str] = Field(default_factory=list)
    variants: list[list[str]] = Field(default_factory=list)
    variant_every: int = 4


class EffectStyle(_Strict):
    preset: str | None = None
    intensity: float = 1.0
    colors: list[tuple[float, float, float]] = Field(
        default_factory=lambda: [(1.0, 0.45, 0.05)]
    )
    thickness: float = 0.06
    hdr_gain: float = 2.5
    noise: NoiseParams = Field(default_factory=NoiseParams)
    seed_offset: int = 0
    lightning: LightningParams = Field(default_factory=LightningParams)
    boil_frames: int = 0
    glyph: str = ""
    dash: float = 0.0
    rings: int = 2
    spin: float = 0.6
    hue_speed: float = 0.0
    draw_on: int = 0
    drawing: Drawing | None = None
    # swoosh: fotogramas de estela y velocidad (torsos/fotograma) a partir de la cual se enciende.
    trail_frames: int = 10
    min_speed: float = 0.12
    # swoosh: hebras paralelas; probabilidad de dibujar el contorno de "pintura" en una
    # trayectoria de al menos paint_min_length torsos, con un ancho máximo de paint_width torsos.
    strands: int = 1
    paint_chance: float = 0.0
    paint_width: float = 0.2
    paint_min_length: float = 0.8
    # flame_burst / spark_dashes / droplets: tamaño en torsos y probabilidad por golpe.
    size: float = 0.5
    chance: float = 1.0
    # droplets / eyewear / intent_mark: figuras entre las que se sortea por activación.
    shapes: list[str] = Field(default_factory=lambda: ["drop"])
    # Si no está vacío, el efecto solo se dibuja en estas personas (p. ej. quienes llevan gafas).
    people: list[str] = Field(default_factory=list)
    # swoosh: dibuja además la estela girada sobre su centro, formando una cruz.
    cross: bool = False
    # Si no está vacío, cada activación sortea sus colores de esta paleta (sustituyen a
    # `colors`). Sin evento, se vuelve a sortear cada `palette_every` fotogramas.
    palette: list[tuple[float, float, float]] = Field(default_factory=list)
    palette_every: int = 45
    # Peso de cada color de `palette` al sortear (mismo orden). Vacío = todos iguales. El
    # coreógrafo lo llena según el tono de piel (director/palette.py).
    palette_weights: list[float] = Field(default_factory=list)
    # Con línea de atención en el guion, el efecto se apaga si su región no es protagonista
    # (engine/focus.py). False = siempre visible (cierres, efectos de toda la escena).
    focus: bool = True
    # Impactos: cantidad de chispas diminutas que salen disparadas del golpe (0 = ninguna).
    micro_sparks: int = 0
    # body_glow: opacidad del tinte de color que rellena la parte del cuerpo (0 = solo contorno).
    fill: float = 0.35
    # swoosh: neon (trazo), flame (con lenguas de fuego) o dots (bolas de fuego).
    trail_style: Literal["neon", "flame", "dots"] = "neon"


class EffectRender(_Strict):
    blend: BlendMode = "add"
    motion_blur: float = 0.35
    occlude: bool = False
    group: LayerGroup = "glow"
    persistence: float = 0.0
    glow_layers: int = 2


class EffectTrigger(_Strict):
    event: str
    joint: str | None = None
    min_speed: float = 0.0
    min_duration: int = 1
    hold: int = 8
    # Fotogramas que el efecto se adelanta al evento (el resorte aparece antes de soltar la gorra).
    lead: int = 0
    # start: la ventana empieza con el evento; end: empieza cuando el evento termina y dura
    # `hold` (lo que pasa "después": los cuernos al acabar de girar la gorra).
    anchor: Literal["start", "end"] = "start"
    cooldown: int = 4
    fade_in: int = 2
    fade_out: int = 6
    max_activations: int = 0
    attacker: str | None = None
    # Si no está vacío, solo las ocurrencias que empiezan en estos fotogramas (las que eligió
    # el coreógrafo); el resto del mismo evento no enciende este efecto.
    frames: list[int] = Field(default_factory=list)
    # Paralela a `frames`: el target de cada ocurrencia elegida (dos personas pueden tener la
    # misma acción en el mismo fotograma y solo una salir sorteada).
    targets: list[str] = Field(default_factory=list)


class EffectRefine(_Strict):
    enabled: bool = False
    prompt: str = ""
    strength: float = 0.4
    keyframe_stride: int = 8


class Effect(_Strict):
    id: str
    type: EffectType
    target: EffectTarget
    time: EffectTime = Field(default_factory=EffectTime)
    style: EffectStyle = Field(default_factory=EffectStyle)
    render: EffectRender = Field(default_factory=EffectRender)
    refine: EffectRefine = Field(default_factory=EffectRefine)
    triggers: list[EffectTrigger] = Field(default_factory=list)
    actor: str | None = None


class Grade(_Strict):
    bloom_radius: float = 18.0
    bloom_threshold: float = 1.0
    bloom_intensity: float = 0.85
    soft_knee: float = 0.85


class Chapter(_Strict):
    """Tramo con un mismo foco (parte del cuerpo, objeto): todos sus efectos comparten color."""

    start_frame: int
    end_frame: int
    focus: str
    colors: list[tuple[float, float, float]]


class EffectScript(_Strict):
    version: str = "1.0"
    title: str
    theme: str
    seed: int = 1
    grade: Grade = Field(default_factory=Grade)
    effects: list[Effect]
    # Color por capítulo: los efectos con paleta toman los colores del capítulo en curso.
    chapters: list[Chapter] = Field(default_factory=list)
    # Línea de atención (análisis): un efecto cuya región no es protagonista se apaga.
    attention: list[AttentionSpan] = Field(default_factory=list)
    # Eventos que crea el coreógrafo (spotlight desde la atención); el motor los suma a los del
    # análisis.
    extra_events: list[MotionEvent] = Field(default_factory=list)


SUPPORTED_TYPES: tuple[str, ...] = (
    "ribbon",
    "trail",
    "particles",
    "aura",
    "stroke",
    "lightning",
    "decal",
    "distortion",
    "cracks",
    "ripples",
    "charge",
    "sparks",
    "glyph",
    "impact_accent",
    "smear",
    "silhouette",
    "grade",
    "contour",
    "tip_flame",
    "feature_light",
    "eye_rings",
    "face_linework",
    "drawing",
    "swoosh",
    "flame_burst",
    "spark_dashes",
    "droplets",
    "clash",
    "arm_outline",
    "beam",
    "stars",
    "eyewear",
    "intent_mark",
    "body_glow",
    "adornment",
    "blade_glow",
    "blade_echo",
    "body_outline",
    "ground_burst",
    "ground_cloud",
    "floor_streak",
    "prop_outline",
    "prop_spring",
    "prop_rings",
    "prop_doodle",
    "face_toon",
    "throw_fx",
    "limb_rings",
    "foot_paint",
    "prop_swoosh",
    "pop_fx",
    "closing_stars",
    "disco_fx",
    "beat_pulse",
    "equalizer",
    "heart_fx",
    "point_fx",
    "confetti_fx",
    "sound_waves",
    "whirl_fx",
    "mirror_ball",
)

# Efectos que por defecto pertenecen a un grupo distinto de glow.
DEFAULT_GROUPS: dict[str, str] = {
    "lightning": "lightning",
    "particles": "particles",
    "sparks": "particles",
    "cracks": "interaction",
    "ripples": "interaction",
    "charge": "interaction",
    "grade": "grade",
    "impact_accent": "glow",
    "glyph": "glow",
    "smear": "glow",
    "silhouette": "glow",
    "contour": "glow",
    "tip_flame": "glow",
    "feature_light": "glow",
    "spark_dashes": "particles",
    "droplets": "particles",
}


def effect_group(effect: Effect) -> str:
    """Grupo de la capa. Si el guion no lo dice, lo infiere del tipo."""
    if effect.render.group != "glow":
        return effect.render.group
    return DEFAULT_GROUPS.get(effect.type, "glow")


def envelope(frame: int, timing: EffectTime, frame_count: int) -> float:
    start = timing.start_frame
    end = frame_count - 1 if timing.end_frame < 0 else timing.end_frame
    if frame < start or frame > end:
        return 0.0
    gain = 1.0
    if timing.fade_in > 0 and frame < start + timing.fade_in:
        gain *= (frame - start) / max(timing.fade_in, 1)
    if timing.fade_out > 0 and frame > end - timing.fade_out:
        gain *= (end - frame) / max(timing.fade_out, 1)
    return float(np_clip(gain))


def np_clip(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def resolve_timing(script: EffectScript, frame_count: int) -> EffectScript:
    """Sustituye end_frame negativo por el último fotograma del video."""
    data = script.model_dump()
    last = max(frame_count - 1, 0)
    for effect in data["effects"]:
        if effect["time"]["end_frame"] < 0:
            effect["time"]["end_frame"] = last
    return EffectScript.model_validate(data)
