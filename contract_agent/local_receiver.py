# local_receiver.py —— 接收OA推送的本地服务
# 用法: python local_receiver.py
#
# 支持两种模式：
#   1. ddcode 模式   — 表单按钮推送 fileid+ddcode → 下载→校验→存结果
#   2. requestId 模式 — 审批节点推送 requestId → 取最新结果 → 不通过则退回

import json
import os
import sys
import time
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# Ensure the project root is on sys.path so contract_agent imports work
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from contract_agent.tools.downloader import download_with_ddcode
from contract_agent.agent import run_contract_check
from contract_agent.tracing import init_tracing, trace_step, log_metadata, log_feedback

init_tracing()  # enable LangSmith tracing for local_receiver flows

# ── Result storage ─────────────────────────────────────────────────────────
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "validation_results.json")


def _load_results() -> dict:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_results(results: dict) -> None:
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def _store_result(file_id: str, passed: bool, reason: str, filename: str, report: str) -> None:
    """Store a validation result, keyed by fileId."""
    results = _load_results()
    entry = {
        "fileId": file_id,
        "filename": filename,
        "passed": passed,
        "reason": reason,
        "report": report[:500],
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    results[file_id] = entry
    # Also keep a pointer to the most recent
    results["_latest_fileId"] = file_id
    _save_results(results)
    print(f"📥 校验结果已存储: fileId={file_id}, passed={passed}")


def _build_reason(passed: bool, core_checks: dict, amount_comparison: dict | None) -> str:
    """Build a detailed, human-readable reason from structured check results."""
    if passed:
        return "校验通过"

    parts = ["校验不通过"]

    # Detailed comparison results from amount_comparison
    if amount_comparison:
        for c in amount_comparison.get("comparisons", []):
            if c.get("match") is False:
                parts.append(
                    f"金额不一致：OA表单 {c.get('oa_amount')} vs "
                    f"合同「{c.get('field')}」{c.get('contract_amount')}，"
                    f"差额 {c.get('diff')} 元"
                )

    # Other failed checks (skip amount-related, already covered above)
    for ch in core_checks.get("checks", []):
        if ch.get("passed") is False and "金额" not in ch.get("check", ""):
            parts.append(ch.get("detail", ""))

    if len(parts) == 1:
        parts.append("详见校验报告")

    return "；".join(parts)


def _get_latest_result(poll_seconds: int = 30) -> dict | None:
    """Return the most recent validation result, polling up to *poll_seconds*.

    Returns None if no result is available after the timeout.
    """
    deadline = time.time() + poll_seconds
    while time.time() < deadline:
        results = _load_results()
        latest_id = results.get("_latest_fileId", "")
        if latest_id and latest_id in results:
            return results[latest_id]
        print(f"  ⏳ 等待校验结果就绪... ({int(deadline - time.time())}s)")
        time.sleep(2)
    return None


# ── Mode 2: ddcode → download → validate → store ───────────────────────────

def _process_ddcode_file(file_info: dict, contract_amount: str | None, index: int) -> None:
    """Download via ddcode, run pipeline, and store the result."""
    file_id = str(file_info.get("fileid", ""))
    filename = file_info.get("filename", file_id)
    ddcode = file_info.get("ddcode", "")

    print(f"\n{'='*60}")
    print(f"[ddcode] 附件 {index}: {filename}  (fileid={file_id})")
    print(f"{'='*60}")

    if contract_amount:
        print(f"OA 表单传入金额: {contract_amount}")

    # ── Step 1: Download ────────────────────────────────────────────────
    with trace_step(
        "ddcode_download",
        inputs={"file_id": file_id, "filename": filename},
        run_type="tool",
    ) as span:
        print("[1/2] 正在使用 ddcode 下载...")
        path = download_with_ddcode(file_id, ddcode)
        if path.startswith("下载失败"):
            print(f"❌ {path}")
            span.add_metadata({"error": path})
            _store_result(file_id, False, f"下载失败: {path}", filename, "")
            return
        span.add_metadata({"local_path": path})
        print(f"✅ 下载完成: {path}")

    # ── Step 2: Validate ────────────────────────────────────────────────
    with trace_step(
        "ddcode_validate",
        inputs={"file_path": path, "oa_amount": contract_amount},
        run_type="chain",
    ) as span:
        print("[2/2] 正在执行合同校验...")
        params = {"file_path": path}
        if contract_amount:
            params["oa_amount"] = contract_amount
        result = run_contract_check(params)

        report = result.get("report", str(result))
        passed = result.get("passed", False)
        core_checks = result.get("core_checks", {})
        amount_comparison = result.get("amount_comparison")

        span.add_metadata({
            "passed": passed,
            "core_checks_summary": core_checks.get("summary", ""),
            "amount_comparison": (
                {"match": amount_comparison.get("match"), "oa_amount": amount_comparison.get("oa_amount")}
                if amount_comparison else None
            ),
        })

    # Build a detailed reason from structured check results
    reason = _build_reason(passed, core_checks, amount_comparison)

    if not passed:
        print(f"❌ 校验不通过: {reason}")
        log_feedback("passed", 0.0, comment=reason)
    else:
        print(f"✅ 校验通过")
        log_feedback("passed", 1.0, comment="校验通过")

    print(f"\n{'─'*60}")
    print(f"校验报告:")
    print(f"{'─'*60}")
    print(report)
    print(f"{'─'*60}")

    # Save report to file
    report_dir = os.path.dirname(path)
    report_path = os.path.join(report_dir, "report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"📄 报告已保存: {report_path}")

    # ── Store result ────────────────────────────────────────────────────
    _store_result(file_id, passed, reason, filename, report)


# ── Mode 1: requestId → read latest result → reject if failed ───────────────

def _process_request_id(request_id: int) -> None:
    """Read the most recent validation result.  If it failed, reject the workflow."""
    print(f"\n{'='*60}")
    print(f"[requestId] requestId={request_id}")
    print(f"{'='*60}")

    with trace_step(
        "approval_node",
        inputs={"request_id": request_id},
        run_type="chain",
    ) as span:
        # ── Wait for result if still running ────────────────────────────────
        result = _get_latest_result(poll_seconds=30)

        if result is None:
            print("❌ 超时：未等到校验结果，跳过退回")
            span.add_metadata({"outcome": "timeout", "action": "skip_reject"})
            return

        span.add_metadata({
            "file_id": result.get("fileId"),
            "form_passed": result.get("passed"),
            "form_reason": result.get("reason", ""),
            "form_time": result.get("time"),
        })
        print(f"📋 最近校验: fileId={result['fileId']}, "
              f"passed={result['passed']}, "
              f"reason={result.get('reason', '?')}, "
              f"time={result['time']}")

        if result["passed"]:
            print("✅ 校验通过，流程放行")
            span.add_metadata({"outcome": "approved"})
            log_feedback("workflow_approved", 1.0, comment="校验通过，放行")
            return

        # ── Failed → wait for OA workflow state to settle, then reject ──────
        from contract_agent.config import load_config
        from contract_agent.tools.oa_reject import reject_with_report

        config = load_config()
        delay = config.get("oa", {}).get("reject_delay_seconds", 5)
        span.add_metadata({"reject_delay_s": delay, "outcome": "rejected"})
        print(f"⏳ 等待 {delay} 秒后执行退回（等 OA 流程落库）...")
        time.sleep(delay)

        reject_ok = reject_with_report(
            request_id, result.get("reason", result.get("report", ""))
        )
        span.add_metadata({"reject_success": reject_ok})
        if reject_ok:
            log_feedback("workflow_approved", 0.0, comment="校验不通过，已退回")
        else:
            log_feedback("workflow_approved", 0.0, comment="退回失败")


# ── HTTP server ─────────────────────────────────────────────────────────────

class Receiver(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        data = json.loads(body)

        contract_amount = data.get("amount", None)
        request_id = data.get("requestId", None)
        files = data.get("files", [])

        if request_id is not None:
            # ── requestId mode ─────────────────────────────────────────
            print("\n" + "=" * 60)
            print(f"========== 收到审批节点推送 (requestId={request_id}) ==========")
            print("=" * 60)

            t = threading.Thread(
                target=_process_request_id,
                args=(int(request_id),),
                daemon=True,
            )
            t.start()

            self._respond(200, f"已接收 requestId={request_id}，后台处理中...")

        elif files:
            # ── ddcode mode ────────────────────────────────────────────
            print("\n" + "=" * 60)
            print(f"========== 收到表单按钮推送 (ddcode) ==========")
            print(f"合同金额: {contract_amount or '未传'}")
            print(f"附件数量: {len(files)} 个")
            for i, f in enumerate(files, 1):
                print(f"  [{i}] {f.get('filename', '?')}  fileid={f.get('fileid', '?')}")
            print("=" * 60)

            for i, file_info in enumerate(files, 1):
                t = threading.Thread(
                    target=_process_ddcode_file,
                    args=(file_info, contract_amount, i),
                    daemon=True,
                )
                t.start()

            self._respond(200, f"已接收 {len(files)} 个文件，后台处理中...")

        else:
            self._respond(400, "请求中缺少 requestId 或 files 字段")

    def _respond(self, status: int, message: str) -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"status": "ok" if status == 200 else "error", "message": message},
            ensure_ascii=False,
        ).encode())


if __name__ == "__main__":
    port = 18888
    print(f"本地接收服务启动: http://0.0.0.0:{port}")
    print("等待 OA 推送...")
    print("  模式1: 表单按钮 → fileid+ddcode → 下载→校验→存结果")
    print("  模式2: 审批节点 → requestId → 查最新结果 → 不通过则退回")
    HTTPServer(("0.0.0.0", port), Receiver).serve_forever()
