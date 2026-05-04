"""OmniParser v2 wrapper.

Provides icon detection (YOLOv8) and optional caption (Florence-2) over a
screenshot, returning normalized bounding boxes that can be merged into the
TuriX UI tree as synthetic interactive nodes.

Install:
    pip install ultralytics transformers torch
    huggingface-cli download microsoft/OmniParser-v2.0 --local-dir weights/

The detector weights live at weights/icon_detect/best.pt; caption weights at
weights/icon_caption_florence (optional). If caption_model_path is None the
parser only returns boxes with the generic label "icon" — the brain VLM is
expected to identify them visually.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PIL import Image

logger = logging.getLogger(__name__)


class OmniParser:
    def __init__(
        self,
        yolo_path: str,
        caption_model_path: Optional[str] = None,
        device: Optional[str] = None,
        conf: float = 0.25,
    ):
        try:
            import torch  # noqa: F401
            from ultralytics import YOLO
        except ImportError as e:
            raise ImportError(
                "OmniParser requires `ultralytics` and `torch`. "
                "Install via: pip install ultralytics torch"
            ) from e

        import torch as _torch

        if device is None:
            if _torch.backends.mps.is_available():
                device = "mps"
            elif _torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        self.device = device
        self.conf = conf
        self._torch = _torch

        logger.info("Loading OmniParser YOLO from %s on %s", yolo_path, device)
        self.yolo = YOLO(yolo_path)

        self.processor = None
        self.captioner = None
        if caption_model_path:
            try:
                from transformers import AutoModelForCausalLM, AutoProcessor

                logger.info("Loading caption model from %s", caption_model_path)
                self.processor = AutoProcessor.from_pretrained(
                    caption_model_path, trust_remote_code=True
                )
                dtype = _torch.float16 if device != "cpu" else _torch.float32
                self.captioner = AutoModelForCausalLM.from_pretrained(
                    caption_model_path,
                    trust_remote_code=True,
                    torch_dtype=dtype,
                ).to(device)
                self.captioner.eval()
            except Exception:
                logger.exception(
                    "Failed to load caption model; running detection-only."
                )
                self.processor = None
                self.captioner = None

    def parse(
        self,
        image: Image.Image,
        conf: Optional[float] = None,
    ) -> List[dict]:
        """Detect interactive elements on the screenshot.

        Returns a list of dicts: {bbox: (x1,y1,x2,y2) normalized to [0,1],
        label: str, confidence: float}.
        """
        if image is None:
            return []
        W, H = image.size
        if W == 0 or H == 0:
            return []

        threshold = conf if conf is not None else self.conf
        try:
            results = self.yolo.predict(
                image,
                conf=threshold,
                verbose=False,
                device=self.device,
            )
        except Exception:
            logger.exception("OmniParser YOLO inference failed")
            return []

        if not results:
            return []

        boxes_attr = getattr(results[0], "boxes", None)
        if boxes_attr is None:
            return []

        try:
            xyxy = boxes_attr.xyxy.cpu().numpy()
            confs = boxes_attr.conf.cpu().numpy() if boxes_attr.conf is not None else None
        except Exception:
            logger.exception("OmniParser failed to extract boxes")
            return []

        out: List[dict] = []
        for i, raw in enumerate(xyxy):
            x1, y1, x2, y2 = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
            if x2 <= x1 or y2 <= y1:
                continue
            label = "icon"
            if self.captioner is not None:
                try:
                    crop = image.crop((x1, y1, x2, y2))
                    label = self._caption(crop) or "icon"
                except Exception:
                    logger.debug("Caption generation failed", exc_info=True)
                    label = "icon"
            out.append(
                {
                    "bbox": (x1 / W, y1 / H, x2 / W, y2 / H),
                    "label": label,
                    "confidence": float(confs[i]) if confs is not None else None,
                }
            )
        return out

    def _caption(self, crop: Image.Image) -> str:
        prompt = "<CAPTION>"
        inputs = self.processor(text=prompt, images=crop, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        with self._torch.no_grad():
            generated = self.captioner.generate(
                **inputs,
                max_new_tokens=32,
                num_beams=1,
                do_sample=False,
            )
        text = self.processor.batch_decode(generated, skip_special_tokens=True)[0]
        return text.strip()
