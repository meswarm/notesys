![Build Status](https://img.shields.io/github/actions/workflow/status/meswarm/notesys/ci.yml?branch=main)
![Version](https://img.shields.io/github/v/release/meswarm/notesys)
![License](https://img.shields.io/github/license/meswarm/notesys)

[![语言-中文](https://img.shields.io/badge/语言-中文-red)](README.md)
[![Language-English](https://img.shields.io/badge/Language-English-blue)](README_EN.md)

# NoteSys

> AI-Powered Note Management System

Provides not only basic note storage but also automated categorization, extraction, and intelligent semantic querying through the integration of Large Language Models and vector databases (Qdrant). Stop losing your thoughts in a messy repository.

## Tech Stack

| Category       | Technology                       |
| -------------- | -------------------------------- |
| Language       | Python (>= 3.12)                 |
| Framework      | FastAPI                          |
| Database       | Qdrant (Vector DB) / SQLite      |
| AI APIs        | DashScopeAPI / Qwen Models       |

## Getting Started

### Prerequisites

* Python >= 3.12

### Installation

```bash
git clone https://github.com/meswarm/notesys.git
cd notesys

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install project dependencies
pip install -e .
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your configuration (e.g., DASHSCOPE_API_KEY)
```

### Running Locally

```bash
# Development mode (auto-reload)
uvicorn src.main:app --reload

# Production mode
.venv/bin/python3 .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
```

## Project Structure

```
.
├── config/           # Model and agent configurations
├── src/              # Source code
│   ├── agents/       # AI agent workflows
│   ├── api/          # API routers
│   ├── core/         # Core mechanics
│   ├── llm/          # Large Language Model integration
│   ├── models/       # Data models and schemas
│   └── storage/      # Storage interface implementations
├── tests/            # Test files
└── docs/             # Specs and documentations
```

## Usage

Once the system is running, interactive API docs are available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

### Health Check

```bash
curl http://localhost:8000/health
# {"status": "ok", "service": "notesys"}
```

---

## API Reference

NoteSys provides two core APIs: **Note Organization** and **Note Query**. Both use an **async task + SSE streaming** pattern:

1. `POST` to submit a task → returns a `task_id`
2. `GET` to subscribe to SSE event stream → receive real-time progress and results

### 1. Note Organization API

#### Submit Organization Task

```
POST /api/organize
Content-Type: application/json
```

**Request Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `markdown_content` | string | ✅ | — | Raw Markdown note content to organize |
| `images_dir` | string | ❌ | notes root | Directory containing referenced images |
| `enable_image_semantic` | bool \| null | ❌ | `null` | Image semantic extraction toggle (VL model) |
| `enable_note_format` | bool \| null | ❌ | `null` | Note formatting toggle (LLM layout) |
| `enable_classify_and_save` | bool \| null | ❌ | `null` | Classification + file storage toggle |
| `enable_embedding` | bool \| null | ❌ | `null` | Chunk embedding toggle |

> **Priority**: API parameter > `config/models.yaml` default. Passing `null` or omitting = use the `organize` section in the config file.

**Pipeline Flow:**

```
Raw Markdown
  │
  ├─ ① Image Semantic Extraction (enable_image_semantic)
  │     VL model analyzes image content, embeds semantic description into alt text
  │
  ├─ ② Note Formatting (enable_note_format)
  │     LLM formats and optimizes note layout
  │
  ├─ ③ Classify + Save (enable_classify_and_save)
  │     LLM auto-classifies and saves to the appropriate directory
  │
  └─ ④ Chunk Embedding (enable_embedding)
        Text chunking → embedding → write to Qdrant (depends on step ③ path)
```

> ⚠️ **Note**: Step ④ depends on step ③ (requires the saved note path). If step ③ is disabled, step ④ will be automatically skipped even if enabled.

**Request Examples:**

```bash
# Full pipeline (uses config defaults)
curl -X POST http://localhost:8000/api/organize \
  -H "Content-Type: application/json" \
  -d '{"markdown_content": "# My Note\n\nSome content..."}'

# Image semantic only, skip everything else
curl -X POST http://localhost:8000/api/organize \
  -H "Content-Type: application/json" \
  -d '{
    "markdown_content": "# Note with image\n\n![](image.png)",
    "enable_note_format": false,
    "enable_classify_and_save": false,
    "enable_embedding": false
  }'

# Skip image semantic (already extracted), run format+classify+embed
curl -X POST http://localhost:8000/api/organize \
  -H "Content-Type: application/json" \
  -d '{"markdown_content": "...", "enable_image_semantic": false}'
```

**Response:**

```json
{
  "task_id": "a1b2c3d4-...",
  "message": "任务已创建，请订阅 SSE 获取进度"
}
```

#### Subscribe to Organization Progress

```
GET /api/organize/{task_id}/stream
Accept: text/event-stream
```

**SSE Event Types:**

| Event | Description | Data Fields |
|-------|-------------|-------------|
| `progress` | Step progress update | `{"step", "progress", "message"}` |
| `result` | Final result | `{"success", "note_path", "category", "subcategory", "title", "chunks", "token_summary"}` |
| `error` | Error info | `{"step", "error"}` |

---

### 2. Note Query API

#### Submit Query Task

```
POST /api/query
Content-Type: application/json
```

**Request Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | ✅ | — | Search keywords or natural language question |
| `top_k` | int | ❌ | `10` | Maximum number of retrieval results |
| `enable_rewrite` | bool \| null | ❌ | `null` | Query rewrite toggle (LLM query optimization) |
| `enable_synthesis` | bool \| null | ❌ | `null` | Result synthesis toggle (LLM summary answer) |

> **Priority**: API parameter > `config/models.yaml` default. Passing `null` or omitting = use the `query` section in the config file.

**Pipeline Flow:**

```
User Query
  │
  ├─ ① Query Rewrite (enable_rewrite)
  │     LLM optimizes query, extracts keywords and intent
  │
  ├─ ② Vector Retrieval (always enabled)
  │     Generate query embedding → Qdrant hybrid search (dense + sparse)
  │
  └─ ③ Result Synthesis (enable_synthesis)
        LLM reads retrieved note contents, generates comprehensive answer
```

> 💡 **Performance tip**: Disabling steps ① and ③ significantly improves query speed (skips 2 LLM calls). When disabled, the original query is used directly for vector search, and results return only the top 5 relevant document paths with scores.

**Request Examples:**

```bash
# Fastest mode: direct vector search, returns document list
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Linux extract commands", "top_k": 10}'

# With query rewrite, no synthesis (returns optimized document list)
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Linux extract commands", "enable_rewrite": true}'

# Full pipeline: rewrite + retrieve + synthesize
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Linux extract commands", "enable_rewrite": true, "enable_synthesis": true}'
```

**Response:**

```json
{
  "task_id": "e5f6g7h8-...",
  "message": "查询任务已创建，请订阅 SSE 获取进度"
}
```

#### Subscribe to Query Progress

```
GET /api/query/{task_id}/stream
Accept: text/event-stream
```

**SSE Event Types:**

| Event | Description | Data Fields |
|-------|-------------|-------------|
| `progress` | Step progress update | `{"step", "progress", "message"}` |
| `result` | Final result | `{"success", "answer", "related_notes", "token_summary"}` |
| `error` | Error info | `{"step", "error"}` |

**`related_notes` structure in `result` event:**

```json
[
  {"note_path": "notes/Tech/Linux/extract_commands.md", "note_title": "Extract Commands", "score": 87},
  {"note_path": "notes/Tech/Linux/common_tools.md", "note_title": "Common Tools", "score": 72}
]
```

---

### 3. Configuration

Default pipeline step toggles are configured in `config/models.yaml`:

```yaml
# Organization pipeline defaults
organize:
  enable_image_semantic: true   # Image semantic extraction (VL model)
  enable_note_format: true      # Note content formatting (LLM)
  enable_classify_and_save: true # Classification + storage (LLM + file write)
  enable_embedding: true        # Chunk vector embedding (embedding model + Qdrant)

# Query pipeline defaults
query:
  enable_rewrite: false      # Query rewrite (LLM, adds latency)
  enable_synthesis: false    # Result synthesis (LLM, adds latency)
```

> Config file sets global defaults. API request parameters override them per-request.

### 4. Common Scenarios

| Scenario | Organize API Params | Query API Params |
|----------|-------------------|-----------------|
| Full pipeline | `{}` (use config defaults) | `{"enable_rewrite": true, "enable_synthesis": true}` |
| Image semantic only | `{"enable_note_format": false, "enable_classify_and_save": false, "enable_embedding": false}` | — |
| Skip images (already done) | `{"enable_image_semantic": false}` | — |
| Classify+save only | `{"enable_image_semantic": false, "enable_note_format": false, "enable_embedding": false}` | — |
| Fastest search | — | `{}` (rewrite & synthesis off by default) |
| Search with rewrite | — | `{"enable_rewrite": true}` |
| Full semantic Q&A | — | `{"enable_rewrite": true, "enable_synthesis": true}` |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Commit your changes (`git commit -m 'feat: add your feature'`)
4. Push to the branch (`git push origin feat/your-feature`)
5. Open a Pull Request

## License

MIT License — see [LICENSE](LICENSE) for details.
