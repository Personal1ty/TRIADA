from alembic import op
import sqlalchemy as sa


revision = "0003_swarm_contract_versions"
down_revision = "0002_enable_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "swarm_contract_versions",
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("contract", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("contract_version"),
    )
    op.create_index(
        "ix_swarm_contract_versions_active_updated_at",
        "swarm_contract_versions",
        ["is_active", "updated_at"],
    )
    op.create_index("ix_swarm_contract_versions_created_at", "swarm_contract_versions", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_swarm_contract_versions_created_at", table_name="swarm_contract_versions")
    op.drop_index("ix_swarm_contract_versions_active_updated_at", table_name="swarm_contract_versions")
    op.drop_table("swarm_contract_versions")
