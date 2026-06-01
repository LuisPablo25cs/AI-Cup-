# Model Inference Cache Specification

## Purpose

Defines a module-level, lazy-loading YOLO model cache that downloads weights from S3 and provides thread-safe inference, keyed by `vision_model_id`.

## Requirements

### Requirement: Cache Registry

The system MUST maintain a module-level `dict[str, YOLO]` registry in `src/services/inference/model_cache.py`. The cache SHALL be empty at startup — no preloading.

#### Scenario: Cache starts empty

- GIVEN the application has started
- WHEN no inference requests have been made
- THEN the cache dict is empty (`len(_MODEL_CACHE) == 0`)

### Requirement: Lazy Load on First Request

On first request for a given `vision_model_id`, the system MUST download weights from S3, load the model, and store it in the cache.

#### Scenario: Cache miss — download and load

- GIVEN `vision_model_id = "abc-123"` with no cached entry
- WHEN `get_model(vision_model_id, s3_key)` is called
- THEN `download_file(s3_key, "/tmp/abc-123/best.pt")` is called; `YOLO(path, task='segment')` loads the model; the result is stored in `_MODEL_CACHE["abc-123"]`

#### Scenario: Cache hit — return immediately

- GIVEN `_MODEL_CACHE["abc-123"]` exists
- WHEN `get_model("abc-123")` is called again
- THEN the cached instance is returned; no S3 download or YOLO load occurs

### Requirement: S3 Model Download

The system SHALL add `download_file(bucket, key, destination_path)` to `src/services/s3.py` that downloads an object to a local file.

#### Scenario: Successful download

- GIVEN a valid S3 key and local path
- WHEN `download_file` is called
- THEN the file is saved to the local path; parent directories are created if missing

#### Scenario: Download failure

- GIVEN an invalid S3 key or network error
- WHEN `download_file` is called
- THEN a `ClientError` or `BotoCoreError` exception propagates; the caller handles it as 500

### Requirement: Thread-Safe Inference

The system MUST run `model.predict()` via `asyncio.get_running_loop().run_in_executor(None, model.predict, image)` to avoid blocking the async event loop.

#### Scenario: Inference in thread pool

- GIVEN a cached YOLO model and a preprocessed image array
- WHEN `run_inference(model, image_np)` is called from an async context
- THEN `model.predict` runs in a thread pool executor; the async handler does not block

### Requirement: Device Configuration

The system MAY read `YOLO_DEVICE` env var to override inference device. Default SHALL be `"cpu"`.

#### Scenario: GPU override

- GIVEN `YOLO_DEVICE="cuda:0"`
- WHEN YOLO is loaded
- THEN `YOLO(path, task='segment')` initializes on CUDA device 0

#### Scenario: Default CPU

- GIVEN `YOLO_DEVICE` is unset
- WHEN YOLO is loaded
- THEN inference runs on CPU
