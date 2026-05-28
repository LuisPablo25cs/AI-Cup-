# Models API

## Overview

Exposes vision model training jobs. The backend creates a `VisionModel` row on `POST /generateModel`, publishes the job to RabbitMQ, and a separate trainer worker picks it up, builds a YOLO dataset, trains, and updates the row through its lifecycle.

## State machine

| Estado | Meaning | Set by |
|---|---|---|
| `QUEUED` | Row created, job published to `trainer-queue`, waiting for worker pickup | Backend (`POST /generateModel`) |
| `PREPARING_DATA` | Worker has picked up the job and is downloading images / building the dataset | Trainer worker |
| `TRAINING` | Dataset is ready, YOLO training is running | Trainer worker |
| `COMPLETED` | Training finished, `best.pt` uploaded to S3, `key_s3_weights` populated | Trainer worker |
| `FAILED` | Pipeline threw an unhandled exception at any stage | Trainer worker |

Lifecycle: `QUEUED → PREPARING_DATA → TRAINING → COMPLETED | FAILED`

## Endpoints

### `POST /generateModel`

Creates a new model training job.

**Request body**

```json
{
  "nombre": "kit-lado-izquierdo-v2",
  "piezas": [
    "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "b2c3d4e5-f6a7-8901-bcde-f12345678901"
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `nombre` | `string` | Yes | Display name for the model |
| `piezas` | `string[]` (UUID) | Yes | Piece IDs to train on. Each maps to a YOLO class index (`0, 1, …, n`) in the order given. |

**Response** `200`

```json
{
  "model_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "nombre": "kit-lado-izquierdo-v2",
  "estado": "QUEUED",
  "message": "Training job queued successfully"
}
```

**Errors**

| Status | Condition |
|---|---|
| `400` | `nombre` is empty or `piezas` is an empty list |
| `404` | One or more `piezas` IDs don't exist in the `pieza` table |

**Side effects**

- Validates all piece IDs exist.
- Inserts one `VisionModel` row (estado = `QUEUED`).
- Inserts one `ModelPiezaLink` per piece with its `class_index`.
- Publishes a JSON message to the `trainer-queue` RabbitMQ queue.

---

### `GET /models`

Returns all models as a light list, newest first.

**Response** `200`

```json
[
  {
    "id_model": "c3d4e5f6-a7b8-9012-cdef-123456789012",
    "nombre": "kit-lado-izquierdo-v2",
    "estado": "COMPLETED",
    "created_at": "2026-05-28T14:30:00Z",
    "completed_at": "2026-05-28T14:45:12Z",
    "piezas_count": 2,
    "key_s3_weights": "models/c3d4e5f6-a7b8-9012-cdef-123456789012/best.pt"
  },
  {
    "id_model": "d4e5f6a7-b8c9-0123-defa-234567890123",
    "nombre": "kit-lado-derecho",
    "estado": "TRAINING",
    "created_at": "2026-05-28T14:00:00Z",
    "completed_at": null,
    "piezas_count": 3,
    "key_s3_weights": null
  }
]
```

`piezas_count` is the number of linked pieces (via `ModelPiezaLink`). Models are ordered by `created_at DESC` with `NULL`s last.

---

### `GET /models/{model_id}`

Full detail for a single model, including its piece assignments.

**Response** `200`

```json
{
  "id_model": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "nombre": "kit-lado-izquierdo-v2",
  "estado": "COMPLETED",
  "created_at": "2026-05-28T14:30:00Z",
  "completed_at": "2026-05-28T14:45:12Z",
  "piezas_count": 2,
  "key_s3_weights": "models/c3d4e5f6-a7b8-9012-cdef-123456789012/best.pt",
  "piezas": [
    {
      "id_pieza": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "nombre": "tornillo-m8",
      "class_index": 0
    },
    {
      "id_pieza": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "nombre": "arandela-plana",
      "class_index": 1
    }
  ]
}
```

The `piezas` array is ordered by `class_index ASC`. `nombre` comes from the `pieza` table via a left join — it will be `null` if the piece row was deleted after training.

**Errors**

| Status | Condition |
|---|---|
| `404` | No model with the given `model_id` exists |

## Data model

### `VisionModelListEntry` (used by `GET /models`)

| Field | Type | Source column |
|---|---|---|
| `id_model` | `UUID` | `vision_model.id_model` |
| `nombre` | `string` | `vision_model.nombre` |
| `estado` | `string` | `vision_model.estado` |
| `created_at` | `datetime \| null` | `vision_model.created_at` |
| `completed_at` | `datetime \| null` | `vision_model.completed_at` |
| `piezas_count` | `int` | `COUNT(model_pieza_link.id_pieza)` |
| `key_s3_weights` | `string \| null` | `vision_model.key_s3_weights` |

### `VisionModelDetail` extends `VisionModelListEntry` (used by `GET /models/{model_id}`)

| Field | Type | Source |
|---|---|---|
| `piezas` | `ModelPiezaEntry[]` | `model_pieza_link` JOIN `pieza` |

### `ModelPiezaEntry`

| Field | Type | Source column |
|---|---|---|
| `id_pieza` | `UUID` | `model_pieza_link.id_pieza` |
| `nombre` | `string \| null` | `pieza.nombre` (left join) |
| `class_index` | `int` | `model_pieza_link.class_index` |

## Worker contract

The trainer worker (`modelWorker.py`) consumes from the `trainer-queue` RabbitMQ queue (durable, `prefetch_count=1`).

**Message shape** (published by `POST /generateModel`)

```json
{
  "model_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "nombre": "kit-lado-izquierdo-v2",
  "piezas": [
    { "id_pieza": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "class_index": 0 },
    { "id_pieza": "b2c3d4e5-f6a7-8901-bcde-f12345678901", "class_index": 1 }
  ]
}
```

**Worker flow**

1. Reads `model_id`, `nombre`, and `piezas[]` from the message.
2. Updates `vision_model.estado` to `PREPARING_DATA`.
3. For each piece: fetches its `nombre` and training samples from the DB, downloads S3 images, remaps labels to the assigned `class_index`, and assembles a local YOLO dataset.
4. Updates `vision_model.estado` to `TRAINING`.
5. Runs YOLOv8n-seg training.
6. Uploads `best.pt` to S3 at `models/{model_id}/best.pt`.
7. Updates `vision_model.estado` to `COMPLETED` and sets `key_s3_weights`.
8. On any exception: sets `vision_model.estado` to `FAILED`.

The worker acknowledges the RabbitMQ message after the entire pipeline completes (success or failure).

## Open follow-ups

- No weights download endpoint. `key_s3_weights` is populated on completion but there is no API to retrieve or download the file.
- No `DELETE` endpoint for models or individual model–piece links.
- No webhook or push notification for training progress — clients must poll `GET /models/{model_id}`.
- Future: configurable hyperparameters (epochs, image size, patience) per training job. Currently all jobs use the trainer's global `config.py` settings.
