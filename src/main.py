"""FastAPI application entry point for NoteSystem Agent."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.agents.organizer.pipeline import OrganizerPipeline
from src.agents.querier.pipeline import QuerierPipeline
from src.api.organize import router as organize_router
from src.api.query import router as query_router
from src.core.config import AppConfig
from src.llm.client import LLMClient
from src.storage.file_manager import FileManager
from src.storage.vector_store import VectorStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize resources on startup, cleanup on shutdown."""
    logger.info("Starting NoteSystem Agent...")

    # Load configuration
    config = AppConfig.load("config")

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

    # Store in app state for route handlers
    app.state.config = config
    app.state.llm_client = llm_client
    app.state.file_manager = file_manager
    app.state.vector_store = vector_store
    app.state.organizer_pipeline = organizer_pipeline
    app.state.querier_pipeline = querier_pipeline

    logger.info("✅ NoteSystem Agent started successfully")
    logger.info(f"  📁 Notes root: {config.note_storage.root_path}")
    logger.info(f"  🔍 Qdrant: {config.qdrant.host}:{config.qdrant.port}")

    yield  # Application is running

    # Shutdown
    logger.info("Shutting down NoteSystem Agent...")


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
            "health": "GET /health",
            "docs": "GET /docs",
        },
    }
