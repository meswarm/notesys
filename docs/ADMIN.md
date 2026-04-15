# NoteSystem Agent — 管理员指南

> 版本 v0.3.0

---

## 目录

- [项目定位](#项目定位)
- [目录结构](#目录结构)
- [首次部署](#首次部署)
- [环境变量配置](#环境变量配置)
- [模型参数配置](#模型参数配置)
- [笔记分类机制](#笔记分类机制)
- [启动与停止服务](#启动与停止服务)
- [修改服务端口](#修改服务端口)
- [与 ragData 集成](#与-ragdata-集成)
- [常见问题](#常见问题)

---

## 项目定位

NoteSystem Agent 是笔记自动整理服务，接收原始 Markdown 内容，通过 AI 流水线完成：

1. **图像语义提取** — 识别笔记中引用的截图内容，生成文字描述替换图片链接
2. **笔记内容整理** — 改善笔记结构、措辞与格式
3. **笔记分类 + 保存** — AI 判断所属类别，自动存入本地文件系统结构

**不负责的事：** 向量化和 RAG 检索由独立的 [ragData](../../../ragdata/) 服务处理。

---

## 目录结构

```
notesys/
├── .env                    # 环境变量（密钥、路径、端口）← 主要配置入口
├── .env.example            # 环境变量模板（不含敏感信息，可提交 git）
├── config/
│   └── models.yaml         # 各流水线步骤的模型和参数配置（categories.yaml 已废弃）
├── docs/
│   ├── API.md              # HTTP 接口说明（给调用方看）
│   └── ADMIN.md            # 本文档（给管理员/运维看）
├── src/                    # 源代码
├── tests/                  # 单元测试
└── pyproject.toml          # Python 依赖定义
```

> **v0.3.0 变化：** `categories.yaml` 已废弃。分类体系由笔记存储目录的实际一二级目录结构动态生成，无需维护静态配置文件。

---

## 首次部署

### 1. 克隆 / 复制项目

```bash
cd /home/txl/Code/meswarm/notes
# 项目已在 notesys/ 目录下
```

### 2. 创建 Python 虚拟环境并安装依赖

```bash
cd notesys
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. 配置环境变量

```bash
cp .env.example .env
vim .env   # 至少填入 DASHSCOPE_API_KEY
```

### 4. （可选）确认默认笔记目录存在

如果设置了 `NOTES_ROOT_PATH`，确保知该目录存在：

```bash
mkdir -p /your/notes/vault
```

> **提示：** v0.3.0 起 `NOTES_ROOT_PATH` 是**可选的服务端默认值**。调用方可在每次请求中通过 `notes_root_path` 字段自行指定目录，服务端不需要提前知道目录在哪里。

### 5. 启动服务

```bash
source .venv/bin/activate
uvicorn src.main:app --port ${PORT:-48002}
```

访问 `http://localhost:48002/docs` 验证服务正常。

---

## 环境变量配置

配置文件位于 **项目根目录的 `.env`**，这是所有运行时参数的主要入口。

### 完整配置说明

```dotenv
# ─── 必填 ───────────────────────────────────────────────
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxx

# ─── 可选 ───────────────────────────────────────────────
# 服务端全局默认笔记目录（绝对路径）
# 调用方可在每次请求中通过 notes_root_path 字段覆盖此默认值
NOTES_ROOT_PATH=/home/txl/Code/meswarm/notes/vault

# 服务 HTTP 端口（默认 48002）
PORT=48002
```

### 各变量说明

| 变量 | 是否必填 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | **必填** | 阿里云百炼 API Key，所有 LLM 调用依赖此 Key |
| `NOTES_ROOT_PATH` | 可选 | 服务端全局默认目录。如果所有调用方都在请求中传 `notes_root_path`，此项可不设置 |
| `PORT` | 可选 | 服务监听端口，默认 48002 |

> ⚠️ `.env` 包含密钥，**不要提交到版本控制系统**。已在 `.gitignore` 中排除。

---

## 模型参数配置

文件：`config/models.yaml`

控制各 AI 步骤使用的模型和推理参数，修改后**重启服务**生效。

```yaml
models:
  # 步骤 1：图像语义提取
  image_semantic:
    provider: "dashscope"
    model: "qwen3-vl-flash"     # 视觉理解模型，支持图片输入
    temperature: 0.3
    max_tokens: 2000
    enable_thinking: false       # 关闭思考链加速响应

  # 步骤 2：笔记内容整理
  note_organizer:
    provider: "dashscope"
    model: "qwen3.5-plus"       # 能力最强，适合复杂改写任务
    temperature: 0.7
    max_tokens: 16384
    enable_thinking: true        # 开启思考链提升质量

  # 步骤 3：笔记分类
  note_classifier:
    provider: "dashscope"
    model: "qwen3.5-flash"      # 轻量快速，分类任务足够
    temperature: 0.1             # 低温度确保分类稳定
    max_tokens: 500
    enable_thinking: false

organize:
  enable_image_semantic: true    # 默认开启图像语义提取
  enable_note_format: true       # 默认开启笔记整理
  enable_classify_and_save: true # 默认开启分类保存
```

**调参建议：**

| 场景 | 建议调整 |
|------|---------|
| 降低 API 费用 | `note_organizer` 改用 `qwen3.5-flash` |
| 提升分类准确率 | `note_classifier` 改用 `qwen3.5-plus`，降低 `temperature` 到 0.05 |
| 关闭整理默认开关 | `organize.enable_note_format: false` |

---

## 笔记分类机制

**v0.3.0 起，分类由实际目录结构决定，不再依赖 `categories.yaml`。**

每次笔记分类时，流水线会扫描 `notes_root_path`（或服务端 `NOTES_ROOT_PATH`）的一级和二级子目录，生成当前分类列表传给 LLM：

```
notes_root_path/          ← 扫描这两层
├── 编程/              ← 一级分类
│   ├── Python/        ← 二级分类
│   └── Go/
├── 工具/
│   ├── Docker/
│   └── VS Code/
└── 操作系统/
    └── Linux/
```

LLM 优先从已有分类中选择。如果笔记内容不属于任何现有分类，则自由命名枰一个新分类，**目录在写入文件时自动创建**。

**自建分类的方法：** 直接在 `notes_root_path` 下手动创建目录即可，下次请求时即自动生效：

```bash
mkdir -p /your/notes/vault/工作/会议记录
mkdir -p /your/notes/vault/AI/提示词工程
```

> ♻️ **退化兼容：** `config/categories.yaml` 仍存在且在目录为空时不会被扫描到时会展示纻 YAML 内容看作备选分类。**如果目录已存在更多内容，将优先使用目录扫描。**

---

## 启动与停止服务

### 前台运行（开发/调试）

```bash
cd /home/txl/Code/meswarm/notes/notesys
source .venv/bin/activate
uvicorn src.main:app --port ${PORT:-48002} --log-level info
```

按 `Ctrl+C` 停止。

### 后台运行（生产/长期）

推荐使用 `nohup` 或 `systemd`：

**nohup 方式：**
```bash
cd /home/txl/Code/meswarm/notes/notesys
source .venv/bin/activate
nohup uvicorn src.main:app --port ${PORT:-48002} > logs/notesys.log 2>&1 &
echo $! > notesys.pid
echo "Started PID $(cat notesys.pid)"
```

停止：
```bash
kill $(cat notesys.pid) && rm notesys.pid
```

**systemd 方式（推荐）：**

创建 `/etc/systemd/system/notesys.service`：

```ini
[Unit]
Description=NoteSystem Agent
After=network.target

[Service]
Type=simple
User=txl
WorkingDirectory=/home/txl/Code/meswarm/notes/notesys
EnvironmentFile=/home/txl/Code/meswarm/notes/notesys/.env
ExecStart=/home/txl/Code/meswarm/notes/notesys/.venv/bin/uvicorn \
    src.main:app --port 48002 --host 0.0.0.0
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable notesys
sudo systemctl start notesys
sudo systemctl status notesys
```

---

## 修改服务端口

**步骤：**

1. 打开 `.env`，修改 `PORT` 的值：

```dotenv
PORT=9000   # 改为你想要的端口
```

2. 重启服务：

```bash
# 如果是前台运行，Ctrl+C 后重新执行：
uvicorn src.main:app --port ${PORT:-48002}

# 如果是 systemd：
sudo systemctl restart notesys
```

3. 通知所有调用方更新地址。

> **原理：** 启动命令使用 `${PORT:-48002}` 读取环境变量，`.env` 中的 `PORT` 会被 shell 自动导出。如果使用 systemd，`EnvironmentFile` 字段负责加载 `.env`。

---

## 与 ragData 集成

notesys 保存文件后，向量化由独立的 [ragData](../../../ragdata/) 服务自动完成：

```
notesys 保存文件 → vault/编程/Python/xxx.md
        ↓
ragData 后台定时扫描（默认 5 分钟间隔）
        ↓
自动检测新文件 → 分块 → 向量化 → 写入 Qdrant
```

**无需任何手动操作**，只需确保 ragData 服务在运行，并且 ragData 的 `config/config.yaml` 中的 `directories` 包含了 notesys 的 `NOTES_ROOT_PATH`。

检查 ragData 是否在监听正确目录：
```bash
curl http://localhost:8001/sync/collections
```

如需立即同步（不等待下一个周期）：
```bash
curl -X POST http://localhost:8001/sync/notes
```

---

## 常见问题

### 服务启动错误 / 警告 `NOTES_ROOT_PATH does not exist`

v0.3.0 起改为软警告，不再阻止启动。两种处理方式：

- **方案 A**：创建默认目录
  ```bash
  mkdir -p /your/notes/vault
  ```
- **方案 B**：不设置 `NOTES_ROOT_PATH`，请求时始终传 `notes_root_path` 字段

### 分类结果不对 / 总是归到“未分类”

1. 检查 `notes_root_path` 下是否已有合适的一二级目录（分类来源）
2. 尝试提高 `note_classifier` 的模型档次（改用 `qwen3.5-plus`）
3. 确认 `DASHSCOPE_API_KEY` 有效

### API Key 失效 / 余额不足

服务会继续运行，但 LLM 调用会在 SSE `error` 事件中返回错误信息，笔记不会被保存。到 [阿里云百炼控制台](https://bailian.console.aliyun.com/) 充值或更换 Key 后，重新发送任务即可，无需重启服务。

### 如何查看已处理笔记

直接浏览 `NOTES_ROOT_PATH` 目录：
```bash
find /home/txl/Code/meswarm/notes/vault -name "*.md" | sort | tail -20
```

### 端口被占用

```bash
# 查看占用端口的进程
lsof -i :48002

# 修改 .env 中的 PORT 换一个端口
```
