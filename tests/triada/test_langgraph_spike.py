import pytest

langgraph = pytest.importorskip("langgraph")

from app.runtime.langgraph_spike import run_research_graph


def test_langgraph_research_spike_persists_state_by_thread_id():
    result, graph, config = run_research_graph("Compare two approaches", thread_id="spike-thread")

    assert result["phase"] == "completed"
    assert result["findings"]
    state = graph.get_state(config)
    assert state.values["goal"] == "Compare two approaches"
    assert state.values["phase"] == "completed"
