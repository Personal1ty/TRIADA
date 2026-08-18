from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.audit.projection import playbook_templates_from_events
from app.schemas.tasks import PlaybookTemplateRequest


def _event(payload, sequence=1):
    return SimpleNamespace(id=uuid4(), task_id=uuid4(), event_type="playbook_template_created", payload=payload, sequence=sequence)


def test_playbook_template_projection_returns_latest_versions():
    result = playbook_templates_from_events([
        _event({"template_id": "t-1", "name": "research", "version": "1.0", "stages": ["plan", "evidence"], "capabilities": ["read_memory"]}),
        _event({"template_id": "t-2", "name": "research", "version": "2.0", "stages": ["plan", "evidence", "audit"], "capabilities": ["read_memory", "issue_verdict"]}, 2),
    ])

    assert result["summary"] == {"template_count": 1, "latest_count": 1}
    assert result["templates"][0]["version"] == "2.0"


def test_playbook_template_rejects_blank_stage_and_secret():
    with pytest.raises(ValueError):
        PlaybookTemplateRequest(name="research", version="1.0", stages=["plan", ""])
    with pytest.raises(ValueError):
        PlaybookTemplateRequest(name="research", version="1.0", stages=["plan"], description="token=secret")
