"""Orquesta las etapas y evita repetir trabajo si la caché sigue vigente."""

from __future__ import annotations

import logging
from pathlib import Path

from vfxglow.analysis.analyzer import analyze_video
from vfxglow.analysis.schema import AnalysisHeader, VideoMeta
from vfxglow.config import LAYER_GROUPS, load_config, preset_file
from vfxglow.device import require_cuda, resolve_device
from vfxglow.director.director import CreativeDirector
from vfxglow.director.schema import EffectScript, effect_group
from vfxglow.engine.engine import EffectEngine, load_events, load_layer, load_tracks, save_layer
from pydantic import BaseModel

from vfxglow.io.store import Manifest, load_manifest, read_model, save_manifest, sha256_file, stage_key, write_model
from vfxglow.io.video import VideoReader

log = logging.getLogger("vfxglow")


class _LayerIndex(BaseModel):
    version: str = "1.0"
    effects: dict[str, str]


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
    ) -> None:
        self.config_path = config_path
        self.config = load_config(config_path)
        if director:
            self.config.director.provider = director  # type: ignore[assignment]
        if preset:
            self.config.director.provider = "preset"
            self.config.director.preset = preset
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

    def _guard_optional_stages(self) -> None:
        if self.config.refiner.enabled:
            require_cuda("El refinador difusor", self.device)
        if self.config.analysis.level == "masks":
            require_cuda("Las máscaras SAM 2.1", self.device)

    def run(self) -> Path:
        self.analyze()
        self.direct()
        if self.config.refiner.enabled or self.config.engine.keep_layers:
            self.render()
            self.refine()
            return self.compose()
        return self.compose(stream=True)

    def analyze(self) -> None:
        key = stage_key("analyze-1", self.manifest.video_sha256, self.config.analysis.model_dump_json())
        tracks = self.run_dir / "analysis" / "tracks.jsonl"
        if not self.force and self.manifest.stages.get("analyze") == key and tracks.exists():
            log.info("Análisis en caché")
            return
        log.info("Analizando %s en %s", self.video.name, self.device)
        analyze_video(self.video, self.run_dir, self.config, self.device)
        self._mark("analyze", key)

    def direct(self) -> None:
        brief_path = self.run_dir / "analysis" / "motion_brief.json"
        preset_path = preset_file(self.config_path, self.config.director.preset)
        preset_hash = sha256_file(preset_path) if self.config.director.provider == "preset" and preset_path.exists() else ""
        key = stage_key(
            "direct-1",
            sha256_file(brief_path),
            self.config.director.model_dump_json(),
            preset_hash,
        )
        dest = self.run_dir / "scripts" / "effect_script.json"
        if not self.force and self.manifest.stages.get("direct") == key and dest.exists():
            log.info("Guion en caché")
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
        log.info("Guion %s con %d efectos", script.theme, len(script.effects))
        self._mark("direct", key)

    def _render_key(self) -> str:
        analysis = self.run_dir / "analysis"
        optional = [analysis / "events.jsonl", analysis / "appearance.json", analysis / "motion_brief.json"]
        return stage_key(
            "render-4",
            sha256_file(self.run_dir / "scripts" / "effect_script.json"),
            sha256_file(analysis / "tracks.jsonl"),
            *[sha256_file(path) if path.exists() else "" for path in optional],
            self.config.engine.model_dump_json(),
        )

    def _engine(self, script: EffectScript) -> tuple[EffectEngine, dict]:
        from vfxglow.analysis.beats import cut_frames
        from vfxglow.analysis.schema import MotionBrief

        analysis = self.run_dir / "analysis"
        meta = self._meta()
        brief_path = analysis / "motion_brief.json"
        cuts = cut_frames(read_model(brief_path, MotionBrief).beats) if brief_path.exists() else []
        tracks = {track.frame: track for track in load_tracks(analysis / "tracks.jsonl")}
        engine = EffectEngine(script, self.config.engine, load_events(analysis / "events.jsonl"), cuts=cuts, fps=meta.fps)
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
        from vfxglow.composite.composite import composite_frame
        from vfxglow.composite.encode import FrameEncoder

        meta = self._meta()
        script = read_model(self.run_dir / "scripts" / "effect_script.json", EffectScript)
        dest = self.run_dir / "output" / "final.mp4"
        index_path = self.run_dir / "layers" / "index.json"
        if stream is None:
            stream = not (index_path.exists() and self.manifest.stages.get("render") == self._render_key())
        key = stage_key(
            "compose-2",
            self._render_key() if stream else self.manifest.stages.get("render", ""),
            self.config.composite.model_dump_json(),
            self.config.refiner.model_dump_json(),
        )
        if not self.force and self.manifest.stages.get("compose") == key and dest.exists():
            log.info("Video final en caché: %s", dest)
            return dest
        engine = tracks = None
        if stream:
            engine, tracks = self._engine(script)
            log.info("Renderizando y componiendo %d fotogramas sin capas en disco", meta.frame_count)
        by_id = {effect.id: effect for effect in script.effects}
        encoder = FrameEncoder(
            dest,
            meta.width,
            meta.height,
            meta.fps,
            codec=self.config.composite.codec,
            crf=self.config.composite.crf,
            audio_from=self.video if meta.has_audio else None,
        )
        log.info("Componiendo sobre el plano original")
        try:
            with VideoReader(self.video) as reader:
                for index, frame in reader:
                    layers = []
                    if engine is not None:
                        rendered = engine.render_frame(tracks.get(index), index, meta.width, meta.height, meta.frame_count, self.run_dir)
                        layers = [(by_id[effect_id], layer) for effect_id, _group, layer in rendered]
                    else:
                        for effect in script.effects:
                            path = self.run_dir / "layers" / effect.id / f"f{index:06d}.npy"
                            if path.exists():
                                layers.append((effect, load_layer(path)))
                    encoder.write(
                        composite_frame(
                            frame,
                            layers,
                            script.grade,
                            enabled_groups=self.config.composite.enabled_groups(),
                        )
                    )
        finally:
            encoder.close()
        self._mark("compose", key)
        log.info("Video final: %s", dest)
        return dest

    def _meta(self) -> VideoMeta:
        header = read_model(self.run_dir / "analysis" / "header.json", AnalysisHeader)
        return header.video

    def _mark(self, stage: str, key: str) -> None:
        self.manifest.stages[stage] = key
        self.manifest.device = self.device
        save_manifest(self.manifest_path, self.manifest)
