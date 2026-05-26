# Kits Catalog Specification

**Capability:** kits-catalog  
**Change:** backend-frontend-integration  
**Phase:** spec  
**Date:** 2026-05-24  
**Status:** NEW (no prior spec — full spec)

---

## Purpose

Provide persistent, server-side management of Kit entities and their composition
(KitPieza items). Each Kit is a named assembly of catalog `Pieza` entries
referenced by UUID. This capability closes IR-007 for the kit side and enables
the inspection capability to validate physical kits against a real catalog.

Cross-references:
- `Pieza` entity (existing) — see `AI-Cup-/backend/src/models/pieza.py`
- Inspection capability — see `specs/inspections/spec.md`

---

## Entities

### Kit

| Field            | Type         | Constraints                          |
|------------------|--------------|--------------------------------------|
| id               | UUID         | PK, auto-generated                   |
| nombre           | string       | REQUIRED, non-empty                  |
| descripcion      | string       | OPTIONAL, nullable                   |
| activo           | boolean      | REQUIRED, default `true`             |
| ancho_cm         | float        | OPTIONAL, nullable                   |
| largo_cm         | float        | OPTIONAL, nullable                   |
| imagen_url       | string       | OPTIONAL, nullable                   |
| vision_model_id  | UUID         | OPTIONAL, nullable FK → VisionModel.id_modelo |
| created_at       | datetime     | auto-set on create (UTC)             |

### KitPiezaLink

| Field               | Type    | Constraints                                        |
|---------------------|---------|----------------------------------------------------|
| id                  | UUID    | PK, auto-generated                                 |
| kit_id              | UUID    | FK → Kit.id, REQUIRED                             |
| pieza_id            | UUID    | FK → Pieza.id_pieza, REQUIRED                     |
| cantidad_requerida  | integer | REQUIRED, > 0                                      |
| pos_x               | float   | OPTIONAL, nullable                                 |
| pos_y               | float   | OPTIONAL, nullable                                 |
| ancho_cm            | float   | OPTIONAL, nullable                                 |
| alto_cm             | float   | OPTIONAL, nullable                                 |
| icono               | string  | OPTIONAL, nullable                                 |
| es_agrupacion       | boolean | OPTIONAL, default `false`                          |

Composite uniqueness: `(kit_id, pieza_id)` MUST be unique — one entry per pieza
per kit.

---

## Endpoints

### POST /kits

Create a new Kit.

**Request body** (`application/json`):
```json
{
  "nombre": "string (required)",
  "descripcion": "string (optional)",
  "activo": "boolean (optional, default true)",
  "ancho_cm": "float (optional)",
  "largo_cm": "float (optional)",
  "imagen_url": "string (optional)",
  "vision_model_id": "UUID string (optional)"
}
```

**Response 201**:
```json
{
  "id": "UUID",
  "nombre": "string",
  "descripcion": "string | null",
  "activo": true,
  "ancho_cm": "float | null",
  "largo_cm": "float | null",
  "imagen_url": "string | null",
  "vision_model_id": "UUID | null",
  "created_at": "ISO-8601 datetime",
  "items": []
}
```

**Errors**: 404 if `vision_model_id` provided but does not exist.

---

### GET /kits

List all kits. Returns Kit summaries (without KitPiezaLink details).

**Query params**: none required for MVP.

**Response 200**: array of Kit objects (items array excluded or empty).

---

### GET /kits/{id}

Retrieve a single Kit with its full item list.

**Response 200**:
```json
{
  "id": "UUID",
  "nombre": "string",
  ...kit fields...,
  "items": [
    {
      "id": "UUID",
      "kit_id": "UUID",
      "pieza_id": "UUID",
      "cantidad_requerida": 2,
      "pos_x": "float | null",
      "pos_y": "float | null",
      "ancho_cm": "float | null",
      "alto_cm": "float | null",
      "icono": "string | null",
      "es_agrupacion": false
    }
  ]
}
```

**Errors**: 404 if kit not found.

---

### PUT /kits/{id}

Update Kit header fields (nombre, descripcion, activo, dimensions, imagen_url,
vision_model_id). MUST NOT affect existing KitPiezaLink rows.

**Request body**: same optional fields as POST /kits body.

**Response 200**: updated Kit object with items.

**Errors**: 404 if kit not found; 404 if `vision_model_id` provided but does
not exist.

---

### DELETE /kits/{id}

Delete a Kit and CASCADE to all its KitPiezaLink rows.

**Response 204**: no body.

**Errors**: 404 if kit not found.

---

### POST /kits/{id}/items

Add a `KitPiezaLink` entry to an existing Kit.

**Request body** (`application/json`):
```json
{
  "pieza_id": "UUID (required)",
  "cantidad_requerida": "integer > 0 (required)",
  "pos_x": "float (optional)",
  "pos_y": "float (optional)",
  "ancho_cm": "float (optional)",
  "alto_cm": "float (optional)",
  "icono": "string (optional)",
  "es_agrupacion": "boolean (optional, default false)"
}
```

**Response 201**: created KitPiezaLink object.

**Errors**:
- 404 if kit not found
- 404 if `pieza_id` does not exist in Pieza catalog
- 409 if `pieza_id` already linked to this kit

---

### PUT /kits/{id}/items/{itemId}

Update an existing KitPiezaLink (e.g., change quantity or position). MUST NOT
change `pieza_id` — if a different pieza is needed, delete and re-add.

**Request body**: same optional fields as POST /kits/{id}/items body (excluding
`pieza_id`).

**Response 200**: updated KitPiezaLink object.

**Errors**: 404 if kit or item not found.

---

### DELETE /kits/{id}/items/{itemId}

Remove a single KitPiezaLink from the kit.

**Response 204**: no body.

**Errors**: 404 if kit or item not found.

---

## Requirements

### Requirement: Kit Creation

The system SHALL create a Kit with the provided fields, auto-generate a UUID
primary key, and return the created resource.

#### Scenario: Happy path kit creation

- GIVEN a valid POST /kits request with at minimum a `nombre` field
- WHEN the request is processed
- THEN a Kit is persisted with a system-generated UUID
- AND the response status is 201
- AND the response body contains all Kit fields including `id` and `created_at`
- AND `items` is an empty array

#### Scenario: Kit creation with non-existent vision_model_id

- GIVEN a POST /kits request that includes a `vision_model_id` value
- WHEN the `vision_model_id` does not match any VisionModel record
- THEN the system SHALL return 404 with a descriptive error message
- AND no Kit row is persisted

---

### Requirement: Kit Retrieval

The system SHALL return a Kit with its full KitPiezaLink list when `GET
/kits/{id}` is called.

#### Scenario: Happy path kit retrieval

- GIVEN a Kit with two linked items exists
- WHEN GET /kits/{id} is called with its UUID
- THEN the response status is 200
- AND the body contains all Kit fields plus an `items` array with 2 elements
- AND each item includes `pieza_id`, `cantidad_requerida`, and layout fields

#### Scenario: Kit not found

- GIVEN no Kit exists for the requested UUID
- WHEN GET /kits/{id} is called
- THEN the system SHALL return 404

---

### Requirement: Kit Update

The system SHALL update Kit header fields without affecting existing item links.

#### Scenario: Partial update preserves items

- GIVEN a Kit with 3 linked items exists
- WHEN PUT /kits/{id} is called with only `nombre` changed
- THEN the response contains the updated `nombre`
- AND the `items` array still contains the same 3 KitPiezaLink entries

#### Scenario: Update with non-existent vision_model_id

- GIVEN a valid Kit UUID
- WHEN PUT /kits/{id} is called with a `vision_model_id` that does not exist
- THEN the system SHALL return 404
- AND the Kit record is NOT modified

---

### Requirement: Kit Deletion with Cascade

The system SHALL delete a Kit and all its KitPiezaLink entries atomically.

#### Scenario: Happy path delete with cascade

- GIVEN a Kit with 2 linked items exists
- WHEN DELETE /kits/{id} is called
- THEN the response status is 204
- AND the Kit row no longer exists
- AND the 2 KitPiezaLink rows no longer exist
- AND GET /kits/{id} returns 404

#### Scenario: Delete non-existent kit

- GIVEN no Kit exists for the requested UUID
- WHEN DELETE /kits/{id} is called
- THEN the system SHALL return 404

---

### Requirement: Kit Item Addition

The system SHALL add a KitPiezaLink entry that references an existing Pieza from
the catalog by UUID.

#### Scenario: Happy path add item

- GIVEN a Kit exists and a Pieza with the given UUID exists in the catalog
- WHEN POST /kits/{id}/items is called with `pieza_id` and `cantidad_requerida`
- THEN the response status is 201
- AND the KitPiezaLink is persisted with the correct `kit_id` and `pieza_id`

#### Scenario: Add item with non-existent pieza UUID

- GIVEN a Kit exists
- WHEN POST /kits/{id}/items is called with a `pieza_id` that does not exist in Pieza catalog
- THEN the system SHALL return 404 with a message indicating the pieza was not found
- AND no KitPiezaLink row is created

#### Scenario: Duplicate pieza in same kit is rejected

- GIVEN a Kit already has a KitPiezaLink for pieza UUID "abc-123"
- WHEN POST /kits/{id}/items is called again with the same `pieza_id` "abc-123"
- THEN the system SHALL return 409 Conflict
- AND the existing KitPiezaLink row is NOT modified
- NOTE: callers who want to change quantity MUST use PUT /kits/{id}/items/{itemId}

---

### Requirement: Kit Item Update

The system SHALL update mutable fields of a KitPiezaLink (quantity, position,
dimensions) without changing the referenced `pieza_id`.

#### Scenario: Update item quantity

- GIVEN a KitPiezaLink exists with `cantidad_requerida: 1`
- WHEN PUT /kits/{id}/items/{itemId} is called with `cantidad_requerida: 3`
- THEN the response status is 200
- AND the KitPiezaLink now has `cantidad_requerida: 3`
- AND `pieza_id` is unchanged

#### Scenario: Item not found

- GIVEN a valid Kit UUID but a non-existent item UUID
- WHEN PUT /kits/{id}/items/{itemId} is called
- THEN the system SHALL return 404

---

### Requirement: Kit Item Removal

The system SHALL remove a single KitPiezaLink without affecting the parent Kit
or other items.

#### Scenario: Happy path item removal

- GIVEN a Kit has items A and B
- WHEN DELETE /kits/{id}/items/{itemId} is called for item A
- THEN response status is 204
- AND item A is deleted
- AND item B still exists
- AND GET /kits/{id} returns only item B in `items`

---

### Requirement: VisionModel FK is Informational for MVP

The system SHALL persist `vision_model_id` on Kit as a nullable FK. For the MVP
inspection strategy (Claude Vision), this field is stored but MUST NOT affect
inspection behavior.

#### Scenario: Kit with vision_model_id does not change inspection outcome

- GIVEN a Kit with `vision_model_id` set to a valid VisionModel UUID
- WHEN an inspection is submitted for this kit
- THEN the inspection uses the `DETECTION_STRATEGY` env var to select strategy
- AND the `vision_model_id` value is NOT consulted during detection

---

## Out of Scope for This Capability

- Snapshot fields (`pieza_nombre`) in detection records — covered in `specs/inspections/spec.md`
- Kit image upload to S3 (`imagen_url` is a free-text field; no upload logic)
- Pagination on `GET /kits`
- Sorting/filtering on `GET /kits`
