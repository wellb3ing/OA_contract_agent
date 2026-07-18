import json
import pytest
from unittest.mock import patch, MagicMock
from contract_agent.tools.ocr.base import OCRProvider
from contract_agent.tools.ocr.factory import get_ocr_provider
from contract_agent.tools.ocr_runner import ocr_images_tool


class MockOCRProvider(OCRProvider):
    def recognize(self, image_path: str) -> str:
        return f"OCR result for {image_path}"


def test_ocr_provider_abstract():
    """OCRProvider 不能直接实例化（未实现 recognize）。"""
    class Incomplete(OCRProvider):
        pass
    with pytest.raises(TypeError):
        Incomplete()


def test_get_ocr_provider_baidu():
    config = {"ocr": {"provider": "baidu", "baidu": {"api_key": "k", "secret_key": "s"}}}
    with patch("contract_agent.tools.ocr.factory.BaiduOCR") as MockBaidu:
        MockBaidu.return_value = MagicMock(spec=OCRProvider)
        provider = get_ocr_provider(config)
    MockBaidu.assert_called_once_with(api_key="k", secret_key="s")


def test_get_ocr_provider_mcp():
    config = {"ocr": {"provider": "mcp", "mcp": {"url": "http://example.com/mcp/sse"}}}
    with patch("contract_agent.tools.ocr.factory.MCPOCR") as MockMCP:
        MockMCP.return_value = MagicMock(spec=OCRProvider)
        provider = get_ocr_provider(config)
    MockMCP.assert_called_once_with(url="http://example.com/mcp/sse")


def test_get_ocr_provider_unknown():
    config = {"ocr": {"provider": "unknown"}}
    with pytest.raises(ValueError, match="不支持的 OCR 提供商"):
        get_ocr_provider(config)


def test_ocr_images_tool_runs_all_pages():
    images = ["/tmp/page_1.png", "/tmp/page_2.png"]
    with patch("contract_agent.tools.ocr_runner.get_ocr_provider") as mock_factory:
        mock_provider = MagicMock(spec=OCRProvider)
        mock_provider.recognize.side_effect = ["第一页文字", "第二页文字"]
        mock_factory.return_value = mock_provider
        result = ocr_images_tool.run(json.dumps(images))
    assert "第一页文字" in result
    assert "第二页文字" in result


def test_ocr_images_tool_invalid_input():
    result = ocr_images_tool.run("not json")
    assert "错误" in result or "Error" in result.lower()
