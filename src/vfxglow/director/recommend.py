"""Recomendación de estilo sin IA, con lo que el análisis ya sabe del video.

Señales usadas (nombres reales de MotionBrief / analysis/events.py):
- personas: `brief.people`, más las que aparecen en `events` (target "person_1:...", attacker,
  receiver) y en `duet` (leader, partner).
- contacto entre personas: eventos `person_contact`, `fist_clash`, `body_bump`.
- dúo: `brief.duet` (tramos unison/solo) con 2+ personas. Si cubre al menos la mitad del video
  es baile en pareja, aunque haya contacto.
- hojas: eventos `blade_swing`, u objetos (`brief.objects`) con nombre de cuchillo/espada/bate.
  El análisis por defecto no detecta hojas (analysis.blades.mode = off): sin ellas no se
  recomienda espadas.
- energía de una persona: `flip`, `tumble`, `jump`, `fast_swing`, `spin_body`.
"""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from vfxglow.analysis.schema import MotionBrief

MAX_RECOMMENDATIONS = 3
CONTACT = {"person_contact", "fist_clash", "body_bump"}
BLADE_WORDS = ("knife", "sword", "bat", "cuchillo", "espada", "bate")
ENERGY = {"fast_swing", "spin_body"}
DUET_SHARE = 0.5


class Recommendation(BaseModel):
    style: str
    reason: str


def _people(brief: MotionBrief) -> set[str]:
    found = {p for p in brief.people if p}
    for event in brief.events:
        for ref in (event.target, event.attacker, event.receiver):
            if ref and ref.startswith("person_"):
                found.add(ref.split(":")[0])
    for span in brief.duet:
        found.update((span.leader, span.partner))
    return found


def _duet_share(brief: MotionBrief) -> float:
    """Fracción del video en que la pareja se mueve como dúo (al unísono o por turnos)."""
    frames = sum(span.end_frame - span.start_frame for span in brief.duet)
    return frames / brief.video.frame_count if brief.video.frame_count else 0.0


def _times(count: int) -> str:
    return "una vez" if count == 1 else f"{count} veces"


def recommend(brief: MotionBrief, available: list[str]) -> list[Recommendation]:
    """Estilos ordenados del más al menos indicado (máximo 3), solo de `available`."""
    counts = Counter(event.name for event in brief.events)
    people = _people(brief)
    contacts = sum(counts[name] for name in CONTACT)
    blades = counts["blade_swing"] + sum(any(w in label.lower() for w in BLADE_WORDS) for label in brief.objects)
    flips = counts["flip"] + counts["tumble"]
    energy = sum(counts[name] for name in ENERGY)

    # Las parejas que bailan también se tocan: lo que separa baile de pelea es cuánto del video
    # se mueven como dúo (≈ 98 % en los bailes medidos, 0 % en las peleas).
    dancing = _duet_share(brief) >= DUET_SHARE
    fight = Recommendation(style="pelea", reason=f"Hay {len(people)} personas que se tocan ({_times(contacts)}): ideal para combate.")
    picks: list[Recommendation] = []
    if len(people) >= 2 and dancing:
        picks.append(Recommendation(style="baile", reason="Dos personas bailan en pareja casi todo el video: ideal para baile neón."))
        if contacts:
            picks.append(fight)
    elif len(people) >= 2 and contacts:
        picks.append(fight)
    elif len(people) >= 2:
        picks.append(Recommendation(style="baile", reason="Hay dos personas moviéndose juntas sin golpes: ideal para baile en pareja."))
    if blades:
        picks.append(Recommendation(style="espadas_fuego", reason="Se ven hojas o espadas en las manos: ideal para espadas de fuego."))
    if len(people) < 2:
        if flips:
            picks.append(Recommendation(style="fuego", reason=f"Hay {'una voltereta' if flips == 1 else f'{flips} volteretas'}: el fuego deja una estela espectacular."))
        if flips or counts["jump"] >= 2 or energy >= 4:
            picks.append(Recommendation(style="rayo", reason="Mucho movimiento y energía: el rayo sigue cada golpe y salto."))
    picks.append(Recommendation(style="avatar", reason="Estilo versátil que funciona con casi cualquier movimiento."))

    out: list[Recommendation] = []
    for pick in picks:
        if pick.style in available and all(pick.style != done.style for done in out):
            out.append(pick)
    return out[:MAX_RECOMMENDATIONS]
