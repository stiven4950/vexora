"""Contratos del análisis: fotograma, cabecera y brief de movimiento."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Landmark(_Strict):
    name: str
    x: float
    y: float
    z: float = 0.0
    c: float = 0.0


class HandFrame(_Strict):
    landmarks: list[Landmark] = Field(default_factory=list)
    score: float = 0.0


class ObjectDet(_Strict):
    label: str
    conf: float
    box: tuple[float, float, float, float]
    id: int = -1
    velocity: tuple[float, float] = (0.0, 0.0)

    @property
    def center(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) * 0.5, (self.box[1] + self.box[3]) * 0.5)


class FlowStats(_Strict):
    mean_dx: float
    mean_dy: float
    magnitude: float


class JointMotion(_Strict):
    name: str
    speed: float
    direction_deg: float
    vx: float
    vy: float
    accel: float = 0.0
    glitch: bool = False


class HandState(_Strict):
    openness: float = 0.5
    valid: bool = False


class PersonPose(_Strict):
    """Una persona dentro del fotograma. person_0 se copia también a los campos planos."""

    person_id: str
    pose: list[Landmark] = Field(default_factory=list)
    left_hand: HandFrame | None = None
    right_hand: HandFrame | None = None
    face: list[Landmark] | None = None
    box: tuple[float, float, float, float] | None = None
    motion: list[JointMotion] = Field(default_factory=list)


class FrameRecord(_Strict):
    frame: int
    time_s: float
    person_id: str = "person_0"
    pose: list[Landmark] = Field(default_factory=list)
    left_hand: HandFrame | None = None
    right_hand: HandFrame | None = None
    face: list[Landmark] | None = None
    box: tuple[float, float, float, float] | None = None
    mask_path: str | None = None
    objects: list[ObjectDet] = Field(default_factory=list)
    flow: FlowStats | None = None
    motion: list[JointMotion] = Field(default_factory=list)
    hand_state: dict[str, HandState] = Field(default_factory=dict)
    torso_yaw_rate: float = 0.0
    people: list[PersonPose] = Field(default_factory=list)


class VideoMeta(_Strict):
    path: str
    fps: float
    width: int
    height: int
    frame_count: int
    duration_s: float
    has_audio: bool = False


class AnalysisHeader(_Strict):
    version: str = "1.0"
    video: VideoMeta
    device: str
    level: str
    models: dict[str, str]
    store_face: bool


class LimbStats(_Strict):
    name: str
    mean_speed: float
    peak_speed: float
    peak_frame: int
    mean_direction_deg: float
    path_length: float
    path: list[tuple[float, float]] = Field(default_factory=list)


class MotionEvent(_Strict):
    name: str
    target: str
    start_frame: int
    end_frame: int
    confidence: float
    detail: str = ""
    position: tuple[float, float] | None = None
    peak_speed: float = 0.0
    direction_deg: float = 0.0
    object_id: int | None = None
    object_label: str | None = None
    attacker: str | None = None
    receiver: str | None = None


class Beat(_Strict):
    """Tramo del clip. Un efecto no debe cruzar un beat cuyo kind sea 'cut'."""

    id: int
    start_frame: int
    end_frame: int
    kind: str = "gesture"
    onsets: list[int] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    gesture: str = ""


class SceneBeat(_Strict):
    """Lectura del VLM para un beat. Vacío si no hay clave de API."""

    beat_id: int
    scene: str = ""
    gesture: str = ""
    intent: str = ""
    objects: list[str] = Field(default_factory=list)


class MotionBrief(_Strict):
    version: str = "1.0"
    video: VideoMeta
    person_id: str
    anchors: list[str]
    limbs: list[LimbStats]
    events: list[MotionEvent]
    objects: list[str] = Field(default_factory=list)
    summary: str
    beats: list[Beat] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    scene: list[SceneBeat] = Field(default_factory=list)
    audio_onsets: list[int] = Field(default_factory=list)
