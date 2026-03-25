"""Integration tests for LLM and vector store.

Requires:
- DASHSCOPE_API_KEY set in .env
- Qdrant running on localhost:6333
"""

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import AppConfig


def test_embedding():
    """Test text-embedding-v4 with dense+sparse output."""
    from src.llm.client import LLMClient

    config = AppConfig.load("config")
    client = LLMClient(api_key=config.env.dashscope_api_key)

    async def _run():
        result = await client.embed(
            texts=["Python 是一种编程语言", "机器学习算法"],
            text_type="document",
            output_type="dense&sparse",
            dimension=1024,
            step="test_embedding",
        )
        print(f"  Embeddings count: {len(result.embeddings)}")
        print(f"  Total tokens: {result.total_tokens}")

        emb0 = result.embeddings[0]
        dense = emb0.get("embedding", [])
        sparse = emb0.get("sparse_embedding", {})
        print(f"  Dense vector dim: {len(dense)}")
        print(f"  Sparse type: {type(sparse)}")
        if isinstance(sparse, dict):
            print(f"  Sparse indices count: {len(sparse.get('indices', []))}")
        else:
            print(f"  Sparse raw: {sparse}")

        assert len(result.embeddings) == 2, "Expected 2 embeddings"
        assert len(dense) == 1024, f"Expected 1024-dim, got {len(dense)}"
        assert isinstance(sparse, dict), f"Expected dict sparse, got {type(sparse)}"
        assert len(sparse.get("indices", [])) > 0, "Expected sparse indices"

        return result

    result = asyncio.run(_run())
    print("✅ test_embedding PASSED")
    return result


def test_qdrant_collection():
    """Test Qdrant collection creation and basic ops."""
    from src.storage.vector_store import VectorStore

    config = AppConfig.load("config")
    store = VectorStore(
        host=config.qdrant.host,
        port=config.qdrant.port,
        grpc_port=config.qdrant.grpc_port,
        collection_name="notes_test",
        dense_dim=1024,
    )

    async def _run():
        await store.init_collection()
        print("  Collection created/verified")

        # Upsert test chunks
        test_chunks = [
            {
                "note_path": "编程/Python/test.md",
                "note_title": "Python测试",
                "chunk_index": 0,
                "heading": "## 概述",
                "chunk_text": "Python 是一种编程语言",
                "dense_vector": [0.1] * 1024,
                "sparse_vector": {"indices": [1, 5, 10], "values": [0.5, 0.3, 0.2]},
            }
        ]
        count = await store.upsert_chunks(test_chunks)
        print(f"  Upserted {count} chunks")
        assert count == 1

        # Search
        results = await store.hybrid_search(
            dense_vector=[0.1] * 1024,
            sparse_vector={"indices": [1, 5], "values": [0.5, 0.3]},
            limit=5,
        )
        print(f"  Search results: {len(results)}")
        assert len(results) >= 1
        assert results[0].note_path == "编程/Python/test.md"

        # Delete
        deleted = await store.delete_by_note_path("编程/Python/test.md")
        print(f"  Deleted {deleted} chunks")

        # Cleanup collection
        store._client.delete_collection("notes_test")
        print("  Test collection cleaned up")

    asyncio.run(_run())
    print("✅ test_qdrant_collection PASSED")


def test_llm_chat():
    """Test LLM chat via MultiModalConversation."""
    from src.llm.client import LLMClient

    config = AppConfig.load("config")
    client = LLMClient(api_key=config.env.dashscope_api_key)
    model_config = config.get_model_config("query_rewriter")

    async def _run():
        messages = [
            {
                "role": "user",
                "content": [{"text": "请用一句话介绍Python。只回答，不要多余内容。"}],
            }
        ]
        response = await client.chat(
            model_config=model_config,
            messages=messages,
            step="test_chat",
        )
        print(f"  Response: {response.content[:100]}")
        print(f"  Tokens: in={response.input_tokens}, out={response.output_tokens}")
        assert len(response.content) > 5, "Expected non-empty response"

    asyncio.run(_run())
    print("✅ test_llm_chat PASSED")


def test_query_rewrite():
    """Test query rewriting pipeline step."""
    from src.llm.client import LLMClient
    from src.agents.querier.rewriter import QueryRewriter

    config = AppConfig.load("config")
    client = LLMClient(api_key=config.env.dashscope_api_key)
    rewriter = QueryRewriter(
        llm_client=client,
        model_config=config.get_model_config("query_rewriter"),
    )

    async def _run():
        result = await rewriter.rewrite("上次python怎么装的来着")
        print(f"  Original: 上次python怎么装的来着")
        print(f"  Rewritten: {result.rewritten_query}")
        print(f"  Keywords: {result.keywords}")
        print(f"  Intent: {result.intent}")
        assert len(result.rewritten_query) > 0
        assert len(result.keywords) > 0

    asyncio.run(_run())
    print("✅ test_query_rewrite PASSED")


def test_note_classify():
    """Test note classification pipeline step."""
    from src.llm.client import LLMClient
    from src.agents.organizer.note_classifier import NoteClassifier

    config = AppConfig.load("config")
    client = LLMClient(api_key=config.env.dashscope_api_key)
    classifier = NoteClassifier(
        llm_client=client,
        model_config=config.get_model_config("note_classifier"),
        categories=config.get_categories(),
        uncategorized_label=config.uncategorized_label,
    )

    test_note = """# Ubuntu 22.04 安装指南

## 系统要求
- 最低 2GB 内存
- 25GB 硬盘空间

## 安装步骤
1. 下载 ISO 镜像
2. 制作启动 U 盘
3. 从 U 盘启动并安装
"""

    async def _run():
        result = await classifier.classify(test_note)
        print(f"  Category: {result.category}")
        print(f"  Subcategory: {result.subcategory}")
        print(f"  Title: {result.title}")
        assert result.category == "操作系统", f"Expected '操作系统', got '{result.category}'"
        assert result.subcategory == "Linux", f"Expected 'Linux', got '{result.subcategory}'"

    asyncio.run(_run())
    print("✅ test_note_classify PASSED")


def test_file_manager():
    """Test file manager atomic writes."""
    from src.storage.file_manager import FileManager

    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(root_path=tmpdir)

        async def _run():
            path = await fm.safe_write("编程", "Python", "测试笔记", "# Test\n\nContent")
            print(f"  Saved to: {path}")
            assert path == "编程/Python/测试笔记.md"

            content = await fm.read_file(path)
            assert content == "# Test\n\nContent"

            dirs = await fm.list_directories()
            assert "编程" in dirs
            assert "Python" in dirs["编程"]

            notes = await fm.list_notes()
            assert len(notes) == 1

        asyncio.run(_run())
    print("✅ test_file_manager PASSED")


def test_token_usage_tracking():
    """Test that token usage is tracked across LLM calls."""
    from src.llm.client import LLMClient

    config = AppConfig.load("config")
    client = LLMClient(api_key=config.env.dashscope_api_key)

    async def _run():
        client.usage_tracker.reset_task_summary()

        # Make an embedding call
        await client.embed(
            texts=["测试文本"],
            text_type="document",
            output_type="dense",
            dimension=1024,
            step="track_test",
        )

        summary = client.usage_tracker.get_task_summary()
        print(f"  Total tokens: {summary['total_tokens']}")
        print(f"  Total cost: {summary['total_cost']}")
        print(f"  Breakdown: {len(summary['breakdown'])} entries")
        assert summary["total_tokens"] > 0, "Expected token usage > 0"
        assert summary["total_cost"] > 0, "Expected cost > 0"

    asyncio.run(_run())
    print("✅ test_token_usage_tracking PASSED")


if __name__ == "__main__":
    print("=" * 50)
    print("Integration Tests (requires API Key + Qdrant)")
    print("=" * 50)

    test_file_manager()
    print()
    test_embedding()
    print()
    test_qdrant_collection()
    print()
    test_llm_chat()
    print()
    test_query_rewrite()
    print()
    test_note_classify()
    print()
    test_token_usage_tracking()

    print()
    print("🎉 All integration tests PASSED!")
