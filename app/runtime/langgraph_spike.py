from __future__ import annotations

from typing import TypedDict


class ResearchState(TypedDict, total=False):
    goal: str
    phase: str
    findings: list[str]


def build_research_graph():
    """Build a small checkpointed research graph for runtime evaluation.

    This is intentionally isolated from TRIADA's execution engine. TRIADA
    owns task/audit identity; this graph only proves that a nested LangGraph
    workflow can persist and inspect state by thread id.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    def research(state: ResearchState) -> dict:
        return {"phase": "researching", "findings": [f"Research started for: {state['goal']}"]}

    def audit(state: ResearchState) -> dict:
        return {"phase": "completed", "findings": [*state.get("findings", []), "Research checkpoint audited."]}

    builder = StateGraph(ResearchState)
    builder.add_node("research", research)
    builder.add_node("audit", audit)
    builder.add_edge(START, "research")
    builder.add_edge("research", "audit")
    builder.add_edge("audit", END)
    return builder.compile(checkpointer=InMemorySaver())


def run_research_graph(goal: str, *, thread_id: str):
    graph = build_research_graph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke({"goal": goal, "phase": "created", "findings": []}, config)
    return result, graph, config
