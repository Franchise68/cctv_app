import os
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np


class PersonDetector:
    """
    Lightweight OpenCV DNN-based person detector using an ONNX YOLO model.
    - Looks for an ONNX model at resources/models/yolov5n.onnx (or YOLOv8n if renamed).
    - If not present, detector remains disabled and detect() returns empty list.
    """

    def __init__(self, root_dir: Path):
        self.enabled = False
        self.net = None
        self.input_size = (640, 640)
        self.conf_thres = 0.35
        self.iou_thres = 0.45
        self.person_class_ids = {0, 1, 2, 5, 7}  # common YOLO COCO indices for person and vehicles; we will filter to person=0
        # Prefer person only
        self.person_only = True

        models_dir = root_dir / "resources" / "models"
        candidates = [
            models_dir / "yolov5n.onnx",
            models_dir / "yolov5s.onnx",
            models_dir / "yolov8n.onnx",
        ]
        for p in candidates:
            if p.exists():
                try:
                    self.net = cv2.dnn.readNetFromONNX(str(p))
                    self.enabled = True
                    break
                except Exception:
                    self.enabled = False

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int, float]]:
        if not self.enabled or self.net is None:
            return []
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(frame, 1/255.0, self.input_size, swapRB=True, crop=False)
        self.net.setInput(blob)
        preds = self.net.forward()
        # Post-process for YOLOv5/YOLOv8-like outputs: [N, 85] where 0:4=xywh, 4=obj, 5: classes
        dets = []
        if preds.ndim == 3:
            preds = np.squeeze(preds, axis=0)
        if preds.ndim == 2:
            for row in preds:
                obj = row[4]
                cls_scores = row[5:]
                cls_id = int(np.argmax(cls_scores))
                cls_conf = cls_scores[cls_id]
                score = obj * cls_conf
                if score < self.conf_thres:
                    continue
                if self.person_only and cls_id != 0:
                    continue
                cx, cy, bw, bh = row[0:4]
                x = int((cx - bw/2) / self.input_size[0] * w)
                y = int((cy - bh/2) / self.input_size[1] * h)
                x2 = int((cx + bw/2) / self.input_size[0] * w)
                y2 = int((cy + bh/2) / self.input_size[1] * h)
                x, y = max(0, x), max(0, y)
                x2, y2 = min(w-1, x2), min(h-1, y2)
                dets.append((x, y, x2, y2, float(score)))
        return dets
