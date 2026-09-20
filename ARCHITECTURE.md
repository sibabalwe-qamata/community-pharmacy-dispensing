# Architecture

## The pieces

```
Browser ──▶ nginx (web/) ──/api──▶ FastAPI (api/app) ──SQLAlchemy──▶ Postgres
              │ static Angular         │
              │                        ├── routers/    thin HTTP adapters
              │                        ├── services/   one transaction per operation
              │                        ├── domain/     pure rule evaluation
              │                        └── core/       time, errors, pagination, config
              └── core/    ApiClient, typed DTOs, problem→field mapping
                  features/ one folder per view
```

Docker Compose runs three services: `db` (Postgres 16), `api` and `web`. The API
entrypoint runs `alembic upgrade head` before uvicorn starts, so a clean clone needs one
command. `web` builds the Angular app and serves it from nginx, which also proxies `/api`
to the API container — one origin for the browser, so CORS never applies in Docker.

## Layout

| Path | Holds |
|---|---|
| `app/main.py` | App assembly: routers mounted under `/api/v1`, error handlers |
| `app/dependencies.py` | Session, pagination, `Idempotency-Key`, stub identity |
| `app/routers/` | `medicines.py`, `rules.py`, `dispenses.py` — parse, call a service, serialise |
| `app/services/` | `catalogue.py`, `formulary.py`, `dispensing.py` — the database work, one transaction each |
| `app/domain/rule_engine.py` | Rule evaluation. No I/O |
| `app/core/` | `business_time.py`, `problems.py`, `pagination.py`, `config.py` |
| `app/db/` | `models.py` (SQLAlchemy models), `session.py` (engine, session factory) |
| `alembic/versions/` | `0001` core schema, `0002` splits `strength` into value + unit, `0003` listing indexes |
| `app/seed.py`, `app/perf.py` | Seed command and the p95 measurement |

## Where rule evaluation lives

All of it is in `app/domain/rule_engine.py`, in one function:

```python
evaluate(request, medicine, rules, neighbours, now) -> list[Violation]
```

It takes plain data and returns every violation it finds — never just the first, since a
rejection must report all of them. It has no database access, so all the awkward cases
(a rule change at midnight in Johannesburg, a backdated dispense, a window straddling
two rules) are unit-tested with no fixtures.

`app/services/dispensing.py` is the only caller. It supplies what the engine needs:

1. The idempotency record for this key, if any
2. A row lock on `(patient_ref, medicine_id)`
3. The medicine's rule history
4. Neighbouring dispenses — 29 days either side of `dispensed_at`, because a backdated
   dispense must fit both its own window and the windows of dispenses that came after it

It then writes the attempt, and a dispense only if there were no violations, in one commit.

## The frontend

Four lazily-loaded standalone views, state in signals, and the URL as the source of truth
for search terms, filters and cursors — so every view is linkable and survives a reload.

| Path | View | Endpoints |
|---|---|---|
| `/medicines` | Search | `GET /medicines` |
| `/medicines/:code` | Detail, rule timeline | `GET /medicines/{code}`, `GET /medicines/{code}/rules` |
| `/dispense` | Capture | `POST /dispenses` |
| `/patients` | Patient ledger | `GET /dispenses` |

`core/api-client.ts` turns every failure — including transport errors — into the API's
`Problem` shape, and `core/problem.ts` splits a rejection's violations into per-field
messages and a summary panel, so all reasons for a rejection are visible at once.

## Time

Instants are `timestamptz`, stored and compared in UTC. Rule periods and the 30-day
window are business dates in `Africa/Johannesburg`. `app/core/business_time.py` is the
only module that crosses between the two.

## Invariants held by the database, not by code

- `ex_rule_no_overlap` — an `EXCLUDE USING gist` constraint on `(medicine_id, period)`,
  where `period` is a generated `daterange`. Overlapping rule periods cannot be written,
  under any amount of concurrency.
- `uq_attempt_idempotency_key` — one attempt per idempotency key.
- `dispense.attempt_id` is unique, so an attempt can never produce two dispenses.
- `patient_medicine_lock` — the row locked while a dispense is evaluated, so two
  concurrent requests for one patient and medicine cannot jointly breach the 30-day limit.
