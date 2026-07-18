# 合同校验 Agent 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 LangChain Agent，从数据库查询合同文件 URL，下载 PDF 或图片，通过商业 OCR 识别中英文混合内容，提取并校验金额字段，输出可读报告。

**Architecture:** 使用 LangChain ReAct Agent + DeepSeek LLM，将流程拆分为 6 个独立 Tool（query_contract_url → download_contract → prepare_images → ocr_images → extract_amounts → validate_amounts）。OCR 层通过抽象接口实现可插拔，支持百度/阿里云/腾讯云三家，通过 config.yaml 切换。校验规则以自然语言写在配置文件中，由 LLM 执行。

**Tech Stack:** Python 3.10+, LangChain, langchain-openai（DeepSeek 兼容 OpenAI 接口）, pdf2image, Pillow, SQLAlchemy, PyMySQL, requests, PyYAML, pytest

## Global Constraints

- Python 3.10+
- 所有 Tool 输入输出均为字符串或 JSON 字符串（LangChain Tool 规范）
- OCR Provider 通过工厂函数按 `config.yaml` 中 `ocr.provider` 实例化，不硬编码
- DeepSeek API 兼容 OpenAI 接口，使用 `langchain-openai` 的 `ChatOpenAI` 类接入
- 配置文件路径默认 `contract_agent/config.yaml`，支持环境变量 `CONFIG_PATH` 覆盖
- 金额精度：所有金额比较允许误差 ±1 元
- 临时文件写入系统临时目录（`tempfile.mkdtemp()`），程序退出前清理

---

## 文件结构

```
contract_agent/
├── config.yaml                  # 配置：OCR、数据库、校验规则、DeepSeek
├── main.py                      # 入口
├── agent.py                     # LangChain Agent 定义
├── config.py                    # 配置加载
├── tools/
│   ├── __init__.py
│   ├── db_query.py              # Tool: query_contract_url
│   ├── downloader.py            # Tool: download_contract
│   ├── prepare_images.py        # Tool: prepare_images
│   ├── ocr/
│   │   ├── __init__.py
│   │   ├── base.py              # OCRProvider 抽象类
│   │   ├── baidu.py             # 百度实现
│   │   ├── aliyun.py            # 阿里云实现
│   │   ├── tencent.py           # 腾讯云实现
│   │   └── factory.py           # 工厂函数
│   ├── extractor.py             # Tool: extract_amounts
│   └── validator.py             # Tool: validate_amounts
tests/
├── conftest.py
├── test_config.py
├── test_db_query.py
├── test_downloader.py
├── test_prepare_images.py
├── test_ocr.py
├── test_extractor.py
├── test_validator.py
└── test_agent.py
requirements.txt
```

---

### Task 1: 项目脚手架与配置加载

**Files:**
- Create: `contract_agent/config.yaml`
- Create: `contract_agent/config.py`
- Create: `contract_agent/__init__.py`
- Create: `contract_agent/tools/__init__.py`
- Create: `contract_agent/tools/ocr/__init__.py`
- Create: `requirements.txt`
- Test: `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `load_config(path: str = None) -> dict` — 加载并返回配置字典，`path` 为 None 时读 `CONFIG_PATH` 环境变量或默认路径

- [ ] **Step 1: 创建 requirements.txt**

```
langchain==0.3.25
langchain-openai==0.3.18
langchain-community==0.3.24
pdf2image==1.17.0
Pillow==11.2.1
SQLAlchemy==2.0.41
PyMySQL==1.1.1
requests==2.32.3
PyYAML==6.0.2
pytest==8.3.5
pytest-mock==3.14.0
```

- [ ] **Step 2: 创建 config.yaml**

```yaml
database:
  host: "localhost"
  port: 3306
  user: "readonly_user"
  password: "your_password"
  db: "contracts"
  sql: "SELECT file_url FROM contracts WHERE contract_id = :contract_id"

ocr:
  provider: "baidu"
  baidu:
    api_key: "your_baidu_api_key"
    secret_key: "your_baidu_secret_key"
  aliyun:
    access_key_id: "your_aliyun_access_key_id"
    access_key_secret: "your_aliyun_access_key_secret"
    region: "cn-shanghai"
  tencent:
    secret_id: "your_tencent_secret_id"
    secret_key: "your_tencent_secret_key"
    region: "ap-guangzhou"

validation:
  rules:
    - "含税金额 = 不含税金额 × (1 + 税率)，允许误差 ±1元"
    - "各分项金额之和应等于合同总价，允许误差 ±1元"

deepseek:
  api_key: "your_deepseek_api_key"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
```

- [ ] **Step 3: 写失败测试**

```python
# tests/test_config.py
import os
import pytest
from contract_agent.config import load_config

def test_load_config_returns_dict(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("database:\n  host: testhost\nocr:\n  provider: baidu\n")
    config = load_config(str(cfg_file))
    assert isinstance(config, dict)
    assert config["database"]["host"] == "testhost"
    assert config["ocr"]["provider"] == "baidu"

def test_load_config_via_env_var(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("database:\n  host: envhost\nocr:\n  provider: baidu\n")
    monkeypatch.setenv("CONFIG_PATH", str(cfg_file))
    config = load_config()
    assert config["database"]["host"] == "envhost"

def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")
```

- [ ] **Step 4: 运行测试确认失败**

```bash
cd /Volumes/Samsung\ SSD\ 990\ EVO\ Plus/myproject/OA_agent_demo
pytest tests/test_config.py -v
```

期望：`ModuleNotFoundError: No module named 'contract_agent'`

- [ ] **Step 5: 实现 config.py**

```python
# contract_agent/config.py
import os
import yaml

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

def load_config(path: str = None) -> dict:
    if path is None:
        path = os.environ.get("CONFIG_PATH", DEFAULT_CONFIG_PATH)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

- [ ] **Step 6: 创建空的 __init__ 文件**

```bash
touch contract_agent/__init__.py
touch contract_agent/tools/__init__.py
touch contract_agent/tools/ocr/__init__.py
touch tests/__init__.py
```

- [ ] **Step 7: 运行测试确认通过**

```bash
pytest tests/test_config.py -v
```

期望：3 个测试全部 PASS

- [ ] **Step 8: 安装依赖**

```bash
pip install -r requirements.txt
```

- [ ] **Step 9: Commit**

```bash
git init
git add .
git commit -m "feat: project scaffold and config loader"
```

---

### Task 2: 数据库查询 Tool

**Files:**
- Create: `contract_agent/tools/db_query.py`
- Test: `tests/test_db_query.py`

**Interfaces:**
- Consumes: `load_config() -> dict`（来自 Task 1）
- Produces:
  - `query_contract_url_tool` — LangChain `Tool`，输入 JSON 字符串 `{"contract_id": "xxx"}`，输出合同文件 HTTP URL 字符串

- [ ] **Step 1: 写失败测试**

```python
# tests/test_db_query.py
import json
import pytest
from unittest.mock import patch, MagicMock
from contract_agent.tools.db_query import query_contract_url_tool

def test_query_returns_url():
    mock_result = [{"file_url": "http://192.168.1.10/contracts/001.pdf"}]
    with patch("contract_agent.tools.db_query.execute_query", return_value=mock_result):
        result = query_contract_url_tool.run(json.dumps({"contract_id": "C001"}))
    assert result == "http://192.168.1.10/contracts/001.pdf"

def test_query_no_result():
    with patch("contract_agent.tools.db_query.execute_query", return_value=[]):
        result = query_contract_url_tool.run(json.dumps({"contract_id": "NOTEXIST"}))
    assert "未找到" in result

def test_query_invalid_input():
    result = query_contract_url_tool.run("not a json")
    assert "错误" in result or "Error" in result.lower()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_db_query.py -v
```

期望：`ImportError` 或 `ModuleNotFoundError`

- [ ] **Step 3: 实现 db_query.py**

```python
# contract_agent/tools/db_query.py
import json
from sqlalchemy import create_engine, text
from langchain.tools import Tool
from contract_agent.config import load_config


def execute_query(sql: str, params: dict) -> list:
    """执行 SQL 查询，返回结果列表（每行为 dict）。"""
    config = load_config()
    db = config["database"]
    url = f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['db']}"
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(row._mapping) for row in result]


def _query_contract_url(input_str: str) -> str:
    try:
        params = json.loads(input_str)
    except json.JSONDecodeError:
        return "错误：输入必须是 JSON 格式，例如 {\"contract_id\": \"C001\"}"

    config = load_config()
    sql = config["database"]["sql"]

    try:
        rows = execute_query(sql, params)
    except Exception as e:
        return f"数据库查询失败：{e}"

    if not rows:
        return f"未找到合同，查询参数：{params}"

    # 取第一行第一列作为 URL
    first_row = rows[0]
    url = next(iter(first_row.values()))
    return str(url)


query_contract_url_tool = Tool(
    name="query_contract_url",
    func=_query_contract_url,
    description=(
        "根据查询条件从数据库获取合同文件的下载 URL。"
        "输入：JSON 字符串，包含查询参数，例如 {\"contract_id\": \"C001\"}。"
        "输出：合同文件的 HTTP URL 字符串。"
    ),
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_db_query.py -v
```

期望：3 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add contract_agent/tools/db_query.py tests/test_db_query.py
git commit -m "feat: add query_contract_url tool"
```

---

### Task 3: 合同文件下载 Tool

**Files:**
- Create: `contract_agent/tools/downloader.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Produces:
  - `download_contract_tool` — LangChain `Tool`，输入 HTTP URL 字符串，输出本地文件路径字符串（含扩展名）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_downloader.py
import pytest
from unittest.mock import patch, MagicMock
from contract_agent.tools.downloader import download_contract_tool

def _make_mock_response(content: bytes, content_type: str):
    mock = MagicMock()
    mock.content = content
    mock.headers = {"Content-Type": content_type}
    mock.raise_for_status = MagicMock()
    return mock

def test_download_pdf(tmp_path):
    mock_resp = _make_mock_response(b"%PDF-1.4 fake content", "application/pdf")
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("http://example.com/contract.pdf")
    assert result.endswith(".pdf")
    assert "contract" in result

def test_download_image_by_content_type(tmp_path):
    mock_resp = _make_mock_response(b"fake image bytes", "image/jpeg")
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("http://example.com/contract")
    assert result.endswith(".jpg")

def test_download_image_by_url_extension(tmp_path):
    mock_resp = _make_mock_response(b"fake png bytes", "application/octet-stream")
    with patch("contract_agent.tools.downloader.requests.get", return_value=mock_resp):
        with patch("contract_agent.tools.downloader.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = download_contract_tool.run("http://example.com/scan.png")
    assert result.endswith(".png")

def test_download_failure():
    with patch("contract_agent.tools.downloader.requests.get", side_effect=Exception("连接失败")):
        result = download_contract_tool.run("http://example.com/contract.pdf")
    assert "失败" in result or "Error" in result.lower()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_downloader.py -v
```

期望：`ImportError`

- [ ] **Step 3: 实现 downloader.py**

```python
# contract_agent/tools/downloader.py
import os
import tempfile
import requests
from urllib.parse import urlparse
from langchain.tools import Tool

CONTENT_TYPE_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

URL_EXT_MAP = {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


def _get_extension(url: str, content_type: str) -> str:
    # 优先从 Content-Type 判断
    ct = content_type.split(";")[0].strip().lower()
    if ct in CONTENT_TYPE_EXT:
        return CONTENT_TYPE_EXT[ct]
    # 其次从 URL 后缀判断
    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path)
    if ext.lower() in URL_EXT_MAP:
        return ext.lower().replace(".jpeg", ".jpg").replace(".tif", ".tiff")
    # 默认当 PDF 处理
    return ".pdf"


def _download_contract(url: str) -> str:
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
    except Exception as e:
        return f"下载失败：{e}"

    ext = _get_extension(url, response.headers.get("Content-Type", ""))
    tmp_dir = tempfile.mkdtemp()
    file_path = os.path.join(tmp_dir, f"contract{ext}")
    with open(file_path, "wb") as f:
        f.write(response.content)
    return file_path


download_contract_tool = Tool(
    name="download_contract",
    func=_download_contract,
    description=(
        "下载合同文件到本地临时目录。"
        "输入：合同文件的 HTTP URL。"
        "输出：本地文件路径字符串（含扩展名，如 /tmp/xxx/contract.pdf）。"
    ),
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_downloader.py -v
```

期望：4 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add contract_agent/tools/downloader.py tests/test_downloader.py
git commit -m "feat: add download_contract tool"
```

---

### Task 4: 文件转图片 Tool

**Files:**
- Create: `contract_agent/tools/prepare_images.py`
- Test: `tests/test_prepare_images.py`

**Interfaces:**
- Produces:
  - `prepare_images_tool` — LangChain `Tool`，输入本地文件路径字符串，输出 JSON 字符串表示图片路径列表，例如 `["/tmp/xxx/page_1.png", "/tmp/xxx/page_2.png"]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_prepare_images.py
import json
import os
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
from contract_agent.tools.prepare_images import prepare_images_tool

def test_pdf_converted_to_images(tmp_path):
    fake_images = [MagicMock(spec=Image.Image), MagicMock(spec=Image.Image)]
    with patch("contract_agent.tools.prepare_images.convert_from_path", return_value=fake_images):
        with patch("contract_agent.tools.prepare_images.Image.Image.save") as mock_save:
            fake_images[0].save = MagicMock()
            fake_images[1].save = MagicMock()
            result = prepare_images_tool.run(str(tmp_path / "contract.pdf"))
    paths = json.loads(result)
    assert isinstance(paths, list)
    assert len(paths) == 2
    assert all(p.endswith(".png") for p in paths)

def test_image_file_returned_directly(tmp_path):
    img_path = tmp_path / "scan.jpg"
    img_path.write_bytes(b"fake image")
    result = prepare_images_tool.run(str(img_path))
    paths = json.loads(result)
    assert paths == [str(img_path)]

def test_png_file_returned_directly(tmp_path):
    img_path = tmp_path / "scan.png"
    img_path.write_bytes(b"fake image")
    result = prepare_images_tool.run(str(img_path))
    paths = json.loads(result)
    assert paths == [str(img_path)]

def test_unsupported_format(tmp_path):
    weird_path = tmp_path / "contract.docx"
    weird_path.write_bytes(b"fake docx")
    result = prepare_images_tool.run(str(weird_path))
    assert "不支持" in result or "unsupported" in result.lower()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_prepare_images.py -v
```

期望：`ImportError`

- [ ] **Step 3: 实现 prepare_images.py**

```python
# contract_agent/tools/prepare_images.py
import json
import os
import tempfile
from langchain.tools import Tool
from pdf2image import convert_from_path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}


def _prepare_images(file_path: str) -> str:
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext in IMAGE_EXTENSIONS:
        return json.dumps([file_path])

    if ext in PDF_EXTENSIONS:
        try:
            pages = convert_from_path(file_path, dpi=200)
        except Exception as e:
            return f"PDF 转图片失败：{e}"

        tmp_dir = tempfile.mkdtemp()
        image_paths = []
        for i, page in enumerate(pages, start=1):
            img_path = os.path.join(tmp_dir, f"page_{i}.png")
            page.save(img_path, "PNG")
            image_paths.append(img_path)
        return json.dumps(image_paths)

    return f"不支持的文件格式：{ext}，支持 PDF 和图片（JPG/PNG/BMP/TIFF）"


prepare_images_tool = Tool(
    name="prepare_images",
    func=_prepare_images,
    description=(
        "将合同文件（PDF 或图片）转换为图片列表，供 OCR 识别。"
        "输入：本地文件路径字符串。"
        "输出：JSON 字符串，包含图片路径列表，例如 [\"/tmp/xxx/page_1.png\"]。"
    ),
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_prepare_images.py -v
```

期望：4 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add contract_agent/tools/prepare_images.py tests/test_prepare_images.py
git commit -m "feat: add prepare_images tool (PDF and image support)"
```

---

### Task 5: OCR 抽象层与百度实现

**Files:**
- Create: `contract_agent/tools/ocr/base.py`
- Create: `contract_agent/tools/ocr/factory.py`
- Create: `contract_agent/tools/ocr/baidu.py`
- Create: `contract_agent/tools/ocr/aliyun.py`
- Create: `contract_agent/tools/ocr/tencent.py`
- Create: `contract_agent/tools/ocr_runner.py`  （ocr_images Tool）
- Test: `tests/test_ocr.py`

**Interfaces:**
- Consumes: `load_config() -> dict`（Task 1）
- Produces:
  - `OCRProvider` — 抽象基类，含 `recognize(image_path: str) -> str`
  - `get_ocr_provider(config: dict) -> OCRProvider` — 工厂函数
  - `ocr_images_tool` — LangChain `Tool`，输入 JSON 字符串（图片路径列表），输出合并后的 OCR 文字

- [ ] **Step 1: 写失败测试**

```python
# tests/test_ocr.py
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_ocr.py -v
```

期望：`ImportError`

- [ ] **Step 3: 实现 base.py**

```python
# contract_agent/tools/ocr/base.py
from abc import ABC, abstractmethod

class OCRProvider(ABC):
    @abstractmethod
    def recognize(self, image_path: str) -> str:
        """识别单张图片，返回识别出的原始文字字符串。"""
        pass
```

- [ ] **Step 4: 实现 baidu.py**

```python
# contract_agent/tools/ocr/baidu.py
import base64
import requests
from contract_agent.tools.ocr.base import OCRProvider


class BaiduOCR(OCRProvider):
    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self._token = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            self.TOKEN_URL,
            params={"grant_type": "client_credentials", "client_id": self.api_key, "client_secret": self.secret_key},
            timeout=10,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def recognize(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        token = self._get_token()
        resp = requests.post(
            self.OCR_URL,
            params={"access_token": token},
            data={"image": image_b64},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "words_result" not in data:
            raise ValueError(f"百度 OCR 返回错误：{data}")
        return "\n".join(item["words"] for item in data["words_result"])
```

- [ ] **Step 5: 实现 aliyun.py**

```python
# contract_agent/tools/ocr/aliyun.py
import base64
import json
import hmac
import hashlib
import datetime
import requests
from contract_agent.tools.ocr.base import OCRProvider


class AliyunOCR(OCRProvider):
    """阿里云通用文字识别（印刷体）。"""

    def __init__(self, access_key_id: str, access_key_secret: str, region: str = "cn-shanghai"):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.endpoint = f"https://ocr-api.{region}.aliyuncs.com"

    def recognize(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {"image": image_b64, "outputTable": False}
        # 使用阿里云 OCR 通用印刷体识别接口
        url = f"{self.endpoint}/ocr/request"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"APPCODE {self.access_key_id}",  # 简化版，实际按阿里云文档签名
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "content" not in data:
            raise ValueError(f"阿里云 OCR 返回错误：{data}")
        return data["content"]
```

- [ ] **Step 6: 实现 tencent.py**

```python
# contract_agent/tools/ocr/tencent.py
import base64
import requests
from contract_agent.tools.ocr.base import OCRProvider


class TencentOCR(OCRProvider):
    """腾讯云通用印刷体识别。"""

    def __init__(self, secret_id: str, secret_key: str, region: str = "ap-guangzhou"):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.endpoint = "https://ocr.tencentcloudapi.com"

    def recognize(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        # 腾讯云 OCR 通用印刷体识别（GeneralBasicOCR）
        payload = {"ImageBase64": image_b64}
        headers = {
            "Content-Type": "application/json",
            "X-TC-Action": "GeneralBasicOCR",
            "X-TC-Version": "2018-11-19",
            "X-TC-Region": self.region,
            # 实际使用需按腾讯云文档进行签名，此处简化
            "Authorization": f"TC3-HMAC-SHA256 SecretId={self.secret_id}",
        }
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("Response", {})
        if "TextDetections" not in result:
            raise ValueError(f"腾讯云 OCR 返回错误：{data}")
        return "\n".join(item["DetectedText"] for item in result["TextDetections"])
```

- [ ] **Step 7: 实现 factory.py**

```python
# contract_agent/tools/ocr/factory.py
from contract_agent.tools.ocr.base import OCRProvider
from contract_agent.tools.ocr.baidu import BaiduOCR
from contract_agent.tools.ocr.aliyun import AliyunOCR
from contract_agent.tools.ocr.tencent import TencentOCR


def get_ocr_provider(config: dict) -> OCRProvider:
    provider_name = config["ocr"]["provider"].lower()
    if provider_name == "baidu":
        cfg = config["ocr"]["baidu"]
        return BaiduOCR(api_key=cfg["api_key"], secret_key=cfg["secret_key"])
    elif provider_name == "aliyun":
        cfg = config["ocr"]["aliyun"]
        return AliyunOCR(
            access_key_id=cfg["access_key_id"],
            access_key_secret=cfg["access_key_secret"],
            region=cfg.get("region", "cn-shanghai"),
        )
    elif provider_name == "tencent":
        cfg = config["ocr"]["tencent"]
        return TencentOCR(
            secret_id=cfg["secret_id"],
            secret_key=cfg["secret_key"],
            region=cfg.get("region", "ap-guangzhou"),
        )
    else:
        raise ValueError(f"不支持的 OCR 提供商：{provider_name}，可选：baidu / aliyun / tencent")
```

- [ ] **Step 8: 实现 ocr_runner.py**

```python
# contract_agent/tools/ocr_runner.py
import json
from langchain.tools import Tool
from contract_agent.config import load_config
from contract_agent.tools.ocr.factory import get_ocr_provider


def _ocr_images(input_str: str) -> str:
    try:
        image_paths = json.loads(input_str)
    except json.JSONDecodeError:
        return "错误：输入必须是 JSON 格式的图片路径列表，例如 [\"/tmp/page_1.png\"]"

    config = load_config()
    try:
        provider = get_ocr_provider(config)
    except ValueError as e:
        return f"OCR 初始化失败：{e}"

    results = []
    for i, path in enumerate(image_paths, start=1):
        try:
            text = provider.recognize(path)
            results.append(f"=== 第 {i} 页 ===\n{text}")
        except Exception as e:
            results.append(f"=== 第 {i} 页（识别失败：{e}）===")

    return "\n\n".join(results)


ocr_images_tool = Tool(
    name="ocr_images",
    func=_ocr_images,
    description=(
        "对图片列表进行 OCR 文字识别。"
        "输入：JSON 字符串，包含图片路径列表，例如 [\"/tmp/page_1.png\", \"/tmp/page_2.png\"]。"
        "输出：各页识别出的文字，按页合并为一个字符串。"
    ),
)
```

- [ ] **Step 9: 运行测试确认通过**

```bash
pytest tests/test_ocr.py -v
```

期望：5 个测试全部 PASS

- [ ] **Step 10: Commit**

```bash
git add contract_agent/tools/ocr/ contract_agent/tools/ocr_runner.py tests/test_ocr.py
git commit -m "feat: add OCR abstraction layer with Baidu/Aliyun/Tencent implementations"
```

---

### Task 6: 金额提取 Tool

**Files:**
- Create: `contract_agent/tools/extractor.py`
- Test: `tests/test_extractor.py`

**Interfaces:**
- Consumes: `load_config() -> dict`（Task 1，获取 DeepSeek 配置）
- Produces:
  - `extract_amounts_tool` — LangChain `Tool`，输入 OCR 文字字符串，输出 JSON 字符串表示金额字段字典，例如 `{"合同总价": 100000.0, "税率": "13%", ...}`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_extractor.py
import json
import pytest
from unittest.mock import patch, MagicMock
from contract_agent.tools.extractor import extract_amounts_tool

SAMPLE_OCR_TEXT = """
合同编号：HT-2024-001
甲方：某某公司
乙方：另一公司

合同金额：
不含税金额：88,495.58元
增值税率：13%
税额：11,504.42元
含税合同总价：100,000.00元
"""

def test_extract_amounts_returns_json():
    mock_llm_output = json.dumps({
        "不含税金额": 88495.58,
        "税率": "13%",
        "税额": 11504.42,
        "含税合同总价": 100000.0
    })
    with patch("contract_agent.tools.extractor._call_llm", return_value=mock_llm_output):
        result = extract_amounts_tool.run(SAMPLE_OCR_TEXT)
    data = json.loads(result)
    assert data["含税合同总价"] == 100000.0
    assert data["税率"] == "13%"

def test_extract_amounts_empty_text():
    with patch("contract_agent.tools.extractor._call_llm", return_value="{}"):
        result = extract_amounts_tool.run("此合同无金额信息")
    data = json.loads(result)
    assert data == {}

def test_extract_amounts_llm_failure():
    with patch("contract_agent.tools.extractor._call_llm", side_effect=Exception("API 超时")):
        result = extract_amounts_tool.run(SAMPLE_OCR_TEXT)
    assert "失败" in result or "Error" in result.lower()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_extractor.py -v
```

期望：`ImportError`

- [ ] **Step 3: 实现 extractor.py**

```python
# contract_agent/tools/extractor.py
import json
from langchain.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from contract_agent.config import load_config

EXTRACT_SYSTEM_PROMPT = """你是一个合同金额提取专家。
从用户提供的合同 OCR 文字中，提取所有金额相关字段。
输出严格的 JSON 格式，key 为字段名（如"合同总价"、"不含税金额"、"税率"、"税额"等），
value 为数值（金额字段用 float，税率用字符串如"13%"）。
如果找不到任何金额信息，返回空对象 {}。
不要输出任何 JSON 以外的内容，不要加 markdown 代码块。"""


def _call_llm(text: str) -> str:
    config = load_config()
    ds = config["deepseek"]
    llm = ChatOpenAI(
        model=ds["model"],
        openai_api_key=ds["api_key"],
        openai_api_base=ds["base_url"],
        temperature=0,
    )
    messages = [
        SystemMessage(content=EXTRACT_SYSTEM_PROMPT),
        HumanMessage(content=f"请从以下合同文字中提取金额字段：\n\n{text}"),
    ]
    response = llm.invoke(messages)
    return response.content.strip()


def _extract_amounts(ocr_text: str) -> str:
    try:
        raw = _call_llm(ocr_text)
        # 验证是合法 JSON
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        # LLM 误加了 markdown，尝试提取 JSON 块
        import re
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return match.group(0)
        return json.dumps({})
    except Exception as e:
        return f"金额提取失败：{e}"


extract_amounts_tool = Tool(
    name="extract_amounts",
    func=_extract_amounts,
    description=(
        "从 OCR 识别的合同文字中提取所有金额相关字段。"
        "输入：OCR 识别出的合同全文字符串。"
        "输出：JSON 字符串，key 为字段名，value 为金额数值或税率字符串。"
        "例如：{\"合同总价\": 100000.0, \"税率\": \"13%\", \"税额\": 11504.42}"
    ),
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_extractor.py -v
```

期望：3 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add contract_agent/tools/extractor.py tests/test_extractor.py
git commit -m "feat: add extract_amounts tool"
```

---

### Task 7: 金额校验 Tool

**Files:**
- Create: `contract_agent/tools/validator.py`
- Test: `tests/test_validator.py`

**Interfaces:**
- Consumes: `load_config() -> dict`（Task 1）
- Produces:
  - `validate_amounts_tool` — LangChain `Tool`，输入 JSON 字符串（金额字段），输出 JSON 字符串（校验结果）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_validator.py
import json
import pytest
from unittest.mock import patch
from contract_agent.tools.validator import validate_amounts_tool

AMOUNTS = json.dumps({
    "不含税金额": 88495.58,
    "税率": "13%",
    "税额": 11504.42,
    "含税合同总价": 100000.0
})

MOCK_VALIDATION_RESULT = json.dumps({
    "passed": True,
    "results": [
        {
            "rule": "含税金额 = 不含税金额 × (1 + 税率)，允许误差 ±1元",
            "passed": True,
            "detail": "88495.58 × 1.13 = 100000.01，误差 0.01 元，通过"
        }
    ]
})

def test_validate_returns_json():
    with patch("contract_agent.tools.validator._call_llm", return_value=MOCK_VALIDATION_RESULT):
        result = validate_amounts_tool.run(AMOUNTS)
    data = json.loads(result)
    assert "passed" in data
    assert "results" in data
    assert isinstance(data["results"], list)

def test_validate_invalid_input():
    result = validate_amounts_tool.run("not json")
    assert "错误" in result or "Error" in result.lower()

def test_validate_llm_failure():
    with patch("contract_agent.tools.validator._call_llm", side_effect=Exception("超时")):
        result = validate_amounts_tool.run(AMOUNTS)
    assert "失败" in result or "Error" in result.lower()
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_validator.py -v
```

期望：`ImportError`

- [ ] **Step 3: 实现 validator.py**

```python
# contract_agent/tools/validator.py
import json
import re
from langchain.tools import Tool
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from contract_agent.config import load_config

VALIDATE_SYSTEM_PROMPT = """你是一个合同金额校验专家。
用户会提供：1) 从合同中提取的金额字段（JSON）；2) 校验规则列表。
请对每条规则进行校验，输出严格的 JSON 格式：
{
  "passed": true/false,  // 所有规则是否全部通过
  "results": [
    {
      "rule": "规则描述",
      "passed": true/false,
      "detail": "详细说明，包括计算过程和数值"
    }
  ]
}
注意：
- 如果缺少校验所需字段，passed 设为 null，detail 说明原因
- 金额误差在 ±1 元以内视为通过
- 不要输出任何 JSON 以外的内容，不要加 markdown 代码块"""


def _call_llm(amounts_json: str, rules: list) -> str:
    config = load_config()
    ds = config["deepseek"]
    llm = ChatOpenAI(
        model=ds["model"],
        openai_api_key=ds["api_key"],
        openai_api_base=ds["base_url"],
        temperature=0,
    )
    rules_text = "\n".join(f"- {r}" for r in rules)
    prompt = f"金额字段：\n{amounts_json}\n\n校验规则：\n{rules_text}"
    messages = [
        SystemMessage(content=VALIDATE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]
    response = llm.invoke(messages)
    return response.content.strip()


def _validate_amounts(amounts_json_str: str) -> str:
    try:
        json.loads(amounts_json_str)
    except json.JSONDecodeError:
        return "错误：输入必须是 JSON 格式的金额字段"

    config = load_config()
    rules = config["validation"]["rules"]

    try:
        raw = _call_llm(amounts_json_str, rules)
    except Exception as e:
        return f"校验失败：{e}"

    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return match.group(0)
        return json.dumps({"passed": False, "results": [], "error": f"LLM 输出格式错误：{raw}"})


validate_amounts_tool = Tool(
    name="validate_amounts",
    func=_validate_amounts,
    description=(
        "按配置的规则校验合同金额字段。"
        "输入：JSON 字符串，包含金额字段，例如 {\"合同总价\": 100000.0, \"税率\": \"13%\"}。"
        "输出：JSON 字符串，包含校验结果，格式为 {\"passed\": true, \"results\": [{\"rule\": ..., \"passed\": ..., \"detail\": ...}]}。"
    ),
)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_validator.py -v
```

期望：3 个测试全部 PASS

- [ ] **Step 5: Commit**

```bash
git add contract_agent/tools/validator.py tests/test_validator.py
git commit -m "feat: add validate_amounts tool"
```

---

### Task 8: LangChain Agent 组装与入口

**Files:**
- Create: `contract_agent/agent.py`
- Create: `contract_agent/main.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: 全部 6 个 Tool（Tasks 2-7）
- Produces:
  - `run_contract_check(query_params: dict) -> str` — 完整运行 Agent，返回可读报告字符串

- [ ] **Step 1: 写失败测试**

```python
# tests/test_agent.py
import json
import pytest
from unittest.mock import patch, MagicMock
from contract_agent.agent import run_contract_check

MOCK_VALIDATION = json.dumps({
    "passed": True,
    "results": [
        {"rule": "含税金额 = 不含税金额 × (1 + 税率)", "passed": True, "detail": "通过"}
    ]
})

def test_run_contract_check_returns_string():
    with patch("contract_agent.tools.db_query._query_contract_url", return_value="http://example.com/c.pdf"), \
         patch("contract_agent.tools.downloader._download_contract", return_value="/tmp/c.pdf"), \
         patch("contract_agent.tools.prepare_images._prepare_images", return_value=json.dumps(["/tmp/page_1.png"])), \
         patch("contract_agent.tools.ocr_runner._ocr_images", return_value="合同总价：100000元"), \
         patch("contract_agent.tools.extractor._extract_amounts", return_value=json.dumps({"合同总价": 100000.0})), \
         patch("contract_agent.tools.validator._validate_amounts", return_value=MOCK_VALIDATION), \
         patch("contract_agent.agent._create_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="校验完成，合同金额校验通过。")
        mock_llm_factory.return_value = mock_llm
        result = run_contract_check({"contract_id": "C001"})
    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_agent.py -v
```

期望：`ImportError`

- [ ] **Step 3: 实现 agent.py**

```python
# contract_agent/agent.py
import json
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from contract_agent.config import load_config
from contract_agent.tools.db_query import query_contract_url_tool
from contract_agent.tools.downloader import download_contract_tool
from contract_agent.tools.prepare_images import prepare_images_tool
from contract_agent.tools.ocr_runner import ocr_images_tool
from contract_agent.tools.extractor import extract_amounts_tool
from contract_agent.tools.validator import validate_amounts_tool

AGENT_PROMPT = PromptTemplate.from_template("""你是一个合同审核助手，负责下载合同、识别内容并校验金额。

请按照以下步骤处理用户的请求：
1. 使用 query_contract_url 查询合同文件 URL
2. 使用 download_contract 下载合同文件
3. 使用 prepare_images 将文件转换为图片
4. 使用 ocr_images 识别图片中的文字
5. 使用 extract_amounts 提取金额字段
6. 使用 validate_amounts 校验金额
7. 根据校验结果生成可读报告

可用工具：
{tools}

工具名称：{tool_names}

对话历史：
{agent_scratchpad}

用户请求：{input}

请按步骤执行，最终输出完整的合同校验报告。""")

TOOLS = [
    query_contract_url_tool,
    download_contract_tool,
    prepare_images_tool,
    ocr_images_tool,
    extract_amounts_tool,
    validate_amounts_tool,
]


def _create_llm():
    config = load_config()
    ds = config["deepseek"]
    return ChatOpenAI(
        model=ds["model"],
        openai_api_key=ds["api_key"],
        openai_api_base=ds["base_url"],
        temperature=0,
    )


def run_contract_check(query_params: dict) -> str:
    llm = _create_llm()
    agent = create_react_agent(llm, TOOLS, AGENT_PROMPT)
    executor = AgentExecutor(
        agent=agent,
        tools=TOOLS,
        verbose=True,
        max_iterations=15,
        handle_parsing_errors=True,
    )
    input_str = f"请处理合同查询请求，查询参数：{json.dumps(query_params, ensure_ascii=False)}"
    result = executor.invoke({"input": input_str})
    return result.get("output", "Agent 未返回结果")
```

- [ ] **Step 4: 实现 main.py**

```python
# contract_agent/main.py
import argparse
import json
import sys
from contract_agent.agent import run_contract_check


def main():
    parser = argparse.ArgumentParser(description="合同校验 Agent")
    parser.add_argument(
        "--params",
        type=str,
        required=True,
        help='查询参数 JSON 字符串，例如 \'{"contract_id": "C001"}\'',
    )
    args = parser.parse_args()

    try:
        query_params = json.loads(args.params)
    except json.JSONDecodeError:
        print("错误：--params 必须是合法的 JSON 字符串", file=sys.stderr)
        sys.exit(1)

    print("正在处理合同，请稍候...\n")
    report = run_contract_check(query_params)
    print(report)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行测试确认通过**

```bash
pytest tests/test_agent.py -v
```

期望：1 个测试 PASS

- [ ] **Step 6: 运行全量测试**

```bash
pytest tests/ -v
```

期望：所有测试 PASS，无失败

- [ ] **Step 7: Commit**

```bash
git add contract_agent/agent.py contract_agent/main.py tests/test_agent.py
git commit -m "feat: assemble LangChain agent and main entry point"
```

---

### Task 9: 端到端冒烟测试与文档

**Files:**
- Create: `tests/conftest.py`（补充公共 fixture）
- Create: `README.md`

- [ ] **Step 1: 补充 conftest.py**

```python
# tests/conftest.py
import pytest
import os

@pytest.fixture(autouse=True)
def set_test_config(tmp_path, monkeypatch):
    """每个测试自动使用临时 config，避免读取真实 config.yaml。"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
database:
  host: localhost
  port: 3306
  user: test
  password: test
  db: test
  sql: "SELECT file_url FROM contracts WHERE contract_id = :contract_id"
ocr:
  provider: baidu
  baidu:
    api_key: test_key
    secret_key: test_secret
validation:
  rules:
    - "含税金额 = 不含税金额 × (1 + 税率)，允许误差 ±1元"
deepseek:
  api_key: test_deepseek_key
  base_url: https://api.deepseek.com
  model: deepseek-chat
""")
    monkeypatch.setenv("CONFIG_PATH", str(cfg))
```

- [ ] **Step 2: 创建 README.md**

```markdown
# 合同校验 Agent

基于 LangChain + DeepSeek 的合同金额校验工具，支持 PDF 和图片格式的扫描件合同。

## 安装

```bash
pip install -r requirements.txt
# PDF 转图片需要 poppler（macOS: brew install poppler，Ubuntu: apt install poppler-utils）
```

## 配置

复制并编辑 `contract_agent/config.yaml`：
- `database`：填写数据库连接信息和 SQL 语句
- `ocr.provider`：选择 `baidu` / `aliyun` / `tencent` 并填写对应 API key
- `deepseek`：填写 DeepSeek API key
- `validation.rules`：用自然语言描述校验规则

## 使用

```bash
python -m contract_agent.main --params '{"contract_id": "C001"}'
```

## 运行测试

```bash
pytest tests/ -v
```
```

- [ ] **Step 3: 运行全量测试最终确认**

```bash
pytest tests/ -v --tb=short
```

期望：所有测试 PASS

- [ ] **Step 4: 最终 Commit**

```bash
git add tests/conftest.py README.md
git commit -m "feat: add conftest fixtures and README"
```

---

## 自查：Spec 覆盖确认

| Spec 需求 | 对应 Task |
|---|---|
| 从数据库 SQL 查询 URL | Task 2 |
| 下载内网 HTTP URL 合同文件 | Task 3 |
| 支持 PDF 格式 | Task 4 |
| 支持图片格式（JPG/PNG/BMP/TIFF） | Task 4 |
| 商业 OCR API 识别中英文 | Task 5 |
| OCR 可插拔（百度/阿里云/腾讯云） | Task 5 |
| 提取金额字段 | Task 6 |
| 按规则校验金额 | Task 7 |
| 校验规则配置化 | Task 1（config.yaml）|
| LangChain Agent 编排 | Task 8 |
| DeepSeek LLM | Tasks 6、7、8 |
| 输出可读报告 | Task 8 |
