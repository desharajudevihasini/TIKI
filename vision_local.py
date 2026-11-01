"""Optional local YOLO object tags; never required for Gemini Vision.

Install optional ultralytics separately and enable TIKI_YOLO_ENABLED=1.
YOLO generic object detection does NOT classify dog breeds. Gemini vision
handles the breed estimate and must be honest when uncertain.
"""
from __future__ import annotations
import io
import os
import threading

_LOCK=threading.Lock()
_MODEL=None


def object_labels(jpeg: bytes) -> list[str]:
    global _MODEL
    if os.getenv('TIKI_YOLO_ENABLED','0') != '1':
        return []
    try:
        from ultralytics import YOLO
        from PIL import Image
        with _LOCK:
            if _MODEL is None:
                # Ultralytics downloads a pretrained model on the first run.
                # This optional path must never block a basic demo on startup.
                _MODEL=YOLO(os.getenv('TIKI_YOLO_MODEL','yolo11n.pt'))
            results = _MODEL.predict(source=Image.open(io.BytesIO(jpeg)),
                                     verbose=False, imgsz=640, conf=.30)
        labels=[]
        for result in results:
            names=result.names
            for box in result.boxes:
                cid=int(box.cls[0])
                name=str(names.get(cid,'object'))
                if name not in labels:
                    labels.append(name)
        return labels[:12]
    except Exception:
        # Supplemental recognition must never prevent a camera capture.
        return []
