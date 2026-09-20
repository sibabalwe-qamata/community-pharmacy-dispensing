from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    """Every listing returns this shape."""

    items: list[T]
    page_size: int
    next_cursor: str | None = None


class ProblemDetail(BaseModel):
    """Documents the error contract in the OpenAPI schema (see core/problems.py)."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    errors: list[dict[str, Any]] | None = None
