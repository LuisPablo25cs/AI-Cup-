# Proposal: backend-frontend-integration

## Intent

Wire the React frontend to the real FastAPI backend end-to-end so the kitting-inspection demo runs without the temporary Node sidecar (`server.js`) and without MSW mocks for kits/inspections. Today the frontend talks to MSW + a Node Claude Vision proxy; the backend has piezas + the Blender/Trainer pipeline but no `Kit`/`Inspeccion` models. This change unblocks the competition demo (Friday) by closing the gap with the minimum surface area.

## Scope

### In Scope
- **Backend**: `Kit` + `KitPiezaLink` (FK to `Pieza`), `kitRouter`; `Inspeccion` + `Deteccion`, `inspeccionRouter` (CRUD + filters); SYNC `POST /inspections` with Claude Vision ported from `server.js`; nullable `imagen_s3_key` on `Inspeccion`; `CORSMiddleware`; env vars (`REDIS_HOST`, `RABBITMQ_HOST`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `CORS_ORIGINS`); `requirements.txt` updates.
- **Frontend**: ID type migration `number → string` (UUID) across `types.ts`, stores, pages; `CreateKitPage` picker over `GET /piezas/`; wire `kitsApi`, `inspectionsApi`, `InspectionPage`, `HistoryPage` to real backend; `import.meta.env` for base URLs; remove kit/inspection MSW handlers; remove `server.js` (last slice, optional).
- **Ops**: `nginx.conf` + docker-compose frontend service; `.env.example` on both sides.

### Out of Scope
- Tests (no runner configured — follow-up).
- Alembic migrations (use `create_all` — follow-up).
- Real CV at `/find-objects` (Claude Vision is inspection backend for now).
- Auth / user management.
- S3 upload for inspection images (nullable column reserved).
- Refactoring Blender/Trainer pipelines.

## Capabilities

### New Capabilities
- `kits-catalog`: Kit + KitPieza entities and CRUD, referencing catalog `Pieza` by UUID.
- `inspections`: Inspection execution (SYNC Claude Vision) + history with filters; Inspeccion + Deteccion entities.
- `integration-runtime`: CORS, env-driven hostnames, prod routing (nginx), API base URLs via `import.meta.env`.

### Modified Capabilities
- None (piezas + pipeline endpoints remain unchanged; additive only).

## Approach

Backend additive: new models with FKs to `Pieza`, new routers mounted in `main.py`, `CORSMiddleware`, env-var-ize Redis/RabbitMQ hostnames. Frontend: migrate IDs first (TypeScript guides every fix), then wire kits, then inspections/history, then port Claude Vision into FastAPI and drop the Node sidecar. Prod: nginx in front; backend `:8000` internal, frontend as static.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `AI-Cup-/backend/src/models/` | New | `kit.py`, `inspeccion.py` |
| `AI-Cup-/backend/src/routes/` | New | `kitRouter.py`, `inspeccionRouter.py` |
| `AI-Cup-/backend/src/main.py` | Modified | Mount routers, add `CORSMiddleware` |
| `AI-Cup-/backend/src/runserver.py` + workers | Modified | Env vars for Redis/RabbitMQ hostnames |
| `AI-Cup-/backend/requirements.txt` | Modified | Add `anthropic` |
| `ai-kitting-frontend/src/api/{types,client,backend}.ts` | Modified | UUID strings, real endpoints, env URLs |
| `ai-kitting-frontend/src/store/*.ts` | Modified | `Record<string,…>` |
| `ai-kitting-frontend/src/pages/{CreateKitPage,InspectionPage,HistoryPage}.tsx` | Modified | Wire real APIs, pieza picker |
| `ai-kitting-frontend/src/mocks/` | Removed (kits/inspections) | Drop handlers |
| `ai-kitting-frontend/server.js` | Removed (S5, optional) | Replaced by FastAPI `/inspections` |
| `ai-kitting-frontend/vite.config.ts` | Modified | Proxy `/api → :8000`, drop `:3001` |
| `nginx.conf`, `docker-compose.yml`, `.env.example` | New | Prod routing + env templates |

## Delivery Slices (Review Workload)

6 slices, dependency-ordered, each ≤ ~400 lines.

| Slice | Title | Est. Lines | Depends on |
|-------|-------|-----------|------------|
| S1 | Backend foundation (CORS + env + Kit + kitRouter) | ~150 | — |
| S2 | Backend inspections (Inspeccion + Deteccion + router + filters) | ~200 (watch) | S1 |
| S3 | Frontend ID migration + wire kits (picker + drop mocks) | ~180 | S1 |
| S4 | Frontend wire inspections/history | ~130 | S2, S3 |
| S5 | Port Claude Vision → FastAPI `POST /inspections` (sync), delete `server.js`, fix Vite proxy *(OPTIONAL)* | ~150 | S2 |
| S6 | Prod ops: nginx + docker-compose + `.env.example` *(OPTIONAL)* | ~80 | S1..S4 |

**Parallelism**: S2 ∥ S3 after S1; S5 ∥ S4 after S2.
**S2 overrun plan**: if it crosses 400 lines, split off `S2b` (list + filters) leaving S2 as models + create/get/update/delete.
**400-line budget risk: Medium** (S2). **Chained PRs recommended: Yes**. **Delivery strategy**: `ask-on-risk` (cached).

## Risks

| ID | Severity | Status |
|----|----------|--------|
| IR-001 CORS | High | addressed-in-S1 |
| IR-002 Hardcoded Redis/RabbitMQ hosts | Med | addressed-in-S1 |
| IR-003 ID type mismatch | High | addressed-in-S3 |
| IR-004 No `import.meta.env` | Med | addressed-in-S3 |
| IR-005 Vite proxy dev-only | Med | addressed-in-S5 + S6 |
| IR-006 `server.js` temporary | Med | addressed-in-S5 (or accepted-for-MVP if S5 skipped) |
| IR-007 Missing Kit/Inspeccion endpoints | High | addressed-in-S1 + S2 |
| IR-008 No Alembic | Med | accepted-for-MVP (follow-up) |
| IR-009 KitPieza identity gap | Med | addressed-in-S3 (picker over `/piezas/`) |
| IR-010 `claude-opus-4-6` hardcoded | Low | addressed-in-S5 (env `ANTHROPIC_MODEL`) |
| IR-011 MSW intercepts after wiring | Med | addressed-in-S3 + S4 (remove handlers) |
| IR-012 `create_all` multi-replica race | Low | out-of-scope (single replica) |
| **IR-013 (new)** Claude Vision 5–10 s sync may exceed nginx/uvicorn default timeouts | Med | addressed-in-S5/S6 (raise `proxy_read_timeout` to 60 s) |
| **IR-014 (new)** Schema drift between snapshot fields (`kit_nombre`, `pieza_nombre`) and live catalog edits | Low | accepted-for-MVP (snapshot is the intended behavior) |

## Rollback Plan

Per slice, revert the merge commit — slices are additive and dependency-ordered.
- S1/S2 rollback: drop the new tables (`kit`, `kit_pieza_link`, `inspeccion`, `deteccion`) and unmount routers; piezas + pipeline untouched.
- S3/S4 rollback: restore MSW handlers + revert ID migration commit (single commit per slice).
- S5 rollback: restore `server.js` and revert Vite proxy to `:3001`.
- S6 rollback: stop nginx; frontend dev server + backend `:8000` keep working directly.

## Dependencies

- `anthropic` Python SDK (new).
- Existing `Pieza` catalog populated (already true in dev).
- Anthropic API key in environment.

## Success Criteria

- [ ] Frontend dev runs against real FastAPI for kits, inspections, and history flows.
- [ ] After S5: `npm run dev` does not require `server.js`. If S5 skipped: documented in README that sidecar still runs.
- [ ] All existing `/piezas/*` and Blender/Trainer pipeline endpoints continue to work (no regressions).
- [ ] CORS allows configured origins (`CORS_ORIGINS` env).
- [ ] Backend hostnames (Redis, RabbitMQ) are env-driven, not hardcoded.
- [ ] MSW no longer intercepts kit/inspection routes.

## Follow-ups (Post-Competition)

- Add `pytest` + `ruff` (backend) and `vitest` + RTL (frontend); enable Strict TDD.
- Adopt Alembic.
- Replace Claude Vision with real CV at `/find-objects`.
- S3 image upload for inspection records (column already reserved).
- Async inspection flow if real CV is slow enough to warrant it.
