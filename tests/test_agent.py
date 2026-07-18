import json
from unittest.mock import patch, MagicMock
from contract_agent.agent import run_contract_check

MOCK_FILES_JSON = json.dumps([
    {"file_id": 5367222, "filename": "02-行李费-112.00元.pdf",
     "file_size": 12345, "physical_path": "/weaver/files/abc.pdf"},
])

MOCK_VALIDATION = json.dumps({
    "passed": True,
    "results": [
        {"rule": "花费金额校验，金额小于200为通过", "passed": True, "detail": "通过"}
    ]
})

# Patch paths: agent.py imports the Tool objects and calls tool.func(...).
# Tool.func stores the function reference at creation time, so we must
# patch tool.func on the agent module, not the raw function in tools/.
_BASE = "contract_agent.agent."


def _make_llm_mock(content="校验完成，合同金额校验通过。"):
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = MagicMock(content=content)
    return mock_llm


def test_run_contract_check_with_request_id():
    with patch(_BASE + "query_contract_url_tool.func", return_value=MOCK_FILES_JSON), \
         patch(_BASE + "download_contract_tool.func", return_value="/tmp/5367222.pdf"), \
         patch(_BASE + "prepare_images_tool.func", return_value=json.dumps(["/tmp/page_1.jpg"])), \
         patch(_BASE + "ocr_images_tool.func", return_value="合同总价：100000元"), \
         patch(_BASE + "extract_amounts_tool.func", return_value=json.dumps({"合同总价": 100000.0})), \
         patch(_BASE + "validate_amounts_tool.func", return_value=MOCK_VALIDATION), \
         patch(_BASE + "_create_llm", return_value=_make_llm_mock()):
        result = run_contract_check({"request_id": 917393})
    assert isinstance(result, str)
    assert len(result) > 0
    assert "校验完成" in result


def test_run_contract_check_with_filename_filter():
    """When filename is specified, only matching files should be downloaded."""
    multi_files_json = json.dumps([
        {"file_id": 1, "filename": "02-行李费.pdf", "file_size": 100, "physical_path": "/a.pdf"},
        {"file_id": 2, "filename": "03-餐费.pdf", "file_size": 200, "physical_path": "/b.pdf"},
    ])
    with patch(_BASE + "query_contract_url_tool.func", return_value=multi_files_json), \
         patch(_BASE + "download_contract_tool.func", return_value="/tmp/1.pdf"), \
         patch(_BASE + "prepare_images_tool.func", return_value=json.dumps(["/tmp/page_1.jpg"])), \
         patch(_BASE + "ocr_images_tool.func", return_value="金额：112元"), \
         patch(_BASE + "extract_amounts_tool.func", return_value=json.dumps({"金额": 112.0})), \
         patch(_BASE + "validate_amounts_tool.func", return_value=MOCK_VALIDATION), \
         patch(_BASE + "_create_llm", return_value=_make_llm_mock("校验完成。")):
        result = run_contract_check({"request_id": 917393, "filename": "行李费"})
    assert "校验完成" in result


def test_run_contract_check_filename_not_found():
    """When filename filter matches nothing, should return error."""
    multi_files_json = json.dumps([
        {"file_id": 1, "filename": "03-餐费.pdf", "file_size": 200, "physical_path": "/b.pdf"},
    ])
    with patch(_BASE + "query_contract_url_tool.func", return_value=multi_files_json):
        result = run_contract_check({"request_id": 917393, "filename": "行李费"})
    assert "失败" in result
    assert "行李费" in result


def test_run_contract_check_file_path_mode():
    with patch(_BASE + "prepare_images_tool.func", return_value=json.dumps(["/tmp/page_1.jpg"])), \
         patch(_BASE + "ocr_images_tool.func", return_value="合同总价：100000元"), \
         patch(_BASE + "extract_amounts_tool.func", return_value=json.dumps({"合同总价": 100000.0})), \
         patch(_BASE + "validate_amounts_tool.func", return_value=MOCK_VALIDATION), \
         patch(_BASE + "_create_llm", return_value=_make_llm_mock()), \
         patch("os.path.exists", return_value=True):
        result = run_contract_check({"file_path": "/tmp/test.pdf"})
    assert isinstance(result, str)
    assert "校验完成" in result


def test_run_contract_check_handles_exception():
    with patch(_BASE + "query_contract_url_tool.func", return_value=MOCK_FILES_JSON), \
         patch(_BASE + "download_contract_tool.func", return_value="/tmp/5367222.pdf"), \
         patch(_BASE + "prepare_images_tool.func", return_value=json.dumps(["/tmp/page_1.jpg"])), \
         patch(_BASE + "ocr_images_tool.func", return_value="合同总价：100000元"), \
         patch(_BASE + "extract_amounts_tool.func", return_value=json.dumps({"合同总价": 100000.0})), \
         patch(_BASE + "validate_amounts_tool.func", return_value=MOCK_VALIDATION), \
         patch(_BASE + "_create_llm", side_effect=RuntimeError("network failure")):
        result = run_contract_check({"request_id": 917393})
    assert isinstance(result, str)
    assert "失败" in result
