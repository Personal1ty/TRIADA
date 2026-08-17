from uuid import uuid4

from app.runtime.graph_adapter import TriadaGraphAdapter


def test_graph_adapter_builds_langgraph_compatible_thread_config_without_dependency():
    trace_id = uuid4()
    event_id = uuid4()
    adapter = TriadaGraphAdapter()

    checkpoint = adapter.checkpoint(trace_id=trace_id, event_id=event_id, sequence=7, phase="audit")
    config = adapter.resume_config(checkpoint)

    assert config == {
        "configurable": {
            "thread_id": str(trace_id),
            "checkpoint_id": str(event_id),
        }
    }
    assert checkpoint.sequence == 7
    assert checkpoint.phase == "audit"
