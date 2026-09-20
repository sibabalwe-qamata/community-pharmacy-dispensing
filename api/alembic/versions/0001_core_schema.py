"""Core schema: medicines, rule periods with a non-overlap constraint, attempts, dispenses.

Note `medicine.strength` is a single text column here — migration 0002 splits it into
value and unit, which is the data-moving migration the brief asks for.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "medicine",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("form", sa.String(32), nullable=False),
        sa.Column("strength", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "formulary_rule",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("medicine_id", sa.BigInteger, sa.ForeignKey("medicine.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("effective_to", sa.Date, nullable=True),
        sa.Column("max_quantity_per_dispense", sa.Integer, nullable=False),
        sa.Column("max_quantity_per_30_days", sa.Integer, nullable=False),
        sa.Column("requires_authorisation", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("effective_to IS NULL OR effective_to > effective_from", name="ck_rule_period_forward"),
        sa.CheckConstraint("max_quantity_per_dispense > 0", name="ck_rule_max_per_dispense_positive"),
        sa.CheckConstraint("max_quantity_per_30_days > 0", name="ck_rule_max_30_days_positive"),
    )
    op.create_index("ix_rule_medicine_from", "formulary_rule", ["medicine_id", "effective_from"])

    # The period is derived, never written by the application, and the EXCLUDE constraint
    # makes overlapping periods for one medicine impossible — including under concurrent
    # inserts, which application-level checks cannot guarantee.
    op.execute(
        """
        ALTER TABLE formulary_rule
        ADD COLUMN period daterange
        GENERATED ALWAYS AS (daterange(effective_from, effective_to, '[)')) STORED
        """
    )
    op.execute(
        """
        ALTER TABLE formulary_rule
        ADD CONSTRAINT ex_rule_no_overlap
        EXCLUDE USING gist (medicine_id WITH =, period WITH &&)
        """
    )

    op.create_table(
        "dispense_attempt",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("medicine_code", sa.String(32), nullable=False),
        sa.Column("patient_ref", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("dispensed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorisation_ref", sa.String(64), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("violations", postgresql.JSONB, nullable=True),
        sa.Column("response_body", postgresql.JSONB, nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_attempt_idempotency_key"),
        sa.CheckConstraint("outcome IN ('accepted', 'rejected')", name="ck_attempt_outcome"),
    )

    op.create_table(
        "dispense",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("medicine_id", sa.BigInteger, sa.ForeignKey("medicine.id", ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "attempt_id",
            sa.BigInteger,
            sa.ForeignKey("dispense_attempt.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("patient_ref", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("dispensed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorisation_ref", sa.String(64), nullable=True),
        sa.Column("rule_id", sa.BigInteger, sa.ForeignKey("formulary_rule.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_dispense_quantity_positive"),
    )

    op.create_table(
        "patient_medicine_lock",
        sa.Column("patient_ref", sa.String(64), primary_key=True),
        sa.Column(
            "medicine_id",
            sa.BigInteger,
            sa.ForeignKey("medicine.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("patient_medicine_lock")
    op.drop_table("dispense")
    op.drop_table("dispense_attempt")
    op.drop_index("ix_rule_medicine_from", table_name="formulary_rule")
    op.drop_table("formulary_rule")
    op.drop_table("medicine")
