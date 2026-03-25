![构建状态](https://img.shields.io/github/actions/workflow/status/meswarm/notesys/ci.yml?branch=main&label=构建状态)
![最新版本](https://img.shields.io/github/v/release/meswarm/notesys?label=最新版本)
![许可证](https://img.shields.io/github/license/meswarm/notesys?label=许可证)

[![语言-中文](https://img.shields.io/badge/语言-中文-red)](README.md)
[![Language-English](https://img.shields.io/badge/Language-English-blue)](README_EN.md)

# NoteSys

> 基于 AI 的笔记管理系统

不仅提供基础的笔记存储，还通过集成大语言模型与向量数据库（Qdrant），实现笔记自动化分类、抽取与智能语义查询，帮助您告别混乱的笔记仓库。

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python (>= 3.12) |
| 框架 | FastAPI |
| 数据库 | Qdrant (Vector DB) / SQLite |
| 第三方 API | DashScopeAPI / Qwen 模型 |

## 快速开始

### 前置要求

- Python >= 3.12

### 安装

```bash
git clone https://github.com/OWNER/notesys.git
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

```bash
# 开发模式（自动重载）
uvicorn src.main:app --reload

# 生产模式
.venv/bin/python3 .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000
```

服务启动后可访问自动生成的交互式文档：

- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`

### 健康检查

```bash
curl http://localhost:8000/health
# {"status": "ok", "service": "notesys"}
```

---

## API 参考

NoteSys 提供两大核心 API：**笔记整理** 和 **笔记查询**。两者均采用 **异步任务 + SSE 流式推送** 模式：

1. `POST` 提交任务 → 返回 `task_id`
2. `GET` 订阅 SSE 事件流 → 实时获取进度和结果

### 一、笔记整理 API

#### 1. 提交整理任务

```
POST /api/organize
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `markdown_content` | string | ✅ | — | 要整理的 Markdown 笔记原文 |
| `images_dir` | string | ❌ | 笔记根目录 | 笔记引用图片所在的目录路径 |
| `enable_image_semantic` | bool \| null | ❌ | `null` | 图像语义提取开关（VL 模型）|
| `enable_note_format` | bool \| null | ❌ | `null` | 笔记内容整理开关（LLM 排版）|
| `enable_classify_and_save` | bool \| null | ❌ | `null` | 分类 + 文件存储开关 |
| `enable_embedding` | bool \| null | ❌ | `null` | 分块向量嵌入开关 |

> **开关优先级**：API 参数 > `config/models.yaml` 中的配置默认值。传 `null` 或不传 = 使用配置文件中的 `organize` 部分设置。

**整理管道流程：**

```
原始 Markdown
  │
  ├─ ① 图像语义提取 (enable_image_semantic)
  │     使用 VL 模型分析图片内容，将语义描述嵌入 alt text
  │
  ├─ ② 笔记内容整理 (enable_note_format)
  │     使用 LLM 对笔记进行格式化、排版优化
  │
  ├─ ③ 分类 + 存储 (enable_classify_and_save)
  │     LLM 自动分类并存储到对应目录
  │
  └─ ④ 分块向量嵌入 (enable_embedding)
        文本分块 → 嵌入向量 → 写入 Qdrant（依赖步骤③产生的路径）
```

> ⚠️ **注意**：步骤④依赖步骤③的结果（需要已存储的笔记路径）。如果关闭了步骤③，步骤④即使启用也会自动跳过。

**请求示例：**

```bash
# 全流程整理（使用配置文件默认值）
curl -X POST http://localhost:8000/api/organize \
  -H "Content-Type: application/json" \
  -d '{"markdown_content": "# 我的笔记\n\n这是一段测试内容..."}'

# 仅做图像语义提取，跳过其他步骤
curl -X POST http://localhost:8000/api/organize \
  -H "Content-Type: application/json" \
  -d '{
    "markdown_content": "# 带图笔记\n\n![](image.png)",
    "enable_note_format": false,
    "enable_classify_and_save": false,
    "enable_embedding": false
  }'

# 跳过图像语义（已提取过），执行整理+分类+嵌入
curl -X POST http://localhost:8000/api/organize \
  -H "Content-Type: application/json" \
  -d '{
    "markdown_content": "...",
    "enable_image_semantic": false
  }'
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

### 二、笔记查询 API

#### 1. 提交查询任务

```
POST /api/query
Content-Type: application/json
```

**请求参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | ✅ | — | 查询关键词或自然语言问题 |
| `top_k` | int | ❌ | `10` | 向量检索返回的最大结果数 |
| `enable_rewrite` | bool \| null | ❌ | `null` | 查询词重写开关（LLM 优化查询） |
| `enable_synthesis` | bool \| null | ❌ | `null` | 结果综合整理开关（LLM 生成摘要回答） |

> **开关优先级**：API 参数 > `config/models.yaml` 中的配置默认值。传 `null` 或不传 = 使用配置文件中的 `query` 部分设置。

**查询管道流程：**

```
用户查询
  │
  ├─ ① 查询词重写 (enable_rewrite)
  │     LLM 优化查询词、提取关键字和意图
  │
  ├─ ② 向量检索（始终启用）
  │     生成查询嵌入 → Qdrant 混合检索（稠密+稀疏）
  │
  └─ ③ 结果综合 (enable_synthesis)
        LLM 阅读检索到的笔记全文，生成综合回答
```

> 💡 **性能提示**：关闭步骤①②可大幅提升查询速度（跳过 2 次 LLM 调用）。关闭后，原始查询直接用于向量检索，结果仅返回前 5 篇相关文档的路径和分数。

**请求示例：**

```bash
# 最快模式：直接向量检索，返回文档列表
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Linux解压命令", "top_k": 10}'

# 启用查询改写，但不综合（返回优化查询的文档列表）
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Linux解压命令", "enable_rewrite": true}'

# 全流程：改写 + 检索 + 综合回答
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Linux解压命令", "enable_rewrite": true, "enable_synthesis": true}'
```

**响应：**

```json
{
  "task_id": "e5f6g7h8-...",
  "message": "查询任务已创建，请订阅 SSE 获取进度"
}
```

#### 2. 订阅查询进度

```
GET /api/query/{task_id}/stream
Accept: text/event-stream
```

**SSE 事件类型：**

| 事件 | 说明 | data 字段 |
|------|------|-----------|
| `progress` | 步骤进度更新 | `{"step", "progress", "message"}` |
| `result` | 最终结果 | `{"success", "answer", "related_notes", "token_summary"}` |
| `error` | 错误信息 | `{"step", "error"}` |

**`result` 事件中的 `related_notes` 结构：**

```json
[
  {"note_path": "notes/技术/Linux/解压命令.md", "note_title": "解压命令", "score": 87},
  {"note_path": "notes/技术/Linux/常用工具.md", "note_title": "常用工具", "score": 72}
]
```

---

### 三、配置文件

管道步骤的默认开关在 `config/models.yaml` 中配置：

```yaml
# 笔记整理管道默认开关
organize:
  enable_image_semantic: true   # 图像语义提取（VL 模型调用）
  enable_note_format: true      # 笔记内容整理（LLM 调用）
  enable_classify_and_save: true # 分类 + 存储（LLM + 文件写入）
  enable_embedding: true        # 分块向量嵌入（嵌入模型 + Qdrant）

# 笔记查询管道默认开关
query:
  enable_rewrite: false      # 查询词重写（LLM 调用，增加延迟）
  enable_synthesis: false    # 结果综合整理（LLM 调用，增加延迟）
```

> 配置文件设定全局默认值，API 请求中的参数可逐次覆盖。

### 四、常用场景速查

| 场景 | 整理 API 参数 | 查询 API 参数 |
|------|--------------|--------------|
| 全流程处理 | `{}` (全部使用配置默认值) | `{"enable_rewrite": true, "enable_synthesis": true}` |
| 仅提取图像语义 | `{"enable_note_format": false, "enable_classify_and_save": false, "enable_embedding": false}` | — |
| 跳过图像（已提取） | `{"enable_image_semantic": false}` | — |
| 仅分类+存储（不嵌入） | `{"enable_image_semantic": false, "enable_note_format": false, "enable_embedding": false}` | — |
| 快速检索（最快） | — | `{}` (默认关闭改写和综合) |
| 带改写的检索 | — | `{"enable_rewrite": true}` |
| 完整语义问答 | — | `{"enable_rewrite": true, "enable_synthesis": true}` |

## 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feat/your-feature`)
3. 提交更改 (`git commit -m 'feat: add your feature'`)
4. 推送分支 (`git push origin feat/your-feature`)
5. 发起 Pull Request

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。
