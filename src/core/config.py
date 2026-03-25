"""Configuration loader for NoteSystem Agent.

Loads settings from .env, config/models.yaml, and config/categories.yaml.
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env file
load_dotenv()


class EnvSettings(BaseModel):
    """Environment variables loaded from .env file."""

    dashscope_api_key: str = ""
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    notes_root_path: str = "./notes"

    @classmethod
    def from_env(cls) -> "EnvSettings":
        """Load settings from environment variables."""
        return cls(
            dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            qdrant_host=os.environ.get("QDRANT_HOST", "localhost"),
            qdrant_port=int(os.environ.get("QDRANT_PORT", "6333")),
            qdrant_grpc_port=int(os.environ.get("QDRANT_GRPC_PORT", "6334")),
            notes_root_path=os.environ.get("NOTES_ROOT_PATH", "./notes"),
        )


class ModelConfig(BaseModel):
    """Configuration for a single LLM model."""

    provider: str = "dashscope"
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    enable_thinking: bool = False
    # Embedding-specific fields
    dimension: Optional[int] = None
    output_type: Optional[str] = None
    batch_size: Optional[int] = None
    max_tokens_per_text: Optional[int] = None


class QdrantConfig(BaseModel):
    """Qdrant vector database configuration."""

    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    collection: str = "notes"


class NoteStorageConfig(BaseModel):
    """Note file storage configuration."""

    root_path: str = "./notes"
    max_directory_depth: int = 2


class ChunkingConfig(BaseModel):
    """Text chunking configuration."""

    max_chunk_tokens: int = 500
    overlap_tokens: int = 50


class OrganizeConfig(BaseModel):
    """Organize pipeline feature toggles."""

    enable_image_semantic: bool = True
    enable_note_format: bool = True
    enable_classify_and_save: bool = True
    enable_embedding: bool = True


class QueryConfig(BaseModel):
    """Query pipeline feature toggles."""

    enable_rewrite: bool = False
    enable_synthesis: bool = False


class SyncConfig(BaseModel):
    """Vector store sync service configuration."""

    enabled: bool = True
    interval_seconds: int = 300  # 5 minutes
    batch_limit: int = 20  # Max files per sync cycle
    min_depth: int = 1  # Min directory depth (0=root, 1=at least one subfolder)


class AppConfig(BaseModel):
    """Aggregated application configuration."""

    env: EnvSettings = Field(default_factory=EnvSettings)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    note_storage: NoteStorageConfig = Field(default_factory=NoteStorageConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    organize: OrganizeConfig = Field(default_factory=OrganizeConfig)
    query: QueryConfig = Field(default_factory=QueryConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    categories: dict[str, list[str]] = Field(default_factory=dict)
    categories_path: str = "config/categories.yaml"
    uncategorized_label: str = "未分类"

    @classmethod
    def load(cls, config_dir: str = "config") -> "AppConfig":
        """Load all configuration from env and YAML files.

        Args:
            config_dir: Path to the directory containing YAML config files.

        Returns:
            Fully populated AppConfig instance.
        """
        config_path = Path(config_dir)

        # Load env settings
        env = EnvSettings.from_env()

        # Load models.yaml
        models_file = config_path / "models.yaml"
        models_data: dict[str, Any] = {}
        if models_file.exists():
            with open(models_file, "r", encoding="utf-8") as f:
                models_data = yaml.safe_load(f) or {}

        # Parse model configs
        model_configs: dict[str, ModelConfig] = {}
        for name, cfg in models_data.get("models", {}).items():
            model_configs[name] = ModelConfig(**cfg)

        # Parse qdrant config
        qdrant_cfg = models_data.get("qdrant", {})
        qdrant = QdrantConfig(**qdrant_cfg) if qdrant_cfg else QdrantConfig()
        # Override with env vars if set
        qdrant.host = env.qdrant_host
        qdrant.port = env.qdrant_port
        qdrant.grpc_port = env.qdrant_grpc_port

        # Parse storage config
        storage_cfg = models_data.get("note_storage", {})
        note_storage = NoteStorageConfig(**storage_cfg) if storage_cfg else NoteStorageConfig()
        note_storage.root_path = env.notes_root_path

        # Parse chunking config
        chunking_cfg = models_data.get("chunking", {})
        chunking = ChunkingConfig(**chunking_cfg) if chunking_cfg else ChunkingConfig()

        # Parse organize config
        organize_cfg = models_data.get("organize", {})
        organize = OrganizeConfig(**organize_cfg) if organize_cfg else OrganizeConfig()

        # Parse query config
        query_cfg = models_data.get("query", {})
        query = QueryConfig(**query_cfg) if query_cfg else QueryConfig()

        # Parse sync config
        sync_cfg = models_data.get("sync", {})
        sync = SyncConfig(**sync_cfg) if sync_cfg else SyncConfig()

        # Categories file path (hot-loaded by NoteClassifier)
        categories_file = config_path / "categories.yaml"
        categories: dict[str, list[str]] = {}
        if categories_file.exists():
            with open(categories_file, "r", encoding="utf-8") as f:
                cat_data = yaml.safe_load(f) or {}
            categories = cat_data.get("categories", {})

        return cls(
            env=env,
            models=model_configs,
            qdrant=qdrant,
            note_storage=note_storage,
            chunking=chunking,
            organize=organize,
            query=query,
            sync=sync,
            categories=categories,
            categories_path=str(categories_file),
        )

    def get_model_config(self, step: str) -> ModelConfig:
        """Get model configuration for a specific pipeline step.

        Args:
            step: Pipeline step name (e.g., 'image_semantic', 'embedding').

        Returns:
            ModelConfig for the specified step.

        Raises:
            KeyError: If the step is not found in configuration.
        """
        if step not in self.models:
            raise KeyError(f"Model config not found for step: '{step}'. "
                           f"Available steps: {list(self.models.keys())}")
        return self.models[step]

    def get_categories(self) -> dict[str, list[str]]:
        """Get the category enumeration table."""
        return self.categories

    def get_categories_flat_text(self) -> str:
        """Get categories as a flat text string for use in prompts."""
        lines = []
        for category, subcategories in self.categories.items():
            for sub in subcategories:
                lines.append(f"  - {category}/{sub}")
        return "\n".join(lines)
