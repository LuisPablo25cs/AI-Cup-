# Exploration: POST /api/inspections with Real YOLO Inference

## Current State

### What Exists

| Layer | What's there | What's missing |
|-------|-------------|----------------|
| **Models** | `Inspeccion`, `Deteccion`, `VisionModel`, `ModelPiezaLink`, `Kit`, `KitPiezaLink` — all fully implemented with correct FK chains | Nothing — schema is complete |
| **Routes** | `inspeccionRouter.py` has GET /stats, GET /, GET /{id}, GET /{id}/result, POST /{id}/confirm | **NO `POST /`** — the creation endpoint doesn't exist |
| **Vision endpoint** | `visionModelRouter.py` has `POST /find-objects` — a template with commented-out YOLO inference | Real inference is dead code: `# res = inferir(PATH_MODELO, image)` |
| **S3 service** | `upload_imagen()`, `upload_label()`, `upload_model()`, `get_object_read_url()`, `delete_object()` | **No `download_file()`** — can only upload and generate presigned URLs |
| **Trainer** | Full YOLO training pipeline (`modelWorker.py`, `model_factory.py`) with `YOLO(base_model).train(...)` | **No `model.predict()`** anywhere — only training code |
| **Dependencies** | `ultralytics`, `opencv-python-headless`, `pillow`, `boto3` already in `backend/requirements.txt` | No new packages needed |
| **Detection strategy** | Design doc defines `DetectionStrategy` Protocol with `ClaudeVisionStrategy` | `LocalCVStrategy` is architected but **not implemented** |

### The Full Data Chain Already Exists

```
Kit.vision_model_id ──→ VisionModel.key_s3_weights  (path to best.pt in S3)
                            │
                            ▼
              ModelPiezaLink (vision_model_id, pieza_id, class_index)
                            │
                            ▼
                       Pieza.id_pieza, nombre
```

The `ModelPiezaLink.class_index` field is the **critical piece** — it maps YOLO class output numbers (0, 1, 2…) to specific `pieza_id` values. This mapping is created during model generation (see `visionModelRouter.py:generateModel` lines 88–90) and used by the trainer to remap datasets.

### What the Frontend Sends

`ai-kitting-frontend/src/api/inspections.ts` line 92–101:
```typescript
const form = new FormData()
form.append('kit_id', kitId)
form.append('image', image)        // File object (JPEG/PNG)
if (operador?.trim()) form.append('operador', operador.trim())
const inspection = await apiClient.postFormData<BackendInspeccion>('/inspections', form)
```

Expected response shape: `BackendInspeccion` with `id`, `kit_id`, `kit_nombre`, `fecha`, `resultado_general`, `similitud`, `tiempo_procesamiento`, `operador`, `detecciones[]`.

---

## Affected Areas

- **`AI-Cup-/backend/src/routes/inspeccionRouter.py`** — add `POST /` handler receiving multipart `kit_id`, `image`, `operador?`. ~80 LoC addition.
- **`AI-Cup-/backend/src/services/detection/local.py`** (NEW) — `LocalCVStrategy` implementing `DetectionStrategy` Protocol with YOLO inference, model downloading from S3, class-index-to-pieza mapping. ~180 LoC.
- **`AI-Cup-/backend/src/services/detection/factory.py`** — add `"local"` to `_VALID` set and `elif name == "local"` branch. ~5 LoC.
- **`AI-Cup-/backend/src/services/s3.py`** — add `download_file(bucket, key, local_path)` function (the trainer already has this pattern in `trainer/src/db/s3_client.py`). ~25 LoC.
- **`AI-Cup-/backend/src/services/inference/model_cache.py`** (NEW) — module-level LRU-ish cache of loaded YOLO models keyed by `vision_model_id`. ~50 LoC.
- **`AI-Cup-/backend/src/routes/visionModelRouter.py`** — no changes needed. The template `/find-objects` is separate.
- **`AI-Cup-/docker-compose.yml`** — optionally add GPU device to `backend_server` service (for GPU inference speed).
- **`AI-Cup-/backend/Dockerfile`** — already has `libgl1` for OpenCV. CUDA support would need NVIDIA base image if GPU inference is required.

---

## Approaches

### 1. Synchronous YOLO in `run_in_executor` (RECOMMENDED)

Run YOLO inference in a thread pool to avoid blocking the async event loop.

```python
@router.post("/", response_model=InspeccionRead)
async def submit_inspection(
    kit_id: UUID = Form(...),
    image: UploadFile = File(...),
    operador: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    # 1. Load kit + vision model + pieza mappings
    # 2. Upload image to S3 (optional, for audit trail)
    # 3. Download model weights from S3 if not cached
    # 4. Run YOLO predict in thread pool executor
    # 5. Map class indices → piezas → Deteccion rows
    # 6. Compute similitud + resultado_general
    # 7. Save Inspeccion + Detecciones → return
```

- **Pros**: Non-blocking FastAPI, follows existing async patterns, model can be cached in memory
- **Cons**: Still blocks one thread per request (acceptable for MVP volume)
- **Effort**: Medium (~300 LoC total across 4 files)

### 2. Fully Async with Background Task Queue

Submit inspection to RabbitMQ queue, return `202 Accepted` with a polling URL or WebSocket for results.

- **Pros**: Truly non-blocking, handles spikes, reuses existing RabbitMQ infrastructure
- **Cons**: Frontend needs polling/WebSocket logic (breaking change), much more complex, over-engineered for MVP
- **Effort**: High (~600+ LoC, frontend changes)

### 3. CPU-Only Inference (GPU-Unavailable Fallback)

If GPU is not available in the backend container, YOLO runs on CPU via ultralytics (which supports CPU via `device='cpu'`).

- **Pros**: Works with current Docker setup (backend has no GPU reservation)
- **Cons**: ~5–10× slower per inference (1–3 seconds on CPU vs ~100–300ms on GPU for yolov8n-seg)
- **Effort**: Zero additional code — `YOLO(path, task='segment').predict(image, device='cpu')` just works.

**Actually, the ultralytics model auto-detects device. If no CUDA is available, it falls back to CPU automatically.** No explicit `device` parameter needed in most cases, though we should make it configurable via env var.

---

## Recommendation

**Approach 1 (sync YOLO in `run_in_executor`) with model caching and CPU-first.**

This is the simplest path that:
1. Fits the existing `DetectionStrategy` Protocol from the design doc
2. Reuses the existing `ModelPiezaLink` class->pieza mapping
3. Requires zero frontend changes
4. Can be swapped to GPU later with one env var change

### Key Technical Decisions

#### Decision A: Model Loading — Cache, Don't Load Per-Request

```python
# model_cache.py
_MODEL_CACHE: dict[str, YOLO] = {}  # keyed by vision_model_id

def get_model(vision_model_id: str, s3_key: str) -> YOLO:
    if vision_model_id in _MODEL_CACHE:
        return _MODEL_CACHE[vision_model_id]
    
    # Download from S3 → /tmp/{vision_model_id}/best.pt
    local_path = download_from_s3(s3_key)
    model = YOLO(local_path, task='segment')
    _MODEL_CACHE[vision_model_id] = model
    return model
```

Loading a YOLO model from disk takes 1–2 seconds. Cache eliminates this on subsequent requests. Thread-safe since YOLO models are read-only during inference.

#### Decision B: YOLO Class → Pieza Mapping

Query `ModelPiezaLink` rows for the kit's `vision_model_id` to build a `dict[int, UUID]` (class_index → pieza_id). This must be joined against `KitPiezaLink` rows to determine the **expected** pieces per kit — pieces in the kit but not in the model mapping (or vice versa) need handling.

```python
# Build from DB:
# {class_index: {pieza_id, pieza_nombre}}
class_to_pieza = {
    link.class_index: {"id": link.id_pieza, "nombre": pieza_nombre}
    for link, pieza_nombre in model_pieza_results
}

# Kit's expected pieces:
expected_piece_ids = {item.pieza_id for item in kit.items}
```

#### Decision C: similitud Formula

For YOLO, a reasonable formula:

```python
def compute_similitud(detections: list[DeteccionResult], total_expected: int) -> float:
    """Ratio of found pieces × average confidence."""
    if total_expected == 0:
        return 1.0
    found = sum(1 for d in detections if d.encontrado)
    avg_conf = sum(d.confianza for d in detections if d.encontrado) / max(found, 1)
    return round((found / total_expected) * avg_conf, 4)
```

#### Decision D: resultado_general Thresholds

Per design doc §2.2:
- `similitud >= 0.80` → `"correcto"`
- `similitud >= 0.55` → `"anomalia"`
- Otherwise → `"error"`

#### Decision E: Faltante Handling

Pieces expected in the kit but NOT detected by YOLO must be included as `Deteccion` rows with `encontrado=False`, `estado="faltante"`, and zero/default position values.

#### Decision F: Image Upload to S3

Upload the raw image to S3 for audit trail: `inspections/{inspeccion_id}/original.jpg`. Store the key in `Inspeccion.imagen_s3_key`.

---

## Risks

1. **Cold-start latency**: First request after server restart downloads model weights from S3 (could be 50–200MB depending on model) AND loads YOLO into memory. Expect 5–15 seconds for first request. Mitigation: pre-load model in `lifespan()`.

2. **No GPU in backend Docker**: The `backend_server` service in `docker-compose.yml` has no GPU device reservation. YOLO will run on CPU. For a ~10-piece kit with `yolov8n-seg`, CPU inference is ~1–3 seconds. Acceptable for MVP. Add GPU later with `deploy.resources.reservations.devices`.

3. **Model version mismatch**: If the vision model's `estado` is not `"COMPLETED"`, `key_s3_weights` will be NULL. The endpoint MUST check this and return a clear error (e.g., 409 Conflict: "Vision model is not ready").

4. **YOLO classes vs kit pieces mismatch**: A kit might have pieces not mapped in the model's `ModelPiezaLink` (e.g., a piece was added to the kit after training). These pieces should be reported as `faltante` with `confianza=0.0`.

5. **Thread safety of YOLO model**: Ultralytics `YOLO.predict()` is not async-safe but is thread-safe for inference (read-only). The model cache is safe as long as we only run `predict()`, never `train()` on the cached instances.

6. **Memory footprint**: Each loaded YOLO model is ~6–12MB for `yolov8n-seg`. With only one active vision model per kit, this is negligible. If multiple kits use different models, cache grows linearly — add LRU eviction if needed later.

---

## Estimated Scope

| Artifact | Action | LoC |
|----------|--------|-----|
| `src/services/detection/local.py` | **NEW** — YOLO strategy with S3 download, inference, class mapping | ~180 |
| `src/services/inference/model_cache.py` | **NEW** — Module-level model cache | ~50 |
| `src/routes/inspeccionRouter.py` | **MODIFY** — Add `POST /` handler | ~80 |
| `src/services/s3.py` | **MODIFY** — Add `download_file()` function | ~25 |
| `src/services/detection/factory.py` | **MODIFY** — Register `"local"` strategy | ~5 |
| **Total** | | **~340 LoC** |

All within the 400-line slice budget established by the design doc.

### Implementation Order (within single change)

1. Add `download_file()` to `s3.py` (unblocked, standalone)
2. Create `model_cache.py` (depends on `s3.download_file`)
3. Create `local.py` implementing `DetectionStrategy` (depends on cache + s3)
4. Register in `factory.py` (depends on local.py)
5. Add `POST /` handler to `inspeccionRouter.py` (depends on factory)

---

## Ready for Proposal

**Yes.** All technical unknowns are resolved:
- The mapping chain (Kit → VisionModel → ModelPiezaLink → Pieza) is complete
- Dependencies are already installed
- The `DetectionStrategy` Protocol already defines the interface
- The frontend contract is unambiguous (FormData with 3 fields)
- CPU inference works out of the box with ultralytics

The next step is `sdd-propose` with:
- Change name: `yolo-inference-endpoint`
- Scope: 4 new files + 2 modified
- Risk flag: GPU dependency optional (env-var-driven `YOLO_DEVICE`); server-level model preloading recommended for cold-start
