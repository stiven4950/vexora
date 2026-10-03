"""Flujo óptico. Farneback en CPU; RAFT pequeño solo si hay CUDA y torchvision."""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.analysis.schema import FlowStats


def resize_flow(flow: np.ndarray, width: int, height: int) -> np.ndarray:
    src_h, src_w = flow.shape[:2]
    if src_w == width and src_h == height:
        return flow.astype(np.float32)
    resized = cv2.resize(flow, (width, height), interpolation=cv2.INTER_LINEAR)
    resized = resized.astype(np.float32)
    resized[..., 0] *= width / max(src_w, 1)
    resized[..., 1] *= height / max(src_h, 1)
    return resized


def flow_stats(flow: np.ndarray) -> FlowStats:
    mag = np.linalg.norm(flow, axis=-1)
    return FlowStats(
        mean_dx=float(flow[..., 0].mean()),
        mean_dy=float(flow[..., 1].mean()),
        magnitude=float(mag.mean()),
    )


def farneback(prev_bgr: np.ndarray, curr_bgr: np.ndarray) -> np.ndarray:
    prev = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
    curr = cv2.cvtColor(curr_bgr, cv2.COLOR_BGR2GRAY)
    small_prev = cv2.resize(prev, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    small_curr = cv2.resize(curr, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    flow = cv2.calcOpticalFlowFarneback(small_prev, small_curr, None, 0.5, 3, 15, 3, 5, 1.2, 0)
    flow = flow.astype(np.float32) * 2.0
    return resize_flow(flow, prev.shape[1], prev.shape[0])


class FlowEstimator:
    def __init__(self, method: str, device: str) -> None:
        self.method = resolve_flow_method(method, device)
        self.device = device
        self._raft = None
        self._transforms = None

    def between(self, prev_bgr: np.ndarray, curr_bgr: np.ndarray) -> np.ndarray:
        if self.method == "raft":
            return self._raft_flow(prev_bgr, curr_bgr)
        return farneback(prev_bgr, curr_bgr)

    def _raft_flow(self, prev_bgr: np.ndarray, curr_bgr: np.ndarray) -> np.ndarray:
        if self._raft is None:
            self._load_raft()
        import torch

        def to_tensor(bgr: np.ndarray) -> "torch.Tensor":
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            return torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)

        assert self._transforms is not None and self._raft is not None
        img1, img2 = self._transforms(to_tensor(prev_bgr), to_tensor(curr_bgr))
        with torch.inference_mode():
            flows = self._raft(img1.to(self.device), img2.to(self.device))
        flow = flows[-1][0].permute(1, 2, 0).detach().cpu().numpy()
        return resize_flow(flow, prev_bgr.shape[1], prev_bgr.shape[0])

    def _load_raft(self) -> None:
        try:
            import torch
            from torchvision.models.optical_flow import Raft_Small_Weights, raft_small
        except ImportError as exc:
            raise RuntimeError(
                "RAFT necesita torch y torchvision. Usa method: farneback si no están instalados."
            ) from exc
        weights = Raft_Small_Weights.DEFAULT
        self._transforms = weights.transforms()
        self._raft = raft_small(weights=weights).to(self.device).eval()


def resolve_flow_method(method: str, device: str) -> str:
    if method == "farneback":
        return "farneback"
    if method == "raft":
        if device != "cuda":
            raise RuntimeError("RAFT en este pipeline exige CUDA. Usa farneback en CPU o MPS.")
        return "raft"
    if device == "cuda":
        try:
            import torch  # noqa: F401
            import torchvision  # noqa: F401
        except ImportError:
            return "farneback"
        return "raft"
    return "farneback"
