[语言-中文](README.md) | [Language-English](README_EN.md)

# NoteSys

本地 Markdown 笔记整理与检索系统。

它接收原始笔记，按流水线完成图像语义提取、内容整理、分类与本地存储；向量检索由独立的 `ragData` 服务处理。

## 特性

- 图像语义提取，自动补全 Markdown 图片 `alt` 文本
- 笔记内容整理，保留命令、链接、代码块等结构化内容
- 自动分类并保存到本地文件系统
- SSE 流式返回处理进度和结果

## 依赖

- Python 3.12+
- `DASHSCOPE_API_KEY`
- 可选：`Qdrant` 和独立的 `ragData` 服务，用于查询与向量检索

## 安装

```bash
git clone git@github.com:meswarm/notesys.git
cd notesys
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

编辑 `.env` 后，填入 `DASHSCOPE_API_KEY` 和需要的本地路径配置。

## 运行

```bash
make dev
```

常用命令：

- `make start` 启动服务
- `make dev` 开发模式启动
- `make bg` 后台启动
- `make stop` 停止后台服务
- `make test` 运行测试
- `make lint` 运行静态检查

默认接口地址：

- `http://localhost:48002/docs`
- `http://localhost:48002/health`

## API

- `POST /api/organize`
- `GET /api/organize/{task_id}/stream`

完整接口说明见 [docs/API.md](docs/API.md)。

## 项目结构

```text
.
├── config/
├── docs/
├── src/
├── tests/
├── README.md
└── README_EN.md
```

## 许可证

MIT License。详见 [LICENSE](LICENSE)。
