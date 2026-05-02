[语言-中文](README.md) | [Language-English](README_EN.md)

# NoteSys

A local Markdown note organization and retrieval system.

It takes raw notes, then runs a pipeline that extracts image semantics, reorganizes content, classifies the note, and stores it on the local file system. Vector retrieval is handled by the separate `ragData` service.

## Features

- Image semantic extraction that fills Markdown image `alt` text
- Content reorganization that preserves commands, links, and code blocks
- Automatic classification and local file storage
- SSE progress and result streaming

## Requirements

- Python 3.12+
- `DASHSCOPE_API_KEY`
- Optional: `Qdrant` and the independent `ragData` service for query and vector retrieval

## Installation

```bash
git clone git@github.com:meswarm/notesys.git
cd notesys
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` and set `DASHSCOPE_API_KEY` and any local path settings you need.

## Running

```bash
make dev
```

Common commands:

- `make start` start the service
- `make dev` start in development mode
- `make bg` start in the background
- `make stop` stop the background service
- `make test` run tests
- `make lint` run static checks

Default endpoints:

- `http://localhost:48002/docs`
- `http://localhost:48002/health`

## API

- `POST /api/organize`
- `GET /api/organize/{task_id}/stream`

Full API documentation is in [docs/API.md](docs/API.md).

## Project Structure

```text
.
├── config/
├── docs/
├── src/
├── tests/
├── README.md
└── README_EN.md
```

## License

MIT License. See [LICENSE](LICENSE).
