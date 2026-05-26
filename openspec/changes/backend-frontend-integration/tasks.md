# Tasks: backend-frontend-integration

## Review Workload Forecast

| Scope | Estimated changed lines | 400-line budget risk | 800-line budget risk | Chained PRs recommended | Suggested split (slices per PR) | Delivery strategy recommendation | Decision needed before apply |
|------|-------------------------|----------------------|----------------------|-------------------------|----------------------------------|----------------------------------|----------------------------|
| Whole change (S1–S6) | ~1,100–1,350 | High | Medium | Yes | PR1: S1; PR2: S3; PR3: S2; PR4: S4; PR5: S5; PR6: S6 | ask-on-risk | Yes |
| S1 | ~250–320 | Low | Low | No | PR1: S1 | ask-on-risk | No |
| S2 | ~280–420 | Medium | Low | Yes | PR3: S2 (split if list+filters grows) | ask-on-risk | Yes |
| S3 | ~220–330 | Low | Low | No | PR2: S3 | ask-on-risk | No |
| S4 | ~90–170 | Low | Low | No | PR4: S4 | ask-on-risk | No |
| S5 | ~180–300 | Low | Low | No | PR5: S5 | ask-on-risk | No |
| S6 | ~80–140 | Low | Low | No | PR6: S6 | ask-on-risk | No |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

Notes:
- S5 is only partially parallel-eligible after S1: the detection service modules can land after S1, but wiring `submit_inspection` in `inspeccionRouter.py` depends on S2 creating that router/model.

## Slice S1 — Backend foundation (CORS + env vars + Kit/KitPiezaLink + kitRouter)

- [x] 1.1 Backend: add `CORSMiddleware` with `CORS_ORIGINS` parsing in `AI-Cup-/backend/src/main.py`.
- [x] 1.2 Backend: replace hardcoded Redis/RabbitMQ hosts with `REDIS_HOST`/`RABBITMQ_HOST` env vars in `AI-Cup-/backend/src/main.py`.
- [x] 1.3 Backend: create SQLModel schemas `Kit` + `KitPiezaLink` in `AI-Cup-/backend/src/models/kit.py` (per design §2.1).
- [x] 1.4 Backend: create `AI-Cup-/backend/src/routes/kitRouter.py` implementing CRUD + item link endpoints (per design §2.2, specs kits-catalog).
- [x] 1.5 Backend: mount `kitRouter` and import new models for `create_all` in `AI-Cup-/backend/src/main.py` + `AI-Cup-/backend/src/db.py`.


Definition of Done (S1): `curl POST/GET /api/kits` works; browser fetch from `http://localhost:5173` has no CORS error; no hardcoded `redis`/`rabbitmq` host remains in backend.

## Slice S5 — (OPTIONAL) DetectionStrategy foundation + ClaudeVisionStrategy modules (parallel-safe portion)

- [ ] 5.1 Backend: add `AI-Cup-/backend/src/services/detection/{base.py,factory.py,__init__.py}` with `DetectionStrategy` + `DeteccionResult` + env-driven selection (design §2.3).
- [ ] 5.2 Backend: add `AI-Cup-/backend/src/services/detection/claude.py` as the only `anthropic` callsite; read `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL` (design §2.3, invariants #1/#5).
- [ ] 5.3 Backend: implement `KitPiezaLink -> Pieza` relationship (recommended design §7.1) so Claude prompt can use pieza names without router gymnastics (`AI-Cup-/backend/src/models/kit.py`).

Definition of Done (S5 partial): `get_strategy()` exists and fails fast on missing `ANTHROPIC_API_KEY`; no backend router imports `anthropic` directly.

## Slice S3 — Frontend ID migration (number→string UUID) + wire kits + PiezaPicker + delete kit mocks

- [x] 3.1 Frontend: migrate ID fields to `string` in `ai-kitting-frontend/src/api/types.ts` (incl. `Deteccion.id_pieza: string | null`).
- [x] 3.2 Frontend: update API modules for string IDs in `ai-kitting-frontend/src/api/{kits.ts,inspections.ts}` and env base paths in `ai-kitting-frontend/src/lib/constants.ts` + `ai-kitting-frontend/src/api/backend.ts`.
- [x] 3.3 Frontend: update Zustand stores for string IDs and bump persist key in `ai-kitting-frontend/src/store/{kitStore.ts,inspectionStore.ts}`.
- [x] 3.4 Frontend: add `ai-kitting-frontend/src/components/kit/PiezaPicker.tsx` backed by `GET /backend/piezas/` (design §3.2).
- [x] 3.5 Frontend: rewire `CreateKitPage` and kits flows to real `/api/kits/*` (TanStack Query), remove any remaining kit mock imports.
- [x] 3.6 Frontend: run `tsc -b` clean; fix remaining type errors in the listed 18 files (design §3.1).

Definition of Done (S3): app compiles; CreateKitPage creates a kit using real backend IDs; kits list renders from `GET /api/kits` (not local-only).

## Slice S2 — Backend inspections (Inspeccion+Deteccion models + inspeccionRouter CRUD+filters + imagen_s3_key nullable)

- [x] 2.1 Backend: create SQLModel schemas `Inspeccion` + `Deteccion` in `AI-Cup-/backend/src/models/inspeccion.py` (design §2.1, specs inspections).
- [x] 2.2 Backend: create `AI-Cup-/backend/src/routes/inspeccionRouter.py` with `GET /api/inspections` list + filters and `GET /{id}` detail (design §2.2, specs scenarios).
- [x] 2.3 Backend: implement `GET /{id}/result` returning `InspeccionResultRead` shape for UI result page.
- [x] 2.4 Backend: implement `POST /{id}/confirm` applying corrections (set `corregido_por_operador=true`, validate deteccion belongs to inspection).
- [x] 2.5 Backend: mount `inspeccionRouter` and import new models for `create_all` in `AI-Cup-/backend/src/main.py` + `AI-Cup-/backend/src/db.py`.

Definition of Done (S2): list endpoint supports `kit_id/resultado_general/fecha_desde/fecha_hasta/operador` filters without 500s; detail+result+confirm return 404/422 correctly per spec; `imagen_s3_key` persists as NULL.

## Slice S4 — Frontend wire inspections/history (delete mocks)

- [x] 4.1 Frontend: rewire `ai-kitting-frontend/src/pages/HistoryPage.tsx` to `inspectionsApi.list(filters)` via TanStack Query (design §3.3).
- [ ] 4.2 Frontend: rewire `ai-kitting-frontend/src/pages/InspectionPage.tsx` to submit multipart to `/api/inspections` via `inspectionsApi.submit` and navigate on success. **Implemented client-side multipart call shape and success handling; end-to-end submit remains blocked until S5 exposes `POST /api/inspections`.**
- [x] 4.3 Frontend: update `ai-kitting-frontend/src/components/history/HistoryFilters.tsx` to use server-side filters (string IDs already).
- [x] 4.4 Frontend: delete mock modules `ai-kitting-frontend/src/mocks/{history.ts,inspectionResult.ts,data.ts}` and remove imports.

Definition of Done (S4): submitting an inspection shows a persisted result in HistoryPage; no mock imports remain; UI works with real backend history filters.

## Slice S5 — (OPTIONAL) Wire DetectionStrategy into POST /api/inspections + delete server.js + Vite proxy /api→:8000

- [ ] 5.4 Backend: update `submit_inspection` in `AI-Cup-/backend/src/routes/inspeccionRouter.py` to call `get_strategy().detect(...)`, resolve `pieza_id` by name against kit-linked piezas, and persist detecciones (design §2.2 + §2.3).
- [ ] 5.5 Backend: add `anthropic` dependency to `AI-Cup-/backend/requirements.txt` (pin per design §7.2 if desired).
- [ ] 5.6 Frontend: delete `ai-kitting-frontend/server.js` and remove related scripts/deps from `ai-kitting-frontend/package.json` (design §3.5).
- [ ] 5.7 Frontend: update `ai-kitting-frontend/vite.config.ts` proxy so `/api` targets `http://localhost:8000` (no rewrite) and `/backend` continues to strip prefix (design §3.5).

Definition of Done (S5 full): `npm run dev` no longer starts a sidecar; UI inspection submit hits FastAPI and returns within ~10s; `DETECTION_STRATEGY=foo` fails fast with clear error; no hardcoded Claude model string remains.

## Slice S6 — (OPTIONAL) Prod ops (nginx timeout + docker-compose frontend+nginx + .env.example)

- [ ] 6.1 Ops: add `nginx/nginx.conf` with `/api` and `/backend` proxy rules and `proxy_read_timeout 60s` (design §4.1).
- [ ] 6.2 Ops: add `ai-kitting-frontend/Dockerfile` for multi-stage build producing static `dist/` (design §4.2).
- [ ] 6.3 Ops: update `docker-compose.yml` to add `frontend` + `nginx` services and backend env block (`REDIS_HOST`, `RABBITMQ_HOST`, `ANTHROPIC_*`, `DETECTION_STRATEGY`, `CORS_ORIGINS`) (design §4.2).
- [ ] 6.4 Ops: add `.env.example` files at `AI-Cup-/backend/.env.example` and `ai-kitting-frontend/.env.example` (design §4.3, specs integration-runtime).

Definition of Done (S6): `docker compose up --build` serves UI at `:8080`; `/api/*` and `/backend/*` routes work via nginx; slow inspections do not 504.
