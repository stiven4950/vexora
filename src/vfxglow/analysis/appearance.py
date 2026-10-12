"""Señales de apariencia del plano: pigmento activo, punta, rasgos y brillo ya presente.

No segmenta con un modelo generativo. Compara el fotograma con un fondo lento
y se queda con la mancha que toca la mano. La silueta se calcula al render,
desde la pose, para no guardar máscaras.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import Beat, FrameRecord, VideoMeta

log = logging.getLogger("vfxglow.appearance")

_SMALL = (180, 320)
# Un parpadeo o un fotograma sin ojos no corta el veto; un destello suelto no lo enciende.
BRIGHT_GAP = 8
BRIGHT_MIN = 3


@dataclass
class Appearance:
    contours: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    tips: dict[int, tuple[float, float]] = field(default_factory=dict)
    bright: list[str] = field(default_factory=list)
    bright_spans: list[tuple[int, int, str]] = field(default_factory=list)
    # Pintura nueva por fotograma (analysis/paint.py) y acentos de la obra terminada.
    paint: dict[int, dict] = field(default_factory=dict)
    accents: dict[int, dict] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "contours": [{"frame": frame, "points": points} for frame, points in sorted(self.contours.items())],
            "tips": [{"frame": frame, "point": point} for frame, point in sorted(self.tips.items())],
            "bright": self.bright,
            "bright_spans": [{"start": a, "end": b, "region": region} for a, b, region in self.bright_spans],
            "paint": [{"frame": frame, **data} for frame, data in sorted(self.paint.items())],
            "accents": [{"frame": frame, **data} for frame, data in sorted(self.accents.items())],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Appearance:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            contours={int(item["frame"]): [tuple(p) for p in item["points"]] for item in raw.get("contours", [])},
            tips={int(item["frame"]): tuple(item["point"]) for item in raw.get("tips", [])},
            bright=list(raw.get("bright", [])),
            bright_spans=[(int(item["start"]), int(item["end"]), str(item["region"])) for item in raw.get("bright_spans", [])],
            paint={int(item["frame"]): {"strokes": item["strokes"], "tip": item["tip"], "trail": item.get("trail", [])} for item in raw.get("paint", [])},
            accents={int(item["frame"]): {"head": item["head"], "lines": item["lines"], "eyes": item.get("eyes"), "sockets": item.get("sockets"), "nose": item.get("nose"), "figures": item.get("figures", {})} for item in raw.get("accents", [])},
        )


def analyze_appearance(video_path: Path, frames: list[FrameRecord], meta: VideoMeta, cuts: list[int] | None = None, tool: str = "model") -> Appearance:
    """Ojos que ya brillan, pintura nueva sobre la cara y, tras la pintura, los acentos de la obra.

    La pintura sale de analysis/paint.py (en coordenadas de la cara, sin contar la mano ni el
    pincel); `contours` y `tips` (los usan tool_touch y el retag de beats) salen de ahí."""
    cap = cv2.VideoCapture(str(video_path))
    out = Appearance()
    bright_eyes = 0
    eye_samples = 0
    for record in frames:
        ok, frame = cap.read()
        if not ok:
            break
        if _eyes_bright(frame, record):
            bright_eyes += 1
            out.bright_spans.append((record.frame, record.frame, "eyes"))
        if record.pose:
            eye_samples += 1
    cap.release()
    from vfxglow.analysis.paint import detect_accents, detect_paint

    # Primero sin modelos (segundos): solo si el video tiene pintura vale cargar el detector.
    out.paint = detect_paint(video_path, frames, meta.fps, cuts, "motion")
    if out.paint and tool == "model":
        out.paint = detect_paint(video_path, frames, meta.fps, cuts, "model") or out.paint
    for frame, data in out.paint.items():
        if data["strokes"]:
            biggest = max(data["strokes"], key=len)
            out.contours[frame] = [(x, y) for x, y, _ in biggest]
        if data["tip"] is not None:
            out.tips[frame] = tuple(data["tip"])
    if out.paint:
        out.accents = detect_accents(video_path, frames, max(out.paint) + 1)
    out.bright_spans = [
        span for span in _merge_spans(out.bright_spans, BRIGHT_GAP) if span[1] - span[0] + 1 >= BRIGHT_MIN
    ]
    if eye_samples and bright_eyes / max(eye_samples, 1) > 0.35:
        out.bright.append("eyes")
    log.info("Pigmento en %d fotogramas; rasgos brillantes: %s", len(out.contours), out.bright or "ninguno")
    return out


def retag_paint_beats(beats: list[Beat], appearance: Appearance) -> list[Beat]:
    """Un beat con mucha mancha es pintura ancha; con poca, detalle."""
    updated: list[Beat] = []
    for beat in beats:
        if beat.kind == "cut":
            updated.append(beat)
            continue
        count = sum(1 for frame in range(beat.start_frame, beat.end_frame + 1) if frame in appearance.contours)
        span = max(beat.end_frame - beat.start_frame + 1, 1)
        fraction = count / span
        if fraction > 0.45:
            kind = "paint_broad"
        elif fraction > 0.12:
            kind = "paint_detail"
        else:
            kind = beat.kind
        updated.append(beat.model_copy(update={"kind": kind}))
    return updated


def _eyes_bright(frame: np.ndarray, record: FrameRecord) -> bool:
    """Ojos casi blancos en un plano claro. En un reveal oscuro no se vetan."""
    if float(frame.mean()) < 70:
        return False
    height, width = frame.shape[:2]
    samples = []
    # El centro del iris de la malla cae sobre el lente; el ojo de la pose es más grueso y a veces lo pierde.
    iris = {lm.name: (lm.x, lm.y) for lm in record.face or [] if lm.name in {"face_468", "face_473"}}
    for name, mesh in (("left_eye", "face_473"), ("right_eye", "face_468")):
        point = iris.get(mesh) or next(((lm.x, lm.y) for lm in record.pose if lm.name == name and lm.c > 0.2), None)
        if point is None:
            continue
        x = int(np.clip(point[0] * width, 0, width - 1))
        y = int(np.clip(point[1] * height, 0, height - 1))
        patch = frame[max(0, y - 3) : y + 4, max(0, x - 3) : x + 4]
        if patch.size:
            samples.append(float(patch.max()))
    return bool(samples) and float(np.mean(samples)) > 220.0


def _merge_spans(spans: list[tuple[int, int, str]], gap: int = 2) -> list[tuple[int, int, str]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for start, end, region in ordered[1:]:
        prev_s, prev_e, prev_r = merged[-1]
        if region == prev_r and start <= prev_e + gap:
            merged[-1] = (prev_s, max(prev_e, end), region)
        else:
            merged.append((start, end, region))
    return merged


def tip_touch_events(appearance: Appearance):
    """La punta estimada, sostenida varios fotogramas, es un toque de herramienta."""
    from vfxglow.analysis.schema import MotionEvent

    frames = sorted(appearance.tips)
    if not frames:
        return []
    groups: list[list[int]] = [[frames[0]]]
    for frame in frames[1:]:
        if frame <= groups[-1][-1] + 2:
            groups[-1].append(frame)
        else:
            groups.append([frame])
    events = []
    for group in groups:
        if len(group) < 4:
            continue
        point = appearance.tips[group[len(group) // 2]]
        events.append(
            MotionEvent(
                name="tool_touch",
                target="tool_tip",
                start_frame=group[0],
                end_frame=group[-1],
                confidence=0.8,
                detail="La punta de la herramienta deja pigmento nuevo.",
                position=point,
            )
        )
    return events

