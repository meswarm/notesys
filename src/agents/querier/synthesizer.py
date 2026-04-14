"""Answer synthesis from retrieved note chunks."""

from pathlib import Path
from typing import Any, Optional

from loguru import logger

from src.core.config import ModelConfig
from src.llm.client import LLMClient
from src.storage.file_manager import FileManager
from src.storage.vector_store import SearchResult


class AnswerSynthesizer:
    """Synthesizes answers from retrieved note chunks."""

    def __init__(
        self,
        llm_client: LLMClient,
        model_config: ModelConfig,
        file_manager: FileManager,
    ):
        self._llm = llm_client
        self._config = model_config
        self._file_manager = file_manager
        self._system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path("src/llm/prompts/query_synthesize.txt")
        return prompt_path.read_text(encoding="utf-8")

    async def synthesize(
        self,
        user_query: str,
        retrieval_results: list[SearchResult],
        top_k_notes: int = 5,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Synthesize an answer from retrieved results.

        Args:
            user_query: Original user query.
            retrieval_results: Search results from retriever.
            top_k_notes: Maximum number of unique notes to include.

        Returns:
            Tuple of (answer_text, related_notes_list).
        """
        if not retrieval_results:
            return "未找到相关笔记。请尝试使用不同的关键词搜索。", []

        # De-duplicate by note_path, keep best score
        seen_paths: dict[str, SearchResult] = {}
        for result in retrieval_results:
            if result.note_path not in seen_paths:
                seen_paths[result.note_path] = result
            elif result.score > seen_paths[result.note_path].score:
                seen_paths[result.note_path] = result

        # Take top_k unique notes
        unique_notes = sorted(seen_paths.values(), key=lambda r: r.score, reverse=True)[:top_k_notes]

        # Build related notes list with scores
        related_notes = []
        for note in unique_notes:
            # Normalize score to percentage (Qdrant cosine similarity is 0-1)
            score_pct = min(100, max(0, int(note.score * 100)))
            related_notes.append({
                "note_path": note.note_path,
                "note_title": note.note_title,
                "score": score_pct,
            })

        # Load full note contents for context
        retrieved_text_parts = []
        for i, note in enumerate(unique_notes):
            score_pct = related_notes[i]["score"]
            try:
                full_content = await self._file_manager.read_file(note.note_path)
                # Truncate very long notes
                if len(full_content) > 4000:
                    full_content = full_content[:4000] + "\n\n...(内容已截断)"
                retrieved_text_parts.append(
                    f"### 笔记标题: {note.note_title}\n"
                    f"### 笔记路径: {note.note_path}\n"
                    f"### 相关度: {score_pct}%\n\n"
                    f"{full_content}"
                )
            except FileNotFoundError:
                # Use chunk text as fallback
                retrieved_text_parts.append(
                    f"### 笔记标题: {note.note_title}\n"
                    f"### 笔记路径: {note.note_path}\n"
                    f"### 相关度: {score_pct}%\n\n"
                    f"{note.chunk_text}"
                )

        retrieved_notes_text = "\n\n---\n\n".join(retrieved_text_parts)

        # Build messages with system/user separation
        user_content = (
            f"## 用户问题\n{user_query}\n\n"
            f"## 检索到的笔记内容如下\n{retrieved_notes_text}"
        )

        messages = [
            {"role": "system", "content": [{"text": self._system_prompt}]},
            {"role": "user", "content": [{"text": user_content}]},
        ]

        response = await self._llm.chat_with_retry(
            model_config=self._config,
            messages=messages,
            step="query_synthesize",
            max_retries=2,
            timeout=120,
        )

        answer = response.content.strip()

        # Prepend code-generated note references (paths + scores are precise)
        note_refs = "\n".join(
            f"[{n['note_title']}]({n['note_path']}) — 相关度: {n['score']}%"
            for n in related_notes
        )
        answer = f"{note_refs}\n\n{answer}"

        logger.info(f"Answer synthesized: {len(answer)} chars, {len(related_notes)} notes referenced")
        return answer, related_notes

