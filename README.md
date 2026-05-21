# Freshbot Butler rewrite bootstrap

Freshbot Butler is now bootstrapped as a rewrite-ready monorepo slice with:

- `apps/frontend`: Next.js mobile-first shell with a German-first household entry flow and Today dashboard
- `freshbot_butler/api`: FastAPI backend for passwordless household access and Today data
- `freshbot_butler/worker`: PostgreSQL-backed worker entry point for pending jobs
- `packages/api-client`: generated TypeScript client from the FastAPI OpenAPI contract

## Local development

### Prerequisites

- Python 3.10+
- Node.js 22+
- `uv`

### Install dependencies

```bash
uv sync --extra dev
npm install
npm run generate:api-client
```

### Run tests

```bash
uv run pytest -q
npm run test:frontend
```

Voice capture uses the OpenAI transcription path by default. Set `FRESHBOT_TRANSCRIPTION_OPENAI_API_KEY`
before running the backend if you want to exercise audio upload/recording locally.

### Run the slice without Docker

Start the backend:

```bash
uv run uvicorn freshbot_butler.api.main:app --reload
```

Start the frontend in a second terminal:

```bash
cd apps/frontend
API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The frontend proxies `/api/*` calls to the backend, so the browser only needs the frontend origin.

Run the worker once in a third terminal:

```bash
uv run freshbot-worker --once
```

## Docker compose

Copy the example environment file and start the stack:

```bash
cp .env.example .env
docker compose up --build
```

Services:

- frontend: http://localhost:3000
- backend: http://localhost:8000/api/health
- postgres: localhost:5432

The worker polls PostgreSQL for pending jobs without extra queue infrastructure.

## API client generation

Regenerate the frontend contract after backend schema changes:

```bash
npm run generate:api-client
```

This exports FastAPI's OpenAPI schema and regenerates `packages/api-client/src/generated`.
