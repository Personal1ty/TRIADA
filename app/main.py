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
from app.contracts.repository import SwarmContractRepository
from app.events.bus import InMemoryEventBus
from app.llm.runtime_config import LLMConfigService
from app.persistence.session import create_session_factory
from app.services.execution_engine import ExecutionEngine
from app.services.task_service import TaskService


def create_app(testing: bool = False, database_url: str | None = None) -> FastAPI:
    database_url, testing_database_path = _database_url(testing, database_url)
    llm_config_path, llm_key_path = _llm_config_paths(testing)
    settings = get_settings()
    session_factory = create_session_factory(database_url)
    event_repository = AuditEventRepository(session_factory)
    swarm_contract_repository = SwarmContractRepository(session_factory)
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
        default_contract = load_default_swarm_contract()
        await swarm_contract_repository.ensure_default(default_contract)
        active_contract = await swarm_contract_repository.get_contract()
        if active_contract is None:
            active_contract = default_contract
        execution_engine.set_swarm_contract(active_contract)
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
    app.state.swarm_contract_repository = swarm_contract_repository
    app.state.event_bus = event_bus
    app.state.audit_emitter = audit_emitter
    app.state.llm_config_service = llm_config_service
    app.state.execution_engine = execution_engine
    app.state.task_service = task_service
    app.state.sse_idle_timeout_seconds = 0.1 if testing else 30.0
    app.state.testing_database_path = str(testing_database_path) if testing_database_path is not None else None

    @app.get("/ui", response_class=HTMLResponse)
    async def local_swarm_ui() -> HTMLResponse:
        html = resources.files("app.ui").joinpath("index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    app.include_router(api_router)
    return app


def _database_url(testing: bool, database_url: str | None = None) -> tuple[str, Path | None]:
    if database_url is not None:
        return database_url, None
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
