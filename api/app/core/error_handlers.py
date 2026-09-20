"""FastAPI glue for the error contract. Registered in main.py."""
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .problems import CONTENT_TYPE, ProblemError, Violation, problem_body


def problem_response(problem: ProblemError) -> JSONResponse:
    return JSONResponse(
        problem_body(problem), status_code=problem.status, media_type=CONTENT_TYPE, headers=problem.headers
    )


async def problem_handler(_: Request, exc: ProblemError) -> JSONResponse:
    return problem_response(exc)


async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic shape errors use the same envelope as business-rule rejections."""
    violations = [
        Violation(
            code="INVALID_FIELD",
            field=".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path", "header")) or "body",
            message=err["msg"],
        )
        for err in exc.errors()
    ]
    return problem_response(
        ProblemError(422, "INVALID_REQUEST", "Invalid request", "The request body or query is invalid.", violations)
    )
