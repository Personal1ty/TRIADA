from pathlib import Path


def test_required_docs_exist_and_contain_core_terms():
    required = [
        "README.md",
        "ARCHITECTURE.md",
        "SECURITY.md",
        "AUDIT_MODEL.md",
        "EVENT_SCHEMA.md",
        "LONG_RUNNING_TASKS.md",
        "DEVOPS_TOOLS.md",
        "AGENTS.md",
        ".env.example",
        "docker-compose.yml",
    ]
    for path in required:
        assert Path(path).exists(), path

    architecture = Path("ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "flowchart TD" in architecture
    assert "Orchestrator" in architecture
    assert "Auditor" in architecture


def test_docker_compose_installs_sync_postgres_driver_for_alembic():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "postgresql+asyncpg://triada:triada@postgres:5432/triada" in compose
    assert "psycopg" in compose
    assert compose.index("psycopg") < compose.index("alembic upgrade head")
