# contract_agent/tools/extractor.py
import json
import re
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
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
        # Strip markdown code blocks if present (```json ... ``` or ``` ... ```)
        stripped = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        stripped = re.sub(r"\s*```$", "", stripped.strip())
        # Validate JSON
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        # Try to extract bare JSON object from the raw response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            candidate = match.group(0)
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
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
        '例如：{"合同总价": 100000.0, "税率": "13%", "税额": 11504.42}'
    ),
)
