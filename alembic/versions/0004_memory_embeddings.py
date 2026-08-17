import os

from alembic import op


revision = "0004_memory_embeddings"
down_revision = "0003_swarm_contract_versions"
branch_labels = None
depends_on = None


def _dimensions() -> int:
    raw = os.environ.get("MEMORY_EMBEDDING_DIMENSIONS", "64")
    dimensions = int(raw)
    if dimensions < 8 or dimensions > 2048:
        raise ValueError("MEMORY_EMBEDDING_DIMENSIONS must be between 8 and 2048")
    return dimensions


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    dimensions = _dimensions()
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS triada_memory_embeddings (
            event_id VARCHAR(36) PRIMARY KEY,
            memory_id VARCHAR(36) NOT NULL,
            trace_id VARCHAR(36) NOT NULL,
            task_id VARCHAR(36) NOT NULL,
            payload JSONB NOT NULL,
            embedding vector({dimensions}) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.create_index(
        "ix_triada_memory_embeddings_trace_id",
        "triada_memory_embeddings",
        ["trace_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_index(
        "ix_triada_memory_embeddings_trace_id",
        table_name="triada_memory_embeddings",
        if_exists=True,
    )
    op.drop_table("triada_memory_embeddings", if_exists=True)
