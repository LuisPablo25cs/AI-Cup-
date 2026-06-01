import asyncio
import os
from uuid import UUID

from ultralytics import YOLO

from src.services.s3 import BUCKET_NAME, download_file

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
        return _MODEL_CACHE[vision_model_id]

    local_path = f"/tmp/{vision_model_id}/best.pt"

    # Download is blocking I/O → offload to thread
    await asyncio.to_thread(download_file, BUCKET_NAME, key_s3_weights, local_path)

    # YOLO constructor is also blocking → offload to thread
    # Note: device is passed to predict(), not to the constructor (ultralytics API)
    model = await asyncio.to_thread(
        YOLO, local_path, task="segment",
    )

    _MODEL_CACHE[vision_model_id] = model
    return model
