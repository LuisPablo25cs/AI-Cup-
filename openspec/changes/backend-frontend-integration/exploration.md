# Exploration: backend-frontend-integration

**Change:** backend-frontend-integration  
**Phase:** explore  
**Date:** 2026-05-24  
**Author:** sdd-explore agent  

---

## Current State

The frontend (React + TS) and backend (FastAPI) are largely **decoupled** today:

- Frontend `kitsApi.*` and `inspectionsApi.*` call `/api/*` → proxied to Express `server.js` (port 3001), which only implements `POST /api/inspect` via Claude Vision. All other Kit/Inspection calls hit **MSW mocks** that never reach the network.
- Frontend `backendClient` / `piezasApi` hit `/backend/*` → proxied to FastAPI (port 8000) and work correctly for `Pieza` CRUD.
- `Kit` and `Inspeccion` entities have **no backend models, no routes, no tables**.
- The `POST /find-objects` endpoint in FastAPI exists as a stub (reads the file, opens it with Pillow, does nothing — no response returned, will 500 in production).
- `createAll` runs on startup → safe for adding new tables; unsafe for ALTER TABLE on existing ones.
- No CORS middleware; no `import.meta.env` usage; IDs are `number` in frontend, `UUID` in backend.

---

## Scope 1 — Kit & KitPieza Persistence in FastAPI

### Current State
- Frontend types: `Kit { id_kit: number, nombre, descripcion, activo, imagen_url?, ancho_cm?, largo_cm?, piezas: KitPieza[] }`
- `KitPieza { id_pieza: number, nombre, categoria, cantidad_requerida, ancho_cm?, alto_cm?, icono?, es_agrupacion, pos_x?, pos_y? }`
- `kitStore.ts` auto-generates `id_kit` as `maxId + 1` (localStorage persist). This state is ephemeral per browser.
- Backend has `Pieza` (a catalog of physical parts with UUID PK). **`KitPieza` in the frontend is NOT the same as `Pieza`** — it's a _join_ between a Kit and a catalog Pieza, with kit-specific metadata (position, quantity required, display info).

### Key Architectural Question
`KitPieza` in the frontend conflates:
1. A reference to a catalog `Pieza` (by `id_pieza`)
2. Kit-specific placement data (`pos_x`, `pos_y`, `ancho_cm`, `alto_cm`, `cantidad_requerida`)
3. Display metadata (`nombre`, `categoria`, `icono`, `es_agrupacion`)

This means `KitPieza` is a **join table** (`Kit ↔ Pieza`) enriched with layout data — analogous to `ModelPiezaLink`.

### Options

**Option A — Kit + KitPiezaLink join table (normalized)**
- `Kit` table: `id_kit UUID PK, nombre, descripcion, activo, ancho_cm, largo_cm, imagen_url, created_at`
- `KitPiezaLink` table: `id_kit UUID FK, id_pieza UUID FK, cantidad_requerida, pos_x, pos_y, ancho_cm, alto_cm, icono, es_agrupacion` (composite PK)
- Pros: normalized, aligns with existing `ModelPiezaLink` pattern, no data duplication
- Cons: requires JOIN on every `GET /kits/{id}`, slightly more complex queries
- Effort: Medium

**Option B — Kit + embedded KitPiezas as JSON column**
- `Kit` table: `id_kit UUID PK, nombre, descripcion, activo, ..., piezas JSONB`
- Pros: simplest possible model, single-table read, zero JOIN overhead, fast to implement
- Cons: can't query/filter by pieza efficiently, breaks normalization, harder to migrate later
- Effort: Low

**Option C — Kit + KitPieza denormalized table (pieza data copied)**
- `KitPieza` stores a snapshot of pieza display data (nombre, categoria, icono) copied at link time
- Pros: API response is flat, no JOIN needed for rendering
- Cons: data drift if catalog Pieza changes, duplication
- Effort: Low-Medium

### Recommendation
**Option A** — normalized join table. It mirrors the existing `ModelPiezaLink` pattern already in the codebase. The JOIN overhead is negligible at competition scale. SQLModel handles eager loading via `Relationship`. No Alembic needed — `create_all` will create new tables safely.

Migration strategy: pure additive (new tables only) → `create_all` handles it automatically. Zero risk.

### Open Questions
- Does `KitPieza.nombre/categoria` need to stay in sync with `Pieza.nombre`? If yes, Option A is required. If the kit snapshot is intentional, Option C is valid.
- Is `imagen_url` stored in S3 or is it derived? Skip for MVP?
- Should `KitPiezaLink` reference existing backend `Pieza` catalog, or can it reference piezas by name only (looser coupling)?

---

## Scope 2 — Inspections + History Persistence in FastAPI

### Current State
- Frontend mocks: `mockHistory` (35 hardcoded inspections), `mockInspectionResult()` (generates fake results per kit)
- `Inspeccion { id_inspeccion, id_kit, kit_nombre, fecha, resultado_general, similitud, tiempo_procesamiento, operador?, detecciones[] }`
- `Deteccion { id_deteccion, id_pieza, pieza_nombre, confianza, posicion_x_pct, posicion_y_pct, width_pct, height_pct, estado, corregido_por_operador? }`
- `InspeccionFilters`: by `id_kit`, `operador`, `fecha_desde`, `fecha_hasta`, `resultado_general`, `pieza_nombre`
- History filtering is done client-side today (`HistoryPage.tsx:67-89`)

### Schema Options

**Option A — Inspeccion + Deteccion as separate tables**
- `Inspeccion`: `id_inspeccion UUID PK, id_kit UUID FK, kit_nombre (snapshot), fecha, resultado_general, similitud, tiempo_procesamiento, operador, imagen_s3_key?`
- `Deteccion`: `id_deteccion UUID PK, id_inspeccion UUID FK, id_pieza UUID FK (nullable), pieza_nombre (snapshot), confianza, posicion_x_pct, posicion_y_pct, width_pct, height_pct, estado, corregido_por_operador`
- Pros: queryable, filterable by pieza on server side, proper relational model
- Cons: every inspection result = N rows in Deteccion; slightly heavier write
- Effort: Medium

**Option B — Inspeccion with detecciones as JSONB**
- `Inspeccion`: all fields + `detecciones JSONB`
- Pros: atomic write (one row), simpler model, perfect for MVP
- Cons: pieza-level filtering requires `jsonb_path_exists` (PostgreSQL supports it, but queries become awkward); harder to index
- Effort: Low

### Image Storage
- `InspectionPage.tsx` sends the image to `POST /api/inspect` (Claude Vision) but does NOT store it
- Options: (a) skip image storage in MVP — just store results, (b) upload to S3 before/after inference and store `key_s3` in `Inspeccion`
- **Recommendation for MVP**: skip image storage. Store only the inspection result. Add `imagen_s3_key` column as nullable so we can enable later without schema change.

### Filters
- `resultado_general`, `fecha_desde`, `fecha_hasta`, `id_kit`, `operador` → all filterable as WHERE clauses on `Inspeccion` table
- `pieza_nombre` filter → if using Option A: `JOIN Deteccion WHERE pieza_nombre LIKE %term%`. If using Option B: `jsonb_path_exists`.

### Recommendation
**Option A** — separate tables. At competition scale the join is trivial and the data model is correct. The `pieza_nombre` column in `Deteccion` is a snapshot (denormalized) to avoid needing to JOIN `Pieza` just to show history.

`id_pieza` in `Deteccion` should be **nullable UUID** — Claude Vision returns `pieza_nombre` from the prompt, not a real DB UUID. We match by name after the fact; if the pieza exists in catalog, we store the FK. If not (e.g., unknown part detected), we store NULL.

### Open Questions
- Do we need to store the inspection image? The demo might look better with it — but S3 adds operational complexity.
- Is `operador` a free-text string or a FK to a `User` table? (No user/auth system exists — keep it free-text for MVP.)
- Does the `/inspections` submit flow need to be synchronous (wait for CV result) or async (submit → poll)?

---

## Scope 3 — Inspection Execution Endpoint (Claude Vision → FastAPI)

### Current State
- `server.js` exposes `POST /api/inspect` (multipart: `image`, `piezas` JSON, `kit_nombre`)
- Returns `InspeccionResult`-shaped payload: `{ id_inspeccion, similitud, resultado_general, tiempo_procesamiento, detecciones[] }`
- `InspectionPage.tsx:55` calls `fetch('/api/inspect', ...)` directly (not via `apiClient`)
- FastAPI `POST /find-objects` reads the file, opens with Pillow, returns nothing (stub)

### Options

**Option A — Move Claude Vision INTO FastAPI immediately (delete server.js)**
- Build `POST /inspect` in FastAPI: accepts multipart (image + kit JSON), calls Anthropic API (add `anthropic` to requirements.txt), returns `InspeccionResult`
- Vite proxy: change `/api` → `:8000` (remove `:3001` entry)
- Pros: eliminates sidecar immediately, single backend, simpler ops, ANTHROPIC_API_KEY managed in one place
- Cons: Python `anthropic` SDK needed; adds dependency to backend; blocking call in FastAPI (must use `async` httpx or offload)
- Effort: Medium (port JS logic to Python, straightforward)
- Risk: Anthropic Python SDK is `async`-friendly, works well with FastAPI

**Option B — Keep server.js, update vite proxy to point /api/kits and /api/inspections to FastAPI**
- Split proxy: `/api/inspect` → `:3001`, `/api/kits` and `/api/inspections` → `:8000`
- Pros: no server.js changes needed now, decouple migration from kit/inspection work
- Cons: Vite proxy split is fragile, `/api` prefix now routes to TWO backends, deployment routing is nightmarish
- Effort: Low short-term, High long-term
- Risk: IR-005 (no prod routing) gets significantly worse

**Option C — Feature flag in FastAPI (stub → real)**
- `POST /inspect`: FastAPI endpoint, env var `CV_PROVIDER=claude|yolo|mock`
- `claude` → calls Anthropic, `yolo` → real YOLO inference, `mock` → returns dummy data
- Pros: clean swap path, stable contract, works for both competition and final
- Cons: slightly more code in the endpoint; requires `anthropic` lib in requirements
- Effort: Medium

### Recommendation
**Option A** for the competition. Move Claude Vision into FastAPI NOW. The port from JS to Python is ~80 lines, the logic is identical. This lets the team delete `server.js`, simplify Vite config, and have a single backend. If time permits, wrap it as Option C style with `CV_PROVIDER` env var for future YOLO swap.

**Stable contract** (regardless of option chosen):
```
POST /inspect
Content-Type: multipart/form-data
  image: File
  kit_nombre: string
  piezas: JSON string (array of KitPieza)

Response 200:
{
  id_inspeccion: string (UUID),
  similitud: number,
  resultado_general: "correcto" | "anomalia" | "error",
  tiempo_procesamiento: number,
  detecciones: [...]
}
```

### Open Questions
- Does the competition require real YOLO inference or is Claude Vision acceptable for the demo?
- Should `POST /inspect` also PERSIST the result to DB, or return only the result (client then calls a separate save endpoint)?
- Timeout risk: Claude Vision can take 5-10s. Need to handle in the UI (progress bar already exists).

---

## Scope 4 — ID Strategy Normalization

### Current State (from grep)
Files with `id_kit` (number): `types.ts`, `kits.ts`, `inspections.ts`, `kitStore.ts`, `HomePage.tsx`, `InspectionPage.tsx`, `Header.tsx`, `KitDetail.tsx`, `KitSelector.tsx`, `HistoryFilters.tsx`, `HistoryPage.tsx`, `history.ts`, `inspectionResult.ts`, `data.ts`

Files with `id_pieza` (number): `types.ts`, `CreateKitPage.tsx` (assigns `idx + 1`), `ItemTable.tsx`, `ComparisonView.tsx`, `ComparisonOverlay.tsx`, `history.ts`, `inspectionResult.ts`, `data.ts`, `inspectionStore.ts` (key type: `Record<number, Deteccion>`)

Files with `id_inspeccion` (number): `types.ts`, `inspections.ts`, `InspectionPage.tsx`, `HistoryTable.tsx`, `history.ts`, `inspectionResult.ts`

**Critical finding**: `InspectionPage.tsx:92` uses `parseInt(kitId)` to match a kit from URL params. `HistoryPage.tsx:69` uses `parseInt(f.kitId)`. `CreateKitPage.tsx:93` assigns `id_pieza: idx + 1`.

`backend.ts` already uses `string` for `BackendPieza.id_pieza` — the anti-corruption layer pattern is already established.

### Options

**Option A — Frontend migrates to UUID strings**
- Change all `id_*: number` → `id_*: string` in `types.ts`
- Update every consumer (14+ files)
- Route params become string-native (no `parseInt`)
- `inspectionStore.ts:50` → `corrections: Record<string, Deteccion>`
- Pros: correct long-term, single source of truth, no backend compromise
- Cons: touches 14+ files, risk of missing a comparison (=== vs ==)
- Effort: Medium (mechanical but wide)

**Option B — Backend exposes numeric surrogate keys**
- Add `serial` or `bigint` auto-increment surrogate to `Kit`, `Inspeccion`, `Deteccion`
- Expose as the primary key in API responses
- Keep UUID internal
- Pros: frontend changes nothing
- Cons: pollutes backend model, anti-pattern, confuses future developers, inconsistent with existing `Pieza` which returns UUID
- Effort: Medium-Low (add columns, change serializers)
- Risk: HIGH — introduces permanent tech debt

**Option C — Hybrid: UUIDs in API, number in URL only**
- Frontend types use `string` for IDs
- URLs remain `/kit/:id` where `id` is UUID string (React Router handles it fine)
- Pros: clean types, no backend compromise, URL is still human-copyable
- Cons: same migration scope as Option A
- Effort: Same as A

### Recommendation
**Option A / C** (they're the same thing in practice). Migrate frontend to `string` IDs. The grep shows ~14 files affected but the changes are **mechanical and type-driven** — TypeScript will catch every missed spot at compile time (`tsc -b`). The `parseInt` usages disappear naturally.

**Migration approach**: change `types.ts` first → let TypeScript errors guide the remaining fixes. Estimated 40-60 lines of changes spread across files. Clean, testable, no backend work.

`Record<number, Deteccion>` in `inspectionStore` → `Record<string, Deteccion>` (one-liner).

---

## Scope 5 — CORS + Env Vars + Production Routing

### Current State
- `main.py:32,44`: `host="rabbitmq"`, `host="redis"` — hardcoded Docker service names
- `db.py:10`: `DATABASE_URL = os.getenv("DATABASE_URL")` — already env-var (good)
- `constants.ts:27`: `API_BASE = '/api'` — hardcoded
- `backend.ts:3`: `BACKEND_BASE = '/backend'` — hardcoded
- Vite proxy: `/api → :3001`, `/backend → :8000`
- No `CORSMiddleware` in FastAPI
- No `.env` files in either repo

### CORS Options

**Option A — Dev-only CORS (allow localhost origins)**
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
```
- Pros: simple, env-configurable, safe
- Cons: wildcard methods/headers — acceptable for competition MVP
- Effort: Low (5 lines)

**Option B — Wildcard (allow all origins)**
- `allow_origins=["*"]`
- Pros: zero config
- Cons: not safe for production with credentials
- Effort: Minimal

### Env Vars Strategy
Minimum viable env vars for competition:
```
# Backend
DATABASE_URL=... (already done)
REDIS_HOST=redis (new)
RABBITMQ_HOST=rabbitmq (new)
ANTHROPIC_API_KEY=... (new — for /inspect)
CORS_ORIGINS=http://localhost:5173 (new)

# Frontend
VITE_API_BASE=/api (replaces hardcoded '/api')
VITE_BACKEND_BASE=/backend (replaces hardcoded '/backend')
```

### Production Routing Options

**Option A — nginx reverse proxy (single host)**
```nginx
location /api/    { proxy_pass http://backend:8000/; }
location /backend/ { proxy_pass http://backend:8000/; }
location /        { root /usr/share/nginx/html; try_files $uri /index.html; }
```
- Merge `/api` and `/backend` into one prefix if backend consolidation is complete
- Pros: battle-tested, simple, Docker Compose friendly
- Cons: need nginx container in compose
- Effort: Low (nginx.conf is ~15 lines)

**Option B — Serve frontend from FastAPI**
```python
app.mount("/", StaticFiles(directory="dist", html=True), name="frontend")
```
- Pros: single process, single port, zero nginx
- Cons: need to `npm run build` and copy `dist/` into backend container; couples release cycles
- Effort: Low-Medium

**Option C — Separate deployments (frontend on CDN/Vercel, backend on VPS)**
- Pros: proper decoupling, CDN for assets
- Cons: CORS becomes mandatory (not just dev nice-to-have), two deploy targets
- Effort: Medium-High

### Recommendation for Competition MVP
- **CORS**: Option A (env-configurable origins, allow all methods)
- **Env vars**: minimal set above, `.env.example` for both repos
- **Production routing**: **Option A (nginx)** — add one `nginx.conf` and one service to `docker-compose.yml`. This is the standard pattern for this stack and keeps frontend/backend separate containers.

If time is EXTREMELY tight: Option B (serve from FastAPI) is a valid "just ship it" move — one container, one port, demo works.

---

## Scope 6 — Delivery Slicing

### Dependency Graph

```
Slice 1 (CORS + env + Kit model)
  └── Slice 2 (Inspections model) — depends on Kit UUID
        └── Slice 4 (wire frontend inspections) — depends on Slice 3
  └── Slice 3 (frontend ID migration + wire kits) — depends on Slice 1
        └── Slice 4
Slice 5 (swap server.js → FastAPI /inspect) — depends on Slice 1 (CORS), mostly independent
Slice 6 (production deploy) — depends on everything
```

### Proposed Slices

| Slice | Title | Key work | Est. lines | Risk of overrun |
|-------|-------|----------|------------|-----------------|
| **S1** | Backend foundation | CORS middleware, env vars (redis/rabbitmq/anthropic), `Kit` + `KitPiezaLink` SQLModel models, `kitRouter.py` (CRUD), update `db.py` imports | ~120-150 | Low |
| **S2** | Backend inspections | `Inspeccion` + `Deteccion` SQLModel models, `inspeccionRouter.py` (submit, getResult, list+filters, confirmDetections), update `db.py` | ~180-220 | MEDIUM — list + filters endpoint can balloon |
| **S3** | Frontend ID migration + wire kits | `types.ts` → string IDs, fix all consumers (TypeScript-guided), remove Zustand localStorage kit store, wire `kitsApi.*` to real backend via TanStack Query | ~150-200 | MEDIUM — many files but mechanical |
| **S4** | Frontend wire inspections/history | Remove `mockHistory`, wire `inspectionsApi.*`, replace `HistoryPage` to use TanStack Query, wire `InspectionPage` to save results | ~100-130 | Low |
| **S5** | Swap server.js → FastAPI /inspect | Port Claude Vision logic to Python, `POST /inspect` in FastAPI (+ persist result to DB), update Vite proxy `/api → :8000`, delete `server.js` | ~120-150 | Low-Medium |
| **S6** | Production deploy | `nginx.conf`, update `docker-compose.yml`, `.env.example` files, VITE env vars in frontend build | ~60-80 | Low |

### Line Budget Assessment
- S1: ~150 lines → **within 400**
- S2: ~200 lines → **within 400** (watch endpoint count)  
- S3: ~180 lines → **within 400** (spread across many files, each small)
- S4: ~130 lines → **within 400**
- S5: ~150 lines → **within 400**
- S6: ~80 lines → **within 400**

**None of these slices should overrun the 400-line budget** IF scoped correctly. S2 is the one to watch — if we add filtering logic + pagination it can grow.

### Recommended Order
S1 → S5 (can run in parallel with S1, only needs CORS) → S3 → S2 → S4 → S6

S5 can start as soon as S1 CORS is merged (the `/inspect` endpoint doesn't depend on Kit/Inspeccion models — it's a stateless Claude Vision call). This parallelism saves time in a competition context.

---

## Affected Areas

- `AI-Cup-/backend/src/main.py` — CORS, env vars, remove hardcoded hosts
- `AI-Cup-/backend/src/db.py` — add Kit, KitPiezaLink, Inspeccion, Deteccion imports
- `AI-Cup-/backend/src/models/` — new: `kit.py`, `inspeccion.py`
- `AI-Cup-/backend/src/routes/` — new: `kitRouter.py`, `inspeccionRouter.py`
- `AI-Cup-/backend/requirements.txt` — add `anthropic`
- `ai-kitting-frontend/src/api/types.ts` — ID types `number → string`
- `ai-kitting-frontend/src/api/kits.ts` — update ID param types
- `ai-kitting-frontend/src/api/inspections.ts` — update ID param types
- `ai-kitting-frontend/src/api/client.ts` — read `VITE_API_BASE`
- `ai-kitting-frontend/src/api/backend.ts` — read `VITE_BACKEND_BASE`
- `ai-kitting-frontend/src/lib/constants.ts` — read `VITE_API_BASE`
- `ai-kitting-frontend/src/store/kitStore.ts` — remove localStorage, replace with TanStack Query
- `ai-kitting-frontend/src/store/inspectionStore.ts` — `Record<number,Deteccion> → Record<string,Deteccion>`
- `ai-kitting-frontend/src/pages/InspectionPage.tsx` — remove `parseInt(kitId)`, use real API
- `ai-kitting-frontend/src/pages/HistoryPage.tsx` — remove mock import, use TanStack Query
- `ai-kitting-frontend/src/pages/CreateKitPage.tsx` — wire `kitsApi.create`, handle UUID
- `ai-kitting-frontend/src/mocks/data.ts` — can be kept for development fallback or removed
- `ai-kitting-frontend/vite.config.ts` — update proxy config
- `ai-kitting-frontend/server.js` — DELETE after S5

---

## Risks

### New Risks (beyond IR-001..IR-008)

**IR-009 (MEDIUM): `KitPieza` identity gap**  
Frontend `KitPieza.id_pieza` currently is a local sequential integer (assigned as `idx + 1` in `CreateKitPage.tsx:93`). These are NOT real Pieza catalog UUIDs. When we wire to the real backend, the question is: do `KitPieza`s reference the `pieza` catalog table (by UUID) or are they independent kit-specific items? If the team intends to link them to catalog piezas, the "add item to kit" flow needs a pieza picker (not a free-form form). This is a **product decision** that blocks S1 design.

**IR-010 (LOW): Claude Vision model ID hardcoded in server.js**  
`server.js:76` hardcodes `model: 'claude-opus-4-6'`. When ported to FastAPI, this must become an env var `ANTHROPIC_MODEL` to allow downgrade (opus-4-6 is expensive).

**IR-011 (MEDIUM): MSW mocks intercept ALL `/api` requests**  
If MSW is active in dev mode, it will intercept `kitsApi` and `inspectionsApi` calls even after wiring to real backend. Need to verify MSW handler config and update/remove handlers for migrated endpoints. Check `src/mocks/handlers.ts` or equivalent.

**IR-012 (LOW): `create_all` race on first deploy**  
`db.py:init_db` uses `create_all` at startup. If two backend replicas start simultaneously, there's a race on table creation. For competition single-replica deploy, this is a non-issue. Flag for production.

---

## Open Questions (must resolve before propose)

1. **Kit↔Pieza coupling**: Do `KitPieza` items reference the `pieza` catalog (by UUID), or are they independent items defined per-kit? This determines whether "add item to kit" = pick from catalog or = free-form creation.

2. **Inspection flow: sync or async?** Does `POST /inspections` wait for Claude Vision result (sync, 5-10s) or return immediately and client polls? The current `server.js` is sync. TanStack Query + the existing progress bar UI suggest sync is fine for MVP.

3. **Image persistence**: Store inspection image in S3 or skip for MVP?

4. **MSW handlers**: Are there MSW handlers for `/api/kits` and `/api/inspections`? Need to confirm they exist and will intercept (blocking real backend calls in dev).

5. **`operador` field**: Free-text string or FK to auth? (Assume free-text for MVP — no auth system exists.)

6. **Competition timeline**: How many days/hours remain? Affects whether S5 (server.js elimination) is worth doing now vs. after demo.

---

## Ready for Proposal
**Yes** — with the open questions flagged above surfaced to the user.  
The two blocking questions are #1 (Kit↔Pieza coupling) and #2 (sync vs async inspection). Everything else can be decided by the AI during propose with sensible defaults for a competition MVP.
