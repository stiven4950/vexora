"""El audio de un .mp4 se lee igual en Windows, Mac y Linux (librosa no abre .mp4 en Windows)."""

import subprocess
from pathlib import Path

import pytest

from vfxglow.analysis import beats


def _mp4_with_clicks(path: Path) -> Path:
    """2 s de video negro con un golpe de audio en 0.25, 0.75, 1.25 y 1.75 s."""
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    clicks = "if(lt(mod(t-0.25,0.5),0.02)*gte(t,0.25),sin(2*PI*1000*t),0)"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=2",
         "-f", "lavfi", "-i", f"aevalsrc='{clicks}':s=22050:d=2",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )
    return path


def test_mp4_audio_decodes_with_ffmpeg(tmp_path: Path) -> None:
    samples = beats._decode_audio(_mp4_with_clicks(tmp_path / "c.mp4"), beats.LIBROSA_RATE)
    assert samples is not None and samples.size > beats.LIBROSA_RATE  # unos 2 s de audio


def test_librosa_finds_the_clicks_in_an_mp4(tmp_path: Path) -> None:
    pytest.importorskip("librosa")
    frames = beats._librosa_onsets(_mp4_with_clicks(tmp_path / "c.mp4"), 10.0, 20)
    assert frames is not None
    # Cada golpe cae en el fotograma 2, 7, 12 o 17 (a 10 fps), con un fotograma de margen.
    for expected in (2, 7, 12, 17):
        assert any(abs(f - expected) <= 1 for f in frames), (expected, frames)


def test_video_without_audio_has_no_onsets(tmp_path: Path) -> None:
    imageio_ffmpeg = pytest.importorskip("imageio_ffmpeg")
    path = tmp_path / "mudo.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=64x64:r=10:d=1", "-c:v", "libx264", str(path)], check=True)
    assert beats._decode_audio(path, beats.LIBROSA_RATE) is None
    assert beats._audio_onsets(path, 10.0, 10) == []
