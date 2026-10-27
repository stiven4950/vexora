"""Orquesta las etapas y evita repetir trabajo si la caché sigue vigente."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import cv2

from vfxglow import telemetry
from vfxglow.analysis.analyzer import analyze_video
from vfxglow.analysis.schema import AnalysisHeader, VideoMeta
from vfxglow.config import LAYER_GROUPS, PRESET_ALIASES, catalog_file, catalog_name, load_config, preset_file
from vfxglow.device import require_cuda, resolve_device
from vfxglow.director.director import CreativeDirector
from vfxglow.director.schema import EffectScript, effect_group
from vfxglow.engine.engine import EffectEngine, load_events, load_layer, load_tracks, save_layer
from pydantic import BaseModel

from vfxglow.io.store import (
    write_jsonl,
    Manifest,
    code_fingerprint,
    load_manifest,
    read_model,
    save_manifest,
    sha256_file,
    stage_key,
    write_model,
)
from vfxglow.io.video import VideoReader

log = logging.getLogger("vfxglow")

# Código del que depende cada etapa. Si cambia, la caché de esa etapa deja de valer.
_STAGE_CODE: dict[str, tuple[str, ...]] = {
    "analyze": ("analysis", "io/video.py", "geom.py"),
    "direct": ("director", "analysis/names.py"),
    "render": ("engine", "director/schema.py", "analysis/names.py", "analysis/appearance.py", "analysis/beats.py", "geom.py"),
    "compose": ("composite",),
}


# Los gestos son señales derivadas: con una etiqueta nueva en analyzer.DERIVED se recalculan sobre
# el análisis guardado (Pipeline._ensure_derived) en segundos. Que su código no invalide el
# análisis entero (un detector nuevo costaba rehacer ~15 min de pose por video). extras.py solo lo
# usa la vista previa del Estudio, en memoria: no forma parte del análisis guardado.
_STAGE_SKIP: dict[str, tuple[str, ...]] = {"analyze": ("analysis/gestures.py", "analysis/extras.py")}


def _code(stage: str) -> str:
    return code_fingerprint(*_STAGE_CODE[stage], exclude=_STAGE_SKIP.get(stage, ()))


# Un candado por carpeta de análisis: si el análisis de una subida está en curso y llega el trabajo
# del mismo video, el trabajo espera y luego encuentra la caché en vez de analizar dos veces.
_ANALYSIS_LOCKS: dict[str, threading.Lock] = {}
_ANALYSIS_LOCKS_GUARD = threading.Lock()


def analysis_lock(run_dir: Path) -> threading.Lock:
    """El candado (en este proceso) de una carpeta de análisis; siempre el mismo para la misma."""
    key = str(Path(run_dir).resolve())
    with _ANALYSIS_LOCKS_GUARD:
        return _ANALYSIS_LOCKS.setdefault(key, threading.Lock())


class _LayerIndex(BaseModel):
    version: str = "1.0"
    effects: dict[str, str]


def apply_catalog_needs(config_path: Path, config) -> None:
    """Un catálogo puede pedir señales que el análisis no calcula por defecto."""
    from vfxglow.director.choreography import load_catalog

    path = catalog_file(config_path, config.director.catalog)
    if not path.exists():
        return
    catalog = load_catalog(path)
    needs = set(catalog.needs)
    if "blades" in needs and config.analysis.blades.mode == "off":
        config.analysis.blades.mode = "always"
    if "props" in needs and not config.analysis.props.query:
        config.analysis.props.query = catalog.prop


class Pipeline:
    def __init__(
        self,
        config_path: Path,
        video: Path,
        preset: str | None = None,
        level: str | None = None,
        force: bool = False,
        layers: str | None = None,
        director: str | None = None,
        catalog: str | None = None,
        seed: int | None = None,
        take: int = 0,
        season: str | None = None,
        fire_style: str | None = None,
        bolt_style: str | None = None,
        pins: Path | None = None,
        wardrobe: dict[str, str] | None = None,
        deep: bool | None = None,
        prop: str | None = None,
    ) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        self.prop = prop  # el objeto protagonista elegido (director/prop_choices.py)
        if deep is not None:
            # Análisis profundo (director/deep.py): opcional, más lento y de pago.
            self.config.director.deep.enabled = bool(deep)
        if director:
            self.config.director.provider = director  # type: ignore[assignment]
        if preset in PRESET_ALIASES:
            catalog, preset = catalog or PRESET_ALIASES[preset], None
        if preset:
            self.config.director.provider = "preset"
            self.config.director.preset = preset
        if pins is not None:
            # Guion de prueba: lo fijado manda; el catálogo sale de --catalog o del propio guion.
            from vfxglow.director.pins import load_pins

            if not pins.exists():
                raise FileNotFoundError(f"No existe el guion de prueba {pins}")
            catalog = catalog or load_pins(pins).catalogo
            if not catalog:
                raise ValueError("El guion de prueba necesita un catálogo: --catalog o `catalogo:` en el archivo")
            self.config.director.pins = str(pins.resolve())
        if catalog:
            self.config.director.provider = "catalog"
            self.config.director.catalog = catalog_name(catalog)
        if seed is not None:
            self.config.director.seed = seed
        if wardrobe:
            self.config.director.wardrobe = dict(wardrobe)
        # Sin semilla, la coreografía es la del puesto `take` entre varias candidatas (0 = la mejor).
        self.config.director.take = max(int(take), 0)
        if season:
            self.config.director.season = season
        if fire_style or bolt_style:
            from vfxglow.director.looks import check

            check(fire_style, bolt_style)
            self.config.director.fire_style = fire_style or self.config.director.fire_style
            self.config.director.bolt_style = bolt_style or self.config.director.bolt_style
        if self.config.director.provider == "catalog":
            self._apply_catalog_needs()
        if level:
            self.config.analysis.level = level  # type: ignore[assignment]
        self.video = video
        self.force = force
        if layers:
            wanted = {name.strip() for name in layers.split(",") if name.strip()}
            self.config.composite.groups = {name: name in wanted for name in LAYER_GROUPS}
        self.device = resolve_device(self.config.device)
        self._guard_optional_stages()
        digest = sha256_file(video)
        runs = Path(self.config.paths.runs_dir)
        if not runs.is_absolute():
            runs = Path.cwd() / runs
        self.run_dir = runs / f"{video.stem}-{digest[:8]}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.run_dir / "manifest.json"
        self.manifest = load_manifest(self.manifest_path) or Manifest(
            video_path=str(video),
            video_sha256=digest,
            device=self.device,
        )

    def _apply_catalog_needs(self) -> None:
        apply_catalog_needs(self.config_path, self.config)
        props = self.config.analysis.props
        if self.prop and props.query:  # solo si el catálogo sigue un objeto
            from vfxglow.director.prop_choices import PROP_CHOICES, check

            check(self.prop)
            choice = PROP_CHOICES[self.prop]
            props.query, props.wearable = choice.query, choice.wearable

    def _ensure_derived(self, brief_path: Path) -> None:
        """Análisis anteriores a una señal derivada (piel, gestos, atención): se calcula ahora con
        los tracks guardados, en segundos, sin rehacer el análisis. Los eventos nuevos se suman
        también a events.jsonl, que es lo que lee el motor."""
        from vfxglow.analysis.analyzer import DERIVED
        from vfxglow.analysis.schema import MotionBrief

        analysis = self.run_dir / "analysis"
        tracks_path, events_path = analysis / "tracks.jsonl", analysis / "events.jsonl"
        if not brief_path.exists() or not tracks_path.exists():
            return
        brief = read_model(brief_path, MotionBrief)
        done = set(brief.derived) | ({"skin"} if brief.skin else set())
        missing = [name for name in DERIVED if name not in done]
        if not missing:
            return
        tracks = load_tracks(tracks_path)
        meta = brief.video
        update: dict = {}
        events = list(brief.events)
        if "skin" in missing:
            from vfxglow.analysis.skin import estimate_skin

            update["skin"] = estimate_skin(self.video, tracks)
        if any(name.startswith("gestures") for name in missing):
            from vfxglow.analysis.gestures import GESTURE_DETECTORS, GESTURE_NAMES

            found = [e for detect in GESTURE_DETECTORS for e in detect(tracks, meta.fps, meta.width, meta.height)]
            names = {e.name for e in found} | GESTURE_NAMES
            events = sorted([e for e in events if e.name not in names] + found, key=lambda e: (e.start_frame, e.name))
            update["events"] = events
            write_jsonl(events_path, events)
            missing.append("attention")  # la atención depende de los gestos
        if "attention" in missing:
            from vfxglow.analysis.attention import attention_timeline

            update["attention"] = attention_timeline(tracks, events, meta.fps, meta.width, meta.height)
        if "duet" in missing:
            from vfxglow.analysis.duet import duet_timeline

            update["duet"] = duet_timeline(tracks, meta.fps, meta.width, meta.height)
        update["derived"] = list(DERIVED)
        write_model(brief_path, brief.model_copy(update=update))
        log.info("Señales derivadas calculadas: %s", ", ".join(dict.fromkeys(missing)))

    def _guard_optional_stages(self) -> None:
        if self.config.refiner.enabled:
            require_cuda("El refinador difusor", self.device)
        if self.config.analysis.level == "masks":
            require_cuda("Las máscaras SAM 2.1", self.device)

    def run(self) -> Path:
        # Cada etapa deja stage.started / stage.finished con su duración (telemetry.py).
        with telemetry.span("analyze", analysis_level=self.config.analysis.level):
            self.analyze()
        with telemetry.span("direct", provider=self.config.director.provider):
            self.direct()
        if self.config.refiner.enabled or self.config.engine.keep_layers:
            with telemetry.span("render"):
                self.render()
            with telemetry.span("refine"):
                self.refine()
            with telemetry.span("compose"):
                return self.compose()
        # Sin capas en disco, render y composición van juntos fotograma a fotograma.
        with telemetry.span("compose", streamed=True):
            return self.compose(stream=True)

    def analyze(self) -> None:
        with analysis_lock(self.run_dir):
            # Otro Pipeline pudo terminar el análisis mientras esperábamos: se relee el manifiesto.
            self.manifest = load_manifest(self.manifest_path) or self.manifest
            self._analyze_locked()

    def _analyze_locked(self) -> None:
        key = stage_key("analyze-1", self.manifest.video_sha256, self.config.analysis.model_dump_json(), _code("analyze"))
        tracks = self.run_dir / "analysis" / "tracks.jsonl"
        if not self.force and self.manifest.stages.get("analyze") == key and tracks.exists():
            log.info("Análisis en caché")
            telemetry.annotate(cache_hit=True)
            return
        log.info("Analizando %s en %s", self.video.name, self.device)
        analyze_video(self.video, self.run_dir, self.config, self.device)
        self._mark("analyze", key, level=self.config.analysis.level, code=_code("analyze")[:12])

    def direct(self) -> None:
        brief_path = self.run_dir / "analysis" / "motion_brief.json"
        self._ensure_derived(brief_path)
        self._deep_script()
        preset_path = preset_file(self.config_path, self.config.director.preset)
        preset_hash = sha256_file(preset_path) if self.config.director.provider == "preset" and preset_path.exists() else ""
        catalog_path = catalog_file(self.config_path, self.config.director.catalog)
        if self.config.director.provider == "catalog" and catalog_path.exists():
            preset_hash = sha256_file(catalog_path)
        pins_path = Path(self.config.director.pins) if self.config.director.pins else None
        key = stage_key(
            "direct-1",
            sha256_file(brief_path),
            self.config.director.model_dump_json(),
            preset_hash,
            sha256_file(pins_path) if pins_path is not None else "",
            _code("direct"),
        )
        dest = self.run_dir / "scripts" / "effect_script.json"
        if not self.force and self.manifest.stages.get("direct") == key and dest.exists():
            log.info("Guion en caché")
            telemetry.annotate(cache_hit=True)
            return
        from vfxglow.analysis.schema import MotionBrief

        brief = read_model(brief_path, MotionBrief)
        director = CreativeDirector(
            self.config.director,
            self.config_path.resolve().parent / "presets",
            cache_dir=self.run_dir / "scripts" / "director_cache",
            video=self.video,
        )
        script = director.create(brief)
        write_model(dest, script)
        # Copia por tema: cada preset conserva su guion aunque se dirija otro después.
        write_model(dest.with_name(f"{script.theme}.json"), script)
        if director.choreography is not None:
            # Qué reacción salió en cada acción: la trazabilidad del sorteo.
            write_model(dest.with_name("choreography.json"), director.choreography)
            write_model(dest.with_name(f"{script.theme}.choreography.json"), director.choreography)
        log.info("Guion %s con %d efectos", script.theme, len(script.effects))
        self._mark(
            "direct",
            key,
            provider=self.config.director.provider,
            preset={"preset": self.config.director.preset, "catalog": self.config.director.catalog}.get(self.config.director.provider, ""),
            seed=str(self.config.director.seed if self.config.director.seed is not None else ""),
            take=str(self.config.director.take),
            pins=pins_path.name if pins_path is not None else "",
            theme=script.theme,
            script=sha256_file(dest)[:12],
            code=_code("direct")[:12],
        )

    def direct_in_memory(self, brief=None) -> EffectScript:
        """La coreografía del catálogo con el análisis en caché, sin escribir nada en la carpeta de la
        corrida (ni guion, ni manifiesto): la vista previa del Estudio la usa para no pisar el guion
        de un trabajo real que comparta el video. Sin análisis profundo. `brief`: uno ya cargado
        (p. ej. con los eventos de `window_extras`)."""
        from vfxglow.analysis.schema import MotionBrief

        if brief is None:
            brief_path = self.run_dir / "analysis" / "motion_brief.json"
            self._ensure_derived(brief_path)
            brief = read_model(brief_path, MotionBrief)
        director = CreativeDirector(self.config.director, self.config_path.resolve().parent / "presets", video=self.video)
        return director.create(brief)

    def window_extras(self, window: tuple[int, int]):
        """Si el catálogo pide hojas u objeto (`needs`), los calcula solo en `window` y su
        calentamiento (analysis/extras.py), sin tocar el análisis guardado. Devuelve (brief, pistas,
        eventos) para dirigir y dibujar la vista previa, o None si el catálogo no pide nada."""
        analysis = self.config.analysis
        if analysis.blades.mode == "off" and not analysis.props.query:
            return None
        from vfxglow.analysis.extras import BLADE_EVENTS, window_extras
        from vfxglow.analysis.schema import MotionBrief
        from vfxglow.director.edits import WARMUP_S

        folder = self.run_dir / "analysis"
        brief_path = folder / "motion_brief.json"
        self._ensure_derived(brief_path)
        brief = read_model(brief_path, MotionBrief)
        meta = self._meta()
        tracks = {track.frame: track for track in load_tracks(folder / "tracks.jsonl")}
        start = max(window[0] - int(round(WARMUP_S * (meta.fps or 30.0))), 0)
        frames = [tracks[i].model_copy(deep=True) for i in range(start, window[1] + 1) if i in tracks]
        found = window_extras(self.video, frames, meta, self.config)
        tracks.update({frame.frame: frame for frame in frames})
        # Los eventos de hojas y objeto del análisis guardado (si los había) se cambian por los del tramo.
        replaced = set(BLADE_EVENTS) | {"prop_transfer", "prop_worn", "prop_spin"}
        events = sorted([e for e in load_events(folder / "events.jsonl") if e.name not in replaced] + found, key=lambda e: (e.start_frame, e.name))
        brief_events = sorted([e for e in brief.events if e.name not in replaced] + found, key=lambda e: (e.start_frame, e.name))
        return brief.model_copy(update={"events": brief_events}), tracks, events

    def _deep_script(self) -> None:
        """Con el análisis profundo activo (y sin un guion fijado a mano), el modelo ve el video
        completo y escribe la coreografía como guion de prueba; desde ahí el flujo es el de
        siempre. Sus efectos nuevos se anotan en la lista común de efectos pedidos."""
        director = self.config.director
        if not director.deep.enabled or director.provider != "catalog" or director.pins:
            return
        from vfxglow.director.choreography import load_catalog
        from vfxglow.director.deep import deep_pins, record_proposals, sides_from_tracks

        meta = self._meta()
        catalog = load_catalog(catalog_file(self.config_path, director.catalog))
        out = self.run_dir / "scripts"
        tracks_path = self.run_dir / "analysis" / "tracks.jsonl"
        who = sides_from_tracks(load_tracks(tracks_path), meta.fps or 30.0) if tracks_path.exists() else None
        from vfxglow.analysis.schema import MotionBrief

        brief = read_model(self.run_dir / "analysis" / "motion_brief.json", MotionBrief)
        with telemetry.span("deep", model=director.deep.model):
            guion = deep_pins(self.video, self.manifest.video_sha256, catalog, meta.frame_count / (meta.fps or 30.0), director.deep, out, who, brief)
        added = record_proposals(out / "deep_lectura.json", self.run_dir.parent / "efectos_propuestos.jsonl", self.video.name)
        if added:
            log.info("%d efectos nuevos anotados en %s", added, self.run_dir.parent / "efectos_propuestos.jsonl")
        director.pins = str(guion.resolve())

    def _render_key(self) -> str:
        analysis = self.run_dir / "analysis"
        optional = [analysis / "events.jsonl", analysis / "appearance.json", analysis / "motion_brief.json"]
        return stage_key(
            "render-4",
            sha256_file(self.run_dir / "scripts" / "effect_script.json"),
            sha256_file(analysis / "tracks.jsonl"),
            *[sha256_file(path) if path.exists() else "" for path in optional],
            self.config.engine.model_dump_json(),
            _code("render"),
        )

    def _engine(self, script: EffectScript, events: list | None = None, tracks: dict | None = None) -> tuple[EffectEngine, dict]:
        from vfxglow.analysis.beats import cut_frames
        from vfxglow.analysis.schema import MotionBrief

        analysis = self.run_dir / "analysis"
        meta = self._meta()
        brief_path = analysis / "motion_brief.json"
        cuts = cut_frames(read_model(brief_path, MotionBrief).beats) if brief_path.exists() else []
        if tracks is None:
            tracks = {track.frame: track for track in load_tracks(analysis / "tracks.jsonl")}
        events = load_events(analysis / "events.jsonl") if events is None else events
        engine = EffectEngine(script, self.config.engine, events, cuts=cuts, fps=meta.fps)
        return engine, tracks

    def render(self) -> None:
        """Guarda cada capa en disco. Solo para depurar o para el refinador: ocupa ~7 MB por fotograma y efecto."""
        script_path = self.run_dir / "scripts" / "effect_script.json"
        key = self._render_key()
        script = read_model(script_path, EffectScript)
        marker = self.run_dir / "layers" / script.effects[0].id / "f000000.npy"
        if not self.force and self.manifest.stages.get("render") == key and marker.exists():
            log.info("Capas en caché")
            return
        meta = self._meta()
        engine, tracks = self._engine(script)
        log.info("Renderizando %d fotogramas", meta.frame_count)
        index_map = {effect.id: effect_group(effect) for effect in script.effects}
        for index in range(meta.frame_count):
            layers = engine.render_frame(tracks.get(index), index, meta.width, meta.height, meta.frame_count, self.run_dir)
            for effect_id, group, layer in layers:
                save_layer(self.run_dir / "layers" / effect_id / f"f{index:06d}.npy", layer)
                index_map[effect_id] = group
        write_model(
            self.run_dir / "layers" / "index.json",
            _LayerIndex(effects=index_map),
        )
        self._mark("render", key)

    def refine(self) -> None:
        if not self.config.refiner.enabled:
            log.info("Refinador apagado")
            return
        from vfxglow.refiner.refiner import DiffusionRefiner

        script = read_model(self.run_dir / "scripts" / "effect_script.json", EffectScript)
        tracks = load_tracks(self.run_dir / "analysis" / "tracks.jsonl")
        DiffusionRefiner(self.config.refiner, self.device).refine_run(
            self.run_dir,
            self.video,
            tracks,
            script,
            self.device,
        )
        self._mark("refine", stage_key("refine-1", self.config.refiner.model_dump_json()))

    def compose(self, stream: bool | None = None) -> Path:
        meta = self._meta()
        script_path = self.run_dir / "scripts" / "effect_script.json"
        script = read_model(script_path, EffectScript)
        # Una salida por tema: face_neon y paint_reveal sobre el mismo video no se pisan.
        # Con guion de prueba, el nombre del guion también: la referencia y la propuesta de Gemini
        # sobre video_35 no se pisan.
        name = script.theme
        if self.config.director.pins:
            name += "__" + Path(self.config.director.pins).stem
        # La temporada y los estilos de fuego y de rayo también: cada combinación su video.
        for tag, value in (("", self.config.director.season), ("fuego-", self.config.director.fire_style), ("rayo-", self.config.director.bolt_style)):
            if value:
                name += f"__{tag}{value}"
        # "Otra versión" y el vestuario también: si no, la versión 2 pisa el video de la 1.
        if self.config.director.take:
            name += f"__toma{self.config.director.take}"
        if self.config.director.wardrobe:
            name += "__vestuario-" + "-".join(f"{who.replace('*', 'todos')}.{what}" for who, what in sorted(self.config.director.wardrobe.items()))
        dest = self.run_dir / "output" / f"{name}.mp4"
        stage = f"compose:{name}"
        index_path = self.run_dir / "layers" / "index.json"
        if stream is None:
            stream = not (index_path.exists() and self.manifest.stages.get("render") == self._render_key())
        key = stage_key(
            "compose-2",
            self._render_key() if stream else self.manifest.stages.get("render", ""),
            self.config.composite.model_dump_json(),
            self.config.refiner.model_dump_json(),
            _code("compose"),
        )
        if not self.force and self.manifest.stages.get(stage) == key and dest.exists():
            log.info("Video final en caché: %s", dest)
            telemetry.annotate(cache_hit=True)
            return dest
        if stream:
            log.info("Renderizando y componiendo %d fotogramas sin capas en disco", meta.frame_count)
        encoder = self._write(script, dest, stream=stream)
        self._mark(
            stage,
            key,
            output=dest.name,
            script=sha256_file(script_path)[:12],
            frames=f"{encoder.frames}/{meta.frame_count}",
            code_render=_code("render")[:12],
            code_compose=_code("compose")[:12],
        )
        log.info("Video final: %s", dest)
        return dest

    # ----- editor de efectos (director/edits.py) -----

    def edit_catalog(self):
        """El catálogo de esta corrida (con vestuario, temporada y looks), para el editor."""
        director = CreativeDirector(self.config.director, self.config_path.resolve().parent / "presets", video=self.video)
        return director.catalog()

    def element_of(self) -> Callable[[str, str], str | None]:
        """El elemento de cada opción del catálogo ("" o None si no tiene): las pistas del editor."""
        from vfxglow.director.edits import element_lookup

        return element_lookup(self.edit_catalog())

    def compile_add(self, option: str, action: str | None, frame: int, length: int, person: str | None, seed: int):
        """Los efectos de un momento nuevo ("Agregar efecto"): se coreografía solo ese momento,
        fijado en `frame`, con el mismo catálogo y semilla. Devuelve (efectos, eventos del gesto,
        opción y acción)."""
        from vfxglow.analysis.schema import MotionBrief
        from vfxglow.director.choreography import choreograph
        from vfxglow.director.pins import Pin, PinFile

        meta = self._meta()
        fps = meta.fps or 30.0
        brief = read_model(self.run_dir / "analysis" / "motion_brief.json", MotionBrief)
        pin = Pin(seg=round(frame / fps, 3), opcion=option, accion=action, persona=person, exacto=True, dur=round(length / fps, 3))
        script, choreography = choreograph(self.edit_catalog(), brief, seed, PinFile(solo_estos=True, momentos=[pin]))
        decision = next((d for d in choreography.decisions if not d.choice.startswith("nada")), None)
        if decision is None:
            raise ValueError(f"La opción {option} no dibuja nada en {frame / fps:.2f} s")
        effects = [effect for effect in script.effects if not effect.id.startswith("always_")]
        events = [e for e in script.extra_events if e.name == decision.action and e.start_frame == decision.frame]
        return effects, events, decision.choice, decision.action

    def render_script(
        self,
        script: EffectScript,
        dest: Path,
        base_output: Path | None = None,
        window: tuple[int, int] | None = None,
        events: list | None = None,
    ) -> Path:
        """Compone `script` (el de una versión editada) sobre el plano en `dest`.

        Con `base_output` y `window` (a, b), solo se dibujan los fotogramas a..b; el resto se copia del
        video de la versión anterior, que es idéntico porque lo no editado sale igual
        (director/edits.py). Antes de `a` se dibuja un calentamiento que no se escribe, para que las
        estelas y el agua lleguen al tramo con su estado. `events`: los gestos con que se dibujó la
        versión base (si no, los del análisis actual)."""
        meta = self._meta()
        if window is not None and base_output is not None:
            log.info("Redibujando solo los fotogramas %d-%d de %d; el resto, del video anterior", window[0], window[1], meta.frame_count)
        else:
            window = base_output = None
            log.info("Renderizando y componiendo %d fotogramas sin capas en disco", meta.frame_count)
        self._write(script, dest, stream=True, base_output=base_output, window=window, events=events)
        log.info("Video final: %s", dest)
        return dest

    def render_preview(self, script: EffectScript, dest: Path, window: tuple[int, int], events: list | None = None, max_side: int | None = None, tracks: dict | None = None) -> int:
        """Vista previa: dibuja `window` (a, b) con el motor real y escribe un MP4 corto solo con esos
        fotogramas (sin audio ni copia del resto). Antes de `a` hay calentamiento que no se escribe.
        `max_side`: lado largo máximo; si el video es mayor se reescala al escribir. Devuelve los
        fotogramas escritos. `tracks`: pistas ya cargadas (las de `window_extras`)."""
        encoder = self._write(script, dest, stream=True, window=window, events=events, only_window=True, max_side=max_side, tracks=tracks)
        return encoder.frames

    def _write(
        self,
        script: EffectScript,
        dest: Path,
        stream: bool,
        base_output: Path | None = None,
        window: tuple[int, int] | None = None,
        events: list | None = None,
        only_window: bool = False,
        max_side: int | None = None,
        tracks: dict | None = None,
    ):
        """El bucle de composición: cada fotograma del plano con sus capas, al codificador.

        `only_window` (con `window`): se escribe solo el tramo, sin audio y sin leer más allá de su
        final; con `max_side` el tramo se dibuja ya reducido (más rápido)."""
        from contextlib import nullcontext

        from vfxglow.composite.composite import composite_frame
        from vfxglow.composite.encode import FrameEncoder
        from vfxglow.director.edits import WARMUP_S

        meta = self._meta()
        engine = None
        if stream:
            engine, tracks = self._engine(script, events, tracks)
        by_id = {effect.id: effect for effect in script.effects}
        # Con tramo: se dibuja desde el calentamiento y se escribe desde el inicio del tramo.
        draw_from = max(window[0] - int(round(WARMUP_S * (meta.fps or 30.0))), 0) if window else 0
        only_window = only_window and window is not None
        if only_window:
            window = (window[0], min(window[1], meta.frame_count - 1))
        out_w, out_h = meta.width, meta.height
        if max_side and max(out_w, out_h) > max_side:
            ratio = max_side / max(out_w, out_h)
            out_w, out_h = max(2, int(out_w * ratio) // 2 * 2), max(2, int(out_h * ratio) // 2 * 2)
        encoder = FrameEncoder(
            dest,
            out_w,
            out_h,
            meta.fps,
            codec=self.config.composite.codec,
            crf=self.config.composite.crf,
            audio_from=self.video if meta.has_audio and not only_window else None,
            frames=(window[1] - window[0] + 1) if only_window else meta.frame_count,
        )
        log.info("Componiendo sobre el plano original")
        try:
            with VideoReader(self.video) as reader, (VideoReader(base_output) if base_output else nullcontext()) as previous:
                source = reader.frames(draw_from, window[1]) if only_window else reader
                frames = zip(source, previous) if previous is not None else ((item, None) for item in source)
                for (index, frame), old in frames:
                    inside = window is None or window[0] <= index <= window[1]
                    layers = []
                    if only_window and (frame.shape[1], frame.shape[0]) != (out_w, out_h):
                        # Vista previa: se dibuja y compone ya al tamaño de salida (las coordenadas
                        # del motor son relativas al cuadro), no a resolución completa.
                        frame = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
                    if engine is not None and (window is None or draw_from <= index <= window[1]):
                        rendered = engine.render_frame(tracks.get(index), index, frame.shape[1], frame.shape[0], meta.frame_count, self.run_dir)
                        layers = [(by_id[effect_id], layer) for effect_id, _group, layer in rendered]
                    elif engine is None:
                        for effect in script.effects:
                            path = self.run_dir / "layers" / effect.id / f"f{index:06d}.npy"
                            if path.exists():
                                layers.append((effect, load_layer(path)))
                    if inside:
                        done = composite_frame(frame, layers, script.grade, enabled_groups=self.config.composite.enabled_groups())
                        if done.shape[1] != out_w or done.shape[0] != out_h:
                            done = cv2.resize(done, (out_w, out_h), interpolation=cv2.INTER_AREA)
                        encoder.write(done)
                    elif not only_window:
                        # El video anterior se lee en BGR (OpenCV); el codificador espera RGB.
                        encoder.write(cv2.cvtColor(old[1], cv2.COLOR_BGR2RGB))
                    if (index + 1) % 10 == 0:
                        telemetry.checkpoint()  # la persona pudo cancelar el trabajo
                    if (index + 1) % 50 == 0:
                        log.info("Compuestos %d/%d fotogramas", index + 1, meta.frame_count)
        except BaseException:
            encoder.abort()
            raise
        # Cerrar el archivo (ffmpeg termina de escribir y lo renombra) es la etapa de compresión
        # y almacenamiento del diseño: se mide aparte del dibujo de los fotogramas.
        with telemetry.span("finalize"):
            encoder.close()
        return encoder

    def _meta(self) -> VideoMeta:
        header = read_model(self.run_dir / "analysis" / "header.json", AnalysisHeader)
        return header.video

    def _mark(self, stage: str, key: str, **inputs: str) -> None:
        self.manifest.stages[stage] = key
        if inputs:
            self.manifest.inputs[stage] = {name: str(value) for name, value in inputs.items()}
        self.manifest.device = self.device
        save_manifest(self.manifest_path, self.manifest)

