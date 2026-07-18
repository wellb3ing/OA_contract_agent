# contract_agent/tools/validator.py
import json
import re
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
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
