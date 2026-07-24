from alembic import op


revision = "0002_enable_pgvector"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # The vector extension can be shared or pre-existing in local PostgreSQL.
    # Keep downgrade non-destructive and leave extension ownership to the operator.
    return
