"""端到端测试：提交笔记整理 → SSE 流式获取进度。

使用方法：
  1. 先启动服务：.venv/bin/uvicorn src.main:app --port 8000
  2. 运行本脚本：.venv/bin/python tests/test_organize_e2e.py
"""

import json
import sys
import httpx

BASE_URL = "http://localhost:8000"

# 测试笔记内容（模拟一篇混乱的初稿）
TEST_NOTE = """
# python 安装

先去官网下载，然后安装就行了

## 下载

去 https://python.org 下载 Python 3.12

emmm 其实也可以用 apt 装

```bash
sudo apt update
sudo apt install python3.12
```

## 验证

```bash
python3 --version
```

应该输出 Python 3.12.x

## 虚拟环境

装完之后建个虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## pip

pip 也要升级一下

```bash
pip install --upgrade pip
```

然后就可以装包了比如

```bash
pip install requests
```

就这样吧
"""


def main():
    print("=" * 60)
    print("📝 端到端测试：笔记整理 (Organize)")
    print("=" * 60)

    # Step 1: 提交笔记整理请求
    print("\n🔵 Step 1: 提交整理请求 (POST /api/organize)")
    try:
        resp = httpx.post(
            f"{BASE_URL}/api/organize",
            json={
                "markdown_content": TEST_NOTE,
                "images_dir": None,
            },
            timeout=10,
        )
    except httpx.ConnectError:
        print("❌ 连接失败！请确保服务已启动：")
        print("   .venv/bin/uvicorn src.main:app --port 8000")
        sys.exit(1)

    print(f"   HTTP 状态码: {resp.status_code}")
    data = resp.json()
    task_id = data["task_id"]
    print(f"   任务 ID: {task_id}")
    print(f"   消息: {data['message']}")

    # Step 2: 订阅 SSE 流获取进度
    print(f"\n🔵 Step 2: 订阅 SSE 流 (GET /api/organize/{task_id}/stream)")
    print("-" * 60)

    with httpx.stream(
        "GET",
        f"{BASE_URL}/api/organize/{task_id}/stream",
        timeout=300,  # 整理可能需要几分钟
    ) as stream:
        buffer = ""
        for chunk in stream.iter_text():
            buffer += chunk
            # SSE events are separated by double newlines
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                _process_event_block(event_block.strip())

        # Process any remaining data
        if buffer.strip():
            _process_event_block(buffer.strip())

    print("-" * 60)
    print("\n✅ 整理流程完成！")


def _process_event_block(block: str):
    """Parse an SSE event block and print it."""
    event_type = None
    data_str = None

    for line in block.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]

    if event_type and data_str:
        _print_event(event_type, data_str)


def _print_event(event_type: str, data_str: str):
    """格式化打印 SSE 事件。"""
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        print(f"  [{event_type}] {data_str}")
        return

    if event_type == "progress":
        step = data.get("step", "")
        progress = data.get("progress", 0)
        message = data.get("message", "")
        bar = "█" * int(progress * 20) + "░" * (20 - int(progress * 20))
        print(f"  📊 [{bar}] {progress*100:5.1f}%  {step}: {message}")

    elif event_type == "result":
        print(f"\n  🎉 结果:")
        if data.get("success"):
            print(f"     笔记路径: {data.get('note_path', 'N/A')}")
            print(f"     分类: {data.get('category', '')}/{data.get('subcategory', '')}")
            print(f"     标题: {data.get('title', '')}")
            print(f"     向量数: {data.get('chunks', 0)}")
            summary = data.get("token_summary", {})
            print(f"     Token 消耗: {summary.get('total_tokens', 0)}")
            print(f"     费用: ¥{summary.get('total_cost', 0):.4f}")
        else:
            print(f"     ❌ 失败: {data.get('error', 'unknown')}")

    elif event_type == "error":
        print(f"  ❌ 错误: {data.get('error', '')}")
        print(f"     步骤: {data.get('step', '')}")
        print(f"     重试: {data.get('retry', False)}")

    elif event_type == "status":
        print(f"  ℹ️  状态: {data.get('message', '')}")


if __name__ == "__main__":
    main()
