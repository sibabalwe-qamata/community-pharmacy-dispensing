from decimal import Decimal

from .common import ORMModel
from .rule import RuleRead


class MedicineSummary(ORMModel):
    code: str
    name: str
    form: str
    strength_value: Decimal
    strength_unit: str
    is_active: bool


class MedicineDetail(MedicineSummary):
    current_rule: RuleRead | None = None
