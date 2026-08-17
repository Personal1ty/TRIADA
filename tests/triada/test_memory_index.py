import pytest

from app.memory.index import HashEmbeddingProvider, cosine_similarity, memory_text


def test_hash_embedding_is_deterministic_and_normalized():
    provider = HashEmbeddingProvider(dimensions=8)

    first = provider.embed("bounded swarm memory")
    second = provider.embed("bounded swarm memory")

    assert first == second
    assert len(first) == 8
    assert cosine_similarity(first, first) == pytest.approx(1.0)


def test_memory_text_uses_searchable_fields_without_raw_reasoning():
    payload = {
        "memory_id": "m-1",
        "kind": "decision",
        "content": "Use checkpointed replay",
        "tags": ["replay", "audit"],
        "evidence_refs": ["event-1"],
        "raw_reasoning_content": "must not be indexed",
    }

    text = memory_text(payload)

    assert "Use checkpointed replay" in text
    assert "decision" in text
    assert "replay" in text
    assert "must not be indexed" not in text


def test_hash_embedding_rejects_invalid_dimensions():
    with pytest.raises(ValueError, match="dimensions"):
        HashEmbeddingProvider(dimensions=0)
