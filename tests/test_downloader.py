import pytest
from unittest.mock import patch, MagicMock, ANY
import requests
from contract_agent.tools.downloader import download_contract_tool


def _make_mock_response(content: bytes, content_type: str, headers: dict = None):
    mock = MagicMock()
    mock.content = content
    h = {"Content-Type": content_type}
    if headers:
        h.update(headers)
    mock.headers = h
    mock.raise_for_status = MagicMock()
    return mock


def test_download_with_file_id_constructs_url(tmp_path):
    """download_contract should construct URL from config base_url + file_id."""
    mock_resp = _make_mock_response(b"%PDF-1.4 fake content", "application/pdf")
    with patch("contract_agent.tools.downloader.requests.get") as mock_get:
        mock_get.return_value = mock_resp
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("5367222")
    # Verify the constructed URL
    called_url = mock_get.call_args[0][0]
    assert "fileid=5367222" in called_url
    assert "download=1" in called_url
    assert called_url.startswith("http://172.16.0.18:8081")
    # Verify cookie header was passed
    headers = mock_get.call_args[1].get("headers", {})
    assert "Cookie" in headers
    assert result.endswith(".pdf")


def test_download_pdf_by_content_type(tmp_path):
    mock_resp = _make_mock_response(b"%PDF-1.4 fake content", "application/pdf")
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("12345")
    assert result.endswith(".pdf")


def test_download_image_by_content_type(tmp_path):
    mock_resp = _make_mock_response(b"fake image bytes", "image/jpeg")
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("12345")
    assert result.endswith(".jpg")


def test_download_by_content_disposition(tmp_path):
    mock_resp = _make_mock_response(
        b"fake png bytes", "application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="scan.png"'},
    )
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("12345")
    assert result.endswith(".png")


def test_download_http_error():
    with patch("contract_agent.tools.downloader.requests.get",
               side_effect=requests.ConnectionError("连接失败")):
        result = download_contract_tool.run("12345")
    assert "失败" in result


def test_download_oa_login_page_detected(tmp_path):
    """OA may return a login HTML page instead of the file → should surface error."""
    mock_resp = _make_mock_response(b"<html>login</html>", "text/html")
    mock_resp.status_code = 200
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        result = download_contract_tool.run("12345")
    assert "登录" in result or "失败" in result
