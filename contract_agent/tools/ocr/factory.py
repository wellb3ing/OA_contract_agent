from contract_agent.tools.ocr.base import OCRProvider
from contract_agent.tools.ocr.baidu import BaiduOCR
from contract_agent.tools.ocr.aliyun import AliyunOCR
from contract_agent.tools.ocr.tencent import TencentOCR
from contract_agent.tools.ocr.mcp import MCPOCR


def get_ocr_provider(config: dict) -> OCRProvider:
    provider_name = config["ocr"]["provider"].lower()
    if provider_name == "baidu":
        cfg = config["ocr"]["baidu"]
        return BaiduOCR(api_key=cfg["api_key"], secret_key=cfg["secret_key"])
    elif provider_name == "aliyun":
        cfg = config["ocr"]["aliyun"]
        return AliyunOCR(
            access_key_id=cfg["access_key_id"],
            access_key_secret=cfg["access_key_secret"],
            region=cfg.get("region", "cn-shanghai"),
        )
    elif provider_name == "tencent":
        cfg = config["ocr"]["tencent"]
        return TencentOCR(
            secret_id=cfg["secret_id"],
            secret_key=cfg["secret_key"],
            region=cfg.get("region", "ap-guangzhou"),
        )
    elif provider_name == "mcp":
        cfg = config["ocr"]["mcp"]
        return MCPOCR(url=cfg["url"])
    else:
        raise ValueError(
            f"不支持的 OCR 提供商：{provider_name}，可选：baidu / aliyun / tencent / mcp"
        )
