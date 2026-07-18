"""
Contract check agent: orchestrates the pipeline and produces a readable report.

The pipeline runs sequentially:
  1. query_contract_url  — query OA attachments by requestId → JSON array of file info
  2. download_contract   — download each file by file_id (with cookie auth)
  3. prepare_images      — convert files to page images
  4. ocr_images          — OCR the images and return raw text
  5. extract_amounts     — extract monetary fields from the OCR text
  6. validate_amounts    — validate the extracted amounts against rules

After the pipeline, the LLM generates a human-readable summary report.

Supports two input modes:
  - {"request_id": 917393}                — OA workflow lookup
  - {"request_id": 917393, "filename": "行李费"}  — OA lookup + filename filter
  - {"file_path": "/path/to/contract.pdf"} — local file (skips OA query+download)
"""

import json
import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from contract_agent.config import load_config
from contract_agent.tracing import (
    init_tracing,
    trace_step,
    log_metadata,
    log_feedback,
    trace_function,
)
from contract_agent.tools.db_query import query_contract_url_tool
from contract_agent.tools.downloader import download_contract_tool, download_contract_ddcode_tool
from contract_agent.tools.prepare_images import prepare_images_tool
from contract_agent.tools.ocr_runner import ocr_images_tool
from contract_agent.tools.extractor import extract_amounts_tool
from contract_agent.tools.validator import validate_amounts_tool

init_tracing()  # enable LangSmith tracing for CLI / standalone usage

TOOLS = [
    query_contract_url_tool,
    download_contract_tool,
    download_contract_ddcode_tool,
    prepare_images_tool,
    ocr_images_tool,
    extract_amounts_tool,
    validate_amounts_tool,
]

SYSTEM_PROMPT = (
    "你是一个合同审核助手，负责汇总合同金额校验流程的结果，生成简洁、可读的中文报告。"
    "报告应包含：合同文件来源、OCR 识别到的关键信息、提取的金额字段、"
    "与 OA 表单金额的一致性比对结论（如有），以及最终校验结论（通过/不通过及原因）。"
)

# Error prefixes returned by tools when something goes wrong
_ERROR_PREFIXES = (
    "错误", "PDF 转图片失败", "图片预处理失败", "下载失败",
    "数据库查询失败", "OCR 初始化失败", "金额提取失败",
    "校验失败", "不支持的文件格式", "未找到",
)


def _tool_failed(result: str) -> bool:
    """Return True if *result* looks like a tool error rather than valid data."""
    return any(result.startswith(p) for p in _ERROR_PREFIXES)


# Fields in extracted amounts JSON that are considered "contract total"
_TOTAL_KEYWORDS = ("总价", "总金额", "合同价", "合同金额", "合计", "总计", "含税总价", "不含税总价")


def _compare_amounts(oa_amount: str, amounts_json: str) -> dict:
    """Compare the OA form amount with OCR-extracted contract total fields.

    Returns a dict with ``match`` (bool or None) and ``comparisons`` list.
    ``match`` is True when ALL total-like fields agree with *oa_amount*.
    """
    try:
        amounts = json.loads(amounts_json)
    except (json.JSONDecodeError, TypeError):
        return {"match": None, "oa_amount": oa_amount, "error": "无法解析提取的金额字段"}

    # Find every field whose name contains a total-like keyword
    total_keys = [k for k in amounts if any(kw in k for kw in _TOTAL_KEYWORDS)]

    if not total_keys:
        return {
            "match": None,
            "oa_amount": oa_amount,
            "error": f"提取的金额中未找到总价相关字段，可用字段：{list(amounts.keys())}",
        }

    try:
        oa_val = float(str(oa_amount).replace(",", "").replace("，", "").strip())
    except (ValueError, TypeError):
        return {"match": None, "oa_amount": oa_amount, "error": f"OA 表单金额格式无效：{oa_amount}"}

    comparisons = []
    for key in total_keys:
        try:
            extracted_val = float(amounts[key])
        except (ValueError, TypeError):
            comparisons.append({
                "field": key,
                "oa_amount": oa_val,
                "contract_amount": amounts[key],
                "match": None,
                "detail": f"合同字段「{key}」的值无法转为数字：{amounts[key]}",
            })
            continue

        diff = round(abs(oa_val - extracted_val), 2)
        match = diff < 0.02  # allow 1-cent floating tolerance
        comparisons.append({
            "field": key,
            "oa_amount": oa_val,
            "contract_amount": extracted_val,
            "diff": diff,
            "match": match,
            "detail": (
                f"OA 表单金额 {oa_val} vs 合同「{key}」{extracted_val}，"
                f"差额 {diff}，{'一致 ✅' if match else '不一致 ❌'}"
            ),
        })

    all_match = all(c.get("match") is not False for c in comparisons) if comparisons else None
    return {
        "match": all_match if comparisons else None,
        "oa_amount": oa_val,
        "comparisons": comparisons,
    }


def _extract_total_value(amounts_json: str) -> float | None:
    """Extract the contract total amount from OCR-extracted amounts JSON.

    Looks for fields whose name contains a total-like keyword; falls back
    to the largest numeric value in the dict.
    """
    try:
        amounts = json.loads(amounts_json)
    except (json.JSONDecodeError, TypeError):
        return None

    for key in amounts:
        if any(kw in key for kw in _TOTAL_KEYWORDS):
            try:
                return float(amounts[key])
            except (ValueError, TypeError):
                continue

    # Fallback: return the largest numeric value
    best = None
    for v in amounts.values():
        try:
            val = float(v)
            if best is None or val > best:
                best = val
        except (ValueError, TypeError):
            continue
    return best


def _run_core_checks(
    oa_amount: str | None,
    amounts_json: str,
    ocr_text: str,
    amount_comparison: dict | None,
) -> dict:
    """Run code-based validation checks that are too important to leave to LLM.

    Returns a structured dict with ``passed`` (bool), ``checks`` (list of
    per-check results), and a human-readable ``summary``.
    """
    config = load_config()
    vc = config.get("validation", {})
    threshold = vc.get("amount_threshold", 100)
    required_sig = vc.get("required_signature", "")

    checks: list[dict] = []

    # ── Check 1: OA amount vs contract amount ──────────────────────────
    if amount_comparison is not None and oa_amount:
        am = amount_comparison.get("match")
        comparisons = amount_comparison.get("comparisons", [])
        checks.append({
            "check": "金额一致性",
            "passed": am,
            "detail": (
                "OA 表单金额与合同总价一致 ✅"
                if am else
                "OA 表单金额与合同总价不一致 ❌"
                if am is False else
                "无法判定（缺少可比字段）⚠️"
            ),
            "comparisons": comparisons,
        })

    # ── Check 2: Signature check (only when total > threshold) ─────────
    total = _extract_total_value(amounts_json)
    if total is not None and total > threshold and required_sig:
        has_sig = required_sig in ocr_text
        checks.append({
            "check": f"授权代表签字（需含「{required_sig}」）",
            "passed": has_sig,
            "detail": (
                f"合同金额 {total} 元 > {threshold} 元，"
                f"OCR 文本中{'找到' if has_sig else '未找到'}「{required_sig}」"
                f"{' ✅' if has_sig else ' ❌'}"
            ),
        })
    elif total is not None and total <= threshold and required_sig:
        checks.append({
            "check": f"授权代表签字",
            "passed": True,
            "detail": f"合同金额 {total} 元 ≤ {threshold} 元，无需签字检查，自动通过",
        })

    # ── Build verdict ──────────────────────────────────────────────────
    # None means "undetermined" — treated as pass for the core checks
    # (LLM can still flag issues in the report)
    passed = all(
        c["passed"] is not False for c in checks
    ) if checks else True

    return {
        "passed": passed,
        "checks": checks,
        "summary": (
            "核心校验全部通过 ✅" if passed
            else "核心校验未通过 ❌，详见各检查项"
        ),
    }


def _create_llm() -> ChatOpenAI:
    """Instantiate the LLM from config. Separated for easy mocking in tests."""
    config = load_config()
    ds = config["deepseek"]
    return ChatOpenAI(
        model=ds["model"],
        openai_api_key=ds["api_key"],
        openai_api_base=ds["base_url"],
        temperature=0,
    )


@trace_function(name="contract_check", run_type="chain")
def run_contract_check(query_params: dict) -> str:
    """Run the full contract check pipeline and return a human-readable report.

    Args:
        query_params: One of:
            - {"request_id": 917393}
              OA workflow → query attachments → download → OCR → validate
            - {"request_id": 917393, "filename": "行李费"}
              Same as above but only process files whose name contains the filter
            - {"file_path": "/path/to/contract.pdf"}
              Use local file directly, skip OA query and download
            - {"file_path": "...", "oa_amount": "100000"}
              Same as above + compare OA form amount with OCR-extracted total

    Returns:
        A dict with keys:
        - ``report`` (str): human-readable report from the LLM
        - ``passed`` (bool): final pass/fail verdict
        - ``core_checks`` (dict): structured check results
        - ``amount_comparison`` (dict | None): OA vs contract comparison
        - ``amounts_json`` (str): extracted amounts JSON
    """
    def _fail(reason: str) -> dict:
        return {
            "report": reason,
            "passed": False,
            "core_checks": {},
            "amount_comparison": None,
            "amounts_json": "{}",
        }
    try:
        params_str = json.dumps(query_params, ensure_ascii=False)
        oa_amount = query_params.get("oa_amount", "")
        source_description = ""

        # ================================================================
        # Step 1 & 2: Resolve file(s) — either OA lookup or local path
        # ================================================================
        if "file_path" in query_params:
            # --- Local file path: skip OA query and download ---
            local_path = query_params["file_path"]
            log_metadata({"input_mode": "local_file", "oa_amount": oa_amount})
            with trace_step(
                "resolve_files",
                inputs={"mode": "local", "file_path": local_path},
                metadata={"source": "local"},
            ):
                if not os.path.exists(local_path):
                    return _fail(f"合同校验失败：文件不存在 — {local_path}")
                local_paths = [local_path]
                source_description = f"本地文件：{local_path}"
        else:
            # --- OA lookup: query attachments by request_id ---
            request_id = query_params.get("request_id")
            log_metadata({"input_mode": "oa_workflow", "request_id": request_id})
            with trace_step(
                "query_oa_attachments",
                inputs={"request_id": request_id},
                run_type="tool",
            ) as span:
                files_json = query_contract_url_tool.func(params_str)
                if _tool_failed(files_json):
                    span.add_metadata({"error": files_json[:200]})
                    return _fail(f"合同校验失败：查询附件 — {files_json}")

                try:
                    files = json.loads(files_json)
                except json.JSONDecodeError:
                    span.add_metadata({"error": "invalid_json"})
                    return _fail(f"合同校验失败：查询附件返回格式异常 — {files_json[:200]}")

                if not files:
                    span.add_metadata({"file_count": 0})
                    return _fail(f"合同校验失败：requestId={request_id} 未找到任何附件")

                span.add_metadata({
                    "file_count": len(files),
                    "filenames": [f.get("filename", "?") for f in files],
                })

            # Optional filename filter (exact or substring match)
            target_filename = query_params.get("filename", "")
            if target_filename:
                matched = [f for f in files
                           if target_filename in (f.get("filename") or "")]
                if not matched:
                    names = [f.get("filename", "?") for f in files]
                    return _fail(
                        f"合同校验失败：未找到文件名包含 '{target_filename}' 的附件。"
                        f"可用文件：{', '.join(names)}"
                    )
                files = matched

            # Download each matched file
            local_paths = []
            for f in files:
                file_id = f.get("file_id")
                filename = f.get("filename", str(file_id))
                with trace_step(
                    "download_contract",
                    inputs={"file_id": file_id, "filename": filename},
                    run_type="tool",
                ) as span:
                    path = download_contract_tool.func(str(file_id))
                    span.add_metadata({
                        "success": not _tool_failed(path),
                        "local_path": path if not _tool_failed(path) else None,
                    })
                    if _tool_failed(path):
                        return _fail(f"合同校验失败：下载文件 {filename} (id={file_id}) — {path}")
                    local_paths.append(path)

            source_description = (
                f"OA 流程 requestId={query_params.get('request_id')}，"
                f"附件：{', '.join(f.get('filename', '?') for f in files)}"
            )

        # ================================================================
        # Step 3: Convert each file to images
        # ================================================================
        all_images = []
        for path in local_paths:
            with trace_step(
                "prepare_images",
                inputs={"file_path": path},
                run_type="tool",
            ) as span:
                images_json = prepare_images_tool.func(path)
                if _tool_failed(images_json):
                    span.add_metadata({"error": images_json[:200]})
                    return _fail(f"合同校验失败：文件转图片 ({path}) — {images_json}")
                try:
                    page_images = json.loads(images_json)
                    all_images.extend(page_images)
                    span.add_metadata({"page_count": len(page_images)})
                except json.JSONDecodeError:
                    span.add_metadata({"error": "invalid_json"})
                    return _fail(f"合同校验失败：文件转图片返回格式异常 — {images_json[:200]}")

        # ================================================================
        # Step 4: OCR all images
        # ================================================================
        images_json = json.dumps(all_images, ensure_ascii=False)
        with trace_step(
            "ocr_images",
            inputs={"image_count": len(all_images)},
            run_type="tool",
        ) as span:
            ocr_text = ocr_images_tool.func(images_json)
            if _tool_failed(ocr_text):
                span.add_metadata({"error": ocr_text[:200]})
                return _fail(f"合同校验失败：OCR识别 — {ocr_text}")
            span.add_metadata({
                "page_count": len(all_images),
                "ocr_text_length": len(ocr_text),
                "ocr_provider": load_config().get("ocr", {}).get("provider", "unknown"),
            })

        # ================================================================
        # Step 5: Extract amounts
        # ================================================================
        with trace_step(
            "extract_amounts",
            inputs={"ocr_text_length": len(ocr_text)},
            run_type="tool",
        ) as span:
            amounts_json = extract_amounts_tool.func(ocr_text)
            if _tool_failed(amounts_json):
                span.add_metadata({"error": amounts_json[:200]})
                return _fail(f"合同校验失败：金额提取 — {amounts_json}")
            try:
                amounts_parsed = json.loads(amounts_json)
                span.add_metadata({
                    "fields_found": list(amounts_parsed.keys()) if isinstance(amounts_parsed, dict) else [],
                    "field_count": len(amounts_parsed) if isinstance(amounts_parsed, dict) else 0,
                })
            except json.JSONDecodeError:
                span.add_metadata({"warning": "amounts_json is not valid JSON"})

        # ================================================================
        # Step 5½: Code-based core checks (amount match + signature)
        # ================================================================
        amount_comparison = None
        with trace_step(
            "core_checks",
            inputs={"oa_amount": oa_amount, "has_oa_amount": bool(oa_amount)},
            run_type="chain",
        ) as span:
            if oa_amount:
                amount_comparison = _compare_amounts(oa_amount, amounts_json)

            core_checks = _run_core_checks(
                oa_amount, amounts_json, ocr_text, amount_comparison,
            )

            # Attach structured check results as metadata
            check_meta = {
                "core_passed": core_checks["passed"],
                "checks": [
                    {"name": c["check"], "passed": c["passed"]}
                    for c in core_checks.get("checks", [])
                ],
            }
            if amount_comparison is not None:
                check_meta["amount_match"] = amount_comparison.get("match")
                check_meta["oa_amount"] = amount_comparison.get("oa_amount")
                comps = amount_comparison.get("comparisons", [])
                if comps:
                    check_meta["amount_comparisons"] = [
                        {"field": c["field"], "match": c.get("match"), "diff": c.get("diff")}
                        for c in comps
                    ]
            span.add_metadata(check_meta)

        # ================================================================
        # Step 6: Additional LLM-based validation (optional config rules)
        # ================================================================
        config = load_config()
        extra_rules = config.get("validation", {}).get("rules", [])
        validation_json = "{}"
        if extra_rules:
            with trace_step(
                "llm_validation",
                inputs={"rule_count": len(extra_rules)},
                run_type="tool",
            ) as span:
                validation_json = validate_amounts_tool.func(amounts_json)
                try:
                    v = json.loads(validation_json)
                    span.add_metadata({
                        "llm_validation_passed": v.get("passed"),
                        "rule_results": v.get("results", []),
                    })
                except json.JSONDecodeError:
                    span.add_metadata({"warning": "validation output is not JSON"})

        # ================================================================
        # Step 7: LLM report
        # ================================================================
        llm = _create_llm()

        # Build summary prompt
        comparison_block = ""
        if amount_comparison is not None:
            comparison_block = (
                f"OA 表单金额 vs 合同金额比对结果："
                f"{json.dumps(amount_comparison, ensure_ascii=False)}\n"
            )

        # Pass/fail verdict is determined by the code-based core checks
        final_verdict = "通过 ✅" if core_checks["passed"] else "不通过 ❌"

        summary_prompt = (
            f"查询参数：{params_str}\n"
            f"合同文件来源：{source_description}\n"
            f"图片数量：{len(all_images)} 页\n"
            f"OCR 识别文本：{ocr_text}\n"
            f"提取的金额字段：{amounts_json}\n"
            f"{comparison_block}"
            f"核心校验结果（代码判定，结论不可更改）："
            f"{json.dumps(core_checks, ensure_ascii=False)}\n\n"
            f"最终结论（必须使用此结论）：{final_verdict}\n\n"
            "请根据以上信息生成一份完整的合同金额校验报告。"
            "注意：核心校验结果由系统代码判定，你必须使用上面给出的最终结论。"
            "报告中请逐条列出各项检查及结果，最后给出通过或不通过的明确结论。"
        )

        with trace_step(
            "generate_report",
            inputs={"verdict": final_verdict},
            run_type="chain",
        ) as span:
            response = llm.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=summary_prompt),
            ])
            span.add_metadata({"report_length": len(response.content)})

        # ── Attach feedback scores ──────────────────────────────────────
        log_feedback(
            "passed",
            1.0 if core_checks["passed"] else 0.0,
            comment=core_checks["summary"],
        )
        if amount_comparison is not None and amount_comparison.get("match") is not None:
            log_feedback(
                "amount_match",
                1.0 if amount_comparison["match"] else 0.0,
                comment=f"OA {amount_comparison.get('oa_amount')} vs 合同",
            )

        return {
            "report": response.content,
            "passed": core_checks["passed"],
            "core_checks": core_checks,
            "amount_comparison": amount_comparison,
            "amounts_json": amounts_json,
        }

    except Exception as e:
        return _fail(f"合同校验失败：{e}")
