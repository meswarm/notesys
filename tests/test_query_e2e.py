"""端到端测试：提交查询 → SSE 流式获取进度和回答。

使用方法：
  1. 先启动服务：.venv/bin/uvicorn src.main:app --port 8000
  2. 确保至少运行过一次 test_organize_e2e.py（库中需要有笔记）
  3. 运行本脚本：.venv/bin/python tests/test_query_e2e.py
  4. 也可以带参数指定查询：.venv/bin/python tests/test_query_e2e.py "Python怎么装虚拟环境"
"""

import json
import sys
import httpx

BASE_URL = "http://localhost:8000"

DEFAULT_QUERY = "怎么安装Python？"


def main():
    # 支持命令行参数自定义查询
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY

    print("=" * 60)
    print("🔍 端到端测试：笔记查询 (Query)")
    print("=" * 60)
    print(f"\n   查询: {query}")

    # Step 1: 提交查询请求
    print(f"\n🔵 Step 1: 提交查询请求 (POST /api/query)")
    try:
        resp = httpx.post(
            f"{BASE_URL}/api/query",
            json={
                "query": query,
                "top_k": 10,
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

    # Step 2: 订阅 SSE 流获取进度和结果
    print(f"\n🔵 Step 2: 订阅 SSE 流 (GET /api/query/{task_id}/stream)")
    print("-" * 60)

    with httpx.stream(
        "GET",
        f"{BASE_URL}/api/query/{task_id}/stream",
        timeout=120,
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
    print("\n✅ 查询完成！")


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
        print(f"\n  🎉 查询结果:")
        if data.get("success"):
            # 打印相关笔记
            related = data.get("related_notes", [])
            if related:
                print(f"\n  📎 相关笔记 ({len(related)} 篇):")
                for i, note in enumerate(related, 1):
                    print(f"     {i}. [{note.get('note_title', 'N/A')}] "
                          f"({note.get('note_path', 'N/A')}) "
                          f"— 相关度: {note.get('score', 0)}%")

            # 打印回答
            answer = data.get("answer", "")
            print(f"\n  📝 回答:")
            print(f"  {'─' * 50}")
            for line in answer.split("\n"):
                print(f"  {line}")
            print(f"  {'─' * 50}")

            # 打印 Token 消耗
            summary = data.get("token_summary", {})
            print(f"\n  💰 Token 消耗: {summary.get('total_tokens', 0)}")
            print(f"     费用: ¥{summary.get('total_cost', 0):.4f}")
            breakdown = summary.get("breakdown", [])
            if breakdown:
                print(f"     明细:")
                for item in breakdown:
                    print(f"       - {item.get('step', '')}: "
                          f"{item.get('tokens', 0)} tokens "
                          f"({item.get('model', '')})")
        else:
            print(f"     ❌ 失败: {data.get('error', 'unknown')}")

    elif event_type == "error":
        print(f"  ❌ 错误: {data.get('error', '')}")
        print(f"     步骤: {data.get('step', '')}")

    elif event_type == "status":
        print(f"  ℹ️  状态: {data.get('message', '')}")


if __name__ == "__main__":
    main()
