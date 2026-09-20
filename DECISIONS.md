# Decisions

Each entry: what I chose, what I considered instead, what I gave up.

---

## 1. Rule versioning: non-overlapping periods in one table, enforced by Postgres

`formulary_rule` holds one row per rule period, with `effective_from` and an exclusive
`effective_to` that may be NULL. A generated `daterange` column carries an
`EXCLUDE USING gist (medicine_id WITH =, period WITH &&)` constraint, so overlapping
periods for one medicine are impossible to write — not merely validated in the service.

Introducing a rule from date D trims the period in force to end at D. Rules are never
edited in place and never deleted: a dispense from March must still be explainable by the
rule row that governed it. A new rule whose start date equals an existing rule's start is
a 409 rather than a silent replacement, because replacing would rewrite the past.

**Considered instead.** (a) A `version` integer per medicine with `is_current`, which
makes "the rule in force on 12 March" a scan plus application logic, and makes overlap
unpreventable in the database. (b) Event sourcing the formulary, which answers more
questions than the brief asks and costs a projection to keep. (c) `tstzrange` instead of
dates: precise, but rule changes are announced by date in Johannesburg, so date ranges
say what is meant and read better in the API.

**Gave up.** Rules cannot be corrected in place — a mistake needs a new period.
Two rules cannot coexist for one medicine (no per-region formularies without a schema
change). The `EXCLUDE` constraint is checked per statement, so the service has to flush
the trim before inserting the new rule; that ordering is load-bearing and commented.

---

## 2. Concurrency: a lock row per (patient_ref, medicine), taken with SELECT ... FOR UPDATE

Two dispenses for the same patient and medicine must not jointly breach the 30-day limit.
`patient_medicine_lock` has one row per pair; the dispense transaction inserts it
(`ON CONFLICT DO NOTHING`) and locks it `FOR UPDATE` before reading the window. Everything
else — reading neighbours, evaluating, writing — happens inside that lock. Concurrent
requests for the *same* patient and medicine serialise; everything else runs in parallel.
Superseding a rule locks the medicine row for the same reason.

**Considered instead.** (a) `SERIALIZABLE` isolation with retries: correct, but every
caller must handle serialisation failures, and the retry budget is hard to reason about
under load. (b) Advisory locks keyed on a hash of patient and medicine: no extra table,
but hash collisions silently widen the lock and the key is invisible in the schema.
(c) A check constraint or trigger on a running total: the window is rolling and backdated
inserts change past sums, so there is no single total to constrain.

**Gave up.** A write for one patient and medicine is serialised, so repeated dispensing for
the same pair has a throughput ceiling. The lock table grows by one small row per pair.
At ten times the scale I would shard the lock table or move to advisory locks keyed by a
stored hash, and measure lock wait time before choosing.

**Tested by** `tests/test_concurrency.py`, which starts two real transactions on separate
connections and holds both at a barrier after they have read the window, so both see the
same total before either writes. Exactly one succeeds. The same test with the lock disabled
shows the limit being breached, which is what makes it a demonstration rather than a
coincidence of timing.

---

## 3. Pagination: keyset cursors everywhere

Listings order by a unique composite key — `(name, id)` for the catalogue,
`(dispensed_at DESC, id DESC)` for dispenses — and the cursor is that key,
base64url-encoded so clients treat it as opaque. Queries fetch `limit + 1` rows to decide
whether a next page exists.

**Considered instead.** Offset pagination, which the frontend's page-number UI would have
made slightly simpler. It degrades as the offset grows (Postgres still walks the skipped
rows) and it shifts rows under a reader when new dispenses arrive mid-scroll — bad for a
ledger that is written to constantly.

**Gave up.** No page numbers and no total count, so the UI offers "next" rather than
"jump to page 7". Cursors are not stable across a change of sort order.

---

## 4. Error contract: RFC 9457 problem+json with a machine-readable `errors` array

Every non-2xx response has the same shape: `type`, `title`, `status`, `detail`, a stable
`code`, and for rejections an `errors` array of `{code, field, message, rule_id}`.
Pydantic's own validation errors are rewritten into the same envelope, so the frontend has
one parser. `field` is what lets the dispense form attach each violation to the input that
caused it, and `rule_id` points at the rule row that was violated. Rejections carry every
violation, never just the first.

**Considered instead.** (a) FastAPI's default `{"detail": ...}`, which is either a string
or a list depending on the error and cannot carry a rule reference. (b) A bespoke
`{"success": false, "errors": [...]}` envelope, which is the same work without a standard
behind it.

**Gave up.** Slightly more verbose bodies, and problem+json is unfamiliar to some clients.

---

## 5. Indexing: trigram for search, composite indexes for the keyset listings and the window

- `gin (lower(name) gin_trgm_ops)` and the same on `lower(code)` — partial,
  case-insensitive search. Queries are written as `lower(col) LIKE lower(:pattern)` so they
  match the expression indexes.
- `(name, id)` — the catalogue's keyset order.
- `(patient_ref, dispensed_at DESC, id DESC)` and `(medicine_id, dispensed_at DESC, id DESC)`
  and `(dispensed_at DESC, id DESC)` — one per filter combination of the ledger.
- `(patient_ref, medicine_id, dispensed_at)` — the 30-day window sum, which is the query
  on the hot path of every dispense.

**Validated by** `python -m app.perf`: 200 requests per listing endpoint against the seeded
dataset after a warm-up, reporting p50/p95/max and failing if any p95 reaches 300ms.
`EXPLAIN ANALYZE` on each listing confirms an index scan rather than a sequential scan.

**Considered instead.** (a) `ILIKE '%q%'` with no trigram index — a sequential scan on
every keystroke. (b) Full-text search (`tsvector`), which is better for words but worse for
the partial-prefix matching a code lookup needs. (c) Leaving the window query to the
composite index on `(patient_ref, dispensed_at)`, which would filter by medicine in memory.

**Gave up.** Trigram GIN indexes are large and slow writes a little; the seed loads 500
medicines, so the cost is invisible here but would matter at catalogue-import scale.

---

## 6. Idempotency: the key is a promise about the payload

`POST /dispenses` requires an `Idempotency-Key` header. The attempt row stores a SHA-256
fingerprint of the normalised body along with the response that was sent. A repeat with the
same key and the same body replays the stored response and creates nothing. A repeat with
the same key and a *different* body is **422 `IDEMPOTENCY_KEY_REUSED`**: the request is
well-formed, so 400 is wrong, and it is not a state conflict on the resource, so 409 is
misleading. The IETF Idempotency-Key draft uses 422 for exactly this case. Two requests
carrying the same key at once are resolved by the unique index: the loser catches the
integrity error and replays the winner's response.

**Gave up.** Keys are stored forever (no expiry), so the attempt table grows; at scale
they would need a retention policy.

---

## 7. Rejections are persisted, and that is why the service does not raise

A rejected attempt must be logged *and* leave no dispense behind. Raising an exception to
produce the 422 would roll the transaction back and lose the log row. So the dispense
service writes the attempt, commits, and returns the rejection as a value; the router turns
it into the response. Only unexpected errors raise.

---

## 8. Assumptions (the brief asked for decisions, not questions)

1. **The 30-day window is 30 business dates** in Africa/Johannesburg, ending on the
   dispense's own date, not a rolling 720 hours. Window logic is specified in local terms,
   and the two readings differ by up to a day at the boundary.
2. **A backdated dispense is also checked against later windows.** Rule 3 only requires the
   dispense's own window, but recording 5 March after 20 March can leave the 20 March window
   over its limit with nobody told. A prototype of the rule engine showed this case clearly,
   so the engine checks every later window the new dispense falls into, each against the rule
   in force on *that* date, and reports `LATER_WINDOW_EXCEEDED`.
3. **Rules may start in the past.** Dispenses already accepted stay as they are — they were
   valid under the rule in force when they occurred. The alternative, re-validating history,
   would mean mutating accepted records.
4. **A superseding rule inherits the end date of the rule it supersedes** when no later rule
   follows. Otherwise superseding a rule that ended on 1 June would silently extend cover
   into a gap where dispenses used to be rejected for having no rule.
5. **`dispensed_at` must carry a timezone offset.** A naive timestamp is rejected as a field
   error rather than assumed to be UTC or local.
6. **A future `dispensed_at` is rejected** (`DISPENSED_IN_FUTURE`). Backdating is
   legitimate; forward-dating a dispensing event is not.
7. **`GET /medicines/{code}/rules` is not paginated.** A medicine has a handful of periods;
   pagination would be ceremony.
8. **Seeding writes rows directly** rather than going through the API. It is a fixture
   loader, and it only produces dispenses that satisfy the rule in force at their
   `dispensed_at`.
