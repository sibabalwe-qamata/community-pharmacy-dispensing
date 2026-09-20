#!/usr/bin/env bash
# Migrations apply automatically on every start, so `docker compose up` needs no manual steps.
set -euo pipefail

alembic upgrade head

exec "$@"
