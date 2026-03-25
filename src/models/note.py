"""Data models for notes and pipeline results."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class NoteChunk(BaseModel):
    """A chunk of a note for vector storage."""

    chunk_index: int
    heading: str = ""
    text: str
    dense_vector: list[float] = Field(default_factory=list)
    sparse_vector: Optional[dict[str, Any]] = None  # {indices: [...], values: [...]}


class ClassificationResult(BaseModel):
    """Result of note classification."""

    category: str
    subcategory: str
    title: str


class OrganizeResult(BaseModel):
    """Final result of the organize pipeline."""

    success: bool = True
    note_path: str = ""
    classification: Optional[ClassificationResult] = None
    token_summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class QueryResult(BaseModel):
    """Final result of the query pipeline."""

    success: bool = True
    answer: str = ""
    related_notes: list[dict[str, Any]] = Field(default_factory=list)
    token_summary: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
