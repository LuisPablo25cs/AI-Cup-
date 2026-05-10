import io
from time import perf_counter_ns
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from PIL import Image

from src.schemas.inspect import Detection, InspectionResponse
from src.services.inspection import evaluate
from src.services.model_registry import ModelLoadError, get_model, predict

router = APIRouter(prefix="/inspect", tags=["Inspection"])


@router.post("/{kit_id}", response_model=InspectionResponse)
async def inspect_kit(
    kit_id: str,
    request: Request,
    image: UploadFile = File(...),
    confidence: Annotated[
        float | None,
        Query(ge=0.0, le=1.0, description="Override per-kit confidence threshold"),
    ] = None,
) -> InspectionResponse:
    """Run YOLO-based part inspection for the specified kit.

    - REQ-01: Returns 200 with canonical response shape on success.
    - REQ-02: Returns 404 if kit_id is not in config.
    - REQ-03: Returns 422 if image cannot be decoded.
    - REQ-04: Returns 503 if model file is missing or corrupt.
    - REQ-05/06: Effective confidence = query param > kit config default.
    - REQ-11: Bbox coordinates are normalized to [0, 1] by image dimensions.
    - REQ-15: inference_ms measured only around the predict call.
    """
    # Step 1: Config lookup (REQ-02)
    kits_config = request.app.state.kits_config
    kit_cfg = kits_config.root.get(kit_id)
    if kit_cfg is None:
        raise HTTPException(
            status_code=404,
            detail=f"Kit '{kit_id}' is not defined in models_config.json",
        )

    # Step 2: Decode image (REQ-03)
    try:
        image_bytes = await image.read()
        pil_image = Image.open(io.BytesIO(image_bytes))
        pil_image.verify()  # Raises if not a valid image
        # Re-open after verify (verify() closes the file object internally)
        pil_image = Image.open(io.BytesIO(image_bytes))
    except Exception:
        raise HTTPException(
            status_code=422,
            detail="The uploaded file is not a decodable image.",
        )

    # Step 3: Resolve effective confidence (REQ-05, REQ-06)
    effective_conf: float = (
        confidence if confidence is not None else kit_cfg.confidence_threshold
    )

    # Step 4: Load (or retrieve cached) model (REQ-04, REQ-12, REQ-13)
    try:
        model = await get_model(kit_id, kit_cfg)
    except ModelLoadError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        )

    # Step 5: Run inference — ONLY this block is timed (REQ-15)
    t0 = perf_counter_ns()
    results = await predict(model, pil_image, effective_conf)
    inference_ms: int = (perf_counter_ns() - t0) // 1_000_000

    # Step 6: Convert YOLO results to Detection objects with normalized bboxes (REQ-11)
    img_w: int = pil_image.width
    img_h: int = pil_image.height
    detections: list[Detection] = []

    if results:
        result_obj = results[0]
        if result_obj.boxes is not None:
            for box in result_obj.boxes:
                conf_val: float = float(box.conf[0])
                cls_idx: int = int(box.cls[0])
                class_label: str = model.names.get(cls_idx, str(cls_idx))

                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                bbox_norm = [
                    x1 / img_w,
                    y1 / img_h,
                    x2 / img_w,
                    y2 / img_h,
                ]

                detections.append(
                    Detection(
                        class_label=class_label,
                        confidence=conf_val,
                        bbox_xyxy_norm=bbox_norm,
                    )
                )

    # Step 7: Evaluate pass/fail (REQ-07 – REQ-10)
    inspection_result = evaluate(detections, kit_cfg.expected)

    # Step 8: Build response (REQ-01, REQ-15)
    return InspectionResponse(
        kit_id=kit_id,
        result=inspection_result.result,
        detections=detections,
        counts=inspection_result.counts,
        expected=dict(kit_cfg.expected),
        missing=inspection_result.missing,
        extra=inspection_result.extra,
        model_version=kit_cfg.model_version,
        inference_ms=inference_ms,
    )
