"""Máscaras de silueta con SAM 2.1. Solo CUDA, y solo si un efecto las necesita."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import FrameRecord
from vfxglow.device import require_cuda


SAM2_CHECKPOINT_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt"


class Sam2Masker:
    def __init__(self, model_cfg: str, checkpoint: str, device: str) -> None:
        require_cuda("Las máscaras SAM 2.1", device)
        checkpoint_path = Path(checkpoint)
        if not checkpoint_path.exists():
            raise RuntimeError(
                "No está el checkpoint de SAM 2.1. Descárgalo y apunta analysis.masks.sam2_checkpoint a ese archivo.\n"
                f"URL: {SAM2_CHECKPOINT_URL}"
            )
        try:
            from sam2.build_sam import build_sam2_video_predictor
        except ImportError as exc:
            raise RuntimeError("SAM 2 no está instalado. Instala el extra: pip install 'vfxglow[masks]'.") from exc
        self._predictor = build_sam2_video_predictor(model_cfg, str(checkpoint_path), device="cuda")

    def apply(self, video_path: Path, frames: list[FrameRecord], dest_dir: Path) -> None:
        import torch

        prompt = next((frame for frame in frames if frame.box is not None), None)
        if prompt is None or prompt.box is None:
            return
        dest_dir.mkdir(parents=True, exist_ok=True)
        x0, y0, x1, y1 = prompt.box
        # El esquema guarda la caja normalizada. SAM 2 espera píxeles.
        # El tamaño real lo resuelve el predictor al leer el video; aquí se escala
        # después de conocer la máscara, así que el prompt se pasa normalizado
        # y se convierte con el primer fotograma leído por OpenCV.
        cap = cv2.VideoCapture(str(video_path))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.release()
        box = np.array([x0 * width, y0 * height, x1 * width, y1 * height], dtype=np.float32)
        with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
            state = self._predictor.init_state(
                video_path=str(video_path),
                offload_video_to_cpu=True,
                offload_state_to_cpu=True,
            )
            self._predictor.add_new_points_or_box(
                state,
                frame_idx=prompt.frame,
                obj_id=1,
                box=box,
            )
            by_frame = {record.frame: record for record in frames}
            for frame_idx, _obj_ids, masks in self._predictor.propagate_in_video(state):
                record = by_frame.get(int(frame_idx))
                if record is None:
                    continue
                mask = _mask_u8(masks)
                rel = Path("analysis") / "masks" / f"f{int(frame_idx):06d}.png"
                path = dest_dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), mask)
                record.mask_path = str(rel)


def _mask_u8(masks: object) -> np.ndarray:
    array = masks
    if hasattr(masks, "detach"):
        array = masks.detach().cpu().numpy()
    array = np.asarray(array)
    while array.ndim > 2:
        array = array[0]
    return ((array > 0.0).astype(np.uint8)) * 255
