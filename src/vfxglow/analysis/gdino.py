"""Grounding DINO (Hugging Face): cajas de objetos descritos con texto, sin entrenar.

La consulta es una frase en inglés terminada en punto ("a baseball cap."); varias clases van
separadas por puntos. En MPS tarda ~1,6 s por fotograma con el modelo base.
"""

from __future__ import annotations

import os

import cv2
import numpy as np


def torch_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    return "mps" if torch.backends.mps.is_available() else "cpu"


def trust_certifi() -> None:
    """El Python de python.org no trae la cadena raíz: la descarga de pesos de HF falla sin esto."""
    import certifi

    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())


class GroundingDino:
    def __init__(self, model_id: str, prompt: str, threshold: float) -> None:
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        trust_certifi()
        self.device = torch_device()
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(self.device)
        self.prompt = prompt
        self.threshold = threshold

    def detect(self, frame_bgr: np.ndarray) -> list[tuple[tuple[float, float, float, float], float]]:
        """(caja x0, y0, x1, y1 en píxeles, confianza), de más a menos confiable."""
        import torch
        from PIL import Image

        image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        inputs = self.processor(images=image, text=self.prompt, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=self.threshold, text_threshold=self.threshold, target_sizes=[image.size[::-1]]
        )[0]
        found = [(tuple(map(float, box)), float(score)) for box, score in zip(result["boxes"].cpu().numpy(), result["scores"].cpu().numpy())]
        return sorted(found, key=lambda item: -item[1])

    def __call__(self, frame_bgr: np.ndarray) -> list[tuple[float, float, float, float]]:
        return [box for box, _ in self.detect(frame_bgr)]
