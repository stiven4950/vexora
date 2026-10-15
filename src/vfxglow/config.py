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
    beta: float = 1.0
    d_cutoff: float = 1.0


class MediaPipeConfig(_Strict):
    pose_variant: Literal["lite", "full"] = "full"
    detection_confidence: float = 0.5
    tracking_confidence: float = 0.5
    num_poses: int = 2
    # Con num_poses=2, si solo aparece una persona se tapa su caja y se busca otra con este
    # umbral. MediaPipe Pose suele perder a la segunda persona aunque esté a la vista.
    second_pass_confidence: float = 0.3


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


class BladesConfig(_Strict):
    # off: nunca; auto: solo si el video tiene líneas en las manos en `min_presence` de los
    # casos; always: siempre. Por defecto off: en una pelea sin armas los bordes de brazos y
    # ropa dan "líneas" en el 78% de las manos (igual que con espadas), así que auto no
    # distingue. Un catálogo que necesita hojas las activa (`needs: [blades]`).
    mode: Literal["off", "auto", "always"] = "off"
    min_presence: float = 0.25
    fill_gap: int = 8
    smooth: float = 0.5
    # lines: solo visión clásica; yoloworld: además YOLO-World por texto (extra `objects`).
    # model: detector entrenado con vfxglow-train (model_path); las líneas quedan de respaldo.
    detector: Literal["lines", "yoloworld", "model"] = "lines"
    model_path: str = "models/blade-obb.pt"
    model_confidence: float = 0.25
    # El modelo grande con estas palabras es lo mejor medido en video_39 (ver docs/pendientes.md).
    yolo_model: str = "models/yolov8x-worldv2.pt"
    yolo_classes: list[str] = Field(default_factory=lambda: ["sword", "blade", "metal rod", "long thin metal pole"])
    yolo_confidence: float = 0.05


class PropsConfig(_Strict):
    # Objeto protagonista descrito en inglés, terminado en punto ("a baseball cap."). Vacío =
    # apagado. Un catálogo con `needs: [props]` pone su `prop` si aquí no hay nada.
    query: str = ""
    detector_model: str = "IDEA-Research/grounding-dino-base"
    threshold: float = 0.3
    # Confianza mínima para sembrar SAM 2 (la gorra real da 0,48-0,75; el pelo, hasta 0,48,
    # pero ese lo descarta el filtro de color).
    seed_threshold: float = 0.4
    sam_model: str = "facebook/sam2.1-hiera-tiny"
    # Sin objeto, Grounding DINO lo busca cada `search_every` fotogramas; con objeto, comprueba
    # cada `check_every` que SAM 2 no se haya ido a otra cosa (y lo re-siembra si es así).
    search_every: int = 5
    check_every: int = 30
    # Puntos máximos del contorno guardado por fotograma.
    contour_points: int = 80


class AccessoriesConfig(_Strict):
    # Clasifica qué lleva cada persona en la cabeza (gafas, máscara, gorra...) con el VLM de
    # analysis.scene. Sin clave de API solo cuenta `manual`.
    enabled: bool = True
    crops: int = 6
    # Declaración a mano, gana sobre el VLM: {"person_1": ["sunglasses"]}.
    manual: dict[str, list[str]] = Field(default_factory=dict)


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
    accessories: AccessoriesConfig = Field(default_factory=AccessoriesConfig)
    blades: BladesConfig = Field(default_factory=BladesConfig)
    props: PropsConfig = Field(default_factory=PropsConfig)
    # Herramienta que pinta (paint_reveal): "model" = Grounding DINO + SAM 2 (preciso, ~0,5 s por
    # fotograma con cara); "motion" = lo que se mueve sobre la cara (rápido, sin modelos). En
    # video_2 los dos dan un resultado visible casi igual: por defecto, motion.
    paint_tool: Literal["model", "motion"] = "motion"
    # Contorno del cuerpo por fotograma con el Selfie Segmenter (siluetas de neón).
    body_contour: bool = True


class DeepConfig(_Strict):
    """Análisis profundo (director/deep.py): un modelo ve el video completo con audio, como un
    animador, y escribe la coreografía. Es opcional y cuesta más: por defecto, apagado."""

    enabled: bool = False
    model: str = "gemini-4-argon"
    api_key_env: str = "GEMINI_API_KEY"
    # Fotogramas por segundo que mira el modelo (Gemini usa 1 si no se dice: se pierde los gestos).
    fps: float = 5.0
    timeout_s: float = 600.0
    # Reintentos si el modelo está saturado (503) o se pasa la cuota por minuto (429).
    retries: int = 4


class DirectorConfig(_Strict):
    provider: Literal["preset", "catalog", "openai", "anthropic"] = "preset"
    preset: str = "avatar_fire"
    # catalog: configs/catalogs/<catalog>.yaml. Sin seed se prueban varias coreografías y se usa
    # la del puesto `take` en el ranking (0 = la mejor; 1, 2... = "otra versión"). Con seed, esa
    # coreografía exacta.
    catalog: str = "pelea"
    seed: int | None = None
    take: int = 0
    # Temporada (configs/seasons.yaml) que se aplica encima del estilo: paleta y decoración.
    season: str | None = None
    # Guion de prueba (director/pins.py): momentos fijados a mano que mandan sobre el sorteo.
    pins: str | None = None
    # Vestuario por persona (chaqueta, vestido, ambos, ninguno), que elige el usuario:
    # {"person_0": "vestido", "*": "chaqueta"}. Ver director/choreography.py: wardrobe_allows.
    wardrobe: dict[str, str] = Field(default_factory=dict)
    model: str = "gpt-5"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.4
    base_url: str | None = None
    max_tokens: int = 8000
    style: Literal["artist", "script"] = "artist"
    images: int = 4
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low"
    deep: DeepConfig = Field(default_factory=DeepConfig)


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


# Nombres anteriores de catálogos: siguen funcionando (comandos, guiones de prueba, trabajos viejos).
CATALOG_ALIASES = {"baile_neon": "baile", "baile_duo": "baile"}


def catalog_name(name: str) -> str:
    return CATALOG_ALIASES.get(name, name)


def catalog_file(config_path: Path, name: str) -> Path:
    return config_path.resolve().parent / "catalogs" / f"{catalog_name(name)}.yaml"
