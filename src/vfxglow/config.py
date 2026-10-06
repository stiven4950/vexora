"""Configuración YAML del pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OneEuroConfig(_Strict):
    min_cutoff: float = 1.2
    beta: float = 0.04
    d_cutoff: float = 1.0


class MediaPipeConfig(_Strict):
    pose_variant: Literal["lite", "full"] = "full"
    detection_confidence: float = 0.5
    tracking_confidence: float = 0.5
    num_poses: int = 2


class HQConfig(_Strict):
    yolo_model: str = "yolo11n.pt"
    pose_mode: Literal["lightweight", "balanced", "performance"] = "balanced"
    enable_objects: bool = False
    object_confidence: float = 0.35


class FlowConfig(_Strict):
    enabled: bool = False
    method: Literal["auto", "farneback", "raft"] = "auto"


class MasksConfig(_Strict):
    sam2_model_cfg: str = "configs/sam2.1/sam2.1_hiera_s.yaml"
    sam2_checkpoint: str = "models/sam2.1_hiera_small.pt"


class ObjectsConfig(_Strict):
    enabled: bool = True
    model: str = "yolo11n.pt"
    confidence: float = 0.35
    labels_of_interest: list[str] = Field(default_factory=list)
    stride: int = 2


class EventsConfig(_Strict):
    swing_speed: float = 0.22
    swing_frames: int = 3
    impact_decel: float = 0.14
    contact_hold: int = 6
    contact_radius: float = 0.35
    held_frames: int = 24
    turn_rate_deg: float = 6.0
    jump_rise: float = 0.05
    open_threshold: float = 0.62
    closed_threshold: float = 0.38
    glitch_speed: float = 2.5
    glitch_jump: float = 0.18


class BeatsConfig(_Strict):
    enabled: bool = True
    cut_correlation: float = 0.86
    min_beat: int = 8


class SceneConfig(_Strict):
    enabled: bool = True
    provider: Literal["openai", "gemini"] = "openai"
    model: str = "gpt-5-mini"
    api_key_env: str = "OPENAI_API_KEY"


class AnalysisConfig(_Strict):
    level: Literal["fast", "hq", "masks"] = "fast"
    store_face: bool = True
    # Sin malla facial, recorta la silueta con el Selfie Segmenter y busca el ojo más claro.
    face_fallback: bool = True
    min_confidence: float = 0.35
    max_gap: int = 6
    one_euro: OneEuroConfig = Field(default_factory=OneEuroConfig)
    mediapipe: MediaPipeConfig = Field(default_factory=MediaPipeConfig)
    hq: HQConfig = Field(default_factory=HQConfig)
    flow: FlowConfig = Field(default_factory=FlowConfig)
    masks: MasksConfig = Field(default_factory=MasksConfig)
    objects: ObjectsConfig = Field(default_factory=ObjectsConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    beats: BeatsConfig = Field(default_factory=BeatsConfig)
    scene: SceneConfig = Field(default_factory=SceneConfig)


class DirectorConfig(_Strict):
    provider: Literal["preset", "catalog", "openai", "anthropic"] = "preset"
    preset: str = "avatar_fire"
    # catalog: configs/catalogs/<catalog>.yaml; seed sustituye la del catálogo (otra coreografía).
    catalog: str = "pelea"
    seed: int | None = None
    model: str = "gpt-5"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.4
    base_url: str | None = None
    max_tokens: int = 8000
    style: Literal["artist", "script"] = "artist"
    images: int = 4
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low"


class EngineConfig(_Strict):
    history: int = 18
    max_particles: int = 400
    face_hold: int = 8
    keep_layers: bool = False
    # Por debajo de esta confianza el efecto anclado se atenúa en proporción. 0 lo desactiva.
    min_point_confidence: float = 0.0


class RefinerConfig(_Strict):
    enabled: bool = False
    model_id: str = "runwayml/stable-diffusion-inpainting"
    controlnet_id: str = "lllyasviel/control_v11p_sd15_openpose"
    strength: float = 0.4
    keyframe_stride: int = 8
    steps: int = 12
    guidance_scale: float = 7.5
    dilate_px: int = 10


LAYER_GROUPS: tuple[str, ...] = ("grade", "glow", "particles", "interaction", "lightning")


class CompositeConfig(_Strict):
    codec: Literal["h264", "prores"] = "h264"
    crf: int = 18
    soft_knee: float = 0.85
    groups: dict[str, bool] = Field(default_factory=lambda: {name: True for name in LAYER_GROUPS})

    def enabled_groups(self) -> set[str]:
        return {name for name in LAYER_GROUPS if self.groups.get(name, True)}


class PathsConfig(_Strict):
    models_dir: str = "models"
    runs_dir: str = "runs"


class AppConfig(_Strict):
    version: str = "1.0"
    device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
    paths: PathsConfig = Field(default_factory=PathsConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    director: DirectorConfig = Field(default_factory=DirectorConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    refiner: RefinerConfig = Field(default_factory=RefinerConfig)
    composite: CompositeConfig = Field(default_factory=CompositeConfig)


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AppConfig.model_validate(raw)


def preset_file(config_path: Path, name: str) -> Path:
    return config_path.resolve().parent / "presets" / f"{name}.yaml"


def catalog_file(config_path: Path, name: str) -> Path:
    return config_path.resolve().parent / "catalogs" / f"{name}.yaml"
