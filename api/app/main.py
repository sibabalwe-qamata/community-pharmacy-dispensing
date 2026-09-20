from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.error_handlers import problem_handler, validation_handler
from .core.problems import ProblemError
from .routers import dispenses, medicines, rules

settings = get_settings()

app = FastAPI(
    title="EMGuidance Formulary API",
    version="1.0.0",
    description="Community pharmacy dispensing governed by a time-versioned formulary.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],  # the Angular dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ProblemError, problem_handler)
app.add_exception_handler(RequestValidationError, validation_handler)

app.include_router(medicines.router, prefix=settings.api_prefix)
app.include_router(rules.router, prefix=settings.api_prefix)
app.include_router(dispenses.router, prefix=settings.api_prefix)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
