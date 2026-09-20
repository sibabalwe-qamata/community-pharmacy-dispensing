# EMGuidance Formulary

Community pharmacy dispensing governed by a time-versioned formulary.

## Run

```bash
docker compose up --build
```

Brings up Postgres, the API and the web app. Migrations apply automatically on start.

- Web app: http://localhost:4200
- API: http://localhost:8000/api/v1
- OpenAPI docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

The web container serves the built Angular app and proxies `/api` to the API, so the
browser talks to one origin.

## Seed

```bash
docker compose exec api python -m app.seed
```

Loads 500 medicines, 3–5 rule periods each, and 2,000 dispenses across 2,000 patient
references over a two-year window. Rerunning it replaces the data.

## Test

```bash
docker compose exec api pytest
```

## Measure listing latency

```bash
docker compose exec api python -m app.perf
```

Reports p95 for each listing endpoint against the seeded dataset.

## Develop the frontend outside Docker

```bash
cd web && npm install && npm start
```

Serves on http://localhost:4200 and proxies `/api` to http://localhost:8000
(`web/proxy.conf.json`), so run the API with `docker compose up db api` alongside it.
