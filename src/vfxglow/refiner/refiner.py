"""Refinador opcional. Solo texturiza la máscara de una capa ya dibujada."""

from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.flow import FlowEstimator
from vfxglow.analysis.schema import FrameRecord
from vfxglow.config import RefinerConfig
from vfxglow.device import require_cuda
from vfxglow.director.schema import EffectScript
from vfxglow.engine.anchors import collect_points
from vfxglow.engine.engine import load_layer, save_layer
from vfxglow.refiner.warp import alpha_mask, warp_image


def mix_seed(seed: int, effect_id: str, frame: int) -> int:
    digest = hashlib.sha256(f"{seed}:{effect_id}:{frame}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "little")


class DiffusionRefiner:
    """Inpaint de baja fuerza. Las claves se generan; el resto se deforma con el flujo."""

    def __init__(self, config: RefinerConfig, device: str) -> None:
        require_cuda("El refinador difusor", device)
        self.config = config
        self.device = device
        self._pipe = None
        self._mode = "inpaint"

    def _load(self):
        if self._pipe is not None:
            return self._pipe
        import torch

        try:
            from diffusers import StableDiffusionControlNetInpaintPipeline, ControlNetModel

            controlnet = ControlNetModel.from_pretrained(self.config.controlnet_id, torch_dtype=torch.float16)
            pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
                self.config.model_id,
                controlnet=controlnet,
                torch_dtype=torch.float16,
            )
            self._mode = "controlnet"
        except Exception:
            from diffusers import StableDiffusionInpaintPipeline

            pipe = StableDiffusionInpaintPipeline.from_pretrained(self.config.model_id, torch_dtype=torch.float16)
            self._mode = "inpaint"
        pipe = pipe.to("cuda")
        self._pipe = pipe
        return pipe

    def refine_run(
        self,
        run_dir: Path,
        video_path: Path,
        tracks: list[FrameRecord],
        script: EffectScript,
        device: str,
    ) -> None:
        from vfxglow.io.video import VideoReader

        flow = FlowEstimator("farneback", device)
        by_frame = {track.frame: track for track in tracks}
        plates: list[np.ndarray] = []
        with VideoReader(video_path) as reader:
            plates.extend(frame for _, frame in reader)
        for effect in script.effects:
            if not effect.refine.enabled:
                continue
            previous: np.ndarray | None = None
            prev_plate: np.ndarray | None = None
            for index, plate in enumerate(plates):
                path = run_dir / "layers" / effect.id / f"f{index:06d}.npy"
                if not path.exists():
                    continue
                layer = load_layer(path)
                mask = alpha_mask(layer[..., 3], self.config.dilate_px)
                if int(mask.max()) == 0:
                    previous = layer
                    prev_plate = plate
                    continue
                stride = effect.refine.keyframe_stride or self.config.keyframe_stride
                is_key = index % max(stride, 1) == 0 or previous is None
                if is_key:
                    prompt = effect.refine.prompt or f"{effect.style.preset or effect.type}, luminous, transparent background"
                    pose = _pose_image(by_frame.get(index), plate.shape[1], plate.shape[0])
                    textured = self._inpaint(plate, mask, pose, prompt, mix_seed(script.seed, effect.id, index), effect.refine.strength)
                    if previous is not None and prev_plate is not None:
                        warped = warp_image(previous, flow.between(prev_plate, plate))
                        textured = 0.45 * warped + 0.55 * textured
                else:
                    assert previous is not None and prev_plate is not None
                    textured = warp_image(previous, flow.between(prev_plate, plate))
                layer = _apply_texture(layer, textured, mask)
                save_layer(path, layer)
                previous = layer
                prev_plate = plate

    def _inpaint(self, plate_bgr: np.ndarray, mask: np.ndarray, pose_bgr: np.ndarray, prompt: str, seed: int, strength: float) -> np.ndarray:
        import torch
        from PIL import Image

        pipe = self._load()
        rgb = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        mask_image = Image.fromarray(mask)
        generator = torch.Generator(device="cuda").manual_seed(seed)
        kwargs = {
            "prompt": prompt,
            "image": image,
            "mask_image": mask_image,
            "strength": float(np.clip(strength, 0.05, 0.85)),
            "num_inference_steps": self.config.steps,
            "guidance_scale": self.config.guidance_scale,
            "generator": generator,
        }
        if self._mode == "controlnet":
            kwargs["control_image"] = Image.fromarray(cv2.cvtColor(pose_bgr, cv2.COLOR_BGR2RGB))
        result = pipe(**kwargs).images[0]
        out = np.asarray(result).astype(np.float32) / 255.0
        if out.shape[1] != plate_bgr.shape[1] or out.shape[0] != plate_bgr.shape[0]:
            out = cv2.resize(out, (plate_bgr.shape[1], plate_bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
        return out


def _apply_texture(layer: np.ndarray, texture_rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Sustituye el color dentro de la máscara y tira todo lo que cae fuera."""
    from vfxglow.composite.color import srgb_to_linear

    coverage = np.clip(mask.astype(np.float32) / 255.0, 0.0, 1.0)
    procedural = np.clip(layer[..., 3], 0.0, 1.0)
    keep = coverage * procedural
    linear = srgb_to_linear(texture_rgb)
    energy = linear * np.float32(2.0)
    out = layer.copy()
    out[..., :3] = out[..., :3] * (1.0 - keep[..., None]) + energy * keep[..., None]
    out[..., 3] = procedural
    out[..., :3] *= (procedural > 0.02)[..., None]
    return out


def _pose_image(track: FrameRecord | None, width: int, height: int) -> np.ndarray:
    canvas = np.zeros((height, width, 3), dtype=np.uint8)
    points = collect_points(track, width, height)
    from vfxglow.analysis.names import BONES

    for a, b in BONES:
        if a in points and b in points:
            p0 = tuple(int(v) for v in points[a])
            p1 = tuple(int(v) for v in points[b])
            cv2.line(canvas, p0, p1, (255, 255, 255), 3, cv2.LINE_AA)
    return canvas
