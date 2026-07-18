"""DeepSeek function calling orchestration for contract check agent.

Converts the 6 existing LangChain Tools into OpenAI-compatible function
definitions, then runs a function-calling loop: the LLM decides which
tool(s) to call, we execute them, feed results back, and repeat until
the LLM responds with a final text answer.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import AsyncGenerator
from contract_agent.tracing import get_traced_openai
from contract_agent.agent import TOOLS
from contract_agent.config import load_config


# ---------------------------------------------------------------------------
# Tool → OpenAI function schema
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_contract_url",
            "description": "根据 requestId 查询 OA 流程表单中的附件文件信息，返回文件 ID、文件名、文件大小等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "integer",
                        "description": "OA 流程的 requestId，整数",
                    },
                },
                "required": ["request_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_contract",
            "description": "根据文件 ID 从 OA 系统下载合同附件（Cookie 鉴权）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "文件 ID，从 query_contract_url 返回结果中获取",
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_contract_ddcode",
            "description": "使用 ddcode（一次性下载凭证）从 OA 下载合同附件，无需 Cookie。适用于 OA 表单推送场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "integer",
                        "description": "文件 ID",
                    },
                    "ddcode": {
                        "type": "string",
                        "description": "OA 表单推送的一次性下载凭证 ddcode",
                    },
                },
                "required": ["file_id", "ddcode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "prepare_images",
            "description": "将合同文件（PDF 或图片）转换为适合 OCR 的图片列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "本地文件路径",
                    },
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ocr_images",
            "description": "对图片列表进行 OCR 文字识别，返回各页识别出的文字。",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_paths": {
                        "type": "string",
                        "description": "JSON 字符串格式的图片路径列表，如 '[\"/tmp/page_1.jpg\"]'",
                    },
                },
                "required": ["image_paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extract_amounts",
            "description": "从 OCR 识别的合同文字中提取所有金额相关字段（如合同总价、税率、税额等），返回 JSON。",
            "parameters": {
                "type": "object",
                "properties": {
                    "ocr_text": {
                        "type": "string",
                        "description": "OCR 识别出的合同全文字符串",
                    },
                },
                "required": ["ocr_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_amounts",
            "description": "按配置的规则校验合同金额字段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "amounts_json": {
                        "type": "string",
                        "description": "JSON 字符串，包含金额字段，如 '{\"合同总价\": 100000}'",
                    },
                },
                "required": ["amounts_json"],
            },
        },
    },
]

# Human-readable labels shown in the UI as tool progress steps
TOOL_LABELS: dict[str, str] = {
    "query_contract_url": "正在查询 OA 流程附件...",
    "download_contract": "正在从 OA 下载合同文件...",
    "download_contract_ddcode": "正在从 OA 下载合同文件（ddcode）...",
    "prepare_images": "正在转换文件为图片...",
    "ocr_images": "正在进行 OCR 文字识别...",
    "extract_amounts": "正在提取金额字段...",
    "validate_amounts": "正在校验金额...",
}

# Map tool name → LangChain Tool object
_TOOL_MAP: dict[str, object] = {t.name: t for t in TOOLS}


# ---------------------------------------------------------------------------
# Tool input builders — each LangChain Tool expects a specific string format
# ---------------------------------------------------------------------------

def build_tool_input(tool_name: str, args: dict) -> str:
    """Convert function-call JSON arguments into the string format each
    existing Tool expects.

    - ``query_contract_url`` / ``ocr_images`` / ``validate_amounts``
      expect a JSON string.
    - ``download_contract`` / ``prepare_images`` / ``extract_amounts``
      expect a plain string value.
    """
    if tool_name in ("query_contract_url",):
        return json.dumps(args, ensure_ascii=False)
    if tool_name == "ocr_images":
        return args.get("image_paths", "[]")
    if tool_name == "validate_amounts":
        return args.get("amounts_json", "{}")
    if tool_name == "download_contract":
        return str(args.get("file_id", ""))
    if tool_name == "download_contract_ddcode":
        return json.dumps(args, ensure_ascii=False)
    if tool_name == "prepare_images":
        return args.get("file_path", "")
    if tool_name == "extract_amounts":
        return args.get("ocr_text", "")
    raise ValueError(f"Unknown tool: {tool_name}")


# ---------------------------------------------------------------------------
# SSE formatting
# ---------------------------------------------------------------------------

def format_sse(event: str, data: dict) -> str:
    """Format a single SSE event as a string.

    Returns a string like ``event: delta\\ndata: {"content":"hi"}\\n\\n``.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个合同审核助手。你可以按需使用以下工具：

1. **query_contract_url** — 根据 OA 流程 requestId 查询附件文件列表（返回 file_id、filename 等）
2. **download_contract** — 根据文件 ID 从 OA 系统下载合同附件（Cookie 鉴权）
3. **download_contract_ddcode** — 使用 ddcode 一次性凭证下载合同附件（无需 Cookie）
4. **prepare_images** — 将合同文件转为图片
5. **ocr_images** — OCR 识别图片中的文字
6. **extract_amounts** — 从识别文字中提取金额字段
7. **validate_amounts** — 按规则校验金额

工作流程：
- 用户提供 requestId → 先用 query_contract_url 查出所有附件
- 如果用户提到了文件名，在返回的文件列表中匹配文件名，找出对应的 file_id
- 用 download_contract 下载匹配的文件（传入 file_id）
- 如果用户提供了 ddcode，用 download_contract_ddcode 下载（传入 file_id + ddcode）
- 然后执行 prepare_images → ocr_images → extract_amounts → validate_amounts
- 如果用户上传了文件，直接对文件执行 prepare_images → ocr_images → extract_amounts → validate_amounts
- 完成所有步骤后，根据校验结果生成一份可读的中文合同金额校验报告

请用中文回复用户。"""  # noqa: E501


# ---------------------------------------------------------------------------
# Main orchestration loop
# ---------------------------------------------------------------------------

async def run_function_calling_loop(
    messages: list[dict],
    file_path: str | None = None,
) -> AsyncGenerator[str, None]:
    """Run the DeepSeek function calling loop and yield SSE events.

    Args:
        messages: Chat history as ``[{"role": "user", "content": "..."}, ...]``.
        file_path: If the user uploaded a file, its local path on the server.
            Injected into the system prompt so the LLM knows to skip DB query.

    Yields:
        SSE-formatted strings for ``delta``, ``tool_start``, ``tool_end``,
        ``report``, ``done``, and ``error`` events.
    """
    config = load_config()
    ds = config["deepseek"]

    client = get_traced_openai()

    # Build system prompt — inject file_path if user uploaded one
    system_content = SYSTEM_PROMPT
    if file_path:
        system_content += (
            f"\n\n用户已上传文件，保存在服务器路径：{file_path}。"
            "请直接对该文件执行 prepare_images → ocr_images → "
            "extract_amounts → validate_amounts 流程，"
            "跳过 query_contract_url 和 download_contract。"
        )

    full_messages: list[dict] = [
        {"role": "system", "content": system_content},
        *messages,
    ]

    max_iterations = 20
    iteration = 0

    # Emit an immediate delta so the frontend knows the stream is alive
    yield format_sse("delta", {"content": "正在处理您的请求..."})
    print(f"[fc] 开始循环, file_path={file_path}, messages_count={len(messages)}", flush=True)

    try:
        # --- Function calling loop ---
        while True:
            iteration += 1
            if iteration > max_iterations:
                print(f"[fc] 达到最大迭代次数 {max_iterations}", flush=True)
                yield format_sse("error", {"error": "达到最大迭代次数限制"})
                yield format_sse("done", {})
                return

            print(f"[fc] 第 {iteration} 次调用 LLM...", flush=True)
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=ds["model"],
                messages=full_messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0,
            )

            msg = response.choices[0].message
            print(f"[fc] LLM 返回: content={msg.content!r}, tool_calls={len(msg.tool_calls or [])}", flush=True)

            # If LLM wants to call tools, execute them and feed back results
            if msg.tool_calls:
                # Record the assistant message with tool_calls
                full_messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                })

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    print(f"[fc] 执行工具: {fn_name}({tc.function.arguments[:200]})", flush=True)

                    # Parse arguments (JSON string → dict)
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        yield format_sse("tool_start", {
                            "tool": fn_name,
                            "label": TOOL_LABELS.get(fn_name, fn_name),
                        })
                        yield format_sse("tool_end", {
                            "tool": fn_name,
                            "status": "error",
                            "error": f"LLM 传入了格式错误的参数：{tc.function.arguments[:200]}",
                        })
                        full_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"参数解析失败：{tc.function.arguments[:200]}",
                        })
                        continue

                    # Emit tool_start
                    yield format_sse("tool_start", {
                        "tool": fn_name,
                        "label": TOOL_LABELS.get(fn_name, fn_name),
                    })

                    # Execute the tool
                    tool = _TOOL_MAP.get(fn_name)
                    if tool is None:
                        tool_result = f"未知工具：{fn_name}"
                        status = "error"
                    else:
                        try:
                            tool_input = build_tool_input(fn_name, fn_args)
                            tool_result = await asyncio.to_thread(tool.func, tool_input)
                            status = "success"
                        except Exception as exc:
                            tool_result = f"工具执行失败：{exc}"
                            status = "error"

                    # Emit tool_end
                    yield format_sse("tool_end", {
                        "tool": fn_name,
                        "status": status,
                        "result": tool_result,
                    })

                    # Feed result back to LLM
                    full_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    })

            else:
                # LLM responded with text — yield it in small chunks to
                # simulate streaming, reusing the already-retrieved content
                # instead of making a redundant second API call.
                content = msg.content or ""

                # If the LLM returned no text but tools were executed,
                # provide a fallback summary so the frontend has something to show
                if not content and any(m["role"] == "tool" for m in full_messages):
                    content = "处理完成。详情请查看上方的工具执行步骤和校验报告。"
                    yield format_sse("delta", {"content": content})

                # Yield in ~30-char chunks for a natural streaming feel
                for i in range(0, len(content), 30):
                    yield format_sse("delta", {"content": content[i:i + 30]})

                # Try to detect a validate_amounts result in the
                # conversation and emit it as a structured report event
                for m in reversed(full_messages):
                    if m["role"] == "tool" and _looks_like_validation(m.get("content", "")):
                        try:
                            report_data = json.loads(m["content"])
                            yield format_sse("report", report_data)
                        except json.JSONDecodeError:
                            pass
                        break

                yield format_sse("done", {})
                return

    except Exception as exc:
        print(f"[fc] 异常: {type(exc).__name__}: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        yield format_sse("error", {"error": str(exc)})
        yield format_sse("done", {})


def _looks_like_validation(text: str) -> bool:
    """Return True if *text* looks like a validate_amounts result JSON."""
    try:
        data = json.loads(text)
        return isinstance(data, dict) and "results" in data
    except (json.JSONDecodeError, TypeError):
        return False
