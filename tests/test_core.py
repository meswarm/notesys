"""Tests for core components (config, events, retry, chunker, usage_tracker).

These tests do NOT require LLM API keys or external services.
"""

import json
import os
import sys
import tempfile

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_config_load():
    """Test AppConfig loads from YAML files."""
    from src.core.config import AppConfig

    config = AppConfig.load("config")

    # Check models loaded
    assert "image_semantic" in config.models
    assert "note_organizer" in config.models
    assert "embedding" in config.models
    assert "query_rewriter" in config.models

    # Check embedding config
    emb = config.get_model_config("embedding")
    assert emb.dimension == 1024
    assert emb.output_type == "dense&sparse"
    assert emb.model == "text-embedding-v4"

    # Check categories
    assert len(config.categories) > 0
    assert "编程" in config.categories
    assert "Python" in config.categories["编程"]

    # Check flat text
    flat = config.get_categories_flat_text()
    assert "编程/Python" in flat

    print("✅ test_config_load passed")


def test_sse_events():
    """Test SSE event creation and formatting."""
    from src.core.events import progress_event, error_event, result_event, status_event

    evt = progress_event("test_step", 0.5, "Half done")
    formatted = evt.format()
    assert "event: progress" in formatted
    assert "test_step" in formatted
    assert "0.5" in formatted

    err = error_event("Something failed", retry=True, step="embed")
    formatted = err.format()
    assert "event: error" in formatted
    assert "Something failed" in formatted

    res = result_event({"answer": "hello"})
    formatted = res.format()
    assert "event: result" in formatted
    assert "hello" in formatted

    print("✅ test_sse_events passed")


def test_json_validation():
    """Test JSON output validation from LLM responses."""
    from src.core.retry import validate_json_output

    # Direct JSON
    assert validate_json_output('{"key": "value"}') == {"key": "value"}

    # JSON in code block
    assert validate_json_output('```json\n{"key": 1}\n```') == {"key": 1}

    # JSON with surrounding text
    result = validate_json_output('Here is the result: {"a": 2} done')
    assert result == {"a": 2}

    # Invalid
    assert validate_json_output("not json at all") is None

    print("✅ test_json_validation passed")


def test_markdown_image_validation():
    """Test markdown image ALT text validation."""
    from src.core.retry import validate_markdown_images

    assert validate_markdown_images("![description](img.png)") is True
    assert validate_markdown_images("![](img.png)") is False
    assert validate_markdown_images("No images here") is True

    print("✅ test_markdown_image_validation passed")


def test_chunker():
    """Test markdown chunking."""
    from src.agents.organizer.chunker import chunk_markdown

    content = """# Main Title

Introduction paragraph.

## Section 1

Content of section 1.

### Subsection 1.1

Detailed content here.

## Section 2

Content of section 2.
"""
    chunks = chunk_markdown(content)
    assert len(chunks) >= 3, f"Expected at least 3 chunks, got {len(chunks)}"

    # Check all chunks have text
    for c in chunks:
        assert c.text.strip(), f"Chunk {c.chunk_index} has empty text"

    # Very short content should produce 1 chunk
    short_chunks = chunk_markdown("Just one line")
    assert len(short_chunks) == 1

    print(f"✅ test_chunker passed ({len(chunks)} chunks from multi-section doc)")


def test_usage_tracker_summary():
    """Test usage tracker in-memory summary."""
    from src.core.usage_tracker import UsageTracker, TokenUsage
    import asyncio

    tracker = UsageTracker(usage_dir=tempfile.mkdtemp())

    usage1 = TokenUsage(
        timestamp="2024-01-01T00:00:00",
        model="test-model",
        step="step1",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        cost=0.001,
    )
    usage2 = TokenUsage(
        timestamp="2024-01-01T00:00:01",
        model="test-model",
        step="step2",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        cost=0.002,
    )

    asyncio.run(tracker.record(usage1))
    asyncio.run(tracker.record(usage2))

    summary = tracker.get_task_summary()
    assert summary["total_tokens"] == 450
    assert summary["total_cost"] == 0.003
    assert len(summary["breakdown"]) == 2

    tracker.reset_task_summary()
    assert tracker.get_task_summary()["total_tokens"] == 0

    print("✅ test_usage_tracker_summary passed")


def test_models():
    """Test data models."""
    from src.models.note import NoteChunk, ClassificationResult, OrganizeResult, QueryResult

    chunk = NoteChunk(chunk_index=0, heading="## Test", text="Content")
    assert chunk.chunk_index == 0

    cls_result = ClassificationResult(category="编程", subcategory="Python", title="测试笔记")
    assert cls_result.category == "编程"

    org_result = OrganizeResult(success=True, note_path="编程/Python/测试笔记.md")
    assert org_result.success

    q_result = QueryResult(success=True, answer="Test answer")
    assert q_result.answer == "Test answer"

    print("✅ test_models passed")


if __name__ == "__main__":
    test_config_load()
    test_sse_events()
    test_json_validation()
    test_markdown_image_validation()
    test_chunker()
    test_usage_tracker_summary()
    test_models()
    print("\n🎉 All tests PASSED!")
