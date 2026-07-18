# conftest.py — shared pytest fixtures for contract_agent test suite
import pytest


@pytest.fixture(autouse=True)
def set_test_config(tmp_path, monkeypatch):
    """每个测试自动使用临时 config，避免读取真实 config.yaml。"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
database:
  type: mssql
  driver: ODBC Driver 17 for SQL Server
  server: 127.0.0.1
  port: 1433
  user: test
  password: test
  db: test
  sql: "SELECT file_id, filename FROM attachments WHERE requestId = :request_id"
download:
  base_url: "http://172.16.0.18:8081/weaver/weaver.file.FileDownload"
  cookie: "test_cookie=test_value"
ocr:
  provider: baidu
  baidu:
    api_key: test_key
    secret_key: test_secret
  aliyun:
    access_key_id: test_id
    access_key_secret: test_secret
    region: cn-shanghai
  tencent:
    secret_id: test_id
    secret_key: test_secret
    region: ap-guangzhou
validation:
  rules:
    - "含税金额 = 不含税金额 × (1 + 税率)，允许误差 ±1元"
deepseek:
  api_key: test_deepseek_key
  base_url: https://api.deepseek.com
  model: deepseek-chat
""", encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(cfg))
