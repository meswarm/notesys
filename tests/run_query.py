"""笔记查询模板：输入查询 → SSE 实时进度 → 输出回答到文件。

使用方法：
  1. 修改下方三个变量
  2. 确保服务已启动：.venv/bin/uvicorn src.main:app --port 8000
  3. 确保至少运行过一次 run_organize.py（库中需要有笔记）
  4. 运行：.venv/bin/python tests/run_query.py
"""

import json
import sys
import httpx

# ╔══════════════════════════════════════════════════════════════╗
# ║                    ⬇️ 修改这里 ⬇️                           ║
# ╠══════════════════════════════════════════════════════════════╣

# 查询关键词
QUERY = "Windows如何禁用更新啊?"

# 输出：查询结果保存到的 Markdown 文件路径（留空则不保存，仅打印）
OUTPUT_RESULT_PATH = "/home/txl/Code/meswarm/notes/vault/mytest_result.md"

# 检索返回的最大结果数
TOP_K = 10

# ╚══════════════════════════════════════════════════════════════╝

BASE_URL = "http://localhost:8000"


def main():
    print("=" * 60)
    print("笔记查询")
    print("=" * 60)
    print(f"  查询: {QUERY}")
    print(f"  Top-K: {TOP_K}")
    print(f"  输出文件: {OUTPUT_RESULT_PATH or '(仅打印)'}")

    # Step 1: 提交查询请求
    print(f"\n[1] 提交查询请求")
    try:
        resp = httpx.post(
            f"{BASE_URL}/api/query",
            json={"query": QUERY, "top_k": TOP_K},
            timeout=10,
        )
    except httpx.ConnectError:
        print("连接失败！请先启动服务：")
        print("  .venv/bin/uvicorn src.main:app --port 8000")
        sys.exit(1)

    task_id = resp.json()["task_id"]
    print(f"  任务 ID: {task_id}")

    # Step 2: SSE 流式获取进度
    print(f"\n[2] 实时进度")
    print("-" * 60)

    result_data = None

    with httpx.stream(
        "GET",
        f"{BASE_URL}/api/query/{task_id}/stream",
        timeout=180,
    ) as stream:
        buffer = ""
        for chunk in stream.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                block = event_block.strip()
                if block:
                    rd = _process_event(block)
                    if rd is not None:
                        result_data = rd
        if buffer.strip():
            rd = _process_event(buffer.strip())
            if rd is not None:
                result_data = rd

    print("-" * 60)

    # Step 3: 保存结果
    if result_data and OUTPUT_RESULT_PATH:
        _save_result(result_data)

    print("\n完成！")


def _process_event(block: str):
    """解析 SSE 事件块，打印进度，返回 result 数据。"""
    event_type = None
    data_str = None
    for line in block.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]

    if not event_type or not data_str:
        return None

    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        return None

    if event_type == "progress":
        p = data.get("progress", 0)
        bar = "█" * int(p * 20) + "░" * (20 - int(p * 20))
        print(f"  [{bar}] {p*100:5.1f}%  {data.get('step', '')}: {data.get('message', '')}")

    elif event_type == "result":
        if data.get("success"):
            # 打印回答
            answer = data.get("answer", "")
            print(f"\n  回答:")
            print(f"  {'─' * 50}")
            for line in answer.split("\n"):
                print(f"  {line}")
            print(f"  {'─' * 50}")

            # Token 简要
            summary = data.get("token_summary", {})
            print(f"\n  Token: {summary.get('total_tokens', 0)}, 费用: ¥{summary.get('total_cost', 0):.4f}")
        else:
            print(f"\n  查询失败: {data.get('error', '')}")
        return data

    elif event_type == "error":
        print(f"  错误 [{data.get('step', '')}]: {data.get('error', '')}")

    return None


def _save_result(data: dict):
    """将查询结果保存为 Markdown 文件。"""
    answer = data.get("answer", "")
    summary = data.get("token_summary", {})
    token_line = f"Token: {summary.get('total_tokens', 0)}, 费用: ¥{summary.get('total_cost', 0):.4f}"

    content = f"{answer}\n\n---\n{token_line}\n"

    with open(OUTPUT_RESULT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n  结果已保存: {OUTPUT_RESULT_PATH}")


if __name__ == "__main__":
    main()

