# NoteSystem Agent — API 文档

> 版本 v0.2.0 | 服务地址：`http://localhost:${PORT}` (默认端口 8002)

---

## 概述

NoteSystem Agent 提供笔记自动整理能力，通过 HTTP API 接收原始 Markdown 内容，经由 AI 流水线处理后将笔记保存到本地文件系统。

**交互模式（异步 + SSE）：**
1. 调用 `POST /api/organize` 提交任务 → 立即获得 `task_id`
2. 连接 `GET /api/organize/{task_id}/stream` → 通过 SSE 实时接收进度和结果

---

## 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/organize` | 提交笔记整理任务 |
| `GET` | `/api/organize/{task_id}/stream` | SSE 订阅任务进度与结果 |
| `GET` | `/health` | 服务健康检查 |
| `GET` | `/` | 服务基本信息 |
| `GET` | `/docs` | 交互式 API 文档（Swagger UI） |

---

## POST /api/organize

提交一条笔记给 AI 流水线处理。

### 请求

```http
POST /api/organize
Content-Type: application/json
```

#### 请求体字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `markdown_content` | `string` | ✅ | 原始 Markdown 笔记内容 |
| `images_dir` | `string` | ❌ | 笔记引用的图片所在目录（绝对路径）；不填则使用 `NOTES_ROOT_PATH` |
| `enable_image_semantic` | `bool \| null` | ❌ | 是否开启图像语义提取（null = 读取服务端配置默认值） |
| `enable_note_format` | `bool \| null` | ❌ | 是否开启笔记内容整理（null = 读取服务端配置默认值） |
| `enable_classify_and_save` | `bool \| null` | ❌ | 是否开启分类 + 保存到文件（null = 读取服务端配置默认值） |

> **说明：** 三个 `enable_*` 字段均为可选，传 `null` 或不传时，服务使用 `config/models.yaml` 中的 `organize` 配置作为默认值。

#### 请求示例

```bash
curl -X POST http://localhost:8002/api/organize \
  -H "Content-Type: application/json" \
  -d '{
    "markdown_content": "# Docker 快速入门\n\nDocker 是一个容器化平台，允许在隔离环境中运行应用程序。",
    "enable_image_semantic": false,
    "enable_note_format": true,
    "enable_classify_and_save": true
  }'
```

### 响应

```json
{
  "task_id": "a1b2c3d4-...",
  "message": "任务已创建，请订阅 SSE 获取进度"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_id` | `string` | 用于订阅 SSE 流的唯一任务 ID（UUID） |
| `message` | `string` | 固定提示文本 |

---

## GET /api/organize/{task_id}/stream

订阅指定任务的进度和结果，使用 **Server-Sent Events（SSE）** 协议。

### 请求

```http
GET /api/organize/{task_id}/stream
Accept: text/event-stream
```

连接成功后持续接收事件，直到流关闭（任务完成或出错）。

### 事件格式

每条 SSE 事件的格式：

```
event: <event_type>
data: <JSON 字符串>

```

### 事件类型

#### `progress` — 进度更新

在流水线各步骤开始和完成时发送。

```json
{
  "step":      "note_classify",
  "progress":  0.75,
  "message":   "分类: 编程/Python",
  "timestamp": "2026-04-15T10:49:31.740656"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `step` | `string` | 当前步骤标识，见下表 |
| `progress` | `float` | 整体进度 0.0 ~ 1.0 |
| `message` | `string` | 步骤状态描述文本 |
| `timestamp` | `string` | ISO 8601 时间戳 |

**步骤标识说明：**

| `step` 值 | 说明 |
|-----------|------|
| `image_semantic` | 图像语义提取（qwen3-vl-flash） |
| `note_format` | 笔记内容整理（qwen3.5-plus） |
| `note_classify` | AI 笔记分类（qwen3.5-flash） |
| `file_save` | 保存到本地文件系统 |

#### `result` — 最终结果

任务完成后发送，是流的最后一条事件。

```json
{
  "success":    true,
  "note_path":  "编程/Python/Python asyncio 入门.md",
  "category":   "编程",
  "subcategory": "Python",
  "title":      "Python asyncio 入门",
  "token_summary": {
    "total_tokens": 1280,
    "total_cost":   0.0023,
    "breakdown": [
      { "step": "note_classify", "tokens": 320, "cost": 0.0008 }
    ]
  },
  "processed_content": null,
  "timestamp":  "2026-04-15T10:49:45.123456"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | `bool` | 任务是否成功 |
| `note_path` | `string` | 相对于 `NOTES_ROOT_PATH` 的存储路径（`enable_classify_and_save=false` 时为空）|
| `category` | `string` | 笔记一级分类 |
| `subcategory` | `string` | 笔记二级分类 |
| `title` | `string` | AI 生成的笔记标题 |
| `token_summary` | `object` | Token 用量和费用统计 |
| `processed_content` | `string \| null` | 仅当 `enable_classify_and_save=false` 时返回处理后的 Markdown 内容 |
| `timestamp` | `string` | ISO 8601 时间戳 |

#### `error` — 错误事件

任务失败时发送（代替 `result`）。

```json
{
  "error":     "DashScope API call failed: rate limit exceeded",
  "retry":     false,
  "step":      "note_format",
  "timestamp": "2026-04-15T10:49:35.000000"
}
```

### SSE 订阅示例

**curl:**
```bash
curl -N "http://localhost:8002/api/organize/a1b2c3d4-.../stream"
```

**Python:**
```python
import httpx, json

task_id = "a1b2c3-..."

with httpx.stream("GET", f"http://localhost:8002/api/organize/{task_id}/stream") as r:
    for line in r.iter_lines():
        if line.startswith("data:"):
            event = json.loads(line[5:].strip())
            print(event)
```

**JavaScript (Browser / Node):**
```javascript
const source = new EventSource(
  `http://localhost:8002/api/organize/${taskId}/stream`
);

source.addEventListener("progress", (e) => {
  const data = JSON.parse(e.data);
  console.log(`[${data.step}] ${data.message}`);
});

source.addEventListener("result", (e) => {
  const data = JSON.parse(e.data);
  if (data.success) {
    console.log("✅ 保存路径:", data.note_path);
  }
  source.close();
});

source.addEventListener("error", () => source.close());
```

---

## GET /health

健康检查，用于监控服务是否存活。

```bash
curl http://localhost:8002/health
```

```json
{
  "status": "ok",
  "service": "notesys",
  "version": "0.2.0"
}
```

---

## 完整调用流程

```
╔══════════════════════╗      ①POST /api/organize        ╔══════════════╗
║    调用方（客户端）    ║ ─────────────────────────────► ║   notesys    ║
║                      ║ ◄─────────────────────────────  ║              ║
║  获得 task_id        ║      { task_id: "abc..." }      ║              ║
║                      ║                                  ║              ║
║  ②GET /stream        ║ ─────────────────────────────► ║  异步处理中   ║
║                      ║ ◄── event:progress (多条) ────  ║              ║
║                      ║ ◄── event:result (最后一条) ── ║              ║
╚══════════════════════╝                                  ╚══════════════╝
```

**注意事项：**
- `task_id` 仅在服务运行期间有效（内存存储），服务重启后失效
- `stream` 连接断开后任务仍在后台继续执行（断开不等于取消）
- 文件保存路径为相对于 `NOTES_ROOT_PATH` 的相对路径
- 若 ragData 服务在运行，文件保存后会在下次同步周期内被自动向量化

---

## 错误码

| HTTP 状态码 | 含义 |
|------------|------|
| `200` | 请求成功（任务提交成功或 SSE 流正常） |
| `404` | `task_id` 不存在（已过期或服务曾重启） |
| `422` | 请求体格式错误（缺少必填字段等） |
| `500` | 服务内部错误 |
