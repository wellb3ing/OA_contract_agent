import base64
import requests
from contract_agent.tools.ocr.base import OCRProvider


class AliyunOCR(OCRProvider):
    """阿里云通用文字识别（印刷体）。"""

    def __init__(self, access_key_id: str, access_key_secret: str, region: str = "cn-shanghai"):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.endpoint = f"https://ocr-api.{region}.aliyuncs.com"

    def recognize(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {"image": image_b64, "outputTable": False}
        # 使用阿里云 OCR 通用印刷体识别接口
        url = f"{self.endpoint}/ocr/request"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"APPCODE {self.access_key_id}",  # 简化版，实际按阿里云文档签名
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "content" not in data:
            raise ValueError(f"阿里云 OCR 返回错误：{data}")
        return data["content"]
