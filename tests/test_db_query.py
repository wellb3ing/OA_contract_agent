import json
import pytest
from unittest.mock import patch
from contract_agent.tools.db_query import query_contract_url_tool

MOCK_FILES = [
    {"file_id": 5367222, "filename": "02-行李费-112.00元.pdf", "file_size": 12345, "physical_path": "/weaver/files/abc.pdf"},
    {"file_id": 5367223, "filename": "03-餐费-50.00元.pdf", "file_size": 6789, "physical_path": "/weaver/files/def.pdf"},
]


def test_query_returns_file_list():
    with patch("contract_agent.tools.db_query._execute_sql", return_value=MOCK_FILES):
        result = query_contract_url_tool.run(json.dumps({"request_id": 917393}))
    data = json.loads(result)
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["file_id"] == 5367222
    assert data[0]["filename"] == "02-行李费-112.00元.pdf"
    assert data[1]["file_id"] == 5367223


def test_query_empty_result():
    with patch("contract_agent.tools.db_query._execute_sql", return_value=[]):
        result = query_contract_url_tool.run(json.dumps({"request_id": 999999}))
    assert "未找到" in result


def test_query_sql_fallback_empty():
    """The TSQL fallback path returns ``SELECT '[]' AS result``."""
    fallback_rows = [{"result": "[]"}]
    with patch("contract_agent.tools.db_query._execute_sql", return_value=fallback_rows):
        result = query_contract_url_tool.run(json.dumps({"request_id": 917393}))
    assert result == "[]"


def test_query_missing_request_id():
    result = query_contract_url_tool.run(json.dumps({"foo": "bar"}))
    assert "缺少 request_id" in result


def test_query_request_id_not_integer():
    result = query_contract_url_tool.run(json.dumps({"request_id": "abc"}))
    assert "必须是整数" in result


def test_query_invalid_json():
    result = query_contract_url_tool.run("not a json")
    assert "错误" in result
