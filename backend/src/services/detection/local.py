from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass, field
from uuid import UUID

from PIL import Image
from ultralytics import YOLO

from src.services.inference.model_cache import _YOLO_DEVICE

_YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF_THRESHOLD", "0.25"))


@dataclass
class DetectionResult:
    """A single detection output for one expected piece."""

    pieza_id: UUID | None
    pieza_nombre: str
    encontrado: bool
    confianza: float
    bbox: tuple[float, float, float, float] | None  # x_pct, y_pct, w_pct, h_pct


@dataclass
class InferenceResult:
    """Complete inference output including all detections and scores."""

    detections: list[DetectionResult] = field(default_factory=list)
    similitud: float = 0.0
    resultado_general: str = "error"  # correcto | anomalia | error
    tiempo_procesamiento: float = 0.0


def run_inference(
    image_bytes: bytes,
    model: YOLO,
    class_map: dict[int, tuple[UUID, str]],  # class_idx → (pieza_id, nombre)
    expected_pieces: list[tuple[UUID, str, int]],  # (pieza_id, nombre, cantidad_requerida)
    conf_threshold: float | None = None,
) -> InferenceResult:
    """Run YOLO prediction, map classes to expected pieces, and score the result.

    This is a **synchronous** function — callers MUST offload it via
    ``run_in_executor`` / ``asyncio.to_thread`` to avoid blocking the event loop.

    Parameters
    ----------
    image_bytes : bytes
        Raw image bytes (JPEG / PNG).
    model : YOLO
        Pre-loaded YOLO instance.
    class_map : dict[int, tuple[UUID, str]]
        Mapping from YOLO class index to ``(pieza_id, pieza_nombre)``.
    expected_pieces : list[tuple[UUID, str, int]]
        Pieces expected in the kit: ``(pieza_id, nombre, cantidad_requerida)``.
    conf_threshold : float | None
        Override for YOLO confidence threshold. Falls back to
        ``YOLO_CONF_THRESHOLD`` env var (default 0.25).

    Returns
    -------
    InferenceResult
        Detection list, similarity score, overall classification, and elapsed time.
    """
    t_start = time.perf_counter()

    threshold = conf_threshold if conf_threshold is not None else _YOLO_CONF_THRESHOLD

    # ------------------------------------------------------------------
    # 1. Load image & determine dimensions
    # ------------------------------------------------------------------
    pil_img = Image.open(io.BytesIO(image_bytes))
    img_w, img_h = pil_img.size

    # ------------------------------------------------------------------
    # 2. YOLO prediction
    # ------------------------------------------------------------------
    results = model.predict(pil_img, conf=threshold, device=_YOLO_DEVICE, verbose=False)

    yolo_dets: list[tuple[int, float, float, float, float, float]] = []
    # (class_idx, confidence, x1, y1, x2, y2)

    if results and results[0].boxes is not None:
        boxes = results[0].boxes
        for cls_tensor, conf_tensor, xyxy_tensor in zip(
            boxes.cls, boxes.conf, boxes.xyxy
        ):
            class_idx = int(cls_tensor.item())
            confidence = float(conf_tensor.item())
            x1, y1, x2, y2 = xyxy_tensor.tolist()
            yolo_dets.append((class_idx, confidence, x1, y1, x2, y2))

    # ------------------------------------------------------------------
    # 3. Aggregate detections per pieza (class index → pieza)
    # ------------------------------------------------------------------
    # Only count detections whose class_idx is in class_map
    per_pieza: dict[UUID, list[float]] = {}  # pieza_id → [confidences]
    per_pieza_best_conf: dict[UUID, float] = {}
    per_pieza_best_bbox: dict[UUID, tuple[float, float, float, float]] = {}

    for class_idx, conf, x1, y1, x2, y2 in yolo_dets:
        mapping = class_map.get(class_idx)
        if mapping is None:
            continue  # unknown class — ignore noise

        pieza_id, _ = mapping
        per_pieza.setdefault(pieza_id, []).append(conf)

        # Keep the highest-confidence bbox for this pieza
        if conf > per_pieza_best_conf.get(pieza_id, -1.0):
            per_pieza_best_conf[pieza_id] = conf
            per_pieza_best_bbox[pieza_id] = (
                round(x1 / img_w, 4),
                round(y1 / img_h, 4),
                round((x2 - x1) / img_w, 4),
                round((y2 - y1) / img_h, 4),
            )

    # ------------------------------------------------------------------
    # 4. Build DetectionResult list for expected pieces
    # ------------------------------------------------------------------
    detections: list[DetectionResult] = []
    found_count = 0
    found_confidences: list[float] = []

    for pieza_id, nombre, cantidad_requerida in expected_pieces:
        confs = per_pieza.get(pieza_id, [])
        detected_count = len(confs)

        encontrado = detected_count >= cantidad_requerida

        avg_conf = round(sum(confs) / detected_count * 100, 4) if confs else 0.0

        bbox = per_pieza_best_bbox.get(pieza_id)

        detections.append(
            DetectionResult(
                pieza_id=pieza_id,
                pieza_nombre=nombre,
                encontrado=encontrado,
                confianza=avg_conf,
                bbox=bbox,
            )
        )

        if encontrado:
            found_count += 1
            found_confidences.extend(confs)

    # ------------------------------------------------------------------
    # 5. Compute similitud & resultado_general
    # ------------------------------------------------------------------
    total_expected = len(expected_pieces) or 1  # avoid division by zero
    avg_confidence = (
        round(sum(found_confidences) / len(found_confidences), 4)
        if found_confidences
        else 0.0
    )
    # similitud as percentage (0-100) to align with frontend expectations
    similitud = round((found_count / total_expected) * avg_confidence * 100, 4)

    if similitud >= 80:
        resultado = "correcto"
    elif similitud >= 55:
        resultado = "anomalia"
    else:
        resultado = "error"

    t_end = time.perf_counter()
    tiempo = round(t_end - t_start, 4)

    return InferenceResult(
        detections=detections,
        similitud=similitud,
        resultado_general=resultado,
        tiempo_procesamiento=tiempo,
    )
