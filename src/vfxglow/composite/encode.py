"""Búsqueda de ffmpeg y escritura del video final."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np


def find_ffmpeg(required: bool = True) -> str | None:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
    except ImportError:
        bundled = None
    else:
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    if bundled:
        return bundled
    if required:
        raise RuntimeError(
            "No se encontró ffmpeg. Instálalo en el sistema o añade la dependencia imageio-ffmpeg."
        )
    return None


class FrameEncoder:
    """Recibe RGB uint8 por fotograma y copia el audio del video fuente si existe.

    Escribe en `<nombre>.partial<ext>` y solo lo renombra al destino en `close()` si ffmpeg
    terminó bien y, cuando se indica `frames`, si se escribieron exactamente esos fotogramas.
    Un proceso interrumpido no deja un video truncado con el nombre final.
    """

    def __init__(
        self,
        path: Path,
        width: int,
        height: int,
        fps: float,
        codec: str = "h264",
        crf: int = 18,
        audio_from: Path | None = None,
        frames: int | None = None,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.partial = path.with_name(f"{path.stem}.partial{path.suffix}")
        ffmpeg = find_ffmpeg(required=True)
        assert ffmpeg is not None
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            f"{fps:.6f}",
            "-i",
            "-",
        ]
        self._audio = audio_from is not None
        if audio_from is not None:
            cmd += ["-i", str(audio_from)]
        if codec == "prores":
            video_args = ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuv444p10le"]
        else:
            video_args = ["-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if audio_from is not None:
            # -shortest recortaría el video si el audio acaba unos milisegundos antes.
            limit = ["-t", f"{frames / fps:.6f}"] if frames else []
            cmd += ["-map", "0:v:0", "-map", "1:a:0?", *video_args, "-c:a", "copy", *limit]
        else:
            cmd += video_args
        cmd.append(str(self.partial))
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        self.path = path
        self.width = width
        self.height = height
        self.expected = frames
        self.frames = 0

    def write(self, rgb: np.ndarray) -> None:
        if rgb.shape[0] != self.height or rgb.shape[1] != self.width or rgb.shape[2] != 3:
            raise RuntimeError(
                f"Fotograma {rgb.shape} no coincide con {self.height}x{self.width}."
            )
        if rgb.dtype != np.uint8:
            raise RuntimeError("El encoder espera RGB uint8.")
        assert self.proc.stdin is not None
        self.proc.stdin.write(np.ascontiguousarray(rgb).tobytes())
        self.frames += 1

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        stderr = b""
        if self.proc.stderr:
            stderr = self.proc.stderr.read()
        code = self.proc.wait()
        if code != 0:
            self.partial.unlink(missing_ok=True)
            message = stderr.decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"ffmpeg terminó con código {code}: {message}")
        if self.expected is not None and self.frames != self.expected:
            self.partial.unlink(missing_ok=True)
            raise RuntimeError(f"Se escribieron {self.frames} fotogramas de {self.expected}; no se guarda {self.path.name}.")
        self.partial.replace(self.path)

    def abort(self) -> None:
        """Corta ffmpeg y borra el archivo parcial. El destino anterior, si existía, queda intacto."""
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        self.proc.kill()
        self.proc.wait()
        self.partial.unlink(missing_ok=True)
