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
