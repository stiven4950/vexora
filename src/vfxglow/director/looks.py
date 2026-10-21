"""Estilos de fuego y de rayo que elige el cliente antes de renderizar.

Se aplican encima del catálogo, como las temporadas (director/seasons.py), sin tocar la
coreografía: cambian cómo se pinta, no qué ni cuándo.

- Fuego: la forma de pintarlo (`look` de engine/firebend.py), la paleta y el pixelado.
- Rayo: los colores y la forma del rayo (cinta plana, ramas, hasta el borde, chispazos). El cuadro
  se tiñe del color del rayo.
"""

from __future__ import annotations

import copy

from pydantic import BaseModel


class Look(BaseModel):
    id: str
    title: str
    description: str


# Colores de las brasas que sueltan las extremidades rápidas (efecto droplets) por paleta.
SPARKS = {
    "azul": [[0.8, 0.92, 1.0], [0.25, 0.6, 1.0]],
    "verde": [[0.88, 1.0, 0.7], [0.35, 1.0, 0.2]],
}

FIRE_STYLES: dict[str, dict] = {
    "clasico": {"title": "Clásico", "description": "Cuerpo blanco, borde amarillo y resplandor naranja (video_18).", "style": {"look": "hot", "fire_palette": "naranja"}},
    "plano": {"title": "Plano amarillo", "description": "Amarillo plano y opaco con huecos, como el anime de video_51.", "style": {"look": "cel", "fire_palette": "naranja"}, "blend": "over"},
    "mixto": {"title": "Mixto", "description": "Amarillo plano con el núcleo blanco en lo más grueso.", "style": {"look": "mix", "fire_palette": "naranja"}, "blend": "over"},
    "azul": {"title": "Azul espectral", "description": "Fuego frío: cuerpo blanco azulado, borde y luz azules.", "style": {"look": "hot", "fire_palette": "azul"}},
    "verde": {"title": "Verde fantasmal", "description": "Fuego de espíritu: cuerpo verdoso, borde y luz verdes.", "style": {"look": "hot", "fire_palette": "verde"}},
    "pixel": {"title": "Pixel art", "description": "El fuego clásico en bloques de píxel, como un videojuego retro.", "style": {"look": "hot", "fire_palette": "naranja", "fire_pixel": 0.012}},
}

_BOLT = {"branches": 4, "branch_depth": 2, "branch_angle": 34, "reseed_every": 1, "tail_frames": 3, "reach": 2.2, "hands_only": True}
BOLT_STYLES: dict[str, dict] = {
    "cian": {"title": "Cian", "description": "Cinta quebrada cian hasta el borde, lazo y chispazos (video_51).",
             "colors": [[0.35, 0.92, 1.0], [0.1, 0.62, 0.85], [0.0, 0.3, 0.75]],
             "lightning": {**_BOLT, "jitter": 0.38, "sparks": 4, "ribbon": 0.2, "to_edge": True, "trail": 8, "crackle": 3}},
    "blanco": {"title": "Blanco eléctrico", "description": "Rayo clásico blanco azulado, fino y con muchas ramas.",
               "colors": [[1.0, 1.0, 1.0], [0.75, 0.85, 1.0], [0.45, 0.55, 1.0]],
               "lightning": {**_BOLT, "branches": 6, "branch_depth": 3, "jitter": 0.45, "sparks": 6, "ribbon": 0.0, "to_edge": True, "trail": 0, "crackle": 4}},
    "violeta": {"title": "Violeta", "description": "Energía violeta: cinta quebrada con lazo, como un hechizo.",
                "colors": [[1.0, 0.85, 1.0], [0.72, 0.3, 1.0], [0.42, 0.08, 0.9]],
                "lightning": {**_BOLT, "jitter": 0.4, "sparks": 4, "ribbon": 0.2, "to_edge": True, "trail": 8, "crackle": 3}},
    "rojo": {"title": "Rojo carmesí", "description": "Rayo rojo y agresivo, quebrado y con chispazos.",
             "colors": [[1.0, 0.9, 0.85], [1.0, 0.18, 0.12], [0.65, 0.0, 0.05]],
             "lightning": {**_BOLT, "jitter": 0.5, "sparks": 6, "ribbon": 0.16, "to_edge": True, "trail": 6, "crackle": 4}},
    "fuego": {"title": "De fuego", "description": "El rayo de los maestros fuego: fino, quebrado y color fuego.",
              "colors": [[1.0, 0.9, 0.7], [1.0, 0.5, 0.1], [0.9, 0.2, 0.05]],
              "lightning": {**_BOLT, "reseed_every": 2, "jitter": 0.42, "sparks": 6, "ribbon": 0.0, "to_edge": False, "trail": 0, "crackle": 0}},
}


def fire_looks() -> list[Look]:
    return [Look(id=k, title=v["title"], description=v["description"]) for k, v in FIRE_STYLES.items()]


def bolt_looks() -> list[Look]:
    return [Look(id=k, title=v["title"], description=v["description"]) for k, v in BOLT_STYLES.items()]


def check(fire: str | None, bolt: str | None) -> None:
    if fire and fire not in FIRE_STYLES:
        raise ValueError(f"Estilo de fuego desconocido: {fire}. Opciones: {', '.join(FIRE_STYLES)}")
    if bolt and bolt not in BOLT_STYLES:
        raise ValueError(f"Estilo de rayo desconocido: {bolt}. Opciones: {', '.join(BOLT_STYLES)}")


def _is_bolt(catalog, option, effect: dict) -> bool:
    """Los rayos del elemento rayo; el rayo color fuego de los maestros fuego queda como está."""
    if effect.get("type") != "lightning":
        return False
    element = option.element if option.element is not None else catalog.element
    return element == "rayo" or not catalog.element


def apply_looks(catalog, fire: str | None = None, bolt: str | None = None):
    """Copia del catálogo con el fuego y el rayo elegidos (el original no se toca)."""
    check(fire, bolt)
    out = catalog.model_copy(deep=True)
    if fire:
        spec = FIRE_STYLES[fire]
        defaults = copy.deepcopy(out.defaults)
        defaults.setdefault("style", {}).update(spec["style"])
        if spec.get("blend"):
            defaults.setdefault("render", {})["blend"] = spec["blend"]
        # Cada efecto toma su estilo de los valores por defecto más los suyos (choreography._effect):
        # con cambiarlos alcanza, también para la luz del fuego y las bestias.
        out.defaults = defaults
        sparks = SPARKS.get(spec["style"].get("fire_palette", "naranja"))
        if sparks:  # las brasas de las extremidades, del color del fuego
            for raw in [*out.always, *(e for r in out.reactions for o in r.options for e in o.effects)]:
                if raw.get("type") in ("droplets", "sparks"):
                    raw.setdefault("style", {})["colors"] = [list(c) for c in sparks]
    if bolt:
        spec = BOLT_STYLES[bolt]
        for reaction in out.reactions:
            for option in reaction.options:
                for raw in option.effects:
                    if _is_bolt(out, option, raw):
                        style = raw.setdefault("style", {})
                        style["colors"] = [list(c) for c in spec["colors"]]
                        style["lightning"] = {**style.get("lightning", {}), **spec["lightning"]}
    return out
