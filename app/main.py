from __future__ import annotations

from contextlib import asynccontextmanager
from importlib import resources
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api import router as api_router
from app.audit.emitter import AuditEmitter
from app.audit.repository import AuditEventRepository
from app.config import get_settings
from app.contracts.loader import load_default_swarm_contract
from app.events.bus import InMemoryEventBus
from app.llm.runtime_config import LLMConfigService
from app.persistence.session import create_session_factory
from app.services.execution_engine import ExecutionEngine
from app.services.task_service import TaskService


def create_app(testing: bool = False) -> FastAPI:
    database_url, testing_database_path = _database_url(testing)
    llm_config_path, llm_key_path = _llm_config_paths(testing)
    settings = get_settings()
    session_factory = create_session_factory(database_url)
    event_repository = AuditEventRepository(session_factory)
    event_bus = InMemoryEventBus()
    audit_emitter = AuditEmitter(event_repository, event_bus)
    llm_config_service = LLMConfigService(
        settings=settings,
        config_path=llm_config_path,
        key_path=llm_key_path,
    )
    execution_engine = ExecutionEngine(
        emitter=audit_emitter,
        workspace=Path.cwd(),
        llm_config_service=llm_config_service,
    )
    task_service = TaskService(emitter=audit_emitter, execution_engine=execution_engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            bind = session_factory.kw.get("bind")
            if bind is not None:
                await bind.dispose()
            if testing_database_path is not None:
                testing_database_path.unlink(missing_ok=True)

    app = FastAPI(title="TRIADA", version="0.1.0", lifespan=lifespan)

    app.state.testing = testing
    app.state.session_factory = session_factory
    app.state.event_repository = event_repository
    app.state.event_bus = event_bus
    app.state.audit_emitter = audit_emitter
    app.state.llm_config_service = llm_config_service
    app.state.execution_engine = execution_engine
    app.state.task_service = task_service
    default_contract = load_default_swarm_contract()
    app.state.swarm_contract_versions = {default_contract.contract_version: default_contract}
    app.state.active_swarm_contract_version = default_contract.contract_version
    app.state.sse_idle_timeout_seconds = 0.1 if testing else 30.0
    app.state.testing_database_path = str(testing_database_path) if testing_database_path is not None else None

    @app.get("/ui", response_class=HTMLResponse)
    async def local_swarm_ui() -> HTMLResponse:
        html = resources.files("app.ui").joinpath("index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    app.include_router(api_router)
    return app


def _database_url(testing: bool) -> tuple[str, Path | None]:
    if not testing:
        return get_settings().database_url, None
    path = Path(tempfile.gettempdir()) / f"triada-test-{uuid4()}.db"
    return f"sqlite+aiosqlite:///{path}", path


def _llm_config_paths(testing: bool) -> tuple[Path, Path]:
    if testing:
        directory = Path(tempfile.gettempdir()) / f"triada-test-llm-{uuid4()}"
        return directory / "llm_config.enc", directory / "llm_config.key"
    settings = get_settings()
    return Path(settings.llm_config_path), Path(settings.llm_secret_key_path)
