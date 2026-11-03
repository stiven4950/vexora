"""Motor procedural. Lee tracks, eventos y el guion; no toca el video original."""

from __future__ import annotations

import bisect

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.attention import focus_at
from vfxglow.analysis.regions import load_regions, person_mask
from vfxglow.engine.focus import focus_gain

from vfxglow.analysis.names import FACE_ANCHORS
from vfxglow.analysis.schema import FrameRecord, MotionEvent
from vfxglow.config import EngineConfig
from vfxglow.director.schema import EffectScript, effect_group, envelope
from vfxglow.analysis.appearance import Appearance
from vfxglow.engine.anchors import PointSet, collect_points, joint_velocity
from vfxglow.engine.constraints import FrameState, gain_for
from vfxglow.engine.effects import EffectRuntime, render_effect
from vfxglow.engine.raster import directional_blur, empty_layer, soften_alpha
from vfxglow.engine.swoosh import set_resolution
from vfxglow.engine.timeline import ActivationTimeline
from vfxglow.io.store import read_jsonl


# Fracción por cuadro con la que el ambiente se aparta (o vuelve) cuando hay un efecto grande en la cara.
AMBIENT_YIELD = 0.25

class EffectEngine:
    def __init__(
        self,
        script: EffectScript,
        config: EngineConfig,
        events: list[MotionEvent] | None = None,
        cuts: list[int] | None = None,
        fps: float = 30.0,
    ) -> None:
        self.script = script
        self.config = config
        self.events = sorted([*(events or []), *script.extra_events], key=lambda e: e.start_frame)
        self.cuts = set(cuts or [])
        # Los efectos de elementos guardan estado entre fotogramas en sus módulos: cada video (y
        # cada tramo que se vuelve a dibujar en el editor) empieza en limpio.
        from vfxglow.engine import airbend, firebend, waterbend

        for module in (airbend, firebend, waterbend):
            module.reset()
        self.runtimes = [EffectRuntime(effect, script.seed, config.history) for effect in script.effects]
        for runtime in self.runtimes:
            runtime.fps = fps
        self.timelines = [ActivationTimeline(effect, self.events) for effect in script.effects]
        # Golpes de la música (para el ecualizador): todos los efectos los ven.
        beats = sorted(e.start_frame for e in self.events if e.name == "beat")
        # Pasos (para las huellas): dónde y cuándo cayó cada pie.
        steps = [(e.end_frame, e.position, e.kind) for e in self.events if e.name in ("step", "stomp")]
        # El relevo: lo último que dibujó cada persona, para que un dibujo se convierta en el siguiente.
        relay: dict = {}
        for runtime in self.runtimes:
            runtime.beats = beats
            runtime.steps = steps
            runtime.relay = relay
        # El cierre va último: necesita ver lo que dibujaron los demás en el fotograma.
        # Los rostros especiales primero: si uno está encendido, los demás efectos de cara se apagan en
        # ese cuadro (engine/face_zone.py). El cierre va último.
        from vfxglow.engine.face_zone import is_ambient, is_big, is_special, on_face

        # El ambiente va después de todo lo demás: así sabe si en ese cuadro hay un efecto grande en la cara.
        order = sorted(range(len(self.runtimes)), key=lambda i: (script.effects[i].type == "closing_stars", not is_special(script.effects[i]), is_ambient(script.effects[i])))
        self._special = {effect.id for effect in script.effects if is_special(effect)}
        self._on_face = {effect.id for effect in script.effects if on_face(effect)}
        self._big = {effect.id for effect in script.effects if is_big(effect)}
        self._ambient = {effect.id for effect in script.effects if is_ambient(effect)}
        self._big_frame = -1
        self._mask_frame = -1
        self._needs_regions = needs_regions(script)
        self._needs_garment = needs_garment(script)
        self._garment: dict | None = None
        self.runtimes = [self.runtimes[i] for i in order]
        self.timelines = [self.timelines[i] for i in order]
        self.chapter_starts = [chapter.start_frame for chapter in script.chapters]
        self.fps = fps
        self.closing = next((effect for effect in script.effects if effect.type == "closing_stars"), None)
        self.appearance: Appearance | None = None
        self._appearance_dir: Path | None = None
        self._face_last: dict[str, np.ndarray] = {}
        self._face_age = 0
        # Capa vacía compartida (solo lectura) y búfer de trabajo para los efectos que no dibujan nada.
        self.blank: np.ndarray | None = None
        self._scratch: np.ndarray | None = None

    def _chapter_colors(self, frame_index: int) -> list | None:
        if not self.chapter_starts:
            return None
        index = max(bisect.bisect_right(self.chapter_starts, frame_index) - 1, 0)
        return self.script.chapters[index].colors

    def _hold_face(self, points: PointSet) -> float:
        """Si la malla se pierde unos fotogramas, reutiliza la última y la desvanece."""
        face = {name: value for name, value in points.items() if _is_face(name)}
        if any(name[5:].isdigit() for name in face if name.startswith("face_")):
            self._face_last = face
            self._face_age = 0
            return 1.0
        hold = max(self.config.face_hold, 0)
        if not self._face_last or self._face_age >= hold:
            self._face_last = {}
            return 1.0 if "face_center" in points else 0.0
        self._face_age += 1
        fade = 1.0 - self._face_age / (hold + 1)
        for name, value in self._face_last.items():
            if name not in points:
                points.put(name, value, fade, "hold")
        return fade

    def render_frame(
        self,
        track: FrameRecord | None,
        frame_index: int,
        width: int,
        height: int,
        frame_count: int,
        run_dir: Path | None = None,
    ) -> list[tuple[str, str, np.ndarray]]:
        set_resolution(width)
        if self.blank is None or self.blank.shape != (height, width, 4):
            self.blank = empty_layer(height, width)
            self.blank.flags.writeable = False
            self._scratch = empty_layer(height, width)
        points = collect_points(track, width, height)
        cut = frame_index in self.cuts
        if cut:
            # Otro plano: la última malla pertenece a una cara que ya no está.
            self._face_last = {}
            self._face_age = 0
        face_fade = self._hold_face(points)
        self._attach_appearance(run_dir, frame_index, width, height)
        state = FrameState(face_fade=face_fade, bright=self._bright(frame_index))
        for name in list(points):
            if name.startswith("vel:") or _is_face(name):
                continue
            vx, vy = joint_velocity(track, name)
            points[f"vel:{name}"] = np.array([vx * width, vy * height], dtype=np.float64)
        mask = _load_mask(run_dir, track, width, height)
        regions = load_regions(run_dir, frame_index, width, height) if self._needs_regions else None
        person = person_mask(regions) if regions is not None else None
        if self._needs_garment and self._garment is None:
            from vfxglow.analysis.garment import load_garment

            self._garment = load_garment(run_dir)
        garment = self._garment
        head_px = None
        if track is not None and track.head_contour:
            head_px = np.array([[x * width, y * height] for x, y in track.head_contour], dtype=np.float64)
        layers: list[tuple[str, str, np.ndarray]] = []
        for runtime, timeline in zip(self.runtimes, self.timelines, strict=True):
            effect = runtime.effect
            event_gain, event = timeline.at(frame_index)
            if effect.triggers:
                gain = event_gain
            else:
                gain = envelope(frame_index, effect.time, frame_count)
            gain *= effect.style.intensity
            if self.closing is not None:
                from vfxglow.engine.closing import closing_window, draw_closing, other_gain

                start, length = closing_window(self.closing, self.fps, frame_count)
                if effect is self.closing:
                    layers.append((effect.id, effect_group(effect), draw_closing(runtime, [l for _, _, l in layers], frame_index, start, length, width, height)))
                    continue
                gain *= other_gain(frame_index, start, length)
            if self.script.attention and effect.style.focus and gain > 0:
                gain *= focus_gain(runtime, effect, event, focus_at(self.script.attention, frame_index))
            gain *= gain_for(effect, state, points, self.config.min_point_confidence)
            if effect.id in self._on_face and self._mask_frame == frame_index:
                gain = 0.0  # hay un rostro especial puesto: nada más sobre la cara
            if effect.id in self._ambient:
                # Con un efecto grande en la cara, el ambiente se aparta de a poco (no de golpe).
                target = 0.0 if self._big_frame == frame_index else 1.0
                runtime.yield_level = getattr(runtime, "yield_level", 1.0) + (target - getattr(runtime, "yield_level", 1.0)) * AMBIENT_YIELD
                gain *= runtime.yield_level if runtime.yield_level > 0.02 else 0.0
            # Un efecto disparado no sobrevive a un corte de toma: lo que empezó en la toma anterior
            # (la tierra que se partió, la bestia que vuela) no sigue dibujándose en la nueva.
            keep = effect.style.keep_on_cut
            if cut and not keep and runtime.active_frames > 0 and effect.triggers and event is not None:
                runtime.cut_event = event.start_frame
            if effect.triggers and event is not None and getattr(runtime, "cut_event", None) == event.start_frame:
                gain = 0.0
            if cut and not keep:
                runtime.swoosh.clear()
            if (cut and not keep) or gain <= 0:
                runtime.active_frames = 0
            elif event is not None and getattr(runtime, "event_start", event.start_frame) != event.start_frame:
                # Pasa sin pausa a otra activación (outfits seguidos del desfile): cuenta como un
                # encendido nuevo (su fase y el color de su capítulo vuelven a empezar).
                runtime.active_frames = 0
            if event is not None:
                runtime.event_start = event.start_frame
            if gain > 0:
                runtime.active_frames += 1
                if effect.id in self._special:
                    self._mask_frame = frame_index
                if effect.id in self._big:
                    self._big_frame = frame_index
            if event is not None and event.position is not None:
                runtime.anchor_point = np.array(
                    [event.position[0] * width, event.position[1] * height],
                    dtype=np.float64,
                )
            elif event is not None and gain > 0 and event.target in points:
                # Evento sin posición (fijado a mano, copia para la pareja): la articulación que nombra.
                runtime.anchor_point = np.array(points[event.target], dtype=np.float64)
            # Un efecto disparado conserva el color del capítulo en que se encendió.
            if runtime.active_frames == 1:
                runtime.chapter_frame = frame_index
            runtime.chapter_colors = self._chapter_colors(runtime.chapter_frame if effect.triggers and gain > 0 else frame_index)
            runtime.frame_count = frame_count  # los efectos de cierre saben cuánto falta (firebend.fire_wall)
            # El próximo corte de toma: un efecto largo (el aro grande) se apaga antes, no de golpe en él.
            runtime.next_cut = next((c for c in sorted(self.cuts) if c > frame_index), None)
            runtime.contour_px = None
            runtime.regions = regions
            runtime.garment = garment
            runtime.tool_tip = None
            runtime.appearance = self.appearance
            if self.appearance is not None:
                poly = self.appearance.contours.get(frame_index)
                if poly:
                    runtime.contour_px = np.array([[x * width, y * height] for x, y in poly], dtype=np.float64)
                tip = self.appearance.tips.get(frame_index)
                if tip is not None:
                    runtime.tool_tip = np.array([tip[0] * width, tip[1] * height], dtype=np.float64)
            if effect.target.kind == "contour" and effect.target.id == "head":
                # Contorno de cabeza del segmentador, solo donde faltó la malla facial.
                runtime.contour_px = head_px
            # Un búfer a tamaño completo por cada efecto que no dibuja nada era casi todo el coste del
            # motor. El renderizador corre igual (con ganancia 0 envejece partículas y estelas), pero
            # sobre un búfer reutilizado; si no dejó nada, la capa es la vacía compartida.
            idle = gain <= 0 and effect.render.persistence <= 0
            layer = render_effect(
                runtime,
                track,
                points,
                frame_index,
                width,
                height,
                gain,
                mask,
                self.config.max_particles,
                event,
                scratch=self._scratch if idle else None,
            )
            if idle:
                if layer is self._scratch:
                    if not cv2.hasNonZero(layer.reshape(height, width * 4)):
                        layers.append((effect.id, effect_group(effect), self.blank))
                        continue
                    self._scratch = empty_layer(height, width)  # dibujó con gain 0: ese búfer ya es la capa
                else:
                    self._scratch = empty_layer(height, width)  # pudo ensuciar el búfer antes de cambiar de capa
            if effect.render.occlude and mask is None and person is not None and gain > 0:
                # Sin máscara de SAM: la persona de analysis/regions.py, con el borde suave. El corte
                # binario de render_effect deja escalones alrededor del pelo.
                layer *= (1.0 - person)[..., None]
            if (effect.style.tint is not None or effect.style.scale != 1.0) and gain > 0:
                layer = self._edited(layer, runtime, points, width, height)
            decay = effect.render.persistence
            if decay > 0:
                if runtime.persist is None or runtime.persist.shape != layer.shape:
                    runtime.persist = np.zeros_like(layer)
                runtime.persist = layer + runtime.persist * np.float32(decay)
                runtime.persist[..., 3] = np.clip(runtime.persist[..., 3], 0.0, 1.0)
                layer = runtime.persist.copy()
            if effect.render.motion_blur > 0 and gain > 0:
                vx, vy = joint_velocity(track, effect.target.id)
                directional_blur(layer, vx * width, vy * height, effect.render.motion_blur)
            soften_alpha(layer)
            layers.append((effect.id, effect_group(effect), layer))
        return layers


    def _edited(self, layer: np.ndarray, runtime, points: dict, width: int, height: int) -> np.ndarray:
        """El color y el tamaño que se eligieron en el editor para la pista del efecto."""
        from vfxglow.engine.tint import recolor, scale_about

        effect = runtime.effect
        if effect.style.tint is not None:
            layer = recolor(layer, effect.style.tint)
        if effect.style.scale != 1.0:
            # Se escala alrededor de donde está el efecto: su ancla si la tiene; si no, el centro.
            anchor = runtime.anchor_point
            if anchor is None and effect.target.id in points:
                anchor = points[effect.target.id]
            center = (float(anchor[0]), float(anchor[1])) if anchor is not None else (width / 2.0, height / 2.0)
            layer = scale_about(layer, effect.style.scale, center)
        return layer

    def _bright(self, frame_index: int) -> frozenset[str]:
        if self.appearance is None:
            return frozenset()
        return frozenset(
            region for start, end, region in self.appearance.bright_spans if start <= frame_index <= end
        )

    def _attach_appearance(self, run_dir: Path | None, frame_index: int, width: int, height: int) -> None:
        if run_dir is None or self.appearance is not None or self._appearance_dir == run_dir:
            return
        self._appearance_dir = run_dir
        path = run_dir / "analysis" / "appearance.json"
        self.appearance = Appearance.load(path) if path.exists() else Appearance()


_FACE_ANCHOR_SET = set(FACE_ANCHORS)


def needs_garment(script: EffectScript) -> bool:
    """El guion delinea la ropa (analysis/garment.py, estilo desfile)."""
    from vfxglow.engine.garment_fx import GARMENT_FX

    return any(shape in GARMENT_FX for effect in script.effects for shape in effect.style.shapes or [])


def needs_regions(script: EffectScript) -> bool:
    """El guion usa efectos que necesitan saber qué es cada píxel (analysis/regions.py)."""
    from vfxglow.engine.ambient_fx import AMBIENT

    return any(shape in AMBIENT for effect in script.effects for shape in effect.style.shapes or [])


def _is_face(name: str) -> bool:
    return name.startswith("face_") or name in _FACE_ANCHOR_SET


def load_tracks(path: Path) -> list[FrameRecord]:
    return read_jsonl(path, FrameRecord)


def load_events(path: Path) -> list[MotionEvent]:
    if not path.exists():
        return []
    return read_jsonl(path, MotionEvent)


def save_layer(path: Path, layer: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, layer.astype(np.float16))


def load_layer(path: Path) -> np.ndarray:
    return np.load(path).astype(np.float32)


def _load_mask(run_dir: Path | None, track: FrameRecord | None, width: int, height: int) -> np.ndarray | None:
    if run_dir is None or track is None or not track.mask_path:
        return None
    path = run_dir / track.mask_path
    if not path.exists():
        return None
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        return None
    if mask.shape[:2] != (height, width):
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
    return mask.astype(np.float32) / 255.0
