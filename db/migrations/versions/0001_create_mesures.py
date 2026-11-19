"""create mesures

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE mesures (
            id            BIGSERIAL PRIMARY KEY,
            machine_id    TEXT        NOT NULL,
            ts            TIMESTAMPTZ NOT NULL,
            temperature_c REAL        NOT NULL,
            recu_le       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_mesures_machine_ts ON mesures (machine_id, ts DESC)")


def downgrade():
    op.execute("DROP INDEX idx_mesures_machine_ts")
    op.execute("DROP TABLE mesures")
