"""Director artista: plan por beats con dibujos propios, prompt compacto e imágenes clave.

El LLM no ve el brief entero. Recibe una línea por beat, el catálogo y unas pocas
imágenes en baja resolución. Así una dirección completa cuesta pocos miles de tokens.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vfxglow.analysis.schema import MotionBrief
from vfxglow.director.schema import Drawing, Effect, EffectScript, EffectTime, Grade
from vfxglow.director.strategies import CATALOG, FACE_STRATEGIES, _expand_one, applicable

MAX_EFFECTS = 12
# Estrategias que se encienden con eventos: se incluyen una vez para todo el clip.
_TRIGGERED = set(CATALOG) - FACE_STRATEGIES - {"drawing", "beat_grade", "silhouette_trace", "material_contour"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ArtDrawing(_Strict):
    space: str = "face"
    strokes: list[str]
    variants: list[list[str]] = Field(default_factory=list)
    draw_on: int = 12


class ArtBeat(_Strict):
    beat: int
    use: list[str] = Field(default_factory=list)
    drawing: str = ""
    color: int = 0
    intensity: float = 1.0


class ArtPlan(_Strict):
    title: str = "Dirección de arte"
    theme: str = "mixed"
    motif: str = ""
    palette: list[tuple[float, float, float]] = Field(default_factory=lambda: [(0.35, 0.9, 1.0)])
    beats: list[ArtBeat]
    drawings: dict[str, ArtDrawing] = Field(default_factory=dict)


def expand_art(plan: ArtPlan, brief: MotionBrief) -> EffectScript:
    """Une beats contiguos con la misma elección en un solo efecto con su rango de fotogramas."""
    spans = {beat.id: (beat.start_frame, beat.end_frame) for beat in brief.beats}
    last = max(brief.video.frame_count - 1, 0)
    palette = [_unit_color(color) for color in plan.palette] or [(0.35, 0.9, 1.0)]
    # (clave, color, inicio, fin, intensidad)
    runs: list[list] = []
    triggered: list[str] = []
    for item in sorted(plan.beats, key=lambda b: b.beat):
        start, end = spans.get(item.beat, (0, last))
        keys = [name for name in item.use if name in CATALOG and name != "drawing"]
        if item.drawing and item.drawing in plan.drawings:
            keys.append(f"drawing:{item.drawing}")
        color = item.color % len(palette)
        for key in keys:
            if key in _TRIGGERED:
                if key not in triggered:
                    triggered.append(key)
                continue
            match = next((run for run in reversed(runs) if run[0] == key), None)
            if match is not None and match[1] == color and match[3] >= start - 1:
                match[3] = end
                match[4] = max(match[4], item.intensity)
            else:
                runs.append([key, color, start, end, item.intensity])
    effects: list[Effect] = []
    for index, (key, color, start, end, intensity) in enumerate(runs):
        effect = _timed(key, plan, palette, color, index)
        if effect is None:
            continue
        effect.time = EffectTime(start_frame=start, end_frame=end, fade_in=3, fade_out=6)
        effect.style.intensity = float(max(0.0, min(intensity, 1.5)))
        effects.append(effect)
    for name in triggered:
        effects.extend(_expand_one(name, "star"))
    if not effects:
        effects = _expand_one("face_linework" if "face_linework" in applicable(brief) else "silhouette_trace", "star")
    return EffectScript(title=plan.title, theme=plan.theme, seed=7, grade=Grade(), effects=effects[:MAX_EFFECTS])


def _unit_color(color: tuple[float, float, float]) -> tuple[float, float, float]:
    scale = 255.0 if max(color) > 1.5 else 1.0
    r, g, b = (float(min(max(c / scale, 0.0), 1.0)) for c in color)
    return (r, g, b)


def _timed(key: str, plan: ArtPlan, palette, color: int, index: int) -> Effect | None:
    if key.startswith("drawing:"):
        name = key.split(":", 1)[1]
        art = plan.drawings[name]
        effect = _expand_one("face_linework", "star")[0]
        effect.id = f"draw_{name}_{index}"
        effect.type = "drawing"
        space = art.space if art.space in {"face", "body", "left_hand", "right_hand"} else "face"
        effect.target.id = space
        effect.style.drawing = Drawing(space=space, strokes=art.strokes, variants=art.variants[:4], variant_every=4)  # type: ignore[arg-type]
        effect.style.draw_on = max(0, min(art.draw_on, 90))
        effect.style.colors = [palette[color]]
        effect.style.hue_speed = 0.0
        return effect
    built = _expand_one(key, "star")
    if not built:
        return None
    effect = built[0]
    effect.id = f"{effect.id}_{index}"
    effect.style.colors = [palette[color], *[p for i, p in enumerate(palette) if i != color]][:3]
    return effect


def render_art_prompt(brief: MotionBrief) -> str:
    scenes = {scene.beat_id: scene for scene in brief.scene}
    lines = []
    for beat in brief.beats:
        events = Counter(
            event.name
            for event in brief.events
            if beat.start_frame <= event.start_frame <= beat.end_frame and event.name != "still"
        )
        scene = scenes.get(beat.id)
        read = f"{scene.gesture}; {scene.intent}" if scene else beat.gesture
        tags = ",".join(f"{name}x{count}" if count > 1 else name for name, count in events.most_common(4))
        lines.append(f"{beat.id}|{beat.start_frame}-{beat.end_frame}|{beat.kind}|{read}|{tags}")
    theme = next((scene.scene for scene in brief.scene if scene.scene), "")
    options = ", ".join(name for name in applicable(brief) if name != "drawing")
    catalog = "\n".join(f"- {name}: {CATALOG[name]}" for name in applicable(brief))
    return f"""Video {brief.video.width}x{brief.video.height}, {brief.video.frame_count} fotogramas a {brief.video.fps:.0f} fps. Escena: {theme or "desconocida"}.
Beats (id|fotogramas|tipo|lectura|eventos):
{chr(10).join(lines)}

Estrategias disponibles:
{catalog}

Dibujos propios: trazos SVG (solo M, L, C, Z) en un espacio que sigue a la persona.
- face: (0,0) entre los ojos; ojos en (-0.5,0) y (0.5,0); punta de nariz (0,0.6); boca (0,1.0); barbilla (0,1.5); frente (0,-0.9); coronilla (0,-1.6); bordes de la cara x=±1.1.
- body: (0,0) entre hombros; hombros (±0.5,0); caderas (±0.35,1.3); cabeza (0,-0.9).
- left_hand / right_hand: (0,0) en la muñeca, unidad = ancho de hombros.
y crece hacia abajo. Coordenadas en [-4,4]. Máximo 24 trazos por dibujo, 600 puntos en total. Los trazos se dibujan en el orden que los escribas.
variants: 1 a 3 juegos alternativos del mismo dibujo para animarlo (aleteo, llama, parpadeo).

Responde SOLO este JSON:
{{"title":"","theme":"","motif":"idea visual que se repite","palette":[[r,g,b]],
"beats":[{{"beat":0,"use":["{options.split(', ')[0] if options else 'face_linework'}"],"drawing":"id o vacío","color":0,"intensity":1}}],
"drawings":{{"id":{{"space":"face","strokes":["M -0.6 -0.9 L -0.9 -1.7 L -0.3 -1.0"],"variants":[],"draw_on":12}}}}}}
use admite: {options}. color es índice de palette (valores 0-1)."""


ART_SYSTEM = (
    "Eres director de arte y animador de VFX 2D en neón sobre video real. No tocas el plano: "
    "diseñas capas de luz que siguen a la persona. Piensa como un artista: un motivo visual "
    "que evoluciona durante el clip, un protagonista por beat, contraste entre beats tranquilos "
    "y explosivos, y dibujos simples y legibles, de línea continua, que interpreten lo que la "
    "persona hace o siente. Reutiliza dibujos entre beats en vez de inventar uno por beat. "
    "Responde solo JSON válido."
)


def keyframes(video: Path, brief: MotionBrief, count: int) -> list[bytes]:
    """Un JPEG pequeño por beat, repartidos en el clip. Baja resolución a propósito."""
    if count <= 0 or not brief.beats or not video.exists():
        return []
    import cv2

    beats = brief.beats
    step = max(1, len(beats) // count)
    picks = [beats[i] for i in range(0, len(beats), step)][:count]
    cap = cv2.VideoCapture(str(video))
    blobs: list[bytes] = []
    try:
        for beat in picks:
            cap.set(cv2.CAP_PROP_POS_FRAMES, (beat.start_frame + beat.end_frame) // 2)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            scale = 512 / max(h, w)
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
            ok, encoded = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                blobs.append(encoded.tobytes())
    finally:
        cap.release()
    return blobs
