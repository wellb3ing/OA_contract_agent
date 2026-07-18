import os
import re
import tempfile
import requests
from langchain_core.tools import Tool
from contract_agent.config import load_config

# Map Content-Type → file extension
CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


def _guess_extension(response) -> str:
    """Determine file extension from response headers or Content-Type."""
    # 1. Content-Disposition header
    cd = response.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        match = re.search(r'filename\*?=["\']?([^"\';\s]+)', cd, re.IGNORECASE)
        if match:
            _, ext = os.path.splitext(match.group(1))
            if ext.lower() in {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}:
                return ext.lower().replace(".jpeg", ".jpg").replace(".tif", ".tiff")

    # 2. Content-Type header
    ct = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if ct in CONTENT_TYPE_EXT:
        return CONTENT_TYPE_EXT[ct]

    # 3. Default to PDF
    return ".pdf"


def _do_download(url: str, headers: dict | None = None) -> str:
    """Download a file from *url*, validate the response, save to a temp dir.

    Returns the local file path on success, or an error string starting with
    ``下载失败`` on failure.
    """
    try:
        response = requests.get(
            url, headers=headers or {}, timeout=60, allow_redirects=True,
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        return f"下载失败 HTTP {response.status_code}：{e}（可能是链接已过期或凭证无效）"
    except requests.RequestException as e:
        return f"下载失败：{e}"

    # Basic validation — OA may return an HTML login page instead of the file
    ct = response.headers.get("Content-Type", "")
    if "text/html" in ct and len(response.content) < 2000:
        return "下载失败：OA 返回了登录页面而非文件，请检查 Cookie 或 ddcode 是否有效"

    ext = _guess_extension(response)
    tmp_dir = tempfile.mkdtemp()
    file_path = os.path.join(tmp_dir, f"download{ext}")
    with open(file_path, "wb") as f:
        f.write(response.content)

    return file_path


# ---------------------------------------------------------------------------
# Cookie-based download (existing)
# ---------------------------------------------------------------------------

def _download_contract(input_str: str) -> str:
    """Download a contract file from the OA system by file ID.

    Reads ``download.base_url`` and ``download.cookie`` from config,
    constructs the download URL, and saves the file to a temp directory.
    """
    file_id = input_str.strip()

    config = load_config()
    dl = config.get("download", {})
    base_url = dl.get("base_url", "")
    cookie = dl.get("cookie", "")

    if not base_url:
        return "下载失败：config.yaml 中缺少 download.base_url 配置"

    url = f"{base_url}?fileid={file_id}&download=1"
    headers = {"Cookie": cookie} if cookie else {}
    return _do_download(url, headers)


download_contract_tool = Tool(
    name="download_contract",
    func=_download_contract,
    description=(
        "根据文件 ID 从 OA 系统下载合同附件（Cookie 鉴权）。"
        "输入：文件 ID（整数），例如 \"5367222\"。"
        "输出：本地文件路径字符串（含扩展名）。"
    ),
)


# ---------------------------------------------------------------------------
# DDCode-based download (new — no cookie needed)
# ---------------------------------------------------------------------------

def download_with_ddcode(file_id: str | int, ddcode: str) -> str:
    """Download a contract file using a one-time ddcode (no cookie required).

    Constructs the URL as ``{base_url}?fileid={file_id}&download=1&ddcode={ddcode}``
    and downloads the file to a temp directory.

    Args:
        file_id: OA file ID.
        ddcode: One-time download token pushed from the OA form.

    Returns:
        Local file path on success, or an error string starting with ``下载失败``.
    """
    config = load_config()
    dl = config.get("download", {})
    base_url = dl.get("base_url", "")

    if not base_url:
        return "下载失败：config.yaml 中缺少 download.base_url 配置"

    url = f"{base_url}?fileid={file_id}&download=1&ddcode={ddcode}"
    return _do_download(url)  # no cookie header needed


def _download_contract_ddcode_tool(input_str: str) -> str:
    """LangChain Tool wrapper for ``download_with_ddcode``.

    Expects a JSON string: ``{"file_id": 1097568, "ddcode": "45ba65de..."}``
    or a plain file_id integer string (backward-compatible, but ddcode will be empty).
    """
    import json

    try:
        params = json.loads(input_str)
        file_id = params.get("file_id", input_str)
        ddcode = params.get("ddcode", "")
    except (json.JSONDecodeError, TypeError):
        # Plain integer string — no ddcode available
        file_id = input_str.strip()
        ddcode = ""

    if not ddcode:
        return "下载失败：缺少 ddcode，请从 OA 表单推送数据中获取"

    return download_with_ddcode(str(file_id), ddcode)


download_contract_ddcode_tool = Tool(
    name="download_contract_ddcode",
    func=_download_contract_ddcode_tool,
    description=(
        "使用 OA 表单推送的 ddcode（一次性下载凭证）下载合同附件。"
        "无需 Cookie，适用于 OA 表单按钮推送场景。"
        "输入：JSON 字符串 {\"file_id\": 1097568, \"ddcode\": \"xxx\"}。"
        "输出：本地文件路径字符串（含扩展名）。"
    ),
)
