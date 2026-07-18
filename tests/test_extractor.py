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
