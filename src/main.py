"""FastAPI application entry point for NoteSystem Agent."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.agents.organizer.pipeline import OrganizerPipeline
from src.api.organize import router as organize_router
from src.core.config import AppConfig
from src.llm.client import LLMClient
from src.storage.file_manager import FileManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize resources on startup, cleanup on shutdown."""
    logger.info("Starting NoteSystem Agent...")

    # Load configuration
    config = AppConfig.load("config")

    # --- Validate NOTES_ROOT_PATH (fail-fast) ---
    notes_root = Path(config.note_storage.root_path).resolve()
    if config.env.notes_root_path == "./notes":
        logger.warning(
            "⚠️  NOTES_ROOT_PATH is using the default value './notes'. "
            "Set it explicitly in .env for production use."
        )
    if not notes_root.exists():
        raise RuntimeError(
            f"Notes root directory does not exist: {notes_root}\n"
            f"Set NOTES_ROOT_PATH in .env to a valid directory."
        )
    if not notes_root.is_dir():
        raise RuntimeError(
            f"NOTES_ROOT_PATH is not a directory: {notes_root}"
        )
    # Lock the resolved absolute path
    config.note_storage.root_path = str(notes_root)
    logger.info(f"📁 Notes root locked: {notes_root}")

    if not config.env.dashscope_api_key:
        logger.warning("⚠️  DASHSCOPE_API_KEY not set! LLM calls will fail.")

    # Initialize LLM client
    llm_client = LLMClient(
        api_key=config.env.dashscope_api_key,
    )

    # Initialize file manager
    file_manager = FileManager(
        root_path=config.note_storage.root_path,
        max_depth=config.note_storage.max_directory_depth,
    )

    # Initialize organizer pipeline
    organizer_pipeline = OrganizerPipeline(
        config=config,
        llm_client=llm_client,
        file_manager=file_manager,
    )

    # Store in app state for route handlers
    app.state.config = config
    app.state.llm_client = llm_client
    app.state.file_manager = file_manager
    app.state.organizer_pipeline = organizer_pipeline

    logger.info("✅ NoteSystem Agent started successfully")
    logger.info(f"  📁 Notes root: {config.note_storage.root_path}")

    yield  # Application is running

    logger.info("Shutting down NoteSystem Agent...")


# Create FastAPI app
app = FastAPI(
    title="NoteSystem Agent",
    description="AI-powered note management: image semantic extraction, formatting, and classification",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(organize_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "notesys", "version": "0.2.0"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "NoteSystem Agent",
        "version": "0.2.0",
        "description": "Note organization: image extraction, formatting, classification",
        "endpoints": {
            "organize": "POST /api/organize",
            "organize_stream": "GET /api/organize/{task_id}/stream",
            "health": "GET /health",
            "docs": "GET /docs",
        },
    }
