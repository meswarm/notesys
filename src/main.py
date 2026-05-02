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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize resources on startup, cleanup on shutdown."""
    logger.info("Starting NoteSystem Agent...")

    # Load configuration
    config = AppConfig.load("config")

    # --- Validate server-level NOTES_ROOT_PATH (soft warning only) ---
    # notes_root_path can also be provided per-request; this is just the default.
    default_root = config.note_storage.root_path
    if default_root and default_root != "./notes":
        root_path = Path(default_root).resolve()
        if not root_path.exists():
            logger.warning(
                f"⚠️  Default NOTES_ROOT_PATH does not exist: {root_path}. "
                "Requests that rely on the server default will fail unless "
                "notes_root_path is supplied per-request."
            )
        else:
            logger.info(f"📁 Default notes root: {root_path}")
            config.note_storage.root_path = str(root_path)
    else:
        logger.warning(
            "⚠️  NOTES_ROOT_PATH is not set (or using default './notes'). "
            "All requests must supply notes_root_path explicitly."
        )

    if not config.env.dashscope_api_key:
        logger.warning("⚠️  DASHSCOPE_API_KEY not set! LLM calls will fail.")

    # Initialize LLM client
    llm_client = LLMClient(
        api_key=config.env.dashscope_api_key,
    )

    # Initialize organizer pipeline (FileManager is created per-request inside run())
    organizer_pipeline = OrganizerPipeline(
        config=config,
        llm_client=llm_client,
    )

    # Store in app state for route handlers
    app.state.config = config
    app.state.llm_client = llm_client
    app.state.organizer_pipeline = organizer_pipeline

    logger.info("✅ NoteSystem Agent started successfully")

    yield  # Application is running

    logger.info("Shutting down NoteSystem Agent...")


# Create FastAPI app
app = FastAPI(
    title="NoteSystem Agent",
    description=(
        "AI-powered note organization: image semantic extraction, formatting, classification. "
        "Pass notes_root_path per-request to use any local directory."
    ),
    version="0.3.0",
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
    return {"status": "ok", "service": "notesys", "version": "0.3.0"}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "NoteSystem Agent",
        "version": "0.3.0",
        "description": (
            "Note organization: image extraction, formatting, classification. "
            "Pass notes_root_path per-request for multi-directory support."
        ),
        "endpoints": {
            "organize": "POST /api/organize",
            "organize_stream": "GET /api/organize/{task_id}/stream",
            "health": "GET /health",
            "docs": "GET /docs",
        },
    }
