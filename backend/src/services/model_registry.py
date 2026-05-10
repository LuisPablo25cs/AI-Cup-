import asyncio
from typing import Any

from src.services.kit_config import KitConfig

# Lazy import — ultralytics is heavy; only imported when a model is first needed.
try:
    from ultralytics import YOLO
except ImportError:  # pragma: no cover — optional at import time in tests
    YOLO = None  # type: ignore[assignment,misc]

# Module-level singleton state.
# Locks are created lazily inside the running event loop to avoid binding to
# the wrong loop (or no loop at all) when this module is imported before
# uvicorn starts the event loop. See Python 3.10+ asyncio guidance.
_models: dict[str, Any] = {}
_locks: dict[str, asyncio.Lock] = {}
_registry_lock: asyncio.Lock | None = None


def _get_registry_lock() -> asyncio.Lock:
    """Return the registry lock, creating it lazily inside the running loop.

    Safe to call from a single coroutine at a time without external sync:
    `asyncio.Lock()` construction is synchronous and CPython's GIL guarantees
    that the module-global assignment is atomic. Two coroutines on the same
    event loop cannot execute this function concurrently because there is no
    `await` between the read and the assignment.
    """
    global _registry_lock
    if _registry_lock is None:
        _registry_lock = asyncio.Lock()
    return _registry_lock


class ModelLoadError(Exception):
    """Raised when a YOLO model cannot be loaded from disk."""

    def __init__(self, kit_id: str, model_path: str) -> None:
        super().__init__(
            f"Cannot load model for kit '{kit_id}' from '{model_path}'. "
            "Check that the .pt file exists and is not corrupted."
        )
        self.kit_id = kit_id
        self.model_path = model_path


async def get_model(kit_id: str, kit_cfg: KitConfig) -> Any:
    """Return the cached YOLO model for *kit_id*, loading it on first access.

    Uses double-checked locking:
    - Fast path: `_models[kit_id]` already present → return immediately.
    - Slow path: acquire `_registry_lock` briefly to get/create a per-kit lock,
      then acquire the per-kit lock and re-check the cache before loading.

    This ensures the model file is read exactly once even under N concurrent
    first requests for the same kit (REQ-13).

    Raises:
        ModelLoadError: If the model file is missing or the YOLO constructor fails.
    """
    # Fast path — no locking needed for reads after first population
    if kit_id in _models:
        return _models[kit_id]

    # Slow path: get or create per-kit lock (guards lock-map mutation only)
    async with _get_registry_lock():
        if kit_id not in _locks:
            _locks[kit_id] = asyncio.Lock()
        kit_lock = _locks[kit_id]

    # Per-kit lock: only the first coroutine for this kit actually loads
    async with kit_lock:
        # Double-check: another coroutine may have loaded while we waited
        if kit_id in _models:
            return _models[kit_id]

        loop = asyncio.get_running_loop()
        try:
            model = await loop.run_in_executor(None, YOLO, kit_cfg.model_path)
        except Exception as exc:
            raise ModelLoadError(kit_id, kit_cfg.model_path) from exc

        _models[kit_id] = model
        return model


async def predict(model: Any, image: Any, conf: float) -> Any:
    """Run YOLO inference in a thread pool to avoid blocking the event loop.

    Args:
        model: A loaded YOLO instance.
        image: A PIL Image object.
        conf: Confidence threshold for this prediction.

    Returns:
        The raw YOLO results list.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: model.predict(image, conf=conf, verbose=False)
    )
