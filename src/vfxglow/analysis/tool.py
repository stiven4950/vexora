"""La herramienta que pinta (pincel, esponja, lápiz, dedo), sin suponer su color.

Se trabaja con fotogramas alineados a la cara (analysis/paint.py): ahí la cara queda quieta y lo
que se mueve es la mano y la herramienta. La pieza móvil más grande que entra en la cara es la
herramienta con la mano; su punta es el punto de esa pieza, dentro de la cara, más lejos de por
donde entra (el lado de la mano). Si la alineación falla un fotograma, casi toda la cara "se
mueve": ese fotograma se descarta.
"""

from __future__ import annotations

import cv2
import numpy as np

MOVE = 30  # diferencia (0-255, canal máximo) que cuenta como movimiento
MIN_PIXELS = 60
MAX_MOVING_SHARE = 0.35  # más de esto de la cara en movimiento = alineación fallida


def tool_tip(previous: np.ndarray, current: np.ndarray, region: np.ndarray) -> np.ndarray | None:
    """Punta de la herramienta en coordenadas de la cara, o None."""
    diff = np.abs(current.astype(np.int16) - previous.astype(np.int16)).max(axis=2)
    moving = (diff > MOVE).astype(np.uint8)
    moving = cv2.morphologyEx(moving, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    if (moving.astype(bool) & region).sum() > MAX_MOVING_SHARE * region.sum():
        return None
    count, labels, stats, _ = cv2.connectedComponentsWithStats(moving)
    best = None
    for k in range(1, count):
        if stats[k, 4] < MIN_PIXELS:
            continue
        piece = labels == k
        inside = piece & region
        if not inside.any():
            continue
        if best is None or stats[k, 4] > best[0]:
            best = (stats[k, 4], piece, inside)
    if best is None:
        return None
    _, piece, inside = best
    ys, xs = np.nonzero(piece & ~region)
    entry = np.array([xs.mean(), ys.mean()]) if len(xs) else np.array([region.shape[1] / 2, float(region.shape[0])])
    ys, xs = np.nonzero(inside)
    far = int(np.argmax((xs - entry[0]) ** 2 + (ys - entry[1]) ** 2))
    return np.array([xs[far], ys[far]], dtype=np.float64)


class ToolDetector:
    """La herramienta con modelos (más preciso, ~0,5 s por fotograma en MPS): Grounding DINO la
    busca por texto cada `every` fotogramas (o cuando se pierde) y SAM 2 recorta su máscara exacta
    en cada fotograma con la caja anterior agrandada. La punta es el extremo del eje largo de la
    máscara más cercano a la cara."""

    def __init__(self, query: str = "a paintbrush. a makeup brush. a pencil.", every: int = 6, threshold: float = 0.3) -> None:
        import torch
        from transformers import Sam2Model, Sam2Processor

        from vfxglow.analysis.gdino import GroundingDino, torch_device, trust_certifi

        trust_certifi()
        self.torch = torch
        self.device = torch_device()
        self.dino = GroundingDino("IDEA-Research/grounding-dino-base", query, threshold)
        self.processor = Sam2Processor.from_pretrained("facebook/sam2.1-hiera-tiny")
        self.model = Sam2Model.from_pretrained("facebook/sam2.1-hiera-tiny").to(self.device)
        self.every = every
        self.box: tuple[float, float, float, float] | None = None
        self.count = 0

    def tip(self, frame_bgr: np.ndarray, face_center: np.ndarray) -> np.ndarray | None:
        """Punta en píxeles del fotograma, o None."""
        from PIL import Image

        h, w = frame_bgr.shape[:2]
        if self.box is None or self.count % self.every == 0:
            found = self.dino.detect(frame_bgr)
            self.box = found[0][0] if found else None
        self.count += 1
        if self.box is None:
            return None
        image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        inputs = self.processor(images=image, input_boxes=[[list(self.box)]], return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            out = self.model(**inputs, multimask_output=False)
        mask = self.processor.post_process_masks(out.pred_masks.cpu(), inputs["original_sizes"])[0][0, 0].numpy() > 0
        ys, xs = np.nonzero(mask)
        if len(xs) < 30:
            self.box = None
            return None
        # La caja del fotograma siguiente: la de la máscara, agrandada (la herramienta se mueve).
        pad_x, pad_y = (xs.max() - xs.min()) * 0.25 + 10, (ys.max() - ys.min()) * 0.25 + 10
        self.box = (max(xs.min() - pad_x, 0), max(ys.min() - pad_y, 0), min(xs.max() + pad_x, w - 1), min(ys.max() + pad_y, h - 1))
        pts = np.stack([xs, ys], axis=1).astype(np.float64)
        mean = pts.mean(axis=0)
        _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
        proj = (pts - mean) @ vt[0]
        ends = (pts[int(np.argmin(proj))], pts[int(np.argmax(proj))])
        return min(ends, key=lambda e: float(np.linalg.norm(e - face_center)))
