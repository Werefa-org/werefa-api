# Werefa Backend API

FastAPI backend for Werefa queueing and provider operations.

## Stack

- Python + FastAPI
- SQLModel / SQLAlchemy + Alembic
- PostgreSQL
- Optional Redis for cross-worker WebSocket fan-out
- `uv` for dependency and environment management

## Architecture

The app entrypoint is `werefa/main.py`. Routes are mounted under `/api/v1` and composed in `werefa/api/main.py`.

Feature domains follow a consistent layout:

- `werefa/<feature>/interface`: HTTP and WebSocket routers
- `werefa/<feature>/application`: use-case services
- `werefa/<feature>/infrastructure`: repository/persistence adapters
- `werefa/<feature>/domain`: domain models and policies

Core shared components:

- `werefa/core/config.py`: settings and environment loading
- `werefa/core/db.py`: database engine/session
- `werefa/core/security.py`: password hashing and JWT helpers
- `werefa/shared/models.py`: shared SQLModel entities

## Quick Start

### Option A: Docker Compose (recommended)

From the repository root:

```bash
docker compose watch
```

Useful local URLs:

- API: <http://localhost:8000>
- Swagger: <http://localhost:8000/docs>
- Adminer: <http://localhost:8080>
- Mailcatcher: <http://localhost:1080>

### Option B: Local backend process

From `backend/`:

```bash
uv sync
fastapi dev werefa/main.py
```

## Common Commands

Run these from `backend/` unless noted.

```bash
# Start dev API locally
fastapi dev werefa/main.py

# Run with production-style server settings
fastapi run werefa/main.py

# Run DB prestart (wait, migrate, seed superuser)
bash scripts/prestart.sh

# Populate demo businesses, users, services, and sample queues (idempotent)
uv run python scripts/seed_demo_data.py
uv run python scripts/seed_demo_data.py --reset   # wipe demo-* slugs & *@example.com demo users first

# Lint + type checks
bash scripts/lint.sh

# Format checks
sh scripts/format.sh

# Run tests with coverage
bash scripts/test.sh

# Run tests against already-running compose stack (from repo root)
docker compose exec backend bash scripts/tests-start.sh
```

## Environment

Settings are defined in `werefa/core/config.py` and loaded from `../.env` relative to `backend/` (repo-root `.env`).

Common required variables:

- `POSTGRES_SERVER`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `SECRET_KEY`
- `FIRST_SUPERUSER`
- `FIRST_SUPERUSER_PASSWORD`
- `ENVIRONMENT`
- `FRONTEND_HOST`

Important optional variables:

- `BACKEND_CORS_ORIGINS`
- `POSTGRES_SSLMODE`
- `SENTRY_DSN`
- `REALTIME_REDIS_URL`
- `SMTP_*` and `EMAILS_FROM_EMAIL` for email delivery
- `CLOUDINARY_URL` for KYC uploads (`cloudinary://api_key:api_secret@cloud_name` from the Cloudinary dashboard)
- Optional: `CLOUDINARY_FOLDER` (default `werefa/kyc`)

## API and Real-Time Notes

- HTTP API base path: `/api/v1`
- Local-only private routes are mounted only when `ENVIRONMENT=local`
- Queue streams are available over WebSockets under `/api/v1/ws`
- For multi-worker deployments, set `REALTIME_REDIS_URL`

## Migrations

From `backend/`:

```bash
alembic upgrade head
alembic revision --autogenerate -m "your migration message"
```

## Deployment

Cloud Build and Cloud Run deployment are defined in `../cloudbuild.yaml`.
The container starts with:

```bash
fastapi run --workers 1 --host 0.0.0.0 --port ${PORT:-8080} werefa/main.py
```

## Additional Docs

- Local development: `../development.md`
- Deployment details: `../deployment.md`
