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
    assert "${TRIADA_POSTGRES_PORT:-5432}:5432" in compose
    assert "psycopg" in compose
    assert compose.index("psycopg") < compose.index("alembic upgrade head")


def test_project_dependencies_include_postgres_migration_driver():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "asyncpg" in pyproject
    assert "psycopg[binary]" in pyproject
    assert "greenlet" in pyproject
    assert 'include = ["app*"]' in pyproject


def test_alembic_uses_psycopg_driver_for_asyncpg_urls():
    env = Path("alembic/env.py").read_text(encoding="utf-8")
    assert 'url.set(drivername="postgresql+psycopg")' in env
    assert "hide_password=False" in env
