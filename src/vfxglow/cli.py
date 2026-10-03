"""Interfaz de línea de comandos."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from vfxglow import __version__
from vfxglow.pipeline import Pipeline


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

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    pipeline = Pipeline(
        args.config,
        args.video,
        preset=args.preset,
        level=args.level,
        force=args.force,
        layers=args.layers,
        director=args.director,
    )
    getattr(pipeline, args.command if args.command != "run" else "run")()
    return 0
