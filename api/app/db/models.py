from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Medicine(Base):
    __tablename__ = "medicine"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(String(32))
    strength_value: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    strength_unit: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rules: Mapped[list["FormularyRule"]] = relationship(back_populates="medicine")


class FormularyRule(Base):
    """One rule period for one medicine.

    effective_from/effective_to are business dates; effective_to is exclusive and may
    be NULL (open-ended). Non-overlap is enforced by an EXCLUDE constraint on the
    generated `period` column (see migration 0001) — application code cannot break it,
    even under concurrent writes.
    """

    __tablename__ = "formulary_rule"
    __table_args__ = (
        CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_rule_period_forward"),
        CheckConstraint("max_quantity_per_dispense > 0", name="ck_rule_max_per_dispense_positive"),
        CheckConstraint("max_quantity_per_30_days > 0", name="ck_rule_max_30_days_positive"),
        Index("ix_rule_medicine_from", "medicine_id", "effective_from"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicine.id", ondelete="CASCADE"))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    max_quantity_per_dispense: Mapped[int] = mapped_column(Integer)
    max_quantity_per_30_days: Mapped[int] = mapped_column(Integer)
    requires_authorisation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    medicine: Mapped[Medicine] = relationship(back_populates="rules")


class DispenseAttempt(Base):
    """Every attempt, accepted or rejected. Also the idempotency record."""

    __tablename__ = "dispense_attempt"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_attempt_idempotency_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))  # sha256 of the normalised body
    medicine_code: Mapped[str] = mapped_column(String(32))
    patient_ref: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    dispensed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authorisation_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16))  # accepted | rejected
    violations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[dict] = mapped_column(JSONB)
    response_status: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dispense: Mapped["Dispense | None"] = relationship(back_populates="attempt", uselist=False)


class Dispense(Base):
    """Only accepted attempts get one of these."""

    __tablename__ = "dispense"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_dispense_quantity_positive"),
        Index("ix_dispense_window", "patient_ref", "medicine_id", "dispensed_at"),
        Index("ix_dispense_patient_recent", "patient_ref", "dispensed_at", "id"),
        Index("ix_dispense_medicine_recent", "medicine_id", "dispensed_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicine.id", ondelete="RESTRICT"))
    attempt_id: Mapped[int] = mapped_column(ForeignKey("dispense_attempt.id", ondelete="RESTRICT"), unique=True)
    patient_ref: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    dispensed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authorisation_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("formulary_rule.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    medicine: Mapped[Medicine] = relationship()
    attempt: Mapped[DispenseAttempt] = relationship(back_populates="dispense")


class PatientMedicineLock(Base):
    """One row per (patient_ref, medicine_id), locked FOR UPDATE while a dispense is
    evaluated so two concurrent requests cannot jointly breach the 30-day limit."""

    __tablename__ = "patient_medicine_lock"

    patient_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicine.id", ondelete="CASCADE"), primary_key=True)
