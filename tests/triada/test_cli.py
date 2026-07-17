import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.audit.repository import AuditEventRepository
from app.cli import main
from app.config import Settings, get_settings
from app.persistence.session import create_session_factory


def test_cli_demo_runs(capsys):
    exit_code = main(["demo"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "TRIADA demo" in captured.out
    assert "audit verdict" in captured.out


def test_cli_simulate_long_task_runs(capsys):
    exit_code = main(["simulate-long-task"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "agent_heartbeat" in captured.out
    assert "thinking_summary_delta" in captured.out


def test_cli_test_provider_uses_fake_by_default(capsys):
    exit_code = main(["test-provider"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "fake-devops-model" in captured.out


def test_cli_run_task_missing_file_returns_error(capsys, tmp_path):
    exit_code = main(["run-task", str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "error:" in captured.out
    assert "Traceback" not in captured.out


def test_cli_invalid_args_return_exit_code(capsys):
    assert main(["not-a-command"]) == 2
    assert main(["run-task"]) == 2


def test_cli_verify_trace_reports_missing_trace(capsys):
    exit_code = main(["verify-trace", "00000000-0000-0000-0000-000000000000"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"found": false' in captured.out


def test_cli_run_task_from_json_file(capsys, tmp_path):
    task_file = tmp_path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "goal": "Inspect repository",
                "allowed_tools": ["git"],
                "acceptance_criteria": ["Return status"],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["run-task", str(task_file)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Inspect repository" in captured.out
    assert '"steps"' in captured.out


def test_cli_list_events_outputs_persisted_trace(monkeypatch, capsys, tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path}/triada-cli.db"
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.cli.get_settings",
        lambda: Settings(database_url=database_url),
    )
    trace_id = uuid4()
    task_id = uuid4()
    event = asyncio.run(_append_test_event(database_url, trace_id, task_id))

    exit_code = main(["list-events", str(trace_id)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert str(event.id) in captured.out
    assert "task_created" in captured.out


async def _append_test_event(database_url, trace_id, task_id):
    repository = AuditEventRepository(create_session_factory(database_url))
    return await repository.append_event(
        event_type="task_created",
        trace_id=trace_id,
        task_id=task_id,
        agent_id="orchestrator",
        payload={"status": "created"},
        created_at=datetime.now(UTC),
    )
