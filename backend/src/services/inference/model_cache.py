import asyncio
import logging
import os
from uuid import UUID

from ultralytics import YOLO

from src.services.s3 import BUCKET_NAME, download_file

logger = logging.getLogger("backend.inference.model_cache")

_MODEL_CACHE: dict[UUID, YOLO] = {}
_YOLO_DEVICE = os.getenv("YOLO_DEVICE", "cpu")


async def get_or_load_model(vision_model_id: UUID, key_s3_weights: str) -> YOLO:
    """Return a cached YOLO instance for *vision_model_id*.

    On a cache miss the weights are downloaded from S3 (blocking I/O, run in
    thread via ``asyncio.to_thread``), the model is loaded, and the result is
    stored in the module-level ``_MODEL_CACHE``.

    Parameters
    ----------
    vision_model_id : UUID
        The unique identifier of the vision model.
    key_s3_weights : str
        S3 key pointing to the ``best.pt`` weights file.

    Returns
    -------
    YOLO
        The cached or newly-loaded YOLO instance.
    """
    if vision_model_id in _MODEL_CACHE:
        model = _MODEL_CACHE[vision_model_id]
        logger.info(
            "[MODEL CACHE HIT] model_id=%s | s3_key=%s | local_path=/tmp/%s/best.pt | "
            "task=%s | nc=%s | names=%s",
            vision_model_id,
            key_s3_weights,
            vision_model_id,
            getattr(model, 'task', 'unknown'),
            getattr(model.model, 'nc', 'unknown') if hasattr(model, 'model') else 'unknown',
            list(model.names.values()) if hasattr(model, 'names') else 'unknown',
        )
        return model

    local_path = f"/tmp/{vision_model_id}/best.pt"

    logger.info(
        "[MODEL CACHE MISS] model_id=%s | s3_key=%s | local_path=%s | downloading from S3...",
        vision_model_id,
        key_s3_weights,
        local_path,
    )

    # Download is blocking I/O → offload to thread
    await asyncio.to_thread(download_file, BUCKET_NAME, key_s3_weights, local_path)
    logger.info("[MODEL DOWNLOAD OK] model_id=%s | local_path=%s", vision_model_id, local_path)

    # YOLO constructor is also blocking → offload to thread
    # Note: device is passed to predict(), not to the constructor (ultralytics API)
    model = await asyncio.to_thread(
        YOLO, local_path, task="segment",
    )

    logger.info(
        "[MODEL LOADED] model_id=%s | s3_key=%s | local_path=%s | "
        "task=%s | nc=%s | names=%s",
        vision_model_id,
        key_s3_weights,
        local_path,
        getattr(model, 'task', 'unknown'),
        getattr(model.model, 'nc', 'unknown') if hasattr(model, 'model') else 'unknown',
        list(model.names.values()) if hasattr(model, 'names') else 'unknown',
    )

    _MODEL_CACHE[vision_model_id] = model
    return model
