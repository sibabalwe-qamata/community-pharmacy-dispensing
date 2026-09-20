"""Formulary rule-history endpoints."""
from fastapi import APIRouter, status

from ..db.models import FormularyRule
from ..dependencies import SessionDep
from ..schemas.common import ORMModel
from ..schemas.rule import RuleCreate, RuleRead
from ..services import formulary

router = APIRouter(prefix="/medicines", tags=["rules"])


class RuleHistoryRead(ORMModel):
    """The full rule history for a medicine, plus whichever rule is in force today."""

    items: list[RuleRead]
    in_force_rule_id: int | None


@router.get("/{code}/rules", response_model=RuleHistoryRead)
def list_rules(code: str, session: SessionDep) -> RuleHistoryRead:
    history = formulary.get_rule_history(session, code)
    return RuleHistoryRead(items=history.rules, in_force_rule_id=history.in_force_rule_id)


@router.post("/{code}/rules", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
def create_rule(code: str, data: RuleCreate, session: SessionDep) -> FormularyRule:
    return formulary.supersede_rule(session, code, data)
