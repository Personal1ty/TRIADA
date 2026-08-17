from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_docker_compose_uses_pgvector_image() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "image: pgvector/pgvector:pg16" in compose
    assert "postgres:16-alpine" not in compose


def test_pgvector_migration_is_postgres_guarded() -> None:
    migration = (ROOT / "alembic/versions/0002_enable_pgvector.py").read_text()

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert 'bind.dialect.name != "postgresql"' in migration
    assert "DROP EXTENSION" not in migration


def test_memory_index_migration_creates_secondary_vector_table_without_dropping_extension() -> None:
    migration = (ROOT / "alembic/versions/0004_memory_embeddings.py").read_text()

    assert "triada_memory_embeddings" in migration
    assert "vector(" in migration
    assert 'bind.dialect.name != "postgresql"' in migration
    assert "DROP EXTENSION" not in migration
    assert "CREATE EXTENSION" not in migration
