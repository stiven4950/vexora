"""Convierte triggers del guion y eventos detectados en una envolvente por fotograma."""

from __future__ import annotations

from dataclasses import dataclass

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectTrigger


@dataclass
class ActivationWindow:
    start: int
    end: int
    fade_in: int
    fade_out: int
    event: MotionEvent


def _matches(event: MotionEvent, trigger: EffectTrigger) -> bool:
    if event.name != trigger.event:
        return False
    if trigger.joint and event.target != trigger.joint:
        return False
    if (event.end_frame - event.start_frame + 1) < trigger.min_duration:
        return False
    if event.peak_speed < trigger.min_speed:
        return False
    if trigger.attacker and event.attacker != trigger.attacker:
        return False
    if trigger.frames:
        if trigger.targets:
            if (event.start_frame, event.target) not in set(zip(trigger.frames, trigger.targets, strict=False)):
                return False
        elif event.start_frame not in trigger.frames:
            return False
    return True


class ActivationTimeline:
    """Una ventana por activación, con hold, cooldown y fundidos propios del trigger."""

    def __init__(self, effect: Effect, events: list[MotionEvent]) -> None:
        self.windows: list[ActivationWindow] = []
        if not effect.triggers:
            return
        for trigger in effect.triggers:
            last_end = -10_000
            count = 0
            for event in events:
                if not _matches(event, trigger):
                    continue
                if event.start_frame < last_end + trigger.cooldown:
                    continue
                if trigger.max_activations > 0 and count >= trigger.max_activations:
                    break
                end = event.end_frame + trigger.hold
                self.windows.append(
                    ActivationWindow(
                        start=event.start_frame,
                        end=end,
                        fade_in=trigger.fade_in,
                        fade_out=trigger.fade_out,
                        event=event,
                    )
                )
                last_end = end
                count += 1

    def at(self, frame: int) -> tuple[float, MotionEvent | None]:
        best = 0.0
        chosen: MotionEvent | None = None
        for window in self.windows:
            if frame < window.start or frame > window.end:
                continue
            gain = 1.0
            if window.fade_in > 0 and frame < window.start + window.fade_in:
                gain *= (frame - window.start) / max(window.fade_in, 1)
            if window.fade_out > 0 and frame > window.end - window.fade_out:
                gain *= (window.end - frame) / max(window.fade_out, 1)
            gain = max(0.0, min(1.0, gain))
            if gain >= best:
                best = gain
                chosen = window.event
        return best, chosen
