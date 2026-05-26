# Inspections Specification

**Capability:** inspections  
**Change:** backend-frontend-integration  
**Phase:** spec  
**Date:** 2026-05-24  
**Status:** NEW (no prior spec — full spec)

---

## Purpose

Provide synchronous inspection execution and persistent inspection history.
An inspection receives an image and a kit identifier, runs detection via a
pluggable strategy, persists the result, and returns the full outcome in a
single HTTP round-trip. History endpoints support filtering for the
HistoryPage UI.

Cross-references:
- `Kit` entity — see `specs/kits-catalog/spec.md`
- `Pieza` entity — existing (`AI-Cup-/backend/src/models/pieza.py`)
- `DetectionStrategy` interface — defined in this spec (abstraction boundary)

---

## Entities

### Inspeccion

| Field                | Type      | Constraints                                            |
|----------------------|-----------|--------------------------------------------------------|
| id                   | UUID      | PK, auto-generated                                     |
| kit_id               | UUID      | FK → Kit.id, REQUIRED                                  |
| kit_nombre           | string    | Snapshot of Kit.nombre at inspection time              |
| fecha                | datetime  | Auto-set on create (UTC)                               |
| resultado_general    | string    | `"correcto"` \| `"anomalia"` \| `"error"` REQUIRED     |
| similitud            | float     | 0.0–1.0, detection confidence aggregate                |
| tiempo_procesamiento | float     | Wall-clock seconds for detection                       |
| operador             | string    | OPTIONAL, nullable free-text                           |
| imagen_s3_key        | string    | OPTIONAL, nullable — reserved for future S3 upload     |
| created_at           | datetime  | Auto-set on create (UTC)                               |

### Deteccion

| Field                   | Type    | Constraints                                              |
|-------------------------|---------|----------------------------------------------------------|
| id                      | UUID    | PK, auto-generated                                       |
| inspeccion_id           | UUID    | FK → Inspeccion.id, REQUIRED                             |
| pieza_id                | UUID    | OPTIONAL, nullable FK → Pieza.id_pieza (name-matched)   |
| pieza_nombre            | string  | Snapshot of detected part name                           |
| encontrado              | boolean | Whether the part was detected in the image               |
| confianza               | float   | 0.0–1.0                                                  |
| posicion_x_pct          | float   | OPTIONAL, nullable — bounding box center X (0–100)       |
| posicion_y_pct          | float   | OPTIONAL, nullable — bounding box center Y (0–100)       |
| width_pct               | float   | OPTIONAL, nullable — bounding box width (0–100)          |
| height_pct              | float   | OPTIONAL, nullable — bounding box height (0–100)         |
| estado                  | string  | OPTIONAL, nullable — e.g. `"ok"`, `"faltante"`, etc.    |
| corregido_por_operador  | boolean | OPTIONAL, default `false`                                |

---

## Detection Strategy Abstraction

### DetectionStrategy Interface

The system SHALL expose an internal `DetectionStrategy` abstraction (Protocol or
ABC) with a single method:

```
detect(image_bytes: bytes, kit: Kit) -> List[Deteccion]
```

The interface MUST NOT reference any specific detection provider (Claude,
YOLO, etc.) in its signature or docstring.

**Replacement contract**: A future `LocalCVStrategy` (real CV pipeline at
`/find-objects`) MUST be addable by implementing `DetectionStrategy` alone,
with ZERO changes to:

- The `POST /inspections` HTTP contract
- The router/handler code
- The frontend
- The database schema
- This specification

### ClaudeVisionStrategy

The MVP implementation of `DetectionStrategy`.

- Ports the existing logic from `ai-kitting-frontend/server.js`
- Calls the Anthropic API using `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` env vars
- Returns `List[Deteccion]` shaped according to the `Deteccion` entity above
- MUST NOT leak the name "Claude" into the HTTP response or the `Inspeccion` record

### Strategy Selection

The active strategy MUST be selected at application startup via the
`DETECTION_STRATEGY` environment variable (default: `claude`).

| Value    | Strategy                |
|----------|-------------------------|
| `claude` | `ClaudeVisionStrategy`  |
| *(future)* `local` | `LocalCVStrategy` |

If an unknown value is set, the application MUST fail to start with a clear
error message naming the invalid value and listing valid options.

---

## Endpoints

### POST /inspections

Submit an image for inspection against a kit. Detection is SYNCHRONOUS — the
response is returned only after detection completes.

**Request** (`multipart/form-data`):
```
image:   File     (REQUIRED — binary image data)
kit_id:  string   (REQUIRED — Kit UUID)
operador: string  (OPTIONAL — free-text operator name)
```

**Response 200**:
```json
{
  "id": "UUID",
  "kit_id": "UUID",
  "kit_nombre": "string",
  "fecha": "ISO-8601 datetime",
  "resultado_general": "correcto | anomalia | error",
  "similitud": 0.0,
  "tiempo_procesamiento": 0.0,
  "operador": "string | null",
  "imagen_s3_key": null,
  "created_at": "ISO-8601 datetime",
  "detecciones": [
    {
      "id": "UUID",
      "inspeccion_id": "UUID",
      "pieza_id": "UUID | null",
      "pieza_nombre": "string",
      "encontrado": true,
      "confianza": 0.95,
      "posicion_x_pct": 50.0,
      "posicion_y_pct": 50.0,
      "width_pct": 20.0,
      "height_pct": 10.0,
      "estado": "ok",
      "corregido_por_operador": false
    }
  ]
}
```

**Errors**:
- 404 if `kit_id` does not exist
- 422 if required fields are missing
- 500 if detection strategy raises an unrecoverable error

**Latency note (IR-013)**: This endpoint may take up to ~10 seconds to respond
when using `ClaudeVisionStrategy`. Callers SHOULD implement a progress indicator.
The nginx `proxy_read_timeout` MUST be set to at least 60 s to prevent gateway
timeout. See `specs/integration-runtime/spec.md`.

---

### GET /inspections

List inspections with optional server-side filters.

**Query params**:
| Param             | Type   | Description                             |
|-------------------|--------|-----------------------------------------|
| kit_id            | UUID   | Filter by kit                           |
| resultado_general | string | `correcto`, `anomalia`, or `error`      |
| fecha_desde       | date   | ISO-8601 date, inclusive lower bound    |
| fecha_hasta       | date   | ISO-8601 date, inclusive upper bound    |
| operador          | string | Substring match on operador field       |

**Response 200**: array of Inspeccion objects (without `detecciones` array for
performance — use `GET /inspections/{id}` for full detail).

---

### GET /inspections/{id}

Retrieve a single Inspeccion with full Deteccion list.

**Response 200**: full Inspeccion object with `detecciones` array.

**Errors**: 404 if not found.

---

### GET /inspections/{id}/result

Return the InspeccionResult shape used by the result-display page.

**Response 200**:
```json
{
  "id_inspeccion": "UUID",
  "similitud": 0.95,
  "resultado_general": "correcto",
  "tiempo_procesamiento": 3.2,
  "detecciones": [ ...same as above... ]
}
```

**Errors**: 404 if not found.

---

### POST /inspections/{id}/confirm

Record operator confirmation of detection results (user feedback).

**Request body** (`application/json`):
```json
{
  "corrections": [
    {
      "deteccion_id": "UUID",
      "encontrado": true,
      "estado": "ok"
    }
  ]
}
```

**Response 200**: updated Inspeccion object with corrected detections.

**Errors**: 404 if inspection not found; 422 if a `deteccion_id` does not
belong to the inspection.

---

## Requirements

### Requirement: Synchronous Inspection Execution

The system SHALL accept an image and a kit UUID, run detection via the active
`DetectionStrategy`, persist the full result, and return it in a single
synchronous HTTP response.

#### Scenario: Happy path — valid kit and image

- GIVEN a Kit with UUID "kit-001" exists and has 3 linked Pieza items
- AND `DETECTION_STRATEGY=claude` and a valid `ANTHROPIC_API_KEY` are set
- WHEN POST /inspections is called with `kit_id=kit-001` and a valid image file
- THEN the response status is 200
- AND the body contains an `Inspeccion` with `resultado_general` set
- AND `detecciones` contains one entry per detected part (may differ from kit item count)
- AND both the `Inspeccion` and `Deteccion` rows are persisted to the database

#### Scenario: Kit not found

- GIVEN no Kit exists for UUID "kit-999"
- WHEN POST /inspections is called with `kit_id=kit-999`
- THEN the system SHALL return 404
- AND no Inspeccion row is created

#### Scenario: Detection result does not match a catalog pieza by name

- GIVEN detection returns a part named "Widget X" that does not match any Pieza in the kit catalog
- WHEN the result is persisted
- THEN the Deteccion row has `pieza_nombre="Widget X"` and `pieza_id=null`
- AND the overall Inspeccion is still persisted with the unmatched detection

---

### Requirement: Detection Strategy Selection

The system SHALL select the `DetectionStrategy` implementation at startup using
the `DETECTION_STRATEGY` environment variable.

#### Scenario: Valid strategy selected

- GIVEN `DETECTION_STRATEGY=claude`
- WHEN the application starts
- THEN `ClaudeVisionStrategy` is instantiated and used for all inspection requests

#### Scenario: Unknown strategy value causes startup failure

- GIVEN `DETECTION_STRATEGY=unknown_value`
- WHEN the application starts
- THEN the application MUST fail to start
- AND the error message MUST name the invalid value and list valid options
- AND no HTTP server begins accepting connections

#### Scenario: Default strategy when env var is absent

- GIVEN `DETECTION_STRATEGY` is not set
- WHEN the application starts
- THEN the system MUST default to `ClaudeVisionStrategy` (equivalent to `claude`)

---

### Requirement: Strategy Replaceability

The system SHALL be designed such that replacing `ClaudeVisionStrategy` with
`LocalCVStrategy` requires implementing `DetectionStrategy` only, with no
changes to the HTTP contract, router, frontend, database schema, or this spec.

#### Scenario: LocalCVStrategy substitution (illustrative)

- GIVEN `DETECTION_STRATEGY=local` is set and `LocalCVStrategy` is implemented
- WHEN POST /inspections is called
- THEN the response shape is identical to the `claude` strategy response
- AND the frontend receives the same `Inspeccion` JSON structure without modification

---

### Requirement: Inspection History Listing

The system SHALL provide a filterable list of past inspections with
server-side filtering applied before returning results.

#### Scenario: Filter by kit and date range

- GIVEN 10 inspections exist, 4 for kit "kit-001" on 2026-05-20
- WHEN GET /inspections?kit_id=kit-001&fecha_desde=2026-05-20&fecha_hasta=2026-05-20 is called
- THEN the response contains exactly 4 inspections
- AND each inspection has `kit_id=kit-001`

#### Scenario: Filter by resultado_general

- GIVEN inspections with mixed `resultado_general` values exist
- WHEN GET /inspections?resultado_general=anomalia is called
- THEN only inspections with `resultado_general=anomalia` are returned

---

### Requirement: Full Inspection Detail Retrieval

The system SHALL return a complete Inspeccion including all Deteccion records
when `GET /inspections/{id}` is called.

#### Scenario: Happy path full retrieval

- GIVEN an Inspeccion exists with 5 Deteccion rows
- WHEN GET /inspections/{id} is called
- THEN the response includes the Inspeccion fields and a `detecciones` array with 5 items

#### Scenario: Inspection not found

- GIVEN no Inspeccion exists for the UUID
- WHEN GET /inspections/{id} is called
- THEN the system SHALL return 404

---

### Requirement: Operator Confirmation

The system SHALL allow an operator to confirm or correct detection outcomes,
updating `corregido_por_operador` and adjusting detection fields.

#### Scenario: Operator corrects a false negative

- GIVEN an Inspeccion exists with a Deteccion where `encontrado=false`
- WHEN POST /inspections/{id}/confirm is called with a correction setting `encontrado=true`
- THEN the Deteccion is updated with `encontrado=true` and `corregido_por_operador=true`
- AND the response reflects the updated Inspeccion

#### Scenario: Correction references unknown deteccion_id

- GIVEN a valid Inspeccion ID
- WHEN POST /inspections/{id}/confirm is called with a `deteccion_id` that does not belong to the inspection
- THEN the system SHALL return 422
- AND no Deteccion row is modified

---

### Requirement: Image Storage is Reserved for Future Use

The system SHALL include an `imagen_s3_key` column on `Inspeccion` but MUST
NOT implement any upload logic in this change. The column SHALL be persisted
as `null` for all inspections in this MVP.

#### Scenario: Image is submitted but not stored

- GIVEN a valid inspection request including an image file
- WHEN the inspection is processed and persisted
- THEN `imagen_s3_key` is `null` in the Inspeccion record
- AND no S3 API call is made

---

### Requirement: Timeout Tolerance

The system SHALL remain functional for inspection requests that take up to 10
seconds to process.

#### Scenario: Slow detection completes within timeout window

- GIVEN `ClaudeVisionStrategy` takes 8 seconds to return
- WHEN POST /inspections is called
- THEN the response is returned after 8 seconds with status 200
- AND no gateway or proxy timeout is triggered (nginx `proxy_read_timeout ≥ 60s`)

---

## Out of Scope for This Capability

- S3 upload logic for `imagen_s3_key` (column reserved; upload logic is a
  follow-up)
- `LocalCVStrategy` implementation (interface boundary is specced; impl is
  out of scope)
- Pagination on `GET /inspections`
- Authentication / `operador` FK (free-text only for MVP)
- Async inspection flow (polling, status endpoint)
