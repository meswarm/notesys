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
git clone https://github.com/OWNER/notesys.git
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

### Running locally

```bash
uvicorn src.main:app --reload
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

Once the system is running, you can interact with the endpoints by visiting the API documentation:

```bash
# Open in your browser
http://127.0.0.1:8000/docs
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Commit your changes (`git commit -m 'feat: add your feature'`)
4. Push to the branch (`git push origin feat/your-feature`)
5. Open a Pull Request

## License

MIT License — see [LICENSE](LICENSE) for details.
