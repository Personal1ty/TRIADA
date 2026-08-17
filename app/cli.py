from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from app.agents.orchestrator import Orchestrator
from app.audit.projection import events_to_public_response
from app.audit.repository import AuditEventRepository
from app.config import get_settings
from app.llm.fake import FakeLLMProvider
from app.persistence.session import create_session_factory
from app.services.execution_supervisor import FakeClock, LongTaskSimulator


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triada")
    subparsers = parser.add_subparsers(dest="command")

    demo = subparsers.add_parser("demo", help="run a deterministic TRIADA demo")
    demo.set_defaults(handler=_demo)

    run_task = subparsers.add_parser("run-task", help="plan a task from a JSON file")
    run_task.add_argument("task_json", type=Path)
    run_task.set_defaults(handler=_run_task)

    verify_trace = subparsers.add_parser("verify-trace", help="verify a trace hash chain")
    verify_trace.add_argument("trace_id")
    verify_trace.set_defaults(handler=_verify_trace)

    list_events = subparsers.add_parser("list-events", help="list trace events")
    list_events.add_argument("trace_id")
    list_events.set_defaults(handler=_list_events)

    simulate_long_task = subparsers.add_parser("simulate-long-task", help="print virtual long-task events")
    simulate_long_task.set_defaults(handler=_simulate_long_task)

    test_provider = subparsers.add_parser("test-provider", help="exercise the configured LLM provider")
    test_provider.set_defaults(handler=_test_provider)

    return parser


def _demo(_: argparse.Namespace) -> int:
    return asyncio.run(_demo_async())


async def _demo_async() -> int:
    provider = FakeLLMProvider()
    orchestrator = Orchestrator(provider)
    plan = await orchestrator.plan_task(
        "Inspect repository status and produce an audit verdict.",
        allowed_tools=["git", "shell"],
        acceptance_criteria=["demo completes"],
    )
    verdict = await provider.complete_json(plan.model_dump_json(), schema_name="audit_verdict")

    print("TRIADA demo")
    print(f"plan steps: {len(plan.steps)}")
    print(f"audit verdict: {json.dumps(verdict['answer'], sort_keys=True)}")
    return 0


def _run_task(args: argparse.Namespace) -> int:
    return asyncio.run(_run_task_async(args.task_json))


async def _run_task_async(task_json: Path) -> int:
    task = json.loads(task_json.read_text(encoding="utf-8"))
    goal = str(task.get("goal") or task.get("task") or task.get("description") or "")
    if not goal:
        raise ValueError("task JSON must include goal, task, or description")

    allowed_tools = _string_list(task.get("allowed_tools"), default=["shell"])
    acceptance_criteria = _string_list(task.get("acceptance_criteria"), default=[])
    plan = await Orchestrator(FakeLLMProvider()).plan_task(goal, allowed_tools, acceptance_criteria)
    print(json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


def _verify_trace(args: argparse.Namespace) -> int:
    return asyncio.run(_verify_trace_async(args.trace_id))


async def _verify_trace_async(trace_id: str) -> int:
    repository = _audit_repository()
    try:
        trace_uuid = UUID(trace_id)
        events = await repository.list_events(trace_uuid)
        valid = bool(events) and await repository.verify_trace(trace_uuid)
        print(json.dumps({"trace_id": trace_id, "found": bool(events), "hash_chain_valid": valid}, sort_keys=True))
        return 0 if valid else 1
    finally:
        await repository._session_factory.kw["bind"].dispose()


def _list_events(args: argparse.Namespace) -> int:
    return asyncio.run(_list_events_async(args.trace_id))


async def _list_events_async(trace_id: str) -> int:
    repository = _audit_repository()
    try:
        events = await repository.list_events(UUID(trace_id))
        print(json.dumps({"trace_id": trace_id, "events": events_to_public_response(events)}, indent=2, sort_keys=True))
        return 0
    finally:
        await repository._session_factory.kw["bind"].dispose()


def _simulate_long_task(_: argparse.Namespace) -> int:
    return asyncio.run(_simulate_long_task_async())


async def _simulate_long_task_async() -> int:
    simulator = LongTaskSimulator(clock=FakeClock(), heartbeat_seconds=60, checkpoint_seconds=300)
    result = await simulator.run_virtual(duration_seconds=10 * 60, timeout_seconds=30 * 60)
    print(json.dumps({"status": result.status, "events": result.events}, indent=2, sort_keys=True))
    return 0


def _test_provider(_: argparse.Namespace) -> int:
    return asyncio.run(_test_provider_async())


async def _test_provider_async() -> int:
    settings = get_settings()
    provider = FakeLLMProvider()
    response = await provider.complete_json("provider smoke test", schema_name="default")
    print(f"provider: {settings.llm_provider}")
    print(f"model: {settings.llm_model}")
    print(json.dumps(response["answer"], sort_keys=True))
    return 0


def _audit_repository() -> AuditEventRepository:
    return AuditEventRepository(create_session_factory(get_settings().database_url))


def _string_list(value: Any, *, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if not isinstance(value, list):
        raise ValueError("expected a list of strings")
    result = [item for item in value if isinstance(item, str)]
    if len(result) != len(value):
        raise ValueError("expected a list of strings")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
