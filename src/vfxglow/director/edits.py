"""Edición del resultado: el editor de efectos (docs/analisis_mejoras_y_seguridad.md, §9.5 E).

Se edita el guion compilado (EffectScript), no la coreografía. Cada efecto lleva sus disparos
exactos (fotograma y articulación) y su azar sale de su `id`, no de su posición: quitar, mover o
cambiar un efecto no altera a los demás, que salen idénticos en la versión nueva. Eso permite
volver a dibujar solo el tramo que cambió (`changed_window`) y copiar el resto del video anterior.

- `Moment`: un disparo de la coreografía (una decisión) con los efectos que enciende.
- `tracks`: los momentos agrupados en pistas (por elemento en Avatar y los catálogos de un
  elemento; por tipo de efecto en los demás).
- `apply_edits`: aplica una lista de cambios (quitar, apagar pista, mover o alargar, agregar,
  estilo) sobre el guion de una versión y devuelve el guion y los momentos de la nueva.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.schema import Effect, EffectScript
from vfxglow.engine.timeline import ActivationTimeline

# Elemento → cómo se ve su pista (nombre, icono de la web y color por omisión).
ELEMENT_TRACKS = {
    "agua": ("Agua", "drop", "#1e90ff"),
    "aire": ("Viento", "wind", "#7dd3fc"),
    "rayo": ("Rayo", "bolt", "#a855f7"),
    "fuego": ("Fuego", "flame", "#f59e0b"),
    "tierra": ("Tierra", "mountain", "#9ca3af"),
}
OTHER_TRACK = ("otros", "Otros efectos", "sparkles", "#94a3b8")
# Sin elementos, una pista por tipo de efecto, hasta este número; el resto va a "Otros efectos".
MAX_OPTION_TRACKS = 6
# Colores de las pistas por tipo de efecto, en orden.
OPTION_COLORS = ["#22d3ee", "#a78bfa", "#f472b6", "#34d399", "#fbbf24", "#60a5fa"]
# Antes del tramo que cambia se dibuja este calentamiento (estelas, agua con física, persistencia)
# sin escribirlo; después, este margen para los fundidos de salida.
WARMUP_S = 2.0
# Medido con video real: al quitar una marca de Avatar el cuadro siguió cambiando 9 fotogramas
# después de su activación (la luz del fuego reacciona con un cuadro de retraso y hay estado
# compartido entre efectos de fuego). 1 s cubre eso con margen; a esto se suma la cola de los
# efectos con persistencia.
TAIL_S = 1.0
# Si el tramo que cambia es casi todo el video, se dibuja entero.
FULL_RENDER_SHARE = 0.75
# Límites de los controles de estilo.
INTENSITY_RANGE = (0.2, 2.0)
SIZE_RANGE = (0.5, 2.0)


class Moment(BaseModel):
    """Un disparo de la coreografía: cuándo, sobre qué articulación y qué efectos enciende."""

    id: str
    frame: int
    # Último fotograma en que su efecto sigue encendido.
    until: int
    action: str
    target: str
    choice: str
    effects: list[str]
    track: str = ""
    note: str = ""


class Track(BaseModel):
    key: str
    label: str
    icon: str
    color: str
    element: str | None = None
    moments: list[str] = Field(default_factory=list)


class TrackStyle(BaseModel):
    """Lo que la persona cambió del aspecto de una pista (sobre los valores de la versión base)."""

    color: str | None = None
    intensity: float = 1.0
    size: float = 1.0


class Edit(BaseModel):
    """Un cambio del editor. `start`/`end` en segundos."""

    op: Literal["remove", "track_off", "move", "add", "style"]
    moment: str | None = None
    track: str | None = None
    start: float | None = None
    end: float | None = None
    option: str | None = None
    action: str | None = None
    person: str | None = None
    color: str | None = None
    intensity: float | None = None
    size: float | None = None


# Lo que hace falta para compilar un efecto nuevo ("Agregar efecto"): opción, acción (si la opción
# está en varias), fotograma, duración en fotogramas y persona. Devuelve (efectos, eventos extra,
# nombre de la opción y acción). Lo da el pipeline, que conoce el catálogo y el análisis.
CompileAdd = Callable[[str, str | None, int, int, str | None], tuple[list[Effect], list[MotionEvent], str, str]]


def element_lookup(catalog) -> Callable[[str, str], str | None]:
    """`element_of(opción, acción)`: el elemento de una opción del catálogo (el del catálogo si la
    opción no dice el suyo; "" = neutra)."""
    elements = {(r.action, o.name): (o.element if o.element is not None else catalog.element) for r in catalog.reactions for o in r.options}
    by_name = {name: element for (_action, name), element in elements.items()}
    return lambda option, action: elements.get((action, option), by_name.get(option))


def moment_id(action: str, frame: int, target: str, choice: str) -> str:
    return f"{action}@{frame}@{target}@{choice}"


def _pairs(effect: Effect, action: str) -> list[tuple[int, str | None]]:
    out = []
    for trigger in effect.triggers:
        if trigger.event != action:
            continue
        targets = trigger.targets or [None] * len(trigger.frames)
        out += list(zip(trigger.frames, targets, strict=False))
    return out


def moments_from(script: EffectScript, decisions: list) -> list[Moment]:
    """Los momentos de una coreografía, con los efectos de su disparo. Las decisiones "nada" no
    encienden nada y se omiten. `decisions`: director/choreography.py Decision (o dicts iguales)."""
    index: dict[tuple[str, int, str | None], list[str]] = {}
    for effect in script.effects:
        for trigger in effect.triggers:
            targets = trigger.targets or [None] * len(trigger.frames)
            for frame, target in zip(trigger.frames, targets, strict=False):
                index.setdefault((trigger.event, frame, target), []).append(effect.id)
    moments = []
    for raw in decisions:
        d = raw if isinstance(raw, dict) else raw.model_dump()
        if d["choice"].startswith("nada"):
            continue
        effects = index.get((d["action"], d["frame"], d["target"])) or index.get((d["action"], d["frame"], None)) or []
        if not effects:
            continue
        moments.append(
            Moment(
                id=moment_id(d["action"], d["frame"], d["target"], d["choice"]),
                frame=d["frame"],
                until=max(d.get("until", -1), d["frame"]),
                action=d["action"],
                target=d["target"],
                choice=d["choice"],
                effects=sorted(set(effects)),
                note=d.get("note", ""),
            )
        )
    return moments


def _option_name(choice: str) -> str:
    return re.sub(r" \((espejo|fijado)\)$", "", choice)


def assign_tracks(moments: list[Moment], element_of: Callable[[str, str], str | None]) -> list[Track]:
    """Pone cada momento en su pista. `element_of(opción, acción)`: el elemento de la opción en el
    catálogo ("" o None si no tiene). Con elementos, una pista por elemento (Agua, Viento, Rayo,
    Fuego, Tierra); sin ellos, una por tipo de efecto (los más usados) y "Otros efectos"."""
    elements = {m.id: element_of(_option_name(m.choice), m.action) for m in moments}
    by_element = any(elements.values())
    tracks: dict[str, Track] = {}
    if by_element:
        for moment in moments:
            element = elements[moment.id]
            if element in ELEMENT_TRACKS:
                label, icon, color = ELEMENT_TRACKS[element]
                key = element
            else:
                key, label, icon, color = OTHER_TRACK
            track = tracks.setdefault(key, Track(key=key, label=label, icon=icon, color=color, element=element if key == element else None))
            track.moments.append(moment.id)
            moment.track = key
    else:
        top = [name for name, _ in Counter(_option_name(m.choice) for m in moments).most_common(MAX_OPTION_TRACKS)]
        for moment in moments:
            name = _option_name(moment.choice)
            if name in top:
                key, label = name, name.replace("_", " ").capitalize()
                icon, color = "sparkles", OPTION_COLORS[top.index(name) % len(OPTION_COLORS)]
            else:
                key, label, icon, color = OTHER_TRACK
            track = tracks.setdefault(key, Track(key=key, label=label, icon=icon, color=color))
            track.moments.append(moment.id)
            moment.track = key
    first = {key: min(next(m.frame for m in moments if m.id == mid) for mid in track.moments) for key, track in tracks.items()}
    return sorted(tracks.values(), key=lambda t: (t.key == OTHER_TRACK[0], first[t.key]))


# ----- aplicar cambios -----


def _without_pair(effect: Effect, action: str, frame: int, target: str) -> Effect | None:
    """El efecto sin ese disparo; None si se queda sin ninguno."""
    triggers = []
    for trigger in effect.triggers:
        if trigger.event != action:
            triggers.append(trigger)
            continue
        if trigger.targets:
            kept = [(f, t) for f, t in zip(trigger.frames, trigger.targets, strict=False) if not (f == frame and t == target)]
            frames, targets = [f for f, _ in kept], [t for _, t in kept]
        else:
            frames, targets = [f for f in trigger.frames if f != frame], []
        if frames:
            triggers.append(trigger.model_copy(update={"frames": frames, "targets": targets}))
    has_frames = any(t.frames for t in triggers)
    return effect.model_copy(update={"triggers": triggers}) if has_frames else None


def _hex(color: str) -> tuple[float, float, float]:
    text = color.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        raise ValueError(f"Color no válido: {color}")
    return tuple(int(text[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _styled(effect: Effect, style: TrackStyle) -> Effect:
    """El efecto con el aspecto de su pista: intensidad (la ganancia del motor), tamaño (escala de su
    capa alrededor de su ancla) y color (tinte de su capa). El motor aplica los dos últimos sobre la
    capa dibujada (engine/tint.py), así que valen también para el agua, el fuego, el aire y la tierra."""
    update: dict = {"intensity": effect.style.intensity * style.intensity, "scale": effect.style.scale * style.size}
    if style.color:
        update["tint"] = _hex(style.color)
    return effect.model_copy(update={"style": effect.style.model_copy(update=update)})


def apply_edits(
    script: EffectScript,
    moments: list[Moment],
    tracks: list[Track],
    edits: list[Edit],
    events: list[MotionEvent],
    fps: float,
    frame_count: int,
    compile_add: CompileAdd | None = None,
    main_track: str | None = None,
) -> tuple[EffectScript, list[Moment], dict[str, TrackStyle]]:
    """El guion y los momentos de la versión nueva, y el estilo de cada pista que se cambió.
    `events`: los del análisis (los extra del guion se suman aquí). `main_track`: la pista del
    elemento del catálogo (el fuego en Avatar); su estilo se aplica también a los efectos permanentes
    (`always_`: las brasas, la luz del fuego), que son de ese elemento y no son momentos de ninguna
    pista. Un cambio imposible (un momento que no existe, un tiempo fuera del video) es un error:
    nunca se salta en silencio."""
    effects = {effect.id: effect for effect in script.effects}
    order = [effect.id for effect in script.effects]
    extra = list(script.extra_events)
    all_events = [*events, *extra]
    current = {m.id: m.model_copy(deep=True) for m in moments}
    track_of = {mid: t.key for t in tracks for mid in t.moments}
    styles: dict[str, TrackStyle] = {}
    counter = 0

    def drop(moment: Moment) -> None:
        for effect_id in moment.effects:
            effect = effects.get(effect_id)
            if effect is None:
                continue
            kept = _without_pair(effect, moment.action, moment.frame, moment.target)
            if kept is None:
                del effects[effect_id]
            else:
                effects[effect_id] = kept
        del current[moment.id]

    def seconds_to_frame(seconds: float) -> int:
        frame = int(round(seconds * fps))
        if not 0 <= frame < frame_count:
            raise ValueError(f"{seconds:.2f} s está fuera del video (dura {frame_count / fps:.2f} s)")
        return frame

    for edit in edits:
        if edit.op in ("remove", "move"):
            moment = current.get(edit.moment or "")
            if moment is None:
                raise ValueError(f"No existe el momento {edit.moment}")
        if edit.op == "remove":
            drop(moment)
        elif edit.op == "track_off":
            ids = [mid for mid, key in track_of.items() if key == edit.track and mid in current]
            if not ids:
                raise ValueError(f"No hay momentos en la pista {edit.track}")
            for mid in ids:
                drop(current[mid])
        elif edit.op == "move":
            if edit.start is None or edit.end is None or edit.end <= edit.start:
                raise ValueError("Mover un efecto pide inicio y fin (el fin después del inicio)")
            start = seconds_to_frame(edit.start)
            length = max(int(round((edit.end - edit.start) * fps)), 1)
            source = next((e for e in all_events if e.name == moment.action and e.start_frame == moment.frame and e.target == moment.target), None)
            if source is None:
                raise ValueError(f"No se encontró el gesto del momento {moment.id}")
            new_ids = []
            for effect_id in moment.effects:
                effect = effects.get(effect_id)
                if effect is None:
                    continue
                trigger = next((t for t in effect.triggers if t.event == moment.action), None)
                if trigger is None:
                    continue
                counter += 1
                hold = trigger.hold
                # El evento nuevo dura lo que pide la barra, descontado lo que el efecto se sostiene.
                end = min(max(start + length - 1 - hold, start), frame_count - 1)
                event = source.model_copy(update={"start_frame": start, "end_frame": end, "detail": "Movido en el editor."})
                extra.append(event)
                all_events.append(event)
                copy_id = f"{effect_id.split('~')[0]}~m{counter}"
                copy = effect.model_copy(update={"id": copy_id, "triggers": [trigger.model_copy(update={"frames": [start], "targets": [moment.target], "cooldown": 0, "max_activations": 0})]})
                kept = _without_pair(effect, moment.action, moment.frame, moment.target)
                if kept is None:
                    del effects[effect_id]
                    order[order.index(effect_id)] = copy_id
                else:
                    effects[effect_id] = kept
                    order.insert(order.index(effect_id) + 1, copy_id)
                effects[copy_id] = copy
                new_ids.append(copy_id)
            del current[moment.id]
            moved = moment.model_copy(update={"id": moment_id(moment.action, start, moment.target, moment.choice), "frame": start, "until": start + length - 1, "effects": new_ids})
            current[moved.id] = moved
            track_of[moved.id] = track_of.get(moment.id, moment.track)
        elif edit.op == "add":
            if compile_add is None or not edit.option or edit.start is None:
                raise ValueError("Agregar un efecto pide la opción y el segundo")
            start = seconds_to_frame(edit.start)
            length = max(int(round(((edit.end or edit.start + 0.6) - edit.start) * fps)), 1)
            new_effects, new_events, choice, action = compile_add(edit.option, edit.action, start, length, edit.person)
            counter += 1
            ids = []
            for effect in new_effects:
                effect_id = f"ed{counter}_{effect.id}"
                effects[effect_id] = effect.model_copy(update={"id": effect_id})
                order.append(effect_id)
                ids.append(effect_id)
            extra += new_events
            all_events += new_events
            target = new_events[0].target if new_events else (edit.person or "")
            added = Moment(id=moment_id(action, start, target, choice), frame=start, until=start + length - 1, action=action, target=target, choice=choice, effects=ids)
            current[added.id] = added
            track_of[added.id] = edit.track or ""
        elif edit.op == "style":
            if not edit.track:
                raise ValueError("Cambiar el estilo pide la pista")
            style = styles.setdefault(edit.track, TrackStyle())
            if edit.color is not None:
                _hex(edit.color)
                style.color = edit.color
            if edit.intensity is not None:
                style.intensity = min(max(edit.intensity, INTENSITY_RANGE[0]), INTENSITY_RANGE[1])
            if edit.size is not None:
                style.size = min(max(edit.size, SIZE_RANGE[0]), SIZE_RANGE[1])

    for key, style in styles.items():
        ids = {effect_id for mid, track in track_of.items() if track == key and mid in current for effect_id in current[mid].effects}
        if key == main_track:
            ids |= {effect_id for effect_id in effects if effect_id.startswith("always_")}
        for effect_id in ids:
            if effect_id in effects:
                effects[effect_id] = _styled(effects[effect_id], style)

    for moment in current.values():
        moment.track = track_of.get(moment.id, moment.track)
    new_script = script.model_copy(update={"effects": [effects[i] for i in order if i in effects], "extra_events": extra})
    return new_script, sorted(current.values(), key=lambda m: (m.frame, m.id)), styles


# ----- el tramo que cambia -----


def _windows(effect: Effect, events: list[MotionEvent]) -> list[tuple[int, int]]:
    return [(w.start, w.end) for w in ActivationTimeline(effect, events).windows]


def changed_window(old: EffectScript, new: EffectScript, events: list[MotionEvent], frame_count: int, fps: float) -> tuple[int, int] | None:
    """Los fotogramas que hay que volver a dibujar (y escribir), o None si nada cambia.

    Empieza por las activaciones de los efectos que cambiaron (en las dos versiones) y se extiende
    a toda activación de otro efecto que se cruce con el tramo: un efecto que ya estaba encendido
    al empezar el tramo se dibujaría distinto si empieza en frío. Los permanentes (`always_`) no
    extienden el tramo: dependen del fotograma y de unos pocos anteriores, que cubre el
    calentamiento (WARMUP_S) que el pipeline dibuja antes sin escribirlo."""
    old_events = [*events, *old.extra_events]
    new_events = [*events, *new.extra_events]
    before = {e.id: e for e in old.effects}
    after = {e.id: e for e in new.effects}
    spans: list[tuple[int, int]] = []
    for effect_id in before.keys() | after.keys():
        a, b = before.get(effect_id), after.get(effect_id)
        if a is not None and b is not None and a.model_dump() == b.model_dump():
            continue
        if a is not None and b is not None and a.model_dump(exclude={"triggers"}) == b.model_dump(exclude={"triggers"}):
            # Solo cambiaron sus disparos (se quitó o movió uno): cuentan las activaciones que ya
            # no están o que son nuevas, no las que siguen igual.
            old_w, new_w = set(_windows(a, old_events)), set(_windows(b, new_events))
            spans += sorted(old_w ^ new_w)
            continue
        if a is not None:
            spans += _windows(a, old_events)
        if b is not None:
            spans += _windows(b, new_events)
        # Un efecto sin disparos (por tiempo) que cambió: su intervalo de tiempo entero.
        for effect in (a, b):
            if effect is not None and not effect.triggers:
                end = effect.time.end_frame if effect.time.end_frame >= 0 else frame_count - 1
                spans.append((effect.time.start_frame, end))
    if not spans:
        return None
    start, end = min(s for s, _ in spans), max(e for _, e in spans)
    others = [(e, new_events) for e in new.effects if not e.id.startswith("always_")] + [(e, old_events) for e in old.effects if not e.id.startswith("always_")]
    windows = [w for effect, evs in others for w in _windows(effect, evs)]
    while True:
        grown = [(s, e) for s, e in windows if s <= end and e >= start]
        new_start, new_end = min([start, *(s for s, _ in grown)]), max([end, *(e for _, e in grown)])
        if (new_start, new_end) == (start, end):
            break
        start, end = new_start, new_end
    # La cola de los efectos con persistencia: cuadros hasta que su brillo cae bajo 1/512.
    decays = [e.render.persistence for e in [*old.effects, *new.effects] if 0 < e.render.persistence < 1]
    trail = max((int(np.ceil(np.log(1 / 512) / np.log(d))) for d in decays), default=0)
    end = min(end + int(round(TAIL_S * fps)) + trail, frame_count - 1)
    start = max(start, 0)
    if (end - start + 1) >= FULL_RENDER_SHARE * frame_count:
        return 0, frame_count - 1
    return start, end
