"""Split medicine.strength ('500 mg') into strength_value + strength_unit.

This is the data-moving migration: it adds columns, transforms every existing row,
then drops the old column. The downgrade rebuilds the text form, so the round trip
upgrade -> downgrade -> upgrade is lossless for well-formed values.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("medicine", sa.Column("strength_value", sa.Numeric(10, 3), nullable=True))
    op.add_column("medicine", sa.Column("strength_unit", sa.String(16), nullable=True))

    # '500 mg' / '12.5mg' / '5 mg/ml' -> (number, everything after it)
    op.execute(
        """
        UPDATE medicine
        SET strength_value = NULLIF(substring(strength from '^[0-9]+(?:\\.[0-9]+)?'), '')::numeric,
            strength_unit  = NULLIF(trim(substring(strength from '[^0-9.].*$')), '')
        """
    )
    # Anything unparseable keeps a usable row rather than failing the migration.
    op.execute("UPDATE medicine SET strength_value = 0 WHERE strength_value IS NULL")
    op.execute("UPDATE medicine SET strength_unit = 'unit' WHERE strength_unit IS NULL")

    op.alter_column("medicine", "strength_value", nullable=False)
    op.alter_column("medicine", "strength_unit", nullable=False)
    op.drop_column("medicine", "strength")


def downgrade() -> None:
    op.add_column("medicine", sa.Column("strength", sa.Text, nullable=True))
    op.execute(
        """
        UPDATE medicine
        SET strength = trim(trailing '.' from trim(trailing '0' from strength_value::text))
                       || ' ' || strength_unit
        """
    )
    op.alter_column("medicine", "strength", nullable=False)
    op.drop_column("medicine", "strength_unit")
    op.drop_column("medicine", "strength_value")
