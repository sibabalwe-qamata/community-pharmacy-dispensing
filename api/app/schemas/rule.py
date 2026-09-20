from datetime import date

from pydantic import Field

from .common import ORMModel


class RuleRead(ORMModel):
    id: int
    effective_from: date
    effective_to: date | None = Field(None, description="Exclusive; null means open-ended")
    max_quantity_per_dispense: int
    max_quantity_per_30_days: int
    requires_authorisation: bool


class RuleCreate(ORMModel):
    """A new rule introduced from `effective_from`, superseding what is in force."""

    effective_from: date
    max_quantity_per_dispense: int = Field(gt=0)
    max_quantity_per_30_days: int = Field(gt=0)
    requires_authorisation: bool = False
