# AI usage

## Tools

Claude Code (Opus 5) as the main pair, with three Sonnet sub-agents used once, in
parallel, for the endpoint implementations.

## How the work was split

**Done by me, with the model as a drafting tool.** The domain glossary, the data model and
migrations, the rule engine, the error contract, pagination, business-time handling, the
seed and performance scripts, Docker, and every document here. These are the parts the
design lives in, so they were written and reviewed line by line rather than delegated.

**Delegated to sub-agents.** Three groups of endpoints — catalogue, rule history, and
dispensing — each given the module contracts to work against, each owning three files and
forbidden from touching shared modules. Grouping them this way meant one cold start per
group instead of one per endpoint, which is also why it was cheap.

The frontend was split the same way: I wrote the scaffolding, the typed DTOs, the HTTP
client, the problem-to-field mapping and both endpoint services, and three sub-agents
built the four views on top of them. Keeping the endpoint wiring out of the agents' hands
meant no view has to know a URL or a query-parameter name, and the agents could be given a
much smaller brief.

## Where their output was changed or rejected

- **Supersede would have failed on every mid-period rule change.** The agent trimmed the
  old period and inserted the new rule in the same flush. SQLAlchemy emits inserts before
  updates, and `ex_rule_no_overlap` is checked per statement, so the new row collided with
  the period that had not been shortened yet. I added an explicit flush between the two and
  a comment saying why the ordering matters.
- **Two `Page` classes.** One in `core/pagination.py` from the scaffolding, one in
  `schemas/common.py`. I deleted the first; pagination mechanics and the response model are
  different things and having both invited importing the wrong one.
- **A missed migration.** The catalogue agent reported it could not confirm the trigram
  indexes existed. They do, in `0003_listing_indexes.py`; the query it wrote matches them.
- **An unknown medicine code was a bare 404.** A dispense against a code that does not
  exist is an attempt the pharmacy made and could not complete, so it now writes a
  rejected attempt with a `MEDICINE_NOT_FOUND` violation against `medicine_code`, like
  every other rejection.
- **`ON CONFLICT DO NOTHING` on the lock row.** `DO NOTHING` neither inserts nor locks the
  conflicting row, so a concurrent inserter that then rolled back could leave the
  follow-up `SELECT ... FOR UPDATE` with nothing to lock. Changed to a no-op
  `DO UPDATE`, which always leaves the transaction holding the lock.
- **Private signals used in a template.** The capture view held `problem` and `created` as
  `private`, which Angular's strict template type-checking rejects — the generated
  type-check code reads them from outside the class. Both are now `protected`.
- **Nested `<main>` elements.** Three of the four views wrapped themselves in `<main>`,
  which the app shell already provides.
- **The domain imported FastAPI.** `Violation` lived in a module that also held the
  exception handlers, so the pure rule engine transitively imported the web framework —
  which is how the unit tests failed to run at all. The handlers moved to
  `core/error_handlers.py`; `core/problems.py` is now framework-free.
- The dispense service's structure — commit the attempt and *return* the rejection instead
  of raising — was specified up front rather than left to the agent, because getting it
  wrong loses the attempt log on every rejection and the mistake is invisible in a passing
  happy-path test.

## Before the code: a throwaway prototype

The 30-day window and the supersede semantics were worked out in a small terminal
prototype driven by hand, not by reasoning on paper. It is what surfaced two cases that
changed the design: a backdated dispense pushing a *later* window over its limit, and a
superseding rule silently extending cover into a gap. Both are recorded as assumptions in
`DECISIONS.md`. The prototype was deleted once the logic moved into
`app/domain/rule_engine.py`.

## What I would say in review

Every file here is one I can explain and change. The parts I would expect to be pressed on
— the exclusion constraint and the flush ordering it forces, the lock row and its
throughput cost, why rejections commit, and the later-window rule that goes beyond the
brief's literal wording — are the parts I wrote and tested myself.
