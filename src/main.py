"""FastAPI application entry point for NoteSystem Agent."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from loguru import logger

from src.agents.organizer.embedder import Embedder
from src.agents.organizer.pipeline import OrganizerPipeline
from src.agents.querier.pipeline import QuerierPipeline
from src.api.organize import router as organize_router
from src.api.query import router as query_router
from src.core.config import AppConfig
from src.llm.client import LLMClient
from src.storage.file_manager import FileManager
from src.storage.vector_store import VectorStore
from src.sync.service import SyncService


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

    # Initialize storage
    file_manager = FileManager(
        root_path=config.note_storage.root_path,
        max_depth=config.note_storage.max_directory_depth,
    )

    vector_store = VectorStore(
        host=config.qdrant.host,
        port=config.qdrant.port,
        grpc_port=config.qdrant.grpc_port,
        collection_name=config.qdrant.collection,
        dense_dim=config.get_model_config("embedding").dimension or 1024,
    )

    # Initialize Qdrant collection
    try:
        await vector_store.init_collection()
        logger.info("Qdrant collection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Qdrant: {e}")
        logger.warning("Vector store features will be unavailable")

    # Initialize Embedder (shared by organizer pipeline and sync service)
    embed_config = config.get_model_config("embedding")
    embedder = Embedder(
        llm_client=llm_client,
        vector_store=vector_store,
        dimension=embed_config.dimension or 1024,
        batch_size=embed_config.batch_size or 10,
    )

    # Initialize pipelines
    organizer_pipeline = OrganizerPipeline(
        config=config,
        llm_client=llm_client,
        file_manager=file_manager,
        vector_store=vector_store,
    )

    querier_pipeline = QuerierPipeline(
        config=config,
        llm_client=llm_client,
        file_manager=file_manager,
        vector_store=vector_store,
    )

    # Initialize sync service
    sync_service = SyncService(
        config=config,
        vector_store=vector_store,
        embedder=embedder,
    )

    # Store in app state for route handlers
    app.state.config = config
    app.state.llm_client = llm_client
    app.state.file_manager = file_manager
    app.state.vector_store = vector_store
    app.state.organizer_pipeline = organizer_pipeline
    app.state.querier_pipeline = querier_pipeline
    app.state.sync_service = sync_service

    # Start sync service if enabled
    if config.sync.enabled:
        sync_service.start()

    logger.info("✅ NoteSystem Agent started successfully")
    logger.info(f"  📁 Notes root: {config.note_storage.root_path}")
    logger.info(f"  🔍 Qdrant: {config.qdrant.host}:{config.qdrant.port}")
    logger.info(f"  🔄 Sync: {'enabled' if config.sync.enabled else 'disabled'} "
                f"(interval={config.sync.interval_seconds}s, batch={config.sync.batch_limit})")

    yield  # Application is running

    # Shutdown
    logger.info("Shutting down NoteSystem Agent...")
    await sync_service.stop()


# Create FastAPI app
app = FastAPI(
    title="NoteSystem Agent",
    description="AI-powered note management system with organize and query agents",
    version="0.1.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(organize_router)
app.include_router(query_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "notesys"}


@app.post("/api/sync")
async def trigger_sync(request: Request):
    """Manually trigger a single sync cycle."""
    sync_service: SyncService = request.app.state.sync_service
    result = await sync_service.run_once()
    return {"status": "ok", "result": result}


@app.post("/api/sync/rebuild")
async def trigger_rebuild(request: Request):
    """Trigger a full vector store rebuild (destructive)."""
    sync_service: SyncService = request.app.state.sync_service
    result = await sync_service.run_full_rebuild()
    return {"status": "ok", "result": result}


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "service": "NoteSystem Agent",
        "version": "0.1.0",
        "endpoints": {
            "organize": "POST /api/organize",
            "organize_stream": "GET /api/organize/{task_id}/stream",
            "query": "POST /api/query",
            "query_stream": "GET /api/query/{task_id}/stream",
            "sync": "POST /api/sync",
            "sync_rebuild": "POST /api/sync/rebuild",
            "health": "GET /health",
            "docs": "GET /docs",
        },
    }
