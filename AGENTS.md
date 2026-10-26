# Project instructions

Public FastAPI service for Copart and IAAI lots. Python 3.13, Poetry, SQLAlchemy async, Alembic, Redis cache, gRPC clients.

## Commands

- `poetry run pytest` — run tests (`pythonpath` is `.`)
- `poetry run ruff format` and `poetry run ruff check --select I --fix` — format and sort imports (line length 88, target 3.13)
- `poetry run alembic upgrade head` — apply migrations (also run from `entrypoint.sh`)
- App entry: `main.py` (`uvicorn` on port 8001)

## Architecture

- Public HTTP routes live under `/public/v1`. Add them on `public_v1_router` in `main.py`. Follow `routers/v1/lots.py`.
- Request query/body models go in `request_schemas/`. Response models go in `schemas/` or `auction_api/types/`.
- Database access uses async SQLAlchemy sessions from `database/db/session.py`. New CRUD classes subclass `BaseService` in `database/crud/base.py`.
- Schema changes are Alembic revisions in `alembic/versions/`. Do not edit applied revisions.
- Settings come from `config.py` (`pydantic-settings`). Do not hardcode hosts, credentials, or feature flags.
- Log with `core.logger.logger`. Include `extra` context on request and failure logs.

## Boundaries

- Do not edit `rpc_server/gen/`. It is generated protobuf output and excluded from Ruff and pre-commit.
- `auction_type=timed` is valid only for IAAI (`site=2`). Other sites must keep returning 422.
- Current-lot list `size` max is 30. Keep that cap when adding search endpoints.
