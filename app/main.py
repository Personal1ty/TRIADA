from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import router as api_router
from app.audit.emitter import AuditEmitter
from app.audit.repository import AuditEventRepository
from app.config import get_settings
from app.events.bus import InMemoryEventBus
from app.persistence.session import create_session_factory
from app.services.execution_engine import ExecutionEngine
from app.services.task_service import TaskService


def create_app(testing: bool = False) -> FastAPI:
    database_url, testing_database_path = _database_url(testing)
    session_factory = create_session_factory(database_url)
    event_repository = AuditEventRepository(session_factory)
    event_bus = InMemoryEventBus()
    audit_emitter = AuditEmitter(event_repository, event_bus)
    execution_engine = ExecutionEngine(emitter=audit_emitter, workspace=Path.cwd())
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
    app.state.execution_engine = execution_engine
    app.state.task_service = task_service
    app.state.sse_idle_timeout_seconds = 0.1 if testing else 30.0
    app.state.testing_database_path = str(testing_database_path) if testing_database_path is not None else None

    @app.get("/ui", response_class=FileResponse)
    async def local_swarm_ui() -> FileResponse:
        return FileResponse(Path(__file__).parent / "ui" / "index.html", media_type="text/html")

    app.include_router(api_router)
    return app


def _database_url(testing: bool) -> tuple[str, Path | None]:
    if not testing:
        return get_settings().database_url, None
    path = Path(tempfile.gettempdir()) / f"triada-test-{uuid4()}.db"
    return f"sqlite+aiosqlite:///{path}", path
