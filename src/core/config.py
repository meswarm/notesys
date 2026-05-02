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
    notes_root_path: str = "./notes"

    @classmethod
    def from_env(cls) -> "EnvSettings":
        """Load settings from environment variables."""
        return cls(
            dashscope_api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
            notes_root_path=os.environ.get("NOTES_ROOT_PATH", "./notes"),
        )


class ModelConfig(BaseModel):
    """Configuration for a single LLM model."""

    provider: str = "dashscope"
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    enable_thinking: bool = False


class NoteStorageConfig(BaseModel):
    """Note file storage configuration."""

    root_path: str = "./notes"
    max_directory_depth: int = 2


class OrganizeConfig(BaseModel):
    """Organize pipeline feature toggles."""

    enable_image_semantic: bool = True
    enable_note_format: bool = True
    enable_classify_and_save: bool = True


class AppConfig(BaseModel):
    """Aggregated application configuration."""

    env: EnvSettings = Field(default_factory=EnvSettings)
    models: dict[str, ModelConfig] = Field(default_factory=dict)
    note_storage: NoteStorageConfig = Field(default_factory=NoteStorageConfig)
    organize: OrganizeConfig = Field(default_factory=OrganizeConfig)
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

        # Parse storage config
        storage_cfg = models_data.get("note_storage", {})
        note_storage = NoteStorageConfig(**storage_cfg) if storage_cfg else NoteStorageConfig()
        note_storage.root_path = env.notes_root_path

        # Parse organize config
        organize_cfg = models_data.get("organize", {})
        organize = OrganizeConfig(**organize_cfg) if organize_cfg else OrganizeConfig()

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
            note_storage=note_storage,
            organize=organize,
            categories=categories,
            categories_path=str(categories_file),
        )

    def get_model_config(self, step: str) -> ModelConfig:
        """Get model configuration for a specific pipeline step.

        Args:
            step: Pipeline step name (e.g., 'image_semantic', 'note_format').

        Returns:
            ModelConfig for the specified step.

        Raises:
            KeyError: If the step is not found in configuration.
        """
        if step not in self.models:
            raise KeyError(
                f"Model config not found for step: '{step}'. "
                f"Available steps: {list(self.models.keys())}"
            )
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
