"""Director creativo: presets locales o un LLM que emite el mismo esquema."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from vfxglow.analysis.names import CHAINS, FACE_REGIONS, LIMB_JOINTS
from vfxglow.analysis.schema import MotionBrief
from vfxglow.config import DirectorConfig
from vfxglow.director.art import ART_SYSTEM, ArtPlan, expand_art, keyframes, render_art_prompt
from vfxglow.director.presets import load_preset
from vfxglow.director.providers import Completer, extract_json
from vfxglow.director.schema import EVENT_NAMES, SUPPORTED_TYPES, EffectScript, resolve_timing
from vfxglow.director.strategies import StrategyPlan, applicable, cuts_of, describe, expand
from vfxglow.director.validator import ScriptError, validate_script


# Un catálogo crea un efecto por opción elegida al menos una vez (baile_neon ya pasa de 40). El
# límite es una red de seguridad, no un criterio de estilo: la saturación la controlan la línea de
# atención y la nota de las versiones.
CATALOG_MAX_EFFECTS = 120


class CreativeDirector:
    def __init__(
        self,
        config: DirectorConfig,
        preset_dir: Path,
        complete: Completer | None = None,
        cache_dir: Path | None = None,
        video: Path | None = None,
    ) -> None:
        self.config = config
        self.preset_dir = preset_dir
        self._complete = complete
        self.cache_dir = cache_dir
        self.video = video
        # Registro de decisiones del coreógrafo de la última llamada (solo provider catalog).
        self.choreography = None

    def _season(self):
        from vfxglow.director.seasons import find, load_seasons

        if not self.config.season:
            return None
        season = find(load_seasons(self.preset_dir.parent / "seasons.yaml"), self.config.season)
        if season is None:
            raise ValueError(f"Temporada desconocida: {self.config.season}")
        return season

    def create(self, brief: MotionBrief) -> EffectScript:
        if self.config.provider == "catalog":
            from vfxglow.director.choreography import best_choreography, choreograph, load_catalog

            path = self.preset_dir.parent / "catalogs" / f"{self.config.catalog}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"No existe el catálogo {path}")
            catalog = load_catalog(path)
            season = self._season()
            if season is not None:
                from vfxglow.director.seasons import apply_to_catalog

                catalog = apply_to_catalog(catalog, season)
            if self.config.seed is not None:
                script, self.choreography = choreograph(catalog, brief, self.config.seed)
            else:
                # Sin semilla: la mejor de varias coreografías (o la del puesto `take`).
                script, self.choreography = best_choreography(catalog, brief, self.config.take)
            validate_script(
                script,
                set(brief.anchors) | set(CHAINS) | set(FACE_REGIONS) | set(LIMB_JOINTS),
                cuts_of(brief),
                max_effects=CATALOG_MAX_EFFECTS,
            )
            return script
        if self.config.provider == "preset":
            path = self.preset_dir / f"{self.config.preset}.yaml"
            if not path.exists():
                raise FileNotFoundError(f"No existe el preset {path}")
            script = load_preset(path, brief.video.frame_count)
            season = self._season()
            if season is not None:
                from vfxglow.director.schema import Effect
                from vfxglow.director.seasons import decor_effect

                decor = Effect.model_validate({"id": f"season_{season.id}", **decor_effect(season)})
                script = script.model_copy(update={"effects": [*script.effects, decor]})
            return script
        artist = self.config.style == "artist" and bool(brief.beats)
        prompt = render_art_prompt(brief) if artist else render_prompt(brief)
        images = keyframes(self.video, brief, self.config.images) if artist and self.video else []
        complete = self._complete
        if complete is None:
            from vfxglow.director.providers import build_completer

            complete = build_completer(self.config, images=images, system=ART_SYSTEM if artist else None)
        complete = self._cached(complete, images)
        raw = complete(prompt)
        try:
            script = self._parse(raw, brief)
        except (ValidationError, ScriptError, ValueError) as exc:
            repair = (
                f"{prompt}\n\nTu respuesta anterior no cumple el esquema.\n"
                f"Errores:\n{str(exc)[:600]}\n\n"
                "Corrige solo el JSON. No añadas texto fuera del objeto.\n\n"
                f"JSON anterior:\n{raw[:6000]}"
            )
            raw = complete(repair)
            script = self._parse(raw, brief)
        return script

    def _cached(self, complete: Completer, images: list[bytes]) -> Completer:
        """La misma pregunta no se paga dos veces: se guarda la respuesta por hash."""
        if self.cache_dir is None:
            return complete
        import hashlib

        salt = hashlib.sha256(self.config.model.encode() + b"".join(images)).hexdigest()

        def wrapped(prompt: str) -> str:
            key = hashlib.sha256((salt + prompt).encode("utf-8")).hexdigest()[:24]
            path = self.cache_dir / f"{key}.txt"
            if path.exists():
                return path.read_text(encoding="utf-8")
            text = complete(prompt)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return text

        return wrapped

    def _parse(self, raw: str, brief: MotionBrief) -> EffectScript:
        payload = extract_json(raw)
        if '"beats"' in payload and '"effects"' not in payload:
            script = expand_art(ArtPlan.model_validate_json(payload), brief)
        elif '"choices"' in payload:
            plan = StrategyPlan.model_validate_json(payload)
            script = expand(plan, brief)
        else:
            script = EffectScript.model_validate_json(payload)
        script = resolve_timing(script, brief.video.frame_count)
        anchors = set(brief.anchors) | set(CHAINS) | set(FACE_REGIONS) | set(LIMB_JOINTS)
        validate_script(script, anchors, cuts_of(brief))
        return script


def render_prompt(brief: MotionBrief) -> str:
    anchors = ", ".join(brief.anchors) if brief.anchors else "(ninguna)"
    types = ", ".join(SUPPORTED_TYPES)
    payload = brief.model_dump_json()
    objects = ", ".join(brief.objects) if brief.objects else "(ninguno)"
    events = ", ".join(EVENT_NAMES)
    applicable_names = ", ".join(applicable(brief))
    catalog = describe()
    return f"""Diseña un Effect Script para este plano. El video original no se modifica.

Tipos permitidos: {types}
Anclas disponibles: {anchors}
Cadenas: {", ".join(CHAINS)}
Regiones faciales: {", ".join(FACE_REGIONS)}
Objetos visibles: {objects}
Eventos del catálogo: {events}

Reglas:
- version debe ser "1.0".
- end_frame puede ser -1 para llegar al último fotograma.
- Cada efecto necesita id, type, target, time, style, render y refine.
- target.kind es joint, chain, face_region, mask, object o event_point.
- lightning puede nacer de una sola articulación; secondary es opcional (arco entre dos puntos).
- render.blend es add, screen u over.
- render.group es glow, particles, interaction o lightning.
- triggers: lista de {{event, joint, min_speed, min_duration, hold, cooldown, fade_in, fade_out}}.
- Si triggers no está vacío, el efecto solo se enciende cuando ocurre ese evento.
- event_point ancla el efecto al punto del evento, no sigue a la mano.
- Como máximo 8 efectos, anclados al movimiento descrito.
- No inventes anclas ni nombres de evento que no estén en la lista.
- Puedes responder un plan de estrategias en lugar del Effect Script:
  {{"title", "theme", "seed", "choices": [{{"beat", "strategy", "accents", "glyph", "intensity", "actor"}}]}}
- Como máximo una estrategia principal y dos acentos por beat.
- No cruces un corte de plano. beat_grade como máximo una vez por beat.
- El color de cada actor se mantiene en todo el clip.
- Estrategias aplicables: {applicable_names}

Catálogo:
{catalog}

Resumen del movimiento:
{brief.summary}

Brief JSON:
{payload}
"""
