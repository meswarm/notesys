import asyncio
import tempfile

from src.agents.organizer.note_formatter import NoteFormatter
from src.llm.client import LLMResponse
from src.storage.file_manager import FileManager


class MutatingFakeLLMClient:
    async def chat_with_retry(self, **kwargs):
        content = kwargs["messages"][1]["content"][0]["text"]
        content = content.replace(
            "imgs/20260501140842_image_5f383011-e317-487a-997b-ba8359997ee0.png",
            "imgs/20260501140842_image_5f383011-e317-487a-9377-e8455f0944dd.png",
        )
        content = content.replace("https://xiufeilan.top:8008", "https://changed.example")
        content = content.replace("https://docs.example/path?q=1", "https://changed-docs.example")
        return LLMResponse(content=content)


class DummyModelConfig:
    model = "fake"


def test_note_formatter_preserves_markdown_image_paths():
    source = (
        "# Matrix\n\n"
        "![Matrix客户端版本信息接口返回数据]"
        "(imgs/20260501140842_image_5f383011-e317-487a-997b-ba8359997ee0.png)\n\n"
        "参考 https://docs.example/path?q=1\n\n"
        "```bash\n"
        "curl -k https://xiufeilan.top:8008/_matrix/client/versions\n"
        "```\n"
    )
    formatter = NoteFormatter(MutatingFakeLLMClient(), DummyModelConfig())

    formatted = asyncio.run(formatter.format(source))

    assert "imgs/20260501140842_image_5f383011-e317-487a-997b-ba8359997ee0.png" in formatted
    assert "imgs/20260501140842_image_5f383011-e317-487a-9377-e8455f0944dd.png" not in formatted
    assert "curl -k https://xiufeilan.top:8008/_matrix/client/versions" in formatted
    assert "https://changed.example" not in formatted
    assert "https://docs.example/path?q=1" in formatted
    assert "https://changed-docs.example" not in formatted


def test_file_manager_sanitizes_llm_generated_directory_names():
    with tempfile.TemporaryDirectory() as tmpdir:
        fm = FileManager(root_path=tmpdir)

        async def _run():
            return await fm.safe_write("../escaped", "..", "note", "content")

        path = asyncio.run(_run())

        assert ".." not in path.split("/")
        assert path == "_escaped/_/note.md"
        assert (fm.root_path / path).exists()
