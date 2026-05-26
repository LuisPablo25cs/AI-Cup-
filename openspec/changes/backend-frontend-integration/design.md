# Design: backend-frontend-integration

**Change:** backend-frontend-integration  
**Phase:** design  
**Date:** 2026-05-24  
**Status:** Final — all decisions locked (proposal §"Locked Decisions")

This is a slice-oriented design. Each section is consumable by `sdd-tasks` and
`sdd-apply` slice-by-slice without re-deciding anything.

---

## 1. Executive Design Overview

```
                 ┌───────────────────────────────────────────┐
                 │  Browser (React 18 + Vite dev / nginx)    │
                 └───────────────┬───────────────────────────┘
                                 │
       dev:  Vite proxy            prod:  nginx :80
       ── /api/*  ─→ :8000        ── /api/*     ─→ backend:8000
       ── /backend/* ─→ :8000     ── /backend/* ─→ backend:8000
                                 │
                                 ▼
                  ┌────────────────────────────────┐
                  │   FastAPI :8000 (uvicorn)      │
                  │                                │
                  │   /piezas/*       (existing)   │
                  │   /api/kits/*       NEW (S1)   │
                  │   /api/inspections/* NEW (S2)  │
                  │     └─ DetectionStrategy ──┐   │
                  └────────┬──────────┬────────┘   │
                           │          │            │
                       Postgres    Redis      Anthropic API
                                   RabbitMQ   (Claude Vision, S5)
```

**DetectionStrategy plug-in point:** `POST /api/inspections` resolves the active
strategy from `factory.get_strategy()` (env-driven). Today: `ClaudeVisionStrategy`.
Tomorrow: `LocalCVStrategy` drops in without touching the router, response
shape, DB schema, or frontend.

**Routing prefix scheme (locked):**
- New routers mount under `/api/*` (`kits`, `inspections`) — frontend already
  calls these paths.
- Existing `/piezas/*` stays without prefix (backward compatible).
- Vite proxy (S5) forwards BOTH `/api/*` and `/backend/*` to `:8000`. Same in
  nginx (S6). The two prefixes are an accepted artifact of the gradual migration.

**Key invariants (implementation MUST preserve):**
1. `DetectionStrategy.detect(image_bytes, kit) -> List[DeteccionResult]` is the
   ONLY way the router talks to vision. No `anthropic`/`claude` strings outside
   `services/detection/claude.py`.
2. All IDs in API payloads are UUID strings. Frontend `id_kit | id_pieza |
   id_inspeccion | id_deteccion` types are `string`, never `number`.
3. `Deteccion.pieza_id` is nullable — Claude returns names, not UUIDs. We
   match by `pieza_nombre` against the kit's linked piezas; misses store NULL.
4. `Inspeccion.imagen_s3_key` column exists but stays NULL in S2–S5 (no upload).
5. Backend hostnames (Redis, RabbitMQ) and Anthropic config are env-driven.
   No hardcoded `"redis"`/`"rabbitmq"`/`"claude-opus-4-6"` survive S1/S5.

---

## 2. Backend Design

### 2.1 SQLModel Schemas

Follow the `Pieza` pattern exactly (`pg.UUID` PK with `Column`, server-side
defaults, snake_case `__tablename__`).

#### `src/models/kit.py`

```python
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column as SAColumn, DateTime
import sqlalchemy.dialects.postgresql as pg
from uuid import UUID, uuid4
from datetime import datetime, timezone


class KitPiezaLink(SQLModel, table=True):
    __tablename__ = "kit_pieza_link"

    id: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, default=uuid4)
    )
    kit_id: UUID = Field(
        sa_column=SAColumn(pg.UUID, ForeignKey("kit.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    )
    pieza_id: UUID = Field(
        sa_column=SAColumn(pg.UUID, ForeignKey("pieza.id_pieza"),
                           nullable=False, index=True)
    )
    cantidad_requerida: int = Field(default=1)
    pos_x: float | None = None
    pos_y: float | None = None
    ancho_cm: float | None = None
    alto_cm: float | None = None
    icono: str | None = None
    es_agrupacion: bool = False

    __table_args__ = (
        UniqueConstraint("kit_id", "pieza_id", name="uq_kit_pieza"),
    )

    kit: "Kit" = Relationship(back_populates="items")


class Kit(SQLModel, table=True):
    __tablename__ = "kit"

    id: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    nombre: str
    descripcion: str | None = None
    activo: bool = True
    ancho_cm: float | None = None
    largo_cm: float | None = None
    imagen_url: str | None = None
    vision_model_id: UUID | None = Field(
        default=None,
        sa_column=SAColumn(pg.UUID, ForeignKey("vision_model.id_model"),
                           nullable=True)
    )
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True),
                           default=lambda: datetime.now(timezone.utc))
    )

    items: list[KitPiezaLink] = Relationship(
        back_populates="kit",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )
```

> Import additions at top of file: `from sqlalchemy import ForeignKey, UniqueConstraint`.

**DTOs (Pydantic) — same file or `src/routes/kitRouter.py`:**

```python
class KitItemCreate(BaseModel):
    pieza_id: UUID
    cantidad_requerida: int = 1
    pos_x: float | None = None
    pos_y: float | None = None
    ancho_cm: float | None = None
    alto_cm: float | None = None
    icono: str | None = None
    es_agrupacion: bool = False

class KitItemUpdate(BaseModel):
    cantidad_requerida: int | None = None
    pos_x: float | None = None
    pos_y: float | None = None
    ancho_cm: float | None = None
    alto_cm: float | None = None
    icono: str | None = None
    es_agrupacion: bool | None = None

class KitCreate(BaseModel):
    nombre: str
    descripcion: str | None = None
    activo: bool = True
    ancho_cm: float | None = None
    largo_cm: float | None = None
    imagen_url: str | None = None
    vision_model_id: UUID | None = None

class KitUpdate(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    activo: bool | None = None
    ancho_cm: float | None = None
    largo_cm: float | None = None
    imagen_url: str | None = None
    vision_model_id: UUID | None = None

class KitItemRead(BaseModel):
    id: UUID
    kit_id: UUID
    pieza_id: UUID
    cantidad_requerida: int
    pos_x: float | None
    pos_y: float | None
    ancho_cm: float | None
    alto_cm: float | None
    icono: str | None
    es_agrupacion: bool
    model_config = {"from_attributes": True}

class KitRead(BaseModel):
    id: UUID
    nombre: str
    descripcion: str | None
    activo: bool
    ancho_cm: float | None
    largo_cm: float | None
    imagen_url: str | None
    vision_model_id: UUID | None
    created_at: datetime
    items: list[KitItemRead] = []
    model_config = {"from_attributes": True}
```

#### `src/models/inspeccion.py`

```python
class Deteccion(SQLModel, table=True):
    __tablename__ = "deteccion"

    id: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, default=uuid4)
    )
    inspeccion_id: UUID = Field(
        sa_column=SAColumn(pg.UUID,
                           ForeignKey("inspeccion.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    )
    pieza_id: UUID | None = Field(
        default=None,
        sa_column=SAColumn(pg.UUID, ForeignKey("pieza.id_pieza"), nullable=True)
    )
    pieza_nombre: str                     # snapshot — see IR-014
    encontrado: bool = True
    confianza: float = 0.0
    posicion_x_pct: float | None = None
    posicion_y_pct: float | None = None
    width_pct: float | None = None
    height_pct: float | None = None
    estado: str | None = None             # "correcto" | "incorrecto" | "faltante"
    corregido_por_operador: bool = False

    inspeccion: "Inspeccion" = Relationship(back_populates="detecciones")


class Inspeccion(SQLModel, table=True):
    __tablename__ = "inspeccion"

    id: UUID = Field(
        sa_column=SAColumn(pg.UUID, primary_key=True, unique=True, default=uuid4)
    )
    kit_id: UUID = Field(
        sa_column=SAColumn(pg.UUID, ForeignKey("kit.id"), nullable=False, index=True)
    )
    kit_nombre: str                       # snapshot
    fecha: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True), index=True,
                           default=lambda: datetime.now(timezone.utc))
    )
    resultado_general: str = Field(index=True)  # correcto | anomalia | error
    similitud: float = 0.0
    tiempo_procesamiento: float = 0.0
    operador: str | None = Field(default=None, index=True)
    imagen_s3_key: str | None = None      # reserved — always NULL in MVP
    created_at: datetime = Field(
        sa_column=SAColumn(DateTime(timezone=True),
                           default=lambda: datetime.now(timezone.utc))
    )

    detecciones: list[Deteccion] = Relationship(
        back_populates="inspeccion",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )
```

**DTOs:** `DeteccionRead`, `InspeccionRead`, `InspeccionSummary` (without
`detecciones`), `InspeccionResultRead`, `DeteccionCorrection`. All
`from_attributes=True`, all UUIDs serialized as strings (Pydantic default).

**Indexes recommended (created by the `Field(index=True)` above):**
- `inspeccion.kit_id`, `inspeccion.fecha`, `inspeccion.resultado_general`,
  `inspeccion.operador` — support history filters
- `deteccion.inspeccion_id` — for the eager `selectin` load
- `kit_pieza_link.kit_id`, `kit_pieza_link.pieza_id`
- Unique `(kit_id, pieza_id)` on `kit_pieza_link`

**Cascade rules (explicit):**
- `Kit` deleted → `KitPiezaLink` rows deleted (ORM + DB-level via
  `ondelete="CASCADE"`).
- `Inspeccion` deleted → `Deteccion` rows deleted (same).
- `Pieza` deletion is NOT cascaded into kits/detections — `pieza_id` becomes
  the responsibility of the caller (out of scope; deleting a referenced pieza
  will raise FK error today and that is acceptable for MVP).

### 2.2 Router Files

#### `src/routes/kitRouter.py` — `router = APIRouter(prefix="/api/kits", tags=["Kits"])`

| Method | Path                       | Handler                | Returns / Description                                       |
|--------|----------------------------|------------------------|-------------------------------------------------------------|
| POST   | `/`                        | `create_kit`           | `201 KitRead`. Validates `vision_model_id` if provided.      |
| GET    | `/`                        | `list_kits`            | `200 list[KitRead]` (items empty for list view).             |
| GET    | `/{kit_id}`                | `get_kit`              | `200 KitRead` with items (selectin). 404 if missing.         |
| PUT    | `/{kit_id}`                | `update_kit`           | `200 KitRead`. Items untouched.                              |
| DELETE | `/{kit_id}`                | `delete_kit`           | `204`. Cascades to `KitPiezaLink`.                           |
| POST   | `/{kit_id}/items`          | `add_item`             | `201 KitItemRead`. 404 missing pieza, 409 duplicate.         |
| PUT    | `/{kit_id}/items/{item_id}`| `update_item`          | `200 KitItemRead`. Does NOT change `pieza_id`.               |
| DELETE | `/{kit_id}/items/{item_id}`| `delete_item`          | `204`.                                                       |

Signature pattern (mirror `piezaRouter.py`):

```python
@router.post("/", response_model=KitRead, status_code=201)
async def create_kit(data: KitCreate,
                     session: AsyncSession = Depends(get_session)):
    if data.vision_model_id:
        vm = await session.get(VisionModel, data.vision_model_id)
        if not vm:
            raise HTTPException(404, "VisionModel not found")
    kit = Kit(**data.model_dump())
    session.add(kit)
    await session.commit()
    await session.refresh(kit)
    return kit
```

#### `src/routes/inspeccionRouter.py` — `router = APIRouter(prefix="/api/inspections", tags=["Inspections"])`

| Method | Path                  | Handler              | Returns / Description                                                                          |
|--------|-----------------------|----------------------|------------------------------------------------------------------------------------------------|
| POST   | `/`                   | `submit_inspection`  | `200 InspeccionRead`. multipart: `image`, `kit_id`, `operador?`. SYNC; calls `get_strategy()`. |
| GET    | `/`                   | `list_inspections`   | `200 list[InspeccionSummary]`. Query: kit_id, resultado_general, fecha_desde, fecha_hasta, operador. |
| GET    | `/{inspeccion_id}`    | `get_inspection`     | `200 InspeccionRead` (full, with detecciones).                                                  |
| GET    | `/{inspeccion_id}/result` | `get_result`     | `200 InspeccionResultRead` (id_inspeccion, similitud, resultado_general, tiempo_procesamiento, detecciones). |
| POST   | `/{inspeccion_id}/confirm` | `confirm`       | `200 InspeccionRead`. Body: `{ corrections: [{ deteccion_id, encontrado, estado }] }`.          |

Submit handler shape (full snippet — leaves zero ambiguity for sdd-apply):

```python
@router.post("/", response_model=InspeccionRead)
async def submit_inspection(
    kit_id: UUID = Form(...),
    image: UploadFile = File(...),
    operador: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    kit = await session.get(Kit, kit_id)
    if not kit:
        raise HTTPException(404, "Kit not found")
    # Eager-load items+piezas needed by the strategy
    await session.refresh(kit, attribute_names=["items"])

    image_bytes = await image.read()
    strategy = get_strategy()
    t0 = time.perf_counter()
    results = await strategy.detect(image_bytes, kit)  # List[DeteccionResult]
    elapsed = time.perf_counter() - t0

    similitud = _aggregate_similitud(results)
    resultado_general = _classify(similitud)  # >=0.80 correcto, >=0.55 anomalia, else error

    # Name → pieza_id resolution against kit-linked piezas
    name_to_id = await _build_name_index(session, kit)
    insp = Inspeccion(
        kit_id=kit.id,
        kit_nombre=kit.nombre,
        resultado_general=resultado_general,
        similitud=similitud,
        tiempo_procesamiento=elapsed,
        operador=operador,
        imagen_s3_key=None,
    )
    insp.detecciones = [
        Deteccion(
            pieza_id=name_to_id.get(r.pieza_nombre),
            pieza_nombre=r.pieza_nombre,
            encontrado=r.encontrado,
            confianza=r.confianza,
            posicion_x_pct=r.posicion_x_pct,
            posicion_y_pct=r.posicion_y_pct,
            width_pct=r.width_pct,
            height_pct=r.height_pct,
            estado=r.estado,
        )
        for r in results
    ]
    session.add(insp)
    await session.commit()
    await session.refresh(insp)
    return insp
```

#### Wiring in `main.py`

After `app.include_router(piezaRouter)` add:

```python
from src.routes.kitRouter import router as kitRouter
from src.routes.inspeccionRouter import router as inspeccionRouter
app.include_router(kitRouter)
app.include_router(inspeccionRouter)
```

Also update `src/db.py` imports so `create_all` picks the new tables up:

```python
from .models.kit import Kit, KitPiezaLink
from .models.inspeccion import Inspeccion, Deteccion
```

### 2.3 DetectionStrategy Design (CRITICAL — load-bearing abstraction)

Module layout:

```
src/services/detection/
  __init__.py       # re-exports get_strategy, DetectionStrategy, DeteccionResult
  base.py           # Protocol + DeteccionResult DTO
  claude.py         # ClaudeVisionStrategy
  factory.py        # get_strategy() — env-driven, fail-fast
```

#### `base.py`

```python
from typing import Protocol, runtime_checkable
from pydantic import BaseModel
from src.models.kit import Kit


class DeteccionResult(BaseModel):
    """Internal DTO emitted by every DetectionStrategy. Separate from the
    `Deteccion` DB model. NEVER exposed in the HTTP response — the router
    maps these to `Deteccion` rows before returning."""
    pieza_nombre: str
    encontrado: bool = True
    confianza: float = 0.0           # 0.0–1.0
    posicion_x_pct: float | None = None  # 0.0–1.0
    posicion_y_pct: float | None = None
    width_pct: float | None = None
    height_pct: float | None = None
    estado: str | None = None        # "correcto" | "incorrecto" | "faltante"


@runtime_checkable
class DetectionStrategy(Protocol):
    async def detect(self, image_bytes: bytes, kit: Kit) -> list[DeteccionResult]:
        ...
```

#### `claude.py` — port of `server.js`

```python
import base64, json, os, re
from anthropic import AsyncAnthropic
from src.models.kit import Kit
from .base import DetectionStrategy, DeteccionResult

_PROMPT_TEMPLATE = """Eres un sistema de inspección de calidad para bandejas de kitting industrial.

Analiza la imagen de la bandeja y evalúa cada pieza esperada.

PIEZAS ESPERADAS EN ESTE KIT ({kit_nombre}):
{piezas_list}

Para cada pieza esperada, determina:
- "correcto": la pieza está presente y parece estar en buen estado
- "incorrecto": hay algo en esa posición pero no corresponde o está dañado
- "faltante": la pieza no se encuentra en la bandeja

Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta (sin markdown, sin texto extra):
{{
  "similitud": <número 0-100>,
  "detecciones": [
    {{
      "pieza_nombre": "<nombre exacto de la pieza de la lista>",
      "estado": "correcto" | "incorrecto" | "faltante",
      "confianza": <0-100>,
      "posicion_x_pct": <0-1>,
      "posicion_y_pct": <0-1>,
      "width_pct": <0-1>,
      "height_pct": <0-1>
    }}
  ]
}}
IMPORTANTE:
- Incluye TODAS las piezas esperadas, incluso las faltantes
- Para faltantes usa posicion_x_pct=0.5, posicion_y_pct=0.5"""


class ClaudeVisionStrategy:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for ClaudeVisionStrategy")
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6")

    async def detect(self, image_bytes: bytes, kit: Kit) -> list[DeteccionResult]:
        # Build piezas list from the eager-loaded KitPiezaLink rows.
        # We need pieza.nombre — fetch via the items' loaded pieza if joined,
        # or pass names via dict prepared by the router. Simplest: the router
        # loads them and stashes on kit.items[*].pieza.nombre via selectin on
        # the link itself (see open question 7.1).
        piezas_list = "\n".join(
            f"{i+1}. {item.pieza_nombre} (cantidad requerida: {item.cantidad_requerida})"
            for i, item in enumerate(_kit_items_for_prompt(kit))
        )
        prompt = _PROMPT_TEMPLATE.format(
            kit_nombre=kit.nombre,
            piezas_list=piezas_list or "(sin piezas)",
        )
        image_b64 = base64.b64encode(image_bytes).decode()

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image",
                         "source": {"type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_b64}},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        except Exception as exc:
            raise RuntimeError(f"Anthropic API call failed: {exc}") from exc

        text = response.content[0].text if response.content else ""
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise RuntimeError(f"Claude response missing JSON: {text[:200]}")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Claude returned malformed JSON: {exc}") from exc

        results: list[DeteccionResult] = []
        for d in parsed.get("detecciones", []):
            results.append(DeteccionResult(
                pieza_nombre=d.get("pieza_nombre", "unknown"),
                encontrado=d.get("estado") in ("correcto", "incorrecto"),
                confianza=_clip01(d.get("confianza", 50) / 100.0),
                posicion_x_pct=_clip01(d.get("posicion_x_pct", 0.5)),
                posicion_y_pct=_clip01(d.get("posicion_y_pct", 0.5)),
                width_pct=_clip01(d.get("width_pct", 0.1)),
                height_pct=_clip01(d.get("height_pct", 0.1)),
                estado=d.get("estado", "faltante"),
            ))
        return results


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
```

`_kit_items_for_prompt(kit)` is a helper that yields objects with
`pieza_nombre` and `cantidad_requerida`. The router populates them; see
Open Question 7.1.

#### `factory.py`

```python
import os
from .base import DetectionStrategy
from .claude import ClaudeVisionStrategy

_VALID = {"claude"}  # extend when LocalCVStrategy lands

_INSTANCE: DetectionStrategy | None = None

def get_strategy() -> DetectionStrategy:
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    name = os.getenv("DETECTION_STRATEGY", "claude").lower()
    if name not in _VALID:
        raise RuntimeError(
            f"Unknown DETECTION_STRATEGY={name!r}. Valid: {sorted(_VALID)}"
        )
    if name == "claude":
        _INSTANCE = ClaudeVisionStrategy()
    return _INSTANCE
```

Fail-fast at first request rather than at startup keeps `main.py` lifespan
simple. If the proposal later requires startup validation, move
`get_strategy()` into `lifespan()`.

**Adding `LocalCVStrategy` later** (out of scope) is exactly:
1. New file `services/detection/local.py` implementing `DetectionStrategy`.
2. Add `"local"` to `_VALID` and an `elif name == "local"` branch in
   `factory.py`.
3. Set `DETECTION_STRATEGY=local`.
4. Zero changes to `inspeccionRouter.py`, the DB, or the frontend.

### 2.4 CORS + Env Vars

In `src/main.py` add ABOVE the first router include:

```python
import os
from fastapi.middleware.cors import CORSMiddleware

CORS_ORIGINS = [
    o.strip() for o in
    os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Change `main.py:32` and `:44` to env-driven hosts:

```python
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
REDIS_HOST    = os.getenv("REDIS_HOST", "localhost")

# inside connect_rabbitmq():
pika.ConnectionParameters(host=RABBITMQ_HOST)

# replace the module-level redis init:
r = redis.Redis(host=REDIS_HOST, port=6379, db=0)
```

Same swap inside any inner `pika.BlockingConnection(...)` in `main.py`
(`publishNewPiece`, `generateModel`). No pydantic-settings — `os.getenv` is
sufficient for MVP and matches existing style (`DATABASE_URL`).

**requirements.txt additions:**
```
anthropic>=0.40
```
(No other additions — `python-multipart`, `pydantic`, `httpx` are already
pulled in by `fastapi`. `AsyncAnthropic` is the official 0.40+ async client.)

### 2.5 DB Migration Strategy

- `SQLModel.metadata.create_all` in `db.py:init_db` already runs at startup.
- New tables (`kit`, `kit_pieza_link`, `inspeccion`, `deteccion`) are purely
  additive → `create_all` creates them. No ALTER TABLE risk.
- `db.py` MUST import the new modules so SQLAlchemy registers them BEFORE
  `create_all` runs (see §2.2).
- Alembic is out of scope per proposal; documented as post-competition
  follow-up.

---

## 3. Frontend Design

### 3.1 ID Type Migration Plan

**One file, one type change cascades:** flip every `id_*` and `idK*` from
`number` to `string` in `src/api/types.ts`; TypeScript compiler surfaces every
broken consumer. The pattern is already established by `backend.ts`
(`BackendPieza.id_pieza: string`).

#### Diff in `src/api/types.ts`

```diff
 export interface Kit {
-  id_kit: number
+  id_kit: string
   ...
 }
 export interface KitPieza {
-  id_pieza: number
+  id_pieza: string
   ...
 }
 export interface Inspeccion {
-  id_inspeccion: number
-  id_kit: number
+  id_inspeccion: string
+  id_kit: string
   ...
 }
 export interface Deteccion {
-  id_deteccion: number
-  id_pieza: number
+  id_deteccion: string
+  id_pieza: string | null   // see invariant #3
   ...
 }
 export interface InspeccionFilters {
-  id_kit?: number
+  id_kit?: string
   ...
 }
 export interface InspeccionResult {
-  id_inspeccion: number
+  id_inspeccion: string
   ...
 }
```

#### Files affected (every one becomes a type-driven fix)

| File | Concrete change |
|------|-----------------|
| `src/api/types.ts` | Field type flips above + new `pieza_id: string \| null` on `Deteccion`. |
| `src/api/kits.ts` | All `id: number` params → `id: string`. |
| `src/api/inspections.ts` | All `id: number` / `kitId: number` → `string`. Drop `String(kitId)` cast. |
| `src/store/kitStore.ts` | `updateKit(id: string, …)`, `removeKit(id: string)`. Bump persist `name` to `'ai-kitting-kit-store-v2'` (forces wipe of legacy numeric IDs — chosen mitigation). After wiring real backend, the store stops being the source of truth; see §3.3. |
| `src/store/inspectionStore.ts` | `Record<number, Deteccion>` → `Record<string, Deteccion>`. |
| `src/pages/HomePage.tsx` | Pass `string` ids in route params. |
| `src/pages/InspectionPage.tsx` | Remove any `parseInt(kitId)`; `useParams<{ id: string }>()` is already string. |
| `src/pages/HistoryPage.tsx` | Remove `parseInt(f.kitId)`; filter object uses strings. |
| `src/pages/CreateKitPage.tsx` | Replace `id_pieza: idx + 1` with selected catalog pieza UUID (see §3.2). |
| `src/components/layout/Header.tsx` | Type updates only. |
| `src/components/kit/KitDetail.tsx` | Type updates only. |
| `src/components/kit/KitSelector.tsx` | Type updates only. |
| `src/components/item/ItemTable.tsx` | Type updates only. |
| `src/components/inspection/ComparisonView.tsx` | Type updates only. |
| `src/components/inspection/ComparisonOverlay.tsx` | Type updates only. |
| `src/components/history/HistoryFilters.tsx` | Type updates only. |
| `src/components/history/HistoryTable.tsx` | Type updates only. |
| `src/pages/DataCleaningPage.tsx` | Type updates only (uses `BackendPieza.id_pieza` already; no-op likely). |
| `src/mocks/data.ts`, `mocks/history.ts`, `mocks/inspectionResult.ts` | DELETE in S4 (replaced by real APIs). Until deletion, fix types to compile. |

**localStorage migration:** kits previously persisted with `id_kit: number`
will not deserialize cleanly into the new string-typed shape. Mitigation:
**bump the persist key** (`'ai-kitting-kit-store'` → `'…-v2'`) so Zustand
treats existing storage as empty. This is simpler than a runtime migrator and
acceptable because S3 also drops the store as the source of truth for kits.

### 3.2 CreateKitPage Picker

New component: `src/components/kit/PiezaPicker.tsx`.

```tsx
import { useQuery } from '@tanstack/react-query'
import { piezasApi, type BackendPieza } from '@/api/backend'

interface PiezaPickerProps {
  selected: Map<string, number>          // pieza_id → cantidad_requerida
  onChange: (next: Map<string, number>) => void
}

export function PiezaPicker({ selected, onChange }: PiezaPickerProps) {
  const { data, isLoading } = useQuery({
    queryKey: ['piezas'],
    queryFn: () => piezasApi.list(),
  })
  const [q, setQ] = useState('')
  const filtered = (data ?? []).filter(p =>
    p.nombre.toLowerCase().includes(q.toLowerCase())
  )
  // Render: search input + scrollable list with checkbox + qty input per item.
  // On toggle: insert/delete in `selected`. On qty change: update map value.
  ...
}
```

Wiring in `CreateKitPage`:
- Step 2 now uses `<PiezaPicker selected={...} onChange={...} />` instead of
  the free-form `ItemForm`.
- `handleSave` builds `items: KitItemCreate[]` from the picker map and calls
  `kitsApi.create(...)` → `kitsApi.addItem(kit.id, { pieza_id, cantidad_requerida })`
  for each entry (sequential awaits inside a TanStack mutation).
- Drop `useKitStore.addKit`. Layout fields (`pos_x`, `pos_y`, `ancho_cm`,
  `alto_cm`, `icono`, `es_agrupacion`) keep their roles but are now per-link
  on the picker (or in step 3 tray editor) — **kept identical** to today.

### 3.3 Wiring kits / inspections / history

Frontend modules become thin TanStack Query wrappers around the real APIs.

**API base path (locked):** all `kitsApi` and `inspectionsApi` calls go to
`/api/kits/*` and `/api/inspections/*`. `piezasApi` continues to use `/backend/piezas/`.

**TanStack Query keys (convention):**
- `['kits']` — list
- `['kit', id]` — single kit
- `['inspections', filters]` — list with filter object
- `['inspection', id]` — single inspection
- `['inspection-result', id]` — `/result` shape
- `['piezas']` — catalog list

**Mutations invalidate broad keys** (`queryClient.invalidateQueries({ queryKey: ['kits'] })`).

**MSW handlers audit (IR-011):** The codebase has NO active MSW handlers/server
— only static mock modules (`src/mocks/data.ts`, `mocks/history.ts`,
`mocks/inspectionResult.ts`) imported directly by pages. No `src/mocks/handlers.ts`
or `mocks/browser.ts` exists. MSW is in `package.json` but never started.
**Action for S3/S4:** delete the three mock modules and remove their imports.
No service-worker unregistration needed.

**Loading/error states:** mirror `DataCleaningPage` exactly — `isLoading` spinner,
`error?.message` toast banner; no fancy skeletons.

### 3.4 Env Vars

`src/lib/constants.ts` becomes:

```ts
export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
export const BACKEND_BASE = import.meta.env.VITE_BACKEND_BASE ?? '/backend'
```

`src/api/backend.ts:3` reads `BACKEND_BASE` from `@/lib/constants` instead of
hardcoding `/backend`. `src/api/client.ts` already reads `API_BASE` — no
change there.

`.env.example` (commit):
```
VITE_API_BASE=/api
VITE_BACKEND_BASE=/backend
```
`.env` to `.gitignore` (verify `.gitignore` already covers it — it does by
default Vite scaffolds).

### 3.5 `server.js` Removal (S5)

After §2.3 lands and the backend `/api/inspections` is verified working:

- Delete `ai-kitting-frontend/server.js`.
- `package.json`: drop `"dev": "concurrently …"` style (or whatever dual-run
  command exists) and reduce `"dev"` to `"vite"`. Remove deps `express`,
  `multer`, `cors`, `@anthropic-ai/sdk`, `concurrently`, `dotenv` (keep
  `dotenv` only if used elsewhere — grep first).
- `vite.config.ts`:

```diff
   server: {
     proxy: {
       '/api': {
-        target: 'http://localhost:3001',
+        target: 'http://localhost:8000',
         changeOrigin: true,
       },
       '/backend': {
         target: 'http://localhost:8000',
         changeOrigin: true,
         rewrite: (path) => path.replace(/^\/backend/, ''),
       },
     },
   },
```

(`/api` does NOT rewrite — FastAPI router mounts `/api/kits` and
`/api/inspections` with the prefix.)

---

## 4. Production Routing Design (S6)

### 4.1 `nginx.conf` (workspace root: `nginx/nginx.conf`)

```nginx
events {}
http {
  include       /etc/nginx/mime.types;
  default_type  application/octet-stream;
  sendfile      on;
  client_max_body_size 25m;          # Allow ~20 MB inspection uploads.

  upstream backend  { server backend:8000; }

  server {
    listen 80;
    server_name _;

    # Frontend static
    location / {
      root /usr/share/nginx/html;
      try_files $uri $uri/ /index.html;
    }

    # Backend proxies (both prefixes target the same upstream)
    location /api/ {
      proxy_pass         http://backend;
      proxy_http_version 1.1;
      proxy_set_header   Host              $host;
      proxy_set_header   X-Real-IP         $remote_addr;
      proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
      proxy_set_header   X-Forwarded-Proto $scheme;
      proxy_read_timeout 60s;            # IR-013: Claude Vision up to 10s
      proxy_send_timeout 60s;
    }

    location /backend/ {
      # Strip /backend prefix (FastAPI piezas mount has no prefix).
      rewrite ^/backend/(.*)$ /$1 break;
      proxy_pass         http://backend;
      proxy_http_version 1.1;
      proxy_set_header   Host              $host;
      proxy_set_header   X-Real-IP         $remote_addr;
      proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
      proxy_read_timeout 60s;
    }
  }
}
```

### 4.2 docker-compose additions

New `frontend` and `nginx` services (added next to existing backend/db/redis/rabbitmq):

```yaml
services:
  frontend:
    build:
      context: ./ai-kitting-frontend
      dockerfile: Dockerfile             # multi-stage: node:20 build → output dist/
    volumes:
      - frontend_dist:/dist               # producer: copies dist/ → volume
    command: ["sh", "-c", "cp -r /app/dist/. /dist/ && tail -f /dev/null"]
    # OR simpler: one-shot build container + use bind-mount in nginx.

  nginx:
    image: nginx:1.27-alpine
    depends_on: [backend, frontend]
    ports:
      - "8080:80"                        # host:container — avoid clashing :80
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - frontend_dist:/usr/share/nginx/html:ro

volumes:
  frontend_dist:
```

Backend service additions (env block):

```yaml
  backend:
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_HOST: redis
      RABBITMQ_HOST: rabbitmq
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ANTHROPIC_MODEL: ${ANTHROPIC_MODEL:-claude-opus-4-6}
      DETECTION_STRATEGY: ${DETECTION_STRATEGY:-claude}
      CORS_ORIGINS: ${CORS_ORIGINS:-http://localhost:8080}
```

The `frontend` service is a one-shot dist builder; nginx mounts the volume
read-only. Simpler alternative if the team prefers: replace `frontend` service
with a `Dockerfile` for nginx that does multi-stage build + copy in one image
(documented as Open Question 7.4).

### 4.3 `.env.example`

`AI-Cup-/backend/.env.example`:
```
DATABASE_URL=postgresql://kitting:kitting@db:5432/kitting
REDIS_HOST=redis
RABBITMQ_HOST=rabbitmq
ANTHROPIC_API_KEY=sk-ant-...                 # required when DETECTION_STRATEGY=claude
ANTHROPIC_MODEL=claude-opus-4-6
DETECTION_STRATEGY=claude                    # claude | local (future)
CORS_ORIGINS=http://localhost:5173,http://localhost:8080
AWS_ACCESS_KEY_ID=                           # reserved
AWS_SECRET_ACCESS_KEY=                       # reserved
AWS_REGION=us-east-1                         # reserved
```

`ai-kitting-frontend/.env.example`:
```
VITE_API_BASE=/api
VITE_BACKEND_BASE=/backend
```

---

## 5. Sequence Diagrams

### 5.1 Create kit (picker flow)

```
User      CreateKitPage      PiezaPicker      kitsApi      FastAPI (kitRouter)      DB
 |             |                  |              |                |                  |
 |--name----→  |                  |              |                |                  |
 |             |---useQuery('piezas')-----------→| GET /backend/piezas/             |
 |             |                  |              |                |---select-------→|
 |             |                  |              |←──array─────── |←─rows──────────  |
 |             |←──piezas list────|              |                |                  |
 |--toggle──→  |---update selected map           |                |                  |
 |--save────→  |                  |              |                |                  |
 |             |---kitsApi.create(KitCreate)─→   | POST /api/kits/                  |
 |             |                  |              |---insert Kit───────────────────→ |
 |             |                  |              |←──KitRead────  |                  |
 |             |   for each item:                                                    |
 |             |---kitsApi.addItem(kit.id, …)──→ | POST /api/kits/{id}/items        |
 |             |                  |              |---insert link──────────────────→ |
 |             |                  |              |←─KitItemRead─  |                  |
 |←─navigate──/?id=kit.id                                                            |
```

### 5.2 Run inspection (SYNC, 5–10 s)

```
User   InspectionPage   inspectionsApi   FastAPI (inspeccionRouter)   factory   ClaudeStrategy   Anthropic   DB
 |          |                |                  |                       |             |              |        |
 |--upload->|                |                  |                       |             |              |        |
 |          |  submit(kit_id, image)            |                       |             |              |        |
 |          |---POST /api/inspections (multipart) ────────────────────→ |             |              |        |
 |          |                                   |--session.get(Kit)-----------------------------→ |        |
 |          |                                   |--get_strategy()------→|             |              |        |
 |          |                                   |←─ClaudeStrategy───────|             |              |        |
 |          |                                   |--strategy.detect(image, kit) ──────────────────→ |        |
 |          |   [user sees progress bar 5–10s]  |                       |             |--POST /v1/messages─→ |
 |          |                                   |                       |             |←──JSON──────         |
 |          |                                   |←──List[DeteccionResult]                                    |
 |          |                                   |--insert Inspeccion+Deteccion────────────────────────────→ |
 |          |                                   |←──InspeccionRead                                            |
 |          |←──InspeccionRead──────────────────|                                                             |
 |←──render──results page                                                                                     |
```

### 5.3 Future swap: LocalCVStrategy

Identical to 5.2 — the only box that changes is the strategy:

```
... |--strategy.detect(image, kit) ──→ LocalCVStrategy ──→ YOLO/ONNX inference (local) ──→ ...
```

No other component changes. This is what the abstraction buys us.

---

## 6. Slice-by-slice File Map

### S1 — Backend foundation (CORS + env + Kit + kitRouter)

**Created:**
- `AI-Cup-/backend/src/models/kit.py` (~70 LoC)
- `AI-Cup-/backend/src/routes/kitRouter.py` (~180 LoC)

**Modified:**
- `AI-Cup-/backend/src/main.py` — add CORSMiddleware, env vars for hosts, mount `kitRouter` (~25 LoC)
- `AI-Cup-/backend/src/db.py` — import `Kit, KitPiezaLink` (~2 LoC)
- `AI-Cup-/backend/requirements.txt` — no change yet (anthropic comes in S5)

**LoC estimate:** ~280 → within 400.  
**Dependencies:** none.  
**Acceptance test (manual):**
1. `docker compose up -d db && cd AI-Cup-/backend && uvicorn src.main:app`
2. `curl -X POST localhost:8000/api/kits/ -H 'Content-Type: application/json' -d '{"nombre":"Demo"}'` → 201 with UUID `id`.
3. `curl localhost:8000/api/kits/` → list contains the kit.
4. CORS: from browser console at `http://localhost:5173` run `fetch('http://localhost:8000/api/kits/')` → no CORS error.

---

### S2 — Backend inspections (models + router + filters)

**Created:**
- `AI-Cup-/backend/src/models/inspeccion.py` (~75 LoC)
- `AI-Cup-/backend/src/routes/inspeccionRouter.py` (~220 LoC)

**Modified:**
- `AI-Cup-/backend/src/main.py` — mount `inspeccionRouter` (~2 LoC)
- `AI-Cup-/backend/src/db.py` — import models (~2 LoC)

**LoC estimate:** ~300. **Risk:** crosses 400 if filtering grows. **Mitigation:**
defer `POST /api/inspections/` body to S5 (return 503 for now or stub with
empty `detecciones`) → keep S2 focused on history + CRUD endpoints.

**Dependencies:** S1 (Kit model exists for FK).  
**Acceptance test (manual):**
1. Seed: create a Kit via S1.
2. `curl localhost:8000/api/inspections/` → `[]`.
3. `curl 'localhost:8000/api/inspections/?kit_id=<uuid>&resultado_general=correcto'` → `[]`, no 500.
4. `POST /api/inspections/{id}/confirm` against a known inspection → 404 (no inspection yet — expected).

---

### S3 — Frontend ID migration + wire kits

**Modified:**
- `src/api/types.ts` (~10 LoC of edits)
- `src/api/kits.ts` (~10 LoC)
- `src/api/inspections.ts` (~8 LoC type fixes only)
- `src/api/backend.ts` — read `BACKEND_BASE` from constants (~2 LoC)
- `src/lib/constants.ts` — `import.meta.env` (~4 LoC)
- `src/store/kitStore.ts` — string IDs + persist key bump → eventually phase out (~10 LoC)
- `src/store/inspectionStore.ts` — `Record<string, …>` (~3 LoC)
- `src/pages/CreateKitPage.tsx` — use `PiezaPicker`, call real `kitsApi`, drop `useKitStore.addKit` (~60 LoC of edits)
- `src/pages/HomePage.tsx`, `HistoryPage.tsx`, `InspectionPage.tsx` — remove `parseInt`, use TanStack Query for kits list (~40 LoC across)
- Components: `Header.tsx`, `KitDetail.tsx`, `KitSelector.tsx`, `ItemTable.tsx`, `ComparisonView.tsx`, `ComparisonOverlay.tsx`, `HistoryFilters.tsx`, `HistoryTable.tsx`, `DataCleaningPage.tsx` — type-driven fixes only (~30 LoC total)

**Created:**
- `src/components/kit/PiezaPicker.tsx` (~80 LoC)
- `ai-kitting-frontend/.env.example` (~3 LoC)

**LoC estimate:** ~265 → within 400.  
**Dependencies:** S1 (real `/api/kits` available).  
**Acceptance test (manual):**
1. `npm run dev`. App still loads (kits list may be empty).
2. Create a kit through CreateKitPage with the picker → confirm via `curl /api/kits/` it's persisted.
3. Reload: kit appears in home (fetched from server, not localStorage).
4. `tsc -b` exits zero.

---

### S4 — Frontend wire inspections/history

**Modified:**
- `src/pages/HistoryPage.tsx` — drop `mockHistory` import, `useQuery(['inspections', filters], () => inspectionsApi.list(filters))` (~30 LoC)
- `src/pages/InspectionPage.tsx` — submit via `inspectionsApi.submit(kit_id, image)`; on success navigate to result (~30 LoC)
- `src/components/history/HistoryFilters.tsx` — call server-side filters (string IDs already done in S3) (~10 LoC)

**Deleted:**
- `src/mocks/history.ts`
- `src/mocks/inspectionResult.ts`
- `src/mocks/data.ts` (after verifying nothing else imports it)

**LoC estimate:** ~80 + deletions → well within 400.  
**Dependencies:** S2 (history endpoints), S3 (string IDs).  
**Acceptance test (manual):**
1. Submit an inspection from `InspectionPage`. With S5 not yet done, this expects
   `server.js` still running (sync 5–10 s via the Node sidecar) — confirm result
   stored in DB. If S5 done first, this hits FastAPI directly.
2. Open HistoryPage → see the new inspection. Apply a kit filter → list narrows.

---

### S5 — Port Claude Vision → FastAPI (`POST /api/inspections/`)

**Created:**
- `AI-Cup-/backend/src/services/detection/__init__.py` (~5 LoC)
- `AI-Cup-/backend/src/services/detection/base.py` (~30 LoC)
- `AI-Cup-/backend/src/services/detection/claude.py` (~110 LoC)
- `AI-Cup-/backend/src/services/detection/factory.py` (~25 LoC)

**Modified:**
- `AI-Cup-/backend/src/routes/inspeccionRouter.py` — wire `submit_inspection` to `get_strategy()` (~40 LoC)
- `AI-Cup-/backend/requirements.txt` — add `anthropic>=0.40` (~1 LoC)
- `ai-kitting-frontend/vite.config.ts` — `/api → :8000` (~2 LoC)
- `ai-kitting-frontend/package.json` — drop `express`, `multer`, `cors`, `@anthropic-ai/sdk`, scripts (~5 LoC)

**Deleted:**
- `ai-kitting-frontend/server.js`

**LoC estimate:** ~220. **Within 400.**  
**Dependencies:** S2 (Inspeccion model exists).  
**Acceptance test (manual):**
1. Stop `server.js`. `npm run dev` no longer starts a sidecar.
2. Submit inspection through UI → 5–10 s wait → result renders, DB has row.
3. Bad `DETECTION_STRATEGY=foo` → first request raises 500 with message naming `foo`
   and listing valid options.

---

### S6 — Production routing (nginx + docker-compose)

**Created:**
- `nginx/nginx.conf` (~40 LoC)
- `AI-Cup-/backend/.env.example` (~12 LoC)
- `ai-kitting-frontend/Dockerfile` (multi-stage build, ~15 LoC)

**Modified:**
- `docker-compose.yml` — add `frontend`, `nginx`, env block on `backend` (~30 LoC)

**LoC estimate:** ~95 → well within 400.  
**Dependencies:** all prior slices.  
**Acceptance test (manual):**
1. `docker compose up --build` → 6 services healthy.
2. Visit `http://localhost:8080/` → app loads.
3. Create kit → `POST http://localhost:8080/api/kits/` succeeds via nginx → backend.
4. Run inspection → 5–10 s wait → no 504 gateway timeout.

---

## 7. Open Technical Questions

All non-blocking. Recommended answer included.

1. **`KitPiezaLink` → `Pieza` access in `ClaudeVisionStrategy`.** The strategy
   needs `pieza_nombre` for the prompt, but `KitPiezaLink` does not store it.
   Options: (a) add an ORM `Relationship` to `Pieza` on the link + `selectin`
   on `kit.items` then `link.pieza.nombre`; (b) router pre-builds a
   `list[KitPiezaForPrompt]` dataclass and passes it via a thin wrapper.
   **Recommendation:** (a) — add `pieza: "Pieza" = Relationship()` on
   `KitPiezaLink` with `lazy="selectin"`. Cleanest, no router gymnastics.

2. **Anthropic SDK version.** Doc says `>=0.40`. **Recommendation:** pin to a
   minor (`anthropic>=0.40,<0.50`) in `requirements.txt` to avoid future
   breaking changes during the competition.

3. **`AsyncAnthropic` cancellation on FastAPI client disconnect.** Long
   sync requests held in `await` won't auto-cancel if the user closes the
   tab. **Recommendation:** acceptable for MVP. Add a `Request.is_disconnected()`
   check before persisting if it becomes an issue.

4. **Frontend `Dockerfile` strategy.** One-shot dist volume vs. dedicated
   nginx-with-dist image. **Recommendation:** start with the one-shot
   volume approach (simpler `docker-compose.yml`); switch to the single
   nginx image if it causes confusion during demo prep.

5. **`/api` proxy rewrite in Vite.** Backend mounts `/api/kits` etc., so the
   Vite proxy must NOT strip `/api`. **Recommendation:** verify acceptance
   test S5#3 manually — that confirms it.
