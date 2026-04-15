# NoteSystem Agent — Makefile
# 使用方式: make <命令>

.PHONY: start dev stop install test lint help

# 读取 .env 中的 PORT（默认 48002）
PORT ?= $(shell grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 | tr -d ' ' || echo 48002)
VENV  := .venv
UV    := $(VENV)/bin/uvicorn
PY    := $(VENV)/bin/python

##@ 服务管理

start: ## 前台启动服务（生产模式）
	@echo "▶ 启动 NoteSystem Agent (port $(PORT))..."
	$(UV) src.main:app --host 0.0.0.0 --port $(PORT)

dev: ## 前台启动服务（开发模式，文件变动自动重载）
	@echo "▶ 启动 NoteSystem Agent [开发模式] (port $(PORT))..."
	$(UV) src.main:app --host 0.0.0.0 --port $(PORT) --reload --log-level debug

bg: ## 后台启动服务，日志写入 logs/notesys.log
	@mkdir -p logs
	@echo "▶ 后台启动 NoteSystem Agent (port $(PORT))..."
	nohup $(UV) src.main:app --host 0.0.0.0 --port $(PORT) > logs/notesys.log 2>&1 & \
	echo $$! > notesys.pid && echo "✅ PID $$(cat notesys.pid) — 日志: logs/notesys.log"

stop: ## 停止后台服务
	@if [ -f notesys.pid ]; then \
	  kill $$(cat notesys.pid) && rm notesys.pid && echo "⏹ 服务已停止"; \
	else \
	  echo "⚠ 未找到 notesys.pid，服务可能未在后台运行"; \
	fi

status: ## 查看服务健康状态
	@curl -sf http://localhost:$(PORT)/health | python3 -m json.tool || echo "⚠ 服务未响应 (port $(PORT))"

##@ 开发工具

install: ## 安装依赖（首次部署或更新依赖时使用）
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -e ".[dev]"
	@echo "✅ 依赖安装完成"

test: ## 运行测试
	$(VENV)/bin/pytest tests/ -v

lint: ## 代码格式检查
	$(VENV)/bin/ruff check src/ tests/

##@ 帮助

help: ## 显示帮助信息
	@awk 'BEGIN {FS = ":.*##"; printf "\n\033[1mNoteSystem Agent\033[0m\n\n"} \
	  /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36mmake %-10s\033[0m %s\n", $$1, $$2 } \
	  /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo ""

.DEFAULT_GOAL := help
