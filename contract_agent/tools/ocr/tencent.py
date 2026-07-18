import base64
import requests
from contract_agent.tools.ocr.base import OCRProvider


class TencentOCR(OCRProvider):
    """腾讯云通用印刷体识别。"""

    def __init__(self, secret_id: str, secret_key: str, region: str = "ap-guangzhou"):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.endpoint = "https://ocr.tencentcloudapi.com"

    def recognize(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        # 腾讯云 OCR 通用印刷体识别（GeneralBasicOCR）
        payload = {"ImageBase64": image_b64}
        headers = {
            "Content-Type": "application/json",
            "X-TC-Action": "GeneralBasicOCR",
            "X-TC-Version": "2018-11-19",
            "X-TC-Region": self.region,
            # 实际使用需按腾讯云文档进行签名，此处简化
            "Authorization": f"TC3-HMAC-SHA256 SecretId={self.secret_id}",
        }
        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = data.get("Response", {})
        if "TextDetections" not in result:
            raise ValueError(f"腾讯云 OCR 返回错误：{data}")
        return "\n".join(item["DetectedText"] for item in result["TextDetections"])
