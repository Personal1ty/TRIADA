from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ResearchMode(StrEnum):
    NONE = "none"
    RESEARCH = "research"


class ResearchContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ResearchMode = ResearchMode.NONE
    research_questions: list[str] = Field(default_factory=list)
    depth: str = "standard"
    required_evidence: list[str] = Field(default_factory=list)
    required_artifacts: list[str] = Field(default_factory=list)
    output_schema: str = "human_review_packet"
    min_tool_executions: int = Field(default=0, ge=0)
    acceptance_criteria: list[str] = Field(default_factory=list)
