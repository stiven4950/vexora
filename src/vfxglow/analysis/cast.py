"""Quién baila: deja en el análisis solo a los protagonistas y saca al público.

El detector de pose ve hasta dos personas. En un video con público (video_35: un bailarín y gente
sentada al fondo mirándolo) la segunda suele ser alguien del público, y además las casillas se
cruzan: el bailarín es a ratos person_0 y a ratos person_1. Los efectos no deben ir al público
(docs/criterio_de_analisis.md, P1: la atención manda).

- Protagonista: una detección con la altura de la más alta del cuadro (PERFORMER_SIZE); el
  público está más lejos o sentado y mide menos de la mitad (video_35: 0,46; la pareja de
  video_34: 0,90).
- Y además al menos VIDEO_SIZE de la altura típica del protagonista en todo el video: si en un
  cuadro el detector no ve al bailarín (cortado por el borde, muy cerca de la cámara), el más alto
  que queda es alguien del público y no debe tomar su lugar (video_35, seg. 25,7-26,3).
- Solista o pareja: si en PAIR_SHARE de los cuadros hay dos protagonistas, es una pareja y cada
  una conserva su casilla; si no, es un solista: en cada cuadro queda uno solo, siempre
  person_0, elegido por tamaño y continuidad (el que se solapa con el del cuadro anterior).
"""

from __future__ import annotations

import logging

from vfxglow.analysis.schema import FrameRecord, PersonPose

log = logging.getLogger(__name__)

PERFORMER_SIZE = 0.6
VIDEO_SIZE = 0.55
PAIR_SHARE = 0.5
# En el solista, cuánto puede ganar en tamaño otra detección antes de dejar de seguir al anterior.
SWITCH_SIZE = 1.35


def _height(person: PersonPose) -> float:
    box = person.box
    return (box[3] - box[1]) if box else 0.0


def _iou(a, b) -> float:
    if a is None or b is None:
        return 0.0
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def performers(record: FrameRecord, typical: float = 0.0) -> list[PersonPose]:
    people = [p for p in record.people if p.box is not None]
    if not people:
        return []
    tallest = max(_height(p) for p in people)
    return [p for p in people if _height(p) >= PERFORMER_SIZE * tallest and _height(p) >= VIDEO_SIZE * typical]


def _set_main(record: FrameRecord, person: PersonPose | None) -> None:
    """Los campos planos del registro son los de person_0."""
    record.person_id = "person_0"
    record.pose = person.pose if person else []
    record.left_hand = person.left_hand if person else None
    record.right_hand = person.right_hand if person else None
    record.face = person.face if person else None
    record.box = person.box if person else None


def keep_performers(frames: list[FrameRecord]) -> str:
    """Filtra `frames` en su lugar. Devuelve "solo" o "pareja"."""
    tallest = sorted(max((_height(p) for p in record.people if p.box is not None), default=0.0) for record in frames)
    tallest = [h for h in tallest if h > 0]
    typical = tallest[len(tallest) // 2] if tallest else 0.0
    found = [performers(record, typical) for record in frames]
    seen = sum(1 for group in found if group)
    pair = seen > 0 and sum(1 for group in found if len(group) >= 2) >= PAIR_SHARE * seen
    dropped = 0
    previous = None
    for record, group in zip(frames, found, strict=True):
        dropped += len(record.people) - (len(group) if pair else min(len(group), 1))
        if pair:
            record.people = sorted(group, key=lambda p: p.person_id)
            main = next((p for p in record.people if p.person_id == "person_0"), None)
            if main is not None:
                _set_main(record, main)
            continue
        if not group:
            record.people = []
            _set_main(record, None)
            continue
        biggest = max(group, key=_height)
        follow = max(group, key=lambda p: _iou(p.box, previous)) if previous is not None else None
        lead = follow if follow is not None and _iou(follow.box, previous) > 0.2 and _height(biggest) <= SWITCH_SIZE * _height(follow) else biggest
        lead = lead.model_copy(update={"person_id": "person_0"})
        record.people = [lead]
        _set_main(record, lead)
        previous = lead.box
    kind = "pareja" if pair else "solo"
    log.info("Protagonistas: %s; %d detecciones del público descartadas", kind, dropped)
    return kind
