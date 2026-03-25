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

### 本地运行

```bash
uvicorn src.main:app --reload
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

系统运行后，您可以通过访问 API 文档页面来使用各项功能：

```bash
# 在浏览器打开
http://127.0.0.1:8000/docs
```

## 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feat/your-feature`)
3. 提交更改 (`git commit -m 'feat: add your feature'`)
4. 推送分支 (`git push origin feat/your-feature`)
5. 发起 Pull Request

## 许可证

MIT License — 详见 [LICENSE](LICENSE)。
