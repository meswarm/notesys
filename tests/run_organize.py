"""笔记整理模板：读取 Markdown 文件 → 提交整理 → SSE 实时进度 → 输出结果到文件。

使用方法：
  1. 修改下方三个变量
  2. 确保服务已启动：.venv/bin/uvicorn src.main:app --port 8000
  3. 运行：.venv/bin/python tests/run_organize.py
"""

import json
import sys
import httpx

# ╔══════════════════════════════════════════════════════════════╗
# ║                    ⬇️ 修改这里 ⬇️                           ║
# ╠══════════════════════════════════════════════════════════════╣

# 输入：要整理的 Markdown 笔记文件路径
INPUT_NOTE_PATH = "/home/txl/Code/meswarm/notes/vault/mytest.md"

# 输出：整理结果保存到的文件路径（留空则不保存，仅打印）
OUTPUT_RESULT_PATH = "/home/txl/Code/meswarm/notes/vault/mytest_ed.md"

# 步骤开关（None = 使用服务端配置，True/False = 覆盖）
ENABLE_IMAGE_SEMANTIC = None     # 图像语义提取
ENABLE_NOTE_FORMAT = False        # 笔记内容整理
ENABLE_CLASSIFY_AND_SAVE = False  # 分类 + 存储
ENABLE_EMBEDDING = False          # 分块向量嵌入

# ╚══════════════════════════════════════════════════════════════╝

BASE_URL = "http://localhost:8000"


def main():
    # 读取输入笔记
    try:
        with open(INPUT_NOTE_PATH, "r", encoding="utf-8") as f:
            note_content = f.read()
    except FileNotFoundError:
        print(f"❌ 找不到文件: {INPUT_NOTE_PATH}")
        sys.exit(1)

    print("=" * 60)
    print("📝 笔记整理")
    print("=" * 60)
    print(f"   输入文件: {INPUT_NOTE_PATH}")
    print(f"   内容长度: {len(note_content)} 字符")
    print(f"   输出文件: {OUTPUT_RESULT_PATH or '(仅打印)'}")

    # Step 1: 提交整理请求
    print(f"\n🔵 Step 1: 提交整理请求")
    try:
        payload = {"markdown_content": note_content}
        step_overrides = {
            "enable_image_semantic": ENABLE_IMAGE_SEMANTIC,
            "enable_note_format": ENABLE_NOTE_FORMAT,
            "enable_classify_and_save": ENABLE_CLASSIFY_AND_SAVE,
            "enable_embedding": ENABLE_EMBEDDING,
        }
        for key, val in step_overrides.items():
            if val is not None:
                payload[key] = val
        resp = httpx.post(
            f"{BASE_URL}/api/organize",
            json=payload,
            timeout=10,
        )
    except httpx.ConnectError:
        print("❌ 连接失败！请先启动服务：")
        print("   .venv/bin/uvicorn src.main:app --port 8000")
        sys.exit(1)

    task_id = resp.json()["task_id"]
    print(f"   任务 ID: {task_id}")

    # Step 2: SSE 流式获取进度
    print(f"\n🔵 Step 2: 实时进度")
    print("-" * 60)

    result_data = None

    with httpx.stream(
        "GET",
        f"{BASE_URL}/api/organize/{task_id}/stream",
        timeout=300,
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

    print("\n✅ 完成！")


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
            print(f"\n  🎉 整理成功!")
            print(f"     路径: {data.get('note_path', 'N/A')}")
            print(f"     分类: {data.get('category', '')}/{data.get('subcategory', '')}")
            print(f"     标题: {data.get('title', '')}")
            summary = data.get("token_summary", {})
            print(f"     Token: {summary.get('total_tokens', 0)}, 费用: ¥{summary.get('total_cost', 0):.4f}")
        else:
            print(f"\n  ❌ 整理失败: {data.get('error', '')}")
        return data

    elif event_type == "error":
        print(f"  ❌ 错误 [{data.get('step', '')}]: {data.get('error', '')}")

    return None


def _save_result(data: dict):
    """将整理结果保存为 Markdown 文件。"""
    lines = [
        f"# 整理结果",
        "",
        f"- **状态**: {'✅ 成功' if data.get('success') else '❌ 失败'}",
        f"- **笔记路径**: `{data.get('note_path', 'N/A')}`",
        f"- **分类**: {data.get('category', '')}/{data.get('subcategory', '')}",
        f"- **标题**: {data.get('title', '')}",
        f"- **向量数**: {data.get('chunks', 0)}",
        "",
    ]

    summary = data.get("token_summary", {})
    lines += [
        "## Token 消耗",
        "",
        f"- 总 Token: {summary.get('total_tokens', 0)}",
        f"- 总费用: ¥{summary.get('total_cost', 0):.4f}",
        "",
    ]

    breakdown = summary.get("breakdown", [])
    if breakdown:
        lines += ["| 步骤 | 模型 | Token | 费用 |", "| --- | --- | --- | --- |"]
        for item in breakdown:
            lines.append(
                f"| {item.get('step', '')} | {item.get('model', '')} "
                f"| {item.get('tokens', 0)} | ¥{item.get('cost', 0):.4f} |"
            )
        lines.append("")

    content = "\n".join(lines)
    with open(OUTPUT_RESULT_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n  📄 结果已保存: {OUTPUT_RESULT_PATH}")


if __name__ == "__main__":
    main()
