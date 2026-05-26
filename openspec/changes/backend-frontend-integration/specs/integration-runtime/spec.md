# Integration Runtime Specification

**Capability:** integration-runtime  
**Change:** backend-frontend-integration  
**Phase:** spec  
**Date:** 2026-05-24  
**Status:** NEW (no prior spec — full spec)

---

## Purpose

Provide the runtime glue that connects the React frontend to the FastAPI backend
reliably in both development and production. This includes CORS policy,
environment-variable-driven configuration, Vite proxy reconfiguration for dev,
nginx reverse proxy for production, and docker-compose service definitions.

Addressed risks: IR-001 (CORS), IR-002 (hardcoded hosts), IR-004 (no
import.meta.env), IR-005 (Vite proxy dev-only), IR-013 (Claude Vision latency).

---

## Environment Variables

### Backend (`AI-Cup-/backend/`)

| Variable          | Required | Default            | Description                                     |
|-------------------|----------|--------------------|-------------------------------------------------|
| DATABASE_URL      | YES      | *(existing)*       | PostgreSQL connection string                    |
| REDIS_HOST        | NO       | `localhost`        | Redis host (use `redis` inside Docker Compose)  |
| RABBITMQ_HOST     | NO       | `localhost`        | RabbitMQ host (use `rabbitmq` inside Compose)   |
| ANTHROPIC_API_KEY | YES*     | *(none)*           | Required when `DETECTION_STRATEGY=claude`       |
| ANTHROPIC_MODEL   | NO       | `claude-opus-4-6`  | Anthropic model identifier                      |
| DETECTION_STRATEGY| NO       | `claude`           | See `specs/inspections/spec.md`                 |
| CORS_ORIGINS      | NO       | `http://localhost:5173` | Comma-separated list of allowed origins    |
| AWS_*             | NO       | *(existing)*       | S3 credentials (reserved; no upload MVP)        |

### Frontend (`ai-kitting-frontend/`)

| Variable          | Required | Default     | Description                                           |
|-------------------|----------|-------------|-------------------------------------------------------|
| VITE_API_BASE     | NO       | `/api`      | Base path for inspection/kit API calls                |
| VITE_BACKEND_BASE | NO       | `/backend`  | Base path for pieza/pipeline API calls                |

Both variables MUST be read via `import.meta.env` and MUST NOT be hardcoded in
source files. Absence of either variable MUST fall back to the defaults above
without error.

---

## CORS Middleware

The backend SHALL apply `CORSMiddleware` to all routes with the following
behavior:

- Allowed origins: parsed from `CORS_ORIGINS` env var (comma-separated)
- Allowed methods: `*`
- Allowed headers: `*`
- Credentials: not required for MVP

---

## Vite Proxy (Development Only — addresses IR-005 partially)

After S5 delivery, the Vite dev server proxy MUST route:

- `/api/*` → FastAPI on port 8000
- `/backend/*` → FastAPI on port 8000

Both prefixes MUST target the same backend process. The `:3001` Express sidecar
entry MUST be removed when `server.js` is deleted (S5).

---

## Production Routing via nginx

nginx MUST act as the single ingress for production:

- `GET /` and static asset requests → frontend static files
- `GET|POST|PUT|DELETE /api/*` → backend at port 8000
- `GET|POST|PUT|DELETE /backend/*` → backend at port 8000

nginx `proxy_read_timeout` MUST be set to at least 60 seconds to handle
`ClaudeVisionStrategy` latency of up to ~10 seconds (IR-013 mitigation).

nginx SHALL be a separate Docker Compose service (not folded into the frontend
image) for clarity and independent restartability.

---

## Docker Compose Services

The `docker-compose.yml` MUST define (at minimum) the following services:

| Service    | Description                              |
|------------|------------------------------------------|
| backend    | FastAPI on port 8000 (existing)          |
| frontend   | React build served as static (new)       |
| nginx      | Reverse proxy, exposes port 80 (new)     |
| db         | PostgreSQL (existing)                    |
| redis      | Redis (existing)                         |
| rabbitmq   | RabbitMQ (existing)                      |

---

## .env.example Files

Both projects MUST include a `.env.example` file at their root listing all
environment variables with placeholder or default values.

**Backend** (`AI-Cup-/backend/.env.example`): must include DATABASE_URL,
REDIS_HOST, RABBITMQ_HOST, ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
DETECTION_STRATEGY, CORS_ORIGINS, AWS_*.

**Frontend** (`ai-kitting-frontend/.env.example`): must include VITE_API_BASE,
VITE_BACKEND_BASE.

---

## Requirements

### Requirement: CORS Policy Enforcement

The backend SHALL allow cross-origin requests from origins listed in
`CORS_ORIGINS` and SHALL block requests from unlisted origins.

#### Scenario: Request from allowed origin is accepted

- GIVEN `CORS_ORIGINS=http://localhost:5173`
- AND the backend is running
- WHEN a browser sends a request from `http://localhost:5173`
- THEN the response includes `Access-Control-Allow-Origin: http://localhost:5173`
- AND the request is processed normally

#### Scenario: Request from disallowed origin is blocked

- GIVEN `CORS_ORIGINS=http://localhost:5173`
- WHEN a browser sends a preflight or request from `http://evil.example.com`
- THEN the response does NOT include an `Access-Control-Allow-Origin` header
  matching that origin
- AND the browser CORS policy blocks the response

#### Scenario: Multiple allowed origins via comma-separated CORS_ORIGINS

- GIVEN `CORS_ORIGINS=http://localhost:5173,http://localhost:4173`
- WHEN requests arrive from either origin
- THEN both are accepted
- AND requests from a third origin are blocked

---

### Requirement: Backend Env-Driven Host Configuration

The backend SHALL read Redis and RabbitMQ hostnames from environment variables,
defaulting to `localhost` when not set.

#### Scenario: Backend starts without REDIS_HOST set

- GIVEN `REDIS_HOST` is not present in the environment
- WHEN the backend starts
- THEN it attempts to connect to Redis at `localhost`
- AND the application starts without error (connection failure handled gracefully)

#### Scenario: Backend in Docker Compose uses service names

- GIVEN `REDIS_HOST=redis` and `RABBITMQ_HOST=rabbitmq` are set
- WHEN the backend starts inside Docker Compose
- THEN it connects to the `redis` and `rabbitmq` services by hostname
- AND no hardcoded hostname overrides this behavior

---

### Requirement: Frontend Env-Driven Base URLs

The frontend SHALL use `import.meta.env.VITE_API_BASE` and
`import.meta.env.VITE_BACKEND_BASE` for all API base paths, falling back to
`/api` and `/backend` respectively when the variables are absent.

#### Scenario: Frontend dev without VITE_BACKEND_BASE set

- GIVEN `VITE_BACKEND_BASE` is absent from the `.env` file
- WHEN the frontend dev server starts
- THEN all backend API calls use the path prefix `/backend`
- AND the Vite proxy routes `/backend/*` to FastAPI on port 8000
- AND no runtime error occurs due to the missing variable

#### Scenario: Frontend build with VITE_API_BASE set to production URL

- GIVEN `VITE_API_BASE=/api`
- WHEN `npm run build` produces the static bundle
- THEN all compiled API calls use `/api` as the base path
- AND nginx routes `/api/*` to the backend service

---

### Requirement: Production nginx Routing

nginx SHALL route all traffic to the correct upstream without requiring the
frontend to know the backend's internal port.

#### Scenario: Static frontend asset served by nginx

- GIVEN the nginx service is running and the frontend build is at the configured static root
- WHEN a browser requests `GET /`
- THEN nginx serves the React `index.html`

#### Scenario: API request routed to backend

- GIVEN nginx is running and backend is on port 8000
- WHEN a browser sends `POST /api/inspections` to nginx
- THEN nginx forwards the request to the backend
- AND the backend response is returned to the browser

#### Scenario: Slow inspection request succeeds within nginx timeout

- GIVEN `ClaudeVisionStrategy` takes 8 seconds to return
- AND `proxy_read_timeout 60s` is set in nginx.conf
- WHEN POST /api/inspections is forwarded by nginx
- THEN nginx waits up to 60 seconds for the backend response
- AND the response is returned to the browser with status 200 (not 504)

---

### Requirement: Docker Compose Service Definitions

The docker-compose.yml SHALL define frontend and nginx services alongside the
existing backend, db, redis, and rabbitmq services.

#### Scenario: Compose up starts all services

- GIVEN a configured `.env` file with all required variables
- WHEN `docker-compose up` is executed
- THEN all 6 services start without error
- AND nginx on port 80 proxies correctly to backend and frontend

---

### Requirement: .env.example Files

Both projects SHALL include a `.env.example` that documents every accepted
environment variable.

#### Scenario: Developer onboarding

- GIVEN a new developer clones the repository
- WHEN they copy `.env.example` to `.env` and fill in real values
- THEN the application starts in development mode without additional configuration
- AND no environment variable is silently missing

---

## Out of Scope for This Capability

- TLS/HTTPS termination (nginx HTTP only for competition MVP)
- CDN or external static hosting
- Multi-replica deployment (single replica for competition; IR-012 accepted)
- Authentication headers or session cookies in CORS policy
- CI/CD pipeline configuration
