![构建状态](https://img.shields.io/github/actions/workflow/status/meswarm/notesys/ci.yml?branch=main&label=构建状态)
![最新版本](https://img.shields.io/github/v/release/meswarm/notesys?label=最新版本)
![许可证](https://img.shields.io/github/license/meswarm/notesys?label=许可证)

[![语言-中文](https://img.shields.io/badge/语言-中文-red)](README.md)
[![Language-English](https://img.shields.io/badge/Language-English-blue)](README_EN.md)

# NoteSys

> 基于 AI 的本地笔记自动整理系统

接收原始 Markdown 笔记，通过 AI 流水线自动完成图像语义提取、内容整理、分类并存储到本地文件系统。向量检索由独立的 [ragData](../../../ragdata/) 服务提供。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/API.md](docs/API.md) | HTTP 接口完整说明（调用方参考）|
| [docs/ADMIN.md](docs/ADMIN.md) | 部署、配置、端口修改（管理员参考）|

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python ≥ 3.12 |
| 框架 | FastAPI + SSE |
| AI 模型 | DashScope — qwen3-vl-flash / qwen3.5-plus / qwen3.5-flash |
| 文件存储 | 本地文件系统（不依赖数据库）|

## 快速开始

### 前置要求

- Python >= 3.12

### 安装

```bash
git clone https://github.com/meswarm/notesys.git
cd notesys

# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装项目依赖
pip install -e .
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入你的配置信息（如 DASHSCOPE_API_KEY）
```

## 项目结构

```
.
├── config/           # 模型与分类器配置文件
├── src/              # 源代码
│   ├── agents/       # AI 代理工作流
│   ├── api/          # 接口路由
│   ├── core/         # 核心机制
│   ├── llm/          # 语言模型集成
│   ├── models/       # 数据模型规范
│   └── storage/      # 存储接口实现
├── tests/            # 测试文件
└── docs/             # 文档与计划
```

## 使用方法

### 启动服务

端口由 `.env` 中的 `PORT` 变量控制（默认 48002）：

```bash
uvicorn src.main:app --port ${PORT:-48002}
```

服务启动后可访问：

- Swagger UI：`http://localhost:48002/docs`
- 健康检查：`http://localhost:48002/health`

```bash
curl http://localhost:48002/health
# {"status": "ok", "service": "notesys", "version": "0.2.0"}
```

> 修改端口：编辑 `.env` 中的 `PORT=xxxx`，重启服务即可。详见 [docs/ADMIN.md](docs/ADMIN.md)。

---

## API 参考

> 完整接口文档见 [docs/API.md](docs/API.md)

本服务仅提供**笔记整理**功能。采用**异步任务 + SSE 流式推送**模式：

1. `POST /api/organize` — 提交任务 → 获得 `task_id`
2. `GET /api/organize/{task_id}/stream` — 订阅 SSE → 实时接收进度和结果

> **RAG 查询**功能已独立到 [ragData](../../../ragdata/) 服务，请参阅其 API 文档。

### 笔记整理 API

#### 1. 提交整理任务

```
POST /api/organize
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `markdown_content` | string | ✅ | 原始 Markdown 笔记内容 |
| `images_dir` | string | ❌ | 图片所在目录（不填用 NOTES_ROOT_PATH）|
| `enable_image_semantic` | bool\|null | ❌ | 图像语义提取（null = 读取配置默认值）|
| `enable_note_format` | bool\|null | ❌ | 笔记内容整理（null = 读取配置默认值）|
| `enable_classify_and_save` | bool\|null | ❌ | 分类 + 保存（null = 读取配置默认值）|

> **开关优先级**：API 参数 > `config/models.yaml` 中的配置默认值。传 `null` 或不传 = 使用配置文件中的 `organize` 部分设置。

**流水线步骤：**

```
原始 Markdown
  ├─ ① 图像语义提取  (enable_image_semantic)
  ├─ ② 笔记内容整理  (enable_note_format)
  └─ ③ 分类 + 保存  (enable_classify_and_save)
         ↓
       vault/编程/Python/xxx.md
         ↓ (由 ragData 后台自动扫描)
       Qdrant 向量索引
```

**请求示例：**

```bash
# 全流程（使用配置文件默认值）
curl -X POST http://localhost:48002/api/organize \
  -H "Content-Type: application/json" \
  -d '{"markdown_content": "# 我的笔记\n\n内容..."}'

# 仅分类保存，跳过图像处理和格式整理
curl -X POST http://localhost:48002/api/organize \
  -H "Content-Type: application/json" \
  -d '{"markdown_content": "...", "enable_image_semantic": false, "enable_note_format": false}'
```

**响应：**

```json
{
  "task_id": "a1b2c3d4-...",
  "message": "任务已创建，请订阅 SSE 获取进度"
}
```

#### 2. 订阅整理进度

```
GET /api/organize/{task_id}/stream
Accept: text/event-stream
```

**SSE 事件类型：**

| 事件 | 说明 | data 字段 |
|------|------|-----------|
| `progress` | 步骤进度更新 | `{"step", "progress", "message"}` |
| `result` | 最终结果 | `{"success", "note_path", "category", "subcategory", "title", "chunks", "token_summary"}` |
| `error` | 错误信息 | `{"step", "error"}` |

**SSE 流示例：**

```
event: progress
data: {"step": "image_semantic", "progress": 0.05, "message": "正在提取图像语义..."}

event: progress
data: {"step": "note_format", "progress": 0.50, "message": "笔记整理完成"}

event: result
data: {"success": true, "note_path": "notes/技术/Linux/解压命令.md", "category": "技术", "subcategory": "Linux", "title": "解压命令", "chunks": 3, "token_summary": {...}}
```

---

> **向量检索（RAG）：** 请使用独立的 ragData 服务（`POST http://localhost:8001/query`），详见 [ragData API 文档](../../../ragdata/docs/API.md)。

### 常用场景速查

| 场景 | 请求参数 |
|------|----------|
| 全流程（图像+整理+分类保存）| `{}` 使用配置默认值 |
| 跳过图像处理 | `{"enable_image_semantic": false}` |
| 仅分类保存，不整理内容 | `{"enable_image_semantic": false, "enable_note_format": false}` |
| 纯处理不保存（预览模式）| `{"enable_classify_and_save": false}` → result 中含 `processed_content` |

## 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feat/your-feature`)
3. 提交更改 (`git commit -m 'feat: add your feature'`)
4. 推送分支 (`git push origin feat/your-feature`)
5. 发起 Pull Request

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。
