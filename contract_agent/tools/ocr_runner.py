import json
from langchain_core.tools import Tool
from contract_agent.config import load_config
from contract_agent.tools.ocr.factory import get_ocr_provider


def _ocr_images(input_str: str) -> str:
    try:
        image_paths = json.loads(input_str)
    except json.JSONDecodeError:
        return "错误：输入必须是 JSON 格式的图片路径列表，例如 [\"/tmp/page_1.png\"]"

    config = load_config()
    try:
        provider = get_ocr_provider(config)
    except ValueError as e:
        return f"OCR 初始化失败：{e}"

    results = []
    for i, path in enumerate(image_paths, start=1):
        try:
            text = provider.recognize(path)
            results.append(f"=== 第 {i} 页 ===\n{text}")
        except Exception as e:
            results.append(f"=== 第 {i} 页（识别失败：{e}）===")

    return "\n\n".join(results)


ocr_images_tool = Tool(
    name="ocr_images",
    func=_ocr_images,
    description=(
        "对图片列表进行 OCR 文字识别。"
        "输入：JSON 字符串，包含图片路径列表，例如 [\"/tmp/page_1.png\", \"/tmp/page_2.png\"]。"
        "输出：各页识别出的文字，按页合并为一个字符串。"
    ),
)
