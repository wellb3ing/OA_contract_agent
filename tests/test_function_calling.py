from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from contract_agent.function_calling import (
    TOOL_DEFINITIONS,
    TOOL_LABELS,
    format_sse,
    build_tool_input,
    run_function_calling_loop,
)


class TestToolDefinitions:
    def test_all_six_tools_defined(self):
        names = {d["function"]["name"] for d in TOOL_DEFINITIONS}
        assert names == {
            "query_contract_url",
            "download_contract",
            "prepare_images",
            "ocr_images",
            "extract_amounts",
            "validate_amounts",
        }

    def test_each_tool_has_description_and_parameters(self):
        for d in TOOL_DEFINITIONS:
            assert "description" in d["function"]
            assert "parameters" in d["function"]
            assert d["function"]["parameters"]["type"] == "object"

    def test_query_contract_url_schema(self):
        schema = next(
            d for d in TOOL_DEFINITIONS
            if d["function"]["name"] == "query_contract_url"
        )
        props = schema["function"]["parameters"]["properties"]
        assert "request_id" in props
        assert props["request_id"]["type"] == "integer"


class TestBuildToolInput:
    def test_query_contract_url_input(self):
        result = build_tool_input("query_contract_url", {"request_id": 917393})
        assert json.loads(result) == {"request_id": 917393}

    def test_download_contract_input(self):
        result = build_tool_input("download_contract", {"file_id": 5367222})
        assert result == "5367222"

    def test_prepare_images_input(self):
        result = build_tool_input("prepare_images", {"file_path": "/tmp/c.pdf"})
        assert result == "/tmp/c.pdf"

    def test_ocr_images_input(self):
        result = build_tool_input("ocr_images", {"image_paths": '["/tmp/p1.jpg"]'})
        assert json.loads(result) == ["/tmp/p1.jpg"]

    def test_extract_amounts_input(self):
        result = build_tool_input("extract_amounts", {"ocr_text": "合同总价 100000 元"})
        assert result == "合同总价 100000 元"

    def test_validate_amounts_input(self):
        result = build_tool_input("validate_amounts", {"amounts_json": '{"总价": 100}'})
        assert result == '{"总价": 100}'


class TestFormatSse:
    def test_format_delta(self):
        result = format_sse("delta", {"content": "你好"})
        assert result == 'event: delta\ndata: {"content": "你好"}\n\n'

    def test_format_tool_start(self):
        result = format_sse("tool_start", {"tool": "ocr_images", "label": "OCR识别"})
        assert "event: tool_start" in result
        assert "OCR识别" in result

    def test_format_done(self):
        result = format_sse("done", {})
        assert result == "event: done\ndata: {}\n\n"


# ---------------------------------------------------------------------------
# Helpers for building mock OpenAI responses
# ---------------------------------------------------------------------------

def _make_mock_stream_chunk(content: str | None) -> MagicMock:
    """Build a single MagicMock that looks like a streaming chunk from
    ``client.chat.completions.create(stream=True)``."""
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = content
    return chunk


def _make_mock_non_stream_response(
    content: str = "",
    tool_calls: list[MagicMock] | None = None,
) -> MagicMock:
    """Build a MagicMock for a non-streaming ``chat.completions.create``
    response with the given *content* and optional *tool_calls*."""
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls or []
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def _make_mock_tool_call(tool_call_id: str, name: str, arguments: str) -> MagicMock:
    """Build a MagicMock that looks like a single tool-call object."""
    tc = MagicMock()
    tc.id = tool_call_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


# ---------------------------------------------------------------------------
# RunFunctionCallingLoop tests — OpenAI client is fully mocked
# ---------------------------------------------------------------------------

class TestRunFunctionCallingLoop:
    @patch("contract_agent.function_calling.OpenAI")
    @pytest.mark.asyncio
    async def test_responds_with_text_when_no_tool_needed(self, MockOpenAI):
        """LLM returns text directly without tool calls — verify SSE stream."""
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client

        # Only one (non-streaming) call needed — text is chunked from
        # msg.content directly (no redundant streaming call).
        mock_client.chat.completions.create.return_value = (
            _make_mock_non_stream_response(content="你好！我是合同审核助手。")
        )

        messages = [{"role": "user", "content": "你好"}]
        events = []
        async for event in run_function_calling_loop(messages, file_path=None):
            events.append(event)

        assert len(events) >= 2
        assert any("event: delta" in e and "你好！" in e for e in events)
        assert any("event: delta" in e and "我是合同审核助手" in e for e in events)
        assert "event: done" in events[-1]

    @patch("contract_agent.function_calling.OpenAI")
    @pytest.mark.asyncio
    async def test_tool_call_sequence_yields_tool_events(self, MockOpenAI):
        """LLM initiates a tool call — verify tool_start/tool_end/delta events."""
        import contract_agent.function_calling as fc

        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client

        # Replace the real tool map with a fake so we don't hit a real DB
        mock_tool = MagicMock()
        mock_tool.func.return_value = json.dumps([
            {"file_id": 5367222, "filename": "test.pdf", "file_size": 100, "physical_path": "/weaver/test.pdf"},
        ])
        original_map = fc._TOOL_MAP.copy()
        fc._TOOL_MAP.clear()
        fc._TOOL_MAP["query_contract_url"] = mock_tool

        try:
            mock_client.chat.completions.create.side_effect = [
                # First call: LLM requests a tool call
                _make_mock_non_stream_response(
                    content="",
                    tool_calls=[
                        _make_mock_tool_call(
                            "call_001", "query_contract_url",
                            '{"request_id": 917393}',
                        ),
                    ],
                ),
                # Second call (after tool result fed back): plain text
                _make_mock_non_stream_response(content="已完成查询。"),
            ]

            messages = [{"role": "user", "content": "查询合同 C001"}]
            events = []
            async for event in run_function_calling_loop(messages, file_path=None):
                events.append(event)

            assert len(events) >= 3
            assert any(
                "event: tool_start" in e and "query_contract_url" in e
                for e in events
            )
            assert any("event: tool_end" in e for e in events)
            assert any(
                "event: delta" in e and "已完成查询" in e
                for e in events
            )
            assert "event: done" in events[-1]
        finally:
            fc._TOOL_MAP.clear()
            fc._TOOL_MAP.update(original_map)
