"""The error contract: one shape for every non-2xx response.

    {
      "type": "https://emguidance.test/problems/dispense-rejected",
      "title": "Dispense rejected",
      "status": 422,
      "detail": "The dispense breaks 2 formulary rules.",
      "errors": [
        {"code": "MAX_PER_DISPENSE_EXCEEDED", "field": "quantity",
         "message": "...", "rule_id": 41}
      ]
    }

Routers never build this by hand: they raise a ProblemError (or return violations
from the domain) and the handlers in error_handlers.py render it.

This module is deliberately free of FastAPI imports: the domain layer raises and
carries these types, and the domain must not depend on the web framework.
"""
from dataclasses import asdict, dataclass
from typing import Any

PROBLEM_BASE = "https://emguidance.test/problems/"
CONTENT_TYPE = "application/problem+json"


@dataclass(frozen=True)
class Violation:
    """One broken rule, attributable to a field and (where relevant) a rule."""

    code: str
    field: str
    message: str
    rule_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        errors: list[Violation] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.errors = errors or []
        self.headers = headers or {}


class NotFound(ProblemError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(404, "NOT_FOUND", "Not found", f"{resource} {identifier!r} does not exist")


class Conflict(ProblemError):
    def __init__(self, code: str, detail: str, errors: list[Violation] | None = None) -> None:
        super().__init__(409, code, "Conflict", detail, errors)


class UnprocessableRequest(ProblemError):
    def __init__(self, code: str, detail: str, errors: list[Violation] | None = None) -> None:
        super().__init__(422, code, "Unprocessable request", detail, errors)


class DispenseRejected(ProblemError):
    """422 carrying every violation, so the frontend can mark each field at once."""

    def __init__(self, violations: list[Violation]) -> None:
        super().__init__(
            status=422,
            code="DISPENSE_REJECTED",
            title="Dispense rejected",
            detail=f"The dispense breaks {len(violations)} formulary rule(s).",
            errors=violations,
        )


def problem_body(problem: ProblemError) -> dict[str, Any]:
    """The response body as a dict, so it can be stored against an idempotency key
    and replayed byte-for-byte later."""
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + problem.code.lower().replace("_", "-"),
        "title": problem.title,
        "status": problem.status,
        "detail": problem.detail,
        "code": problem.code,
    }
    if problem.errors:
        body["errors"] = [v.as_dict() for v in problem.errors]
    return body
