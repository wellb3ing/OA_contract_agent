"""泛微 OA 流程退回客户端。

用法::

    from contract_agent.tools.oa_reject import reject_workflow
    reject_workflow(request_id=917393, reason="合同金额不一致")
"""

from urllib.parse import urlencode
import requests
from contract_agent.config import load_config

# 共享 Session —— 登录后的 cookie 自动保留到退回请求
_session = requests.Session()


def _get_token() -> str:
    """调用 OA 登录接口获取 token，Session 自动保存 cookie。"""
    config = load_config()
    oa = config.get("oa", {})
    url = f"{oa['base_url']}/api/hrm/login/checkLogin"

    resp = _session.post(url, data={
        "loginid": oa["login_id"],
        "userpassword": oa["password"],
    }, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    token = data.get("user_token") or data.get("token") or ""
    if not token:
        raise RuntimeError(f"OA 登录失败，未获取到 token: {data}")
    return token


def reject_workflow(request_id: int, reason: str = "") -> dict:
    """退回 OA 流程。"""
    config = load_config()
    oa = config.get("oa", {})
    base_url = oa["base_url"]
    app_id = oa["app_id"]

    token = _get_token()

    url = f"{base_url}/api/workflow/paService/rejectRequest"
    payload_str = urlencode({
        "token": str(token),
        "appid": str(app_id),
        "requestId": str(request_id),
        "remark": reason,
    })

    print(f"⏪ 退回请求:")
    print(f"   URL: {url}")
    print(f"   body: {payload_str}")

    resp = _session.post(
        url,
        data=payload_str,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    print(f"   响应状态: {resp.status_code}")
    print(f"   响应内容: {resp.text[:300]}")

    resp.raise_for_status()
    return resp.json()


def reject_with_report(request_id: int, report_summary: str) -> bool:
    """退回 OA 流程，附带校验报告摘要。"""
    reason = f"合同校验不通过：{report_summary}"[:200]

    print(f"\n⏪ 正在退回 OA 流程 requestId={request_id}...")
    print(f"   原因: {reason}")

    try:
        result = reject_workflow(request_id, reason)
        print(f"✅ 流程已退回: {result}")
        return True
    except Exception as e:
        print(f"❌ 退回失败: {e}")
        return False
