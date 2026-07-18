"""MCP (Model Context Protocol) OCR provider.

Connects to a remote MCP SSE server, auto-discovers its OCR tool,
and calls it with base64-encoded images.

Uses a minimal SSE+JSON-RPC client built on ``requests`` — no external
MCP SDK dependency, works with Python 3.9+.
"""

import base64
import json
import re
import uuid
from typing import Optional
import requests

from contract_agent.tools.ocr.base import OCRProvider

# ---------------------------------------------------------------------------
# Minimal MCP client (stdlib + requests only)
# ---------------------------------------------------------------------------

class _McpError(Exception):
    """Raised when the MCP server returns an error."""


def _mcp_call(base_url: str, method: str, params: Optional[dict] = None) -> dict:
    """Send a single JSON-RPC request to an MCP Streamable-HTTP endpoint.

    POST requests go to the base URL (without ``/sse`` suffix).
    The SSE path is only used for GET (server→client events).
    """
    # strip /sse suffix — POSTs go to the base path
    post_url = base_url.rstrip("/")
    if post_url.endswith("/sse"):
        post_url = post_url[:-4]

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }
    resp = requests.post(
        post_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()

    # The server may return SSE-wrapped JSON or plain JSON
    body = resp.text.strip()
    if body.startswith("data:"):
        # unwrap one level of SSE
        lines = body.splitlines()
        data_parts = []
        for line in lines:
            if line.startswith("data:"):
                data_parts.append(line[5:].strip())
        body = "\n".join(data_parts)

    data = json.loads(body)
    if "error" in data:
        raise _McpError(data["error"].get("message", str(data["error"])))
    return data.get("result", data)


# ---------------------------------------------------------------------------
# MCPOCR provider
# ---------------------------------------------------------------------------

class MCPOCR(OCRProvider):
    """OCR via an MCP SSE server (e.g. Alibaba Cloud API Gateway MCP)."""

    def __init__(self, url: str):
        self.url = url
        self._tool_name: Optional[str] = None
        self._session_ready = False

    def _ensure_session(self):
        """Send the MCP ``initialize`` handshake once."""
        if self._session_ready:
            return
        _mcp_call(self.url, "initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "contract-agent", "version": "1.0"},
        })
        # notify that we're ready
        try:
            _mcp_call(self.url, "notifications/initialized", {})
        except Exception:
            pass  # some servers don't require this
        self._session_ready = True

    def _discover_tool(self) -> str:
        """Return the name of the OCR tool exposed by the server."""
        result = _mcp_call(self.url, "tools/list", {})
        tools = result.get("tools", [])

        for tool in tools:
            if "ocr" in tool["name"].lower():
                return tool["name"]

        for tool in tools:
            name = tool["name"].lower()
            if any(kw in name for kw in ("识别", "recognize", "general", "text", "通用")):
                return tool["name"]

        if tools:
            return tools[0]["name"]

        raise _McpError(f"MCP 服务器未提供任何工具。URL: {self.url}")

    def recognize(self, image_path: str) -> str:
        """Recognise text in a single image via the remote MCP OCR tool."""
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        # 1. initialise session (once)
        self._ensure_session()

        # 2. discover tool (once)
        if self._tool_name is None:
            self._tool_name = self._discover_tool()

        # 3. call the OCR tool
        result = _mcp_call(self.url, "tools/call", {
            "name": self._tool_name,
            "arguments": {"image": image_b64},
        })

        # 4. extract text from the result
        content = result.get("content", [])
        if content:
            raw = content[0].get("text", "")
            return self._parse_response(raw)
        return ""

    @staticmethod
    def _parse_response(raw: str) -> str:
        """Parse the MCP OCR JSON response and extract recognised text lines."""
        json_end = raw.rfind("}")
        if json_end >= 0:
            raw = raw[: json_end + 1]

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    return raw
            else:
                return raw

        ret = data.get("ret", [])
        if not ret:
            return raw if not data.get("success", True) else ""

        lines = []
        for item in ret:
            word = item.get("word", "")
            if word:
                lines.append(word)
        return "\n".join(lines) if lines else ""
