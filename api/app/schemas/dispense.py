"""Request/response shapes for the dispense endpoints.

Timestamps travel over the wire with an explicit UTC offset; the domain and storage
only ever deal in UTC. A naive `dispensed_at` is rejected here, as a field-level
validation error, rather than the service silently guessing a timezone for it.
"""
from datetime import datetime, timezone

from pydantic import Field, field_validator

from .common import ORMModel


class DispenseCreate(ORMModel):
    medicine_code: str
    patient_ref: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)
    dispensed_at: datetime
    authorisation_ref: str | None = None

    @field_validator("dispensed_at")
    @classmethod
    def _require_offset_and_normalise(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(
                "dispensed_at must include a UTC offset, e.g. '2026-01-01T10:00:00+02:00'"
            )
        return value.astimezone(timezone.utc)


class DispenseRead(ORMModel):
    id: int
    medicine_code: str
    patient_ref: str
    quantity: int
    dispensed_at: datetime
    authorisation_ref: str | None = None
    rule_id: int
    created_at: datetime
