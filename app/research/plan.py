from __future__ import annotations


def build_research_plan(
    *,
    question: str,
    parameter_catalog: list[str],
    hypotheses: list[str] | None = None,
    depth: int = 1,
) -> dict:
    question = question.strip()
    parameters = [parameter.strip() for parameter in parameter_catalog if parameter.strip()]
    if not question:
        raise ValueError("question must not be blank")
    if not parameters:
        raise ValueError("parameter_catalog must not be empty")
    if depth < 1 or depth > 3:
        raise ValueError("depth must be between 1 and 3")

    why_questions = [f"Why does {parameter} matter for: {question}" for parameter in parameters]
    how_questions = [f"How can {parameter} be measured or changed?" for parameter in parameters]
    unresolved_questions = [
        f"What evidence would confirm or reject the hypothesis: {hypothesis}"
        for hypothesis in (hypotheses or [])
    ]
    unresolved_questions.extend(how_questions[: max(1, depth)])
    return {
        "question": question,
        "depth": depth,
        "parameter_catalog": parameters,
        "hypotheses": list(hypotheses or []),
        "why_questions": why_questions,
        "how_questions": how_questions,
        "unresolved_questions": unresolved_questions,
    }
