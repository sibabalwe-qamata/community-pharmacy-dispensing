"""Indexes that serve the listing endpoints and the 30-day window lookup.

Kept separate from 0001 so the indexing strategy has its own reviewable step
(see DECISIONS.md): trigram indexes for partial search, composite indexes for the
keyset listings, and one covering the window sum.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Partial, case-insensitive search on name or code.
    op.execute("CREATE INDEX ix_medicine_name_trgm ON medicine USING gin (lower(name) gin_trgm_ops)")
    op.execute("CREATE INDEX ix_medicine_code_trgm ON medicine USING gin (lower(code) gin_trgm_ops)")
    # Keyset order for the catalogue listing.
    op.execute("CREATE INDEX ix_medicine_name_id ON medicine (name, id)")

    # Window sum for one patient and medicine.
    op.execute("CREATE INDEX ix_dispense_window ON dispense (patient_ref, medicine_id, dispensed_at)")
    # Newest-first keyset listings, by patient and by medicine.
    op.execute("CREATE INDEX ix_dispense_patient_recent ON dispense (patient_ref, dispensed_at DESC, id DESC)")
    op.execute("CREATE INDEX ix_dispense_medicine_recent ON dispense (medicine_id, dispensed_at DESC, id DESC)")
    op.execute("CREATE INDEX ix_dispense_recent ON dispense (dispensed_at DESC, id DESC)")


def downgrade() -> None:
    for index in (
        "ix_dispense_recent",
        "ix_dispense_medicine_recent",
        "ix_dispense_patient_recent",
        "ix_dispense_window",
        "ix_medicine_name_id",
        "ix_medicine_code_trgm",
        "ix_medicine_name_trgm",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")
