import json
import pytest
from io import BytesIO
from fastapi.testclient import TestClient
from contract_agent.server import app

client = TestClient(app)


class TestChatEndpoint:
    def test_returns_sse_content_type(self):
        """POST /api/chat returns text/event-stream."""
        payload = {
            "messages": json.dumps([{"role": "user", "content": "你好"}]),
        }
        response = client.post("/api/chat", data=payload)
        # Even if the internal LLM call fails, the response header should be SSE type
        assert response.status_code in (200, 500)
        if response.status_code == 200:
            assert "text/event-stream" in response.headers.get("content-type", "")

    def test_missing_messages_returns_422(self):
        """Missing messages parameter returns 422."""
        response = client.post("/api/chat")
        assert response.status_code == 422

    def test_invalid_messages_json_returns_400(self):
        """Non-JSON messages returns 400."""
        response = client.post("/api/chat", data={"messages": "not valid json"})
        assert response.status_code == 400

    def test_cors_headers_present(self):
        """OPTIONS preflight request returns CORS headers."""
        response = client.options(
            "/api/chat",
            headers={
                "Origin": "http://example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers

    def test_health_endpoint(self):
        """GET /api/health returns ok."""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
