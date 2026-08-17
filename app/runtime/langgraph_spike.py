from __future__ import annotations

from typing import TypedDict

from app.research.plan import build_research_plan


class ResearchState(TypedDict, total=False):
    goal: str
    phase: str
    findings: list[str]


class ResearchSubgraphState(TypedDict, total=False):
    goal: str
    question: str
    parameter_catalog: list[str]
    hypotheses: list[str]
    plan: dict
    evidence_refs: list[str]
    unresolved_questions: list[str]
    phase: str
    audit_summary: str


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


def build_research_subgraph():
    """Build the optional R&D subgraph behind TRIADA's event boundary.

    The subgraph only expands and audits a bounded research plan. Evidence is
    supplied as references and must be persisted by the TRIADA event store;
    this function deliberately has no database or tool side effects.
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    def expand(state: ResearchSubgraphState) -> dict:
        plan = build_research_plan(
            question=state["question"],
            parameter_catalog=state["parameter_catalog"],
            hypotheses=state.get("hypotheses", []),
            depth=1,
        )
        return {
            "plan": plan,
            "unresolved_questions": plan["unresolved_questions"],
            "phase": "evidence_collection",
        }

    def audit(state: ResearchSubgraphState) -> dict:
        plan = state.get("plan", {})
        evidence_refs = state.get("evidence_refs", [])
        valid = bool(plan.get("question")) and all(isinstance(ref, str) and ref.strip() for ref in evidence_refs)
        return {
            "phase": "completed" if valid else "blocked",
            "audit_summary": "Research plan checkpoint audited." if valid else "Evidence references are required.",
        }

    builder = StateGraph(ResearchSubgraphState)
    builder.add_node("expand", expand)
    builder.add_node("audit", audit)
    builder.add_edge(START, "expand")
    builder.add_edge("expand", "audit")
    builder.add_edge("audit", END)
    return builder.compile(checkpointer=InMemorySaver())


def run_research_subgraph(
    *,
    goal: str,
    question: str,
    parameter_catalog: list[str],
    hypotheses: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    thread_id: str,
):
    graph = build_research_subgraph()
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke(
        {
            "goal": goal,
            "question": question,
            "parameter_catalog": parameter_catalog,
            "hypotheses": hypotheses or [],
            "evidence_refs": evidence_refs or [],
            "phase": "created",
        },
        config,
    )
    return result, graph, config
