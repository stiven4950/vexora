"""Interfaz de línea de comandos."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from vfxglow import __version__
from vfxglow.pipeline import Pipeline


def load_env_file(path: Path) -> None:
    """Lee líneas CLAVE=valor de un .env local. No pisa variables ya definidas en el entorno."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def parse_wardrobe(text: str | None) -> dict[str, str] | None:
    """"vestido" (para todos) o "person_0=vestido,person_1=chaqueta"."""
    if not text:
        return None
    from vfxglow.director.choreography import WARDROBE_CHOICES

    out: dict[str, str] = {}
    for part in text.split(","):
        person, _, choice = part.strip().rpartition("=")
        choice = choice.strip().lower()
        if choice not in WARDROBE_CHOICES:
            raise SystemExit(f"Vestuario desconocido: {choice} (usa {', '.join(WARDROBE_CHOICES)})")
        out[person.strip() or "*"] = choice
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vfxglow",
        description="Analiza un video y compone capas de efectos sin alterar el plano original.",
    )
    parser.add_argument("--version", action="version", version=f"vfxglow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(command: argparse.ArgumentParser, video: bool = True) -> None:
        if video:
            command.add_argument("--video", required=True, type=Path, help="Video de entrada")
        command.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
        command.add_argument("--preset", type=str, default=None, help="Sustituye el preset del director")
        command.add_argument(
            "--director",
            choices=["preset", "openai", "anthropic"],
            default=None,
            help="openai: el director artista diseña el guion y sus dibujos",
        )
        command.add_argument("--catalog", type=str, default=None, help="Coreografía por catálogo (configs/catalogs/<nombre>.yaml)")
        command.add_argument("--seed", type=int, default=None, help="Semilla exacta del catálogo (sin ella se elige sola la mejor coreografía)")
        command.add_argument("--season", type=str, default=None, help="Temporada encima del estilo (configs/seasons.yaml): halloween, navidad...")
        command.add_argument("--fuego", type=str, default=None, help="Estilo de fuego (director/looks.py): clasico, plano, mixto, azul, verde, pixel")
        command.add_argument("--rayo", type=str, default=None, help="Estilo de rayo (director/looks.py): cian, blanco, violeta, rojo, fuego")
        command.add_argument("--take", type=int, default=0, help="Sin --seed: 0 = la mejor coreografía; 1, 2... = otras versiones buenas")
        command.add_argument(
            "--pin",
            type=Path,
            default=None,
            help="Guion de prueba (YAML): momentos fijados a mano que mandan sobre el sorteo",
        )
        command.add_argument(
            "--wardrobe",
            type=str,
            default=None,
            help="Vestuario: chaqueta, vestido, ambos o ninguno, para todos o por persona (person_0=vestido,person_1=chaqueta)",
        )
        command.add_argument(
            "--deep",
            action="store_true",
            help="Análisis profundo: un modelo (Gemini) ve el video completo con audio y escribe la coreografía. Más lento y de pago",
        )
        command.add_argument("--level", choices=["fast", "hq", "masks"], default=None)
        command.add_argument("--force", action="store_true", help="Ignora la caché de etapas")
        command.add_argument(
            "--layers",
            type=str,
            default=None,
            help="Grupos activos separados por coma: glow,particles,interaction,lightning",
        )

    add_common(sub.add_parser("run", help="Ejecuta el pipeline completo"))
    add_common(sub.add_parser("analyze", help="Solo análisis y overlay"))
    add_common(sub.add_parser("direct", help="Genera el Effect Script"))
    add_common(sub.add_parser("render", help="Genera las capas HDR"))
    add_common(sub.add_parser("refine", help="Texturiza máscaras si el refinador está activo"))
    add_common(sub.add_parser("compose", help="Mezcla las capas sobre el video original"))
    export = sub.add_parser("pin-export", help="Convierte una coreografía (choreography.json) en guion de prueba")
    export.add_argument("--choreography", required=True, type=Path)
    export.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    load_env_file(Path(".env"))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "pin-export":
        from vfxglow.director.choreography import Choreography
        from vfxglow.director.pins import pins_from_choreography, save_pins

        choreography = Choreography.model_validate_json(args.choreography.read_text(encoding="utf-8"))
        pins = pins_from_choreography(choreography)
        save_pins(pins, args.out)
        logging.info("Guion de prueba con %d momentos: %s", len(pins.momentos), args.out)
        return 0
    pipeline = Pipeline(
        args.config,
        args.video,
        preset=args.preset,
        level=args.level,
        force=args.force,
        layers=args.layers,
        director=args.director,
        catalog=args.catalog,
        seed=args.seed,
        take=args.take,
        season=args.season,
        fire_style=args.fuego,
        bolt_style=args.rayo,
        pins=args.pin,
        wardrobe=parse_wardrobe(args.wardrobe),
        deep=True if args.deep else None,
    )
    getattr(pipeline, args.command if args.command != "run" else "run")()
    return 0
