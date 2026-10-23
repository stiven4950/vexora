"""Guion de prueba: momentos fijados a mano que mandan sobre el sorteo del coreógrafo.

Sirve para comprobar un efecto: se le dice "en el segundo 3 pon la bola de espejos" y el video
sale exactamente con eso (`vfxglow run ... --pin pruebas/x.yaml`). Formato:

    catalogo: baile                # opcional; si está, debe coincidir con --catalog
    solo_estos: true               # true: solo lo fijado (sin sorteo ni efectos `always`)
    momentos:
      - {seg: 3.0, opcion: bola_espejos}
      - {seg: 10.2, opcion: saco, persona: person_1}
      - {seg: 24.0, opcion: rodillas, espejo: true}
      - {seg: 11.2, accion: hand_ear, opcion: corona}

Cada momento se engancha al evento detectado de su acción más cercano (a menos de
PIN_WINDOW_S, de esa persona y de una parte admitida por la opción). Si no hay ninguno, se crea
uno en ese instante, así un efecto se puede probar aunque el análisis no haya visto el gesto. Lo
que no se puede cumplir (una opción que no existe, una persona que no está) es un error, nunca se
salta en silencio.
"""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from vfxglow.analysis.schema import MotionBrief, MotionEvent

# Distancia máxima al evento detectado que se toma como "ese momento".
PIN_WINDOW_S = 0.5
# Articulación del evento creado para acciones que la necesitan (el efecto la usa como origen).
SYNTH_JOINT = {
    "stomp": "right_ankle",
    "step": "right_ankle",
    "foot_strike": "right_ankle",
    "fast_swing": "right_wrist",
    "throw": "right_wrist",
    "raise_hand": "right_wrist",
}
# Gestos de una mano o un pie: el evento creado dice cuál (el efecto lo necesita).
SIDED = ("point", "hand_ear", "throw", "face_touch", "neck_slash", "stomp", "step", "cover_eyes")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Alternativa(_Strict):
    """Otra opción de la misma acción que cuenta la misma intención; `encaje` pesa en el sorteo."""

    opcion: str
    figura: str | None = None
    encaje: float = 0.5


class Pin(_Strict):
    seg: float
    opcion: str
    # La acción del catálogo; hace falta si la opción está en varias.
    accion: str | None = None
    persona: str | None = None
    # true: también en la pareja; false: nunca; sin valor: la regla del catálogo (duet).
    espejo: bool | None = None
    # Duración del evento creado cuando no hay uno detectado (s).
    dur: float = 0.6
    # true: el momento se crea justo en `seg` y dura `dur`, aunque haya un evento detectado cerca
    # (para calcar los tiempos de una referencia).
    exacto: bool = False
    # Mano o pie del momento creado ("left"/"right", lados de la persona): qué mano sostiene el
    # corazón, qué pierna lleva la línea.
    lado: str | None = None
    # Figura exacta de un adorno que sortea entre varias (horns dentro de "ocurrencia").
    figura: str | None = None
    # Color del momento ("#ff3366"): manda sobre los capítulos de color del solista desde aquí
    # hasta el siguiente momento con color (los actos de color del análisis profundo).
    color: str | None = None
    # Qué quiere decir el gesto (la intención que leyó el análisis profundo); se ve en el panel.
    nota: str | None = None
    # Otras opciones de la misma acción que el análisis profundo propone; cada toma sortea entre
    # la principal y ellas.
    alternativas: list[Alternativa] = Field(default_factory=list)


class Capitulo(_Strict):
    """Un tramo que una voz del video asigna a un elemento ("agua", "tierra", "fuego", "aire")."""

    inicio: float
    fin: float
    elemento: str
    # Lo que dice la voz (para revisar a mano).
    voz: str = ""


class PinFile(_Strict):
    catalogo: str | None = None
    solo_estos: bool = False
    momentos: list[Pin] = Field(default_factory=list)
    # Capítulos que marca la voz del video; mandan sobre el reparto automático.
    capitulos: list[Capitulo] = Field(default_factory=list)


def chapter_plan(pins: PinFile, fps: float) -> list[tuple[int, int, str]]:
    """[(cuadro_inicio, cuadro_fin, elemento)] de los capítulos de voz, en orden. Vacío si no hay."""
    plan = [(int(round(c.inicio * fps)), int(round(c.fin * fps)), c.elemento) for c in pins.capitulos]
    return sorted(plan)


def hex_color(text: str | None) -> tuple[float, float, float] | None:
    """"#ff3366" → (1.0, 0.2, 0.4). Lo que no es un color de 6 dígitos da None."""
    value = (text or "").strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[k:k + 2], 16) / 255.0 for k in (0, 2, 4))
    except ValueError:
        return None


def load_pins(path: Path) -> PinFile:
    return PinFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def save_pins(pins: PinFile, path: Path) -> None:
    data = pins.model_dump(exclude_defaults=True)
    data.setdefault("momentos", [])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _person(event: MotionEvent) -> str | None:
    if event.attacker:
        return event.attacker
    return event.target.split(":", 1)[0] if event.target.startswith("person_") else None


def _draw(pin: Pin, catalog, seed: int) -> Pin:
    """El momento con la opción sorteada entre la principal (peso 1) y sus alternativas válidas."""
    valid = [
        a for a in pin.alternativas
        if any(o.name == a.opcion and o.effects for r in catalog.reactions if pin.accion is None or r.action == pin.accion for o in r.options)
    ]
    if not valid:
        return pin
    rng = np.random.default_rng(zlib.crc32(f"{seed}:{pin.seg}".encode()))
    weights = np.array([1.0, *[max(a.encaje, 0.0) for a in valid]])
    pick = int(rng.choice(len(weights), p=weights / weights.sum()))
    if pick == 0:
        return pin
    chosen = valid[pick - 1]
    return pin.model_copy(update={"opcion": chosen.opcion, "figura": chosen.figura})


def resolve_pins(pins: PinFile, catalog, events: list[MotionEvent], brief: MotionBrief, fps: float, seed: int | None = None):
    """[(evento, reacción, opción, pin, creado)]: dónde y con qué se cumple cada momento.

    Con `seed`, los momentos con alternativas sortean su opción (determinista por semilla y segundo)."""
    out = []
    people = brief.people or [brief.person_id]
    for pin in pins.momentos:
        if seed is not None and pin.alternativas:
            pin = _draw(pin, catalog, seed)
        where = f"momento {pin.seg} s ({pin.opcion})"
        matches = [
            (reaction, option)
            for reaction in catalog.reactions
            if pin.accion is None or reaction.action == pin.accion
            for option in reaction.options
            if option.name == pin.opcion
        ]
        if not matches:
            names = sorted({f"{r.action}:{o.name}" for r in catalog.reactions for o in r.options if o.effects})
            raise ValueError(f"{where}: la opción no existe en el catálogo {catalog.name}. Opciones: {', '.join(names)}")
        if len(matches) > 1:
            raise ValueError(f"{where}: la opción está en varias acciones ({', '.join(r.action for r, _ in matches)}); indica `accion`")
        reaction, option = matches[0]
        if not option.effects:
            raise ValueError(f"{where}: la opción no dibuja nada")
        if pin.persona is not None and pin.persona not in people:
            raise ValueError(f"{where}: no hay {pin.persona} en el video (personas: {', '.join(people)})")
        frame = int(round(pin.seg * fps))
        if not 0 <= frame < brief.video.frame_count:
            raise ValueError(f"{where}: fuera del video (dura {brief.video.frame_count / fps:.2f} s)")
        window = PIN_WINDOW_S * fps
        near = [] if pin.exacto else [
            e for e in events
            if e.name == reaction.action
            and abs(e.start_frame - frame) <= window
            and (pin.persona is None or _person(e) == pin.persona)
            and (not option.kinds or e.kind in option.kinds)
        ]
        if near:
            event = min(near, key=lambda e: (abs(e.start_frame - frame), -e.confidence))
            out.append((event, reaction, option, pin, False))
            continue
        person = pin.persona or brief.person_id
        joint = SYNTH_JOINT.get(reaction.action)
        if reaction.action == "entrance":
            # Con persona, su nariz: dos entradas fijadas (una por persona) no se confunden.
            target = f"{pin.persona}:nose" if pin.persona else "nose"
        else:
            target = f"{person}:{joint}" if joint else person
        if pin.lado:
            target = f"{person}:{pin.lado}_wrist" if not joint else f"{person}:{pin.lado}_{joint.split('_', 1)[1]}"
        event = MotionEvent(
            name=reaction.action,
            target=target,
            start_frame=frame,
            end_frame=min(frame + max(int(round(pin.dur * fps)), 1), brief.video.frame_count - 1),
            confidence=1.0,
            detail="Fijado a mano (guion de prueba).",
            attacker=person,
            kind=option.kinds[0] if option.kinds else ("right" if reaction.action in SIDED else ""),
        )
        out.append((event, reaction, option, pin, True))
    return out


def pins_from_choreography(choreography) -> PinFile:
    """Una coreografía hecha como guion de prueba: fijarla tal cual o editarla a mano."""
    mirrors = {(d.action, d.choice.removesuffix(" (espejo)"), d.until) for d in choreography.decisions if d.choice.endswith("(espejo)")}
    moments = []
    for d in choreography.decisions:
        if d.choice.startswith("nada") or d.choice.endswith("(espejo)"):
            continue
        name = d.choice.removesuffix(" (fijado)")
        person = d.target.split(":", 1)[0] if d.target.startswith("person_") else None
        fps = d.frame / d.second if d.second > 0 else 30.0
        side = next((s for s in ("left", "right") if f":{s}_" in d.target), None)
        # Exacto, con lo que duró encendido: se reproduce igual aunque el análisis cambie.
        moments.append(
            Pin(seg=d.second, opcion=name, accion=d.action, persona=person, espejo=(d.action, name, d.until) in mirrors,
                exacto=True, dur=round(max((d.until - d.frame) / fps, 0.1), 2), lado=side)
        )
    return PinFile(catalogo=choreography.catalog, solo_estos=True, momentos=moments)
