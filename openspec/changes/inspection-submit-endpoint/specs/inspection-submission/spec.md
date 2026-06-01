# Inspection Submission Specification

## Purpose

Defines the `POST /api/inspections` endpoint that accepts a kit image, runs YOLO inference, and returns a structured inspection result with detections.

## Requirements

### Requirement: Endpoint Contract

The system MUST expose `POST /api/inspections` accepting `multipart/form-data` with fields:

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `kit_id` | string (UUID) | Yes | Valid UUID v4 |
| `image` | file | Yes | Content-Type `image/*`, max 20 MiB |
| `operador` | string | No | Max 100 chars |

The response SHALL return `InspeccionRead` with `detecciones` populated.

#### Scenario: Successful inspection with detectable pieces

- GIVEN a kit with `VisionModel.estado = "COMPLETED"` and trained YOLO weights in S3
- WHEN the client POSTs a valid kit_id, a quality image, and optional operador
- THEN the system returns 200 with `InspeccionRead` including all `Deteccion` rows

#### Scenario: Invalid kit_id format

- GIVEN any request
- WHEN `kit_id` is not a valid UUID
- THEN 422 with detail `"kit_id must be a valid UUID"`

#### Scenario: Kit not found

- GIVEN a valid UUID that matches no Kit row
- WHEN the client POSTs
- THEN 404 with detail `"Kit not found"`

### Requirement: Model Readiness Gate

The system MUST reject the request if the kit's associated `VisionModel` has `estado != "COMPLETED"`.

#### Scenario: Model not trained

- GIVEN a kit whose `VisionModel.estado` is `"QUEUED"`, `"TRAINING"`, or `"FAILED"`
- WHEN the client POSTs
- THEN 409 with detail `"Model not trained. Current status: {estado}"`

#### Scenario: Kit has no linked vision model

- GIVEN a kit with `vision_model_id = NULL`
- WHEN the client POSTs
- THEN 409 with detail `"No vision model associated with this kit"`

### Requirement: Detection Execution

The system SHALL run YOLO inference via `run_in_executor` and map each detected class index to a `pieza_id` using `ModelPiezaLink`.

#### Scenario: All expected pieces detected

- GIVEN a kit with 5 linked pieces, all mapped in `ModelPiezaLink`, and the image contains all 5
- WHEN inference runs
- THEN 5 `Deteccion` rows are created, all with `encontrado=True` and `confianza > 0`

#### Scenario: Partial detection — some pieces missing

- GIVEN a kit linked to pieces A, B, C but only A and B are detected
- WHEN inference runs
- THEN 3 `Deteccion` rows: A and B with `encontrado=True`; C with `encontrado=False`, `confianza=0.0`

#### Scenario: Empty detection — no pieces found

- GIVEN an image where YOLO returns zero detections
- WHEN inference runs
- THEN all kit pieces produce `Deteccion` rows with `encontrado=False`, `confianza=0.0`; `similitud=0.0`, `resultado_general="error"`

### Requirement: similitud and resultado_general

The system MUST compute `similitud = (found_count / total_expected) × avg_confidence` where `found_count` counts detections with `encontrado=True`. `resultado_general` SHALL be:

| similitud | resultado_general |
|-----------|-------------------|
| ≥ 0.80 | `"correcto"` |
| ≥ 0.55 | `"anomalia"` |
| < 0.55 | `"error"` |

#### Scenario: High-confidence perfect match

- GIVEN 5/5 pieces found with avg confidence 0.95
- WHEN similitud computed as 1.0 × 0.95 = 0.95
- THEN `resultado_general = "correcto"`

#### Scenario: Low-confidence partial match

- GIVEN 2/5 found with avg confidence 0.60
- WHEN similitud computed as 0.4 × 0.60 = 0.24
- THEN `resultado_general = "error"`

### Requirement: Image Upload to S3

The system SHALL upload the original image to S3 at `inspections/{inspeccion_id}/original.jpg` and persist the key as `Inspeccion.imagen_s3_key`.

#### Scenario: S3 upload succeeds

- GIVEN a valid S3 connection and a generated inspeccion_id
- WHEN the image bytes are uploaded
- THEN the image is stored at `inspections/{inspeccion_id}/original.jpg` and `imagen_s3_key` is set

#### Scenario: S3 upload fails

- GIVEN S3 client raises `ClientError`
- WHEN upload is attempted
- THEN 500 with detail `"Failed to upload image to S3"`; no Inspeccion row is committed

### Requirement: Performance Constraints

The system SHOULD complete within 30s total timeout. First request (cold cache) MAY take up to 15s (S3 download + YOLO load). Cached requests SHOULD complete within 5s.

#### Scenario: Cold-start request

- GIVEN no cached model for the kit's vision_model_id
- WHEN the first request arrives
- THEN `tiempo_procesamiento` SHALL be recorded; response completes within 30s

#### Scenario: Warm cache request

- GIVEN a previously loaded model in the cache
- WHEN a subsequent request for the same kit arrives
- THEN `tiempo_procesamiento` ≤ 5s (inference only, no download)
