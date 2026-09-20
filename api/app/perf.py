"""Measure first-page latency for every listing endpoint.

    docker compose exec api python -m app.perf

The brief asks for p95 under 300ms on the seeded dataset, and for how it was measured:
200 sequential requests per endpoint against the running container, after a short
warm-up, timed client-side inside the same Docker network so the number is the API's
own latency rather than the host's networking. Run `python -m app.seed` first.
"""
from __future__ import annotations

import statistics
import time

import httpx

BASE = "http://localhost:8000/api/v1"
REQUESTS = 200
WARMUP = 20

CASES: list[tuple[str, str, dict[str, str | int]]] = [
    ("GET /medicines", "/medicines", {"limit": 25}),
    ("GET /medicines?q=", "/medicines", {"q": "sta", "limit": 25}),
    ("GET /medicines/{code}", "/medicines/MED00001", {}),
    ("GET /medicines/{code}/rules", "/medicines/MED00001/rules", {}),
    ("GET /dispenses", "/dispenses", {"limit": 25}),
    ("GET /dispenses?patient_ref=", "/dispenses", {"patient_ref": "PT-00001", "limit": 25}),
]


def measure(client: httpx.Client, path: str, params: dict) -> list[float]:
    for _ in range(WARMUP):
        client.get(path, params=params)
    samples = []
    for _ in range(REQUESTS):
        started = time.perf_counter()
        response = client.get(path, params=params)
        response.raise_for_status()
        samples.append((time.perf_counter() - started) * 1000)
    return samples


def main() -> None:
    print(f"{REQUESTS} requests per endpoint after {WARMUP} warm-up requests\n")
    print(f"{'endpoint':<32}{'p50':>9}{'p95':>9}{'max':>9}   verdict")
    failures = 0
    with httpx.Client(base_url=BASE, timeout=30) as client:
        for label, path, params in CASES:
            samples = sorted(measure(client, path, params))
            p50 = statistics.median(samples)
            p95 = samples[int(len(samples) * 0.95) - 1]
            verdict = "ok" if p95 < 300 else "OVER 300ms"
            failures += p95 >= 300
            print(f"{label:<32}{p50:>8.1f}ms{p95:>8.1f}ms{samples[-1]:>8.1f}ms   {verdict}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
