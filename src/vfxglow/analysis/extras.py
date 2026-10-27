"""Hojas y objeto protagonista (los `needs` de los catálogos) solo en un tramo del video.

El análisis de la subida no los calcula y rehacerlo entero con ellos tarda minutos. La vista previa
del Estudio de Baile y Espadas los calcula aquí, en memoria, sobre las pistas ya guardadas y solo en
los fotogramas que va a dibujar; el trabajo real hace su análisis completo como siempre.
"""

from __future__ import annotations

from pathlib import Path

from vfxglow.analysis.schema import FrameRecord, MotionEvent, VideoMeta
from vfxglow.config import AppConfig

BLADE_EVENTS = ("blade_swing", "blade_ground")
# El objeto se sigue en uno de cada dos fotogramas: Grounding DINO + SAM 2 cuestan ~0,6 s por
# fotograma y a 30 fps repetir el contorno uno no se nota.
PROP_STRIDE = 2


def window_extras(video: Path, frames: list[FrameRecord], meta: VideoMeta, config: AppConfig) -> list[MotionEvent]:
    """Rellena `blades` y `prop` en `frames` (fotogramas seguidos, ya copiados: se modifican) según
    la config de análisis y devuelve los eventos que salen de ellos, con su fotograma real."""
    if not frames:
        return []
    start, end = frames[0].frame, frames[-1].frame
    analysis = config.analysis
    events: list[MotionEvent] = []
    if analysis.blades.mode != "off":
        from vfxglow.analysis.blades import BladeFinder, finalize_blades
        from vfxglow.analysis.events import EventDetector
        from vfxglow.io.video import VideoReader

        finder = BladeFinder(analysis.blades)
        by_frame = {record.frame: record for record in frames}
        with VideoReader(video) as reader:
            for index, image in reader.frames(start, end):
                if index in by_frame:
                    by_frame[index].blades = finder.detect(by_frame[index], image)
        finalize_blades(frames, analysis.blades, meta.width, meta.height)
        # El detector numera por posición en la lista: se devuelve al fotograma real.
        found = EventDetector(analysis.events).detect(frames, meta)
        events += [e.model_copy(update={"start_frame": e.start_frame + start, "end_frame": e.end_frame + start}) for e in found if e.name in BLADE_EVENTS]
    if analysis.props.query:
        from vfxglow.analysis.props import PropTracker, assign_states, prop_events

        PropTracker(analysis.props).track(video, frames, window=(start, end), stride=PROP_STRIDE)
        assign_states(frames, meta.width, meta.height)
        events += prop_events(frames, meta.fps, meta.width, meta.height)
    return events
