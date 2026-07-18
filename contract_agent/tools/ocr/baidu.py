import base64
import requests
from contract_agent.tools.ocr.base import OCRProvider


class BaiduOCR(OCRProvider):
    TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
    OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"

    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self._token = None

    def _get_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.post(
            self.TOKEN_URL,
            params={"grant_type": "client_credentials", "client_id": self.api_key, "client_secret": self.secret_key},
            timeout=10,
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        return self._token

    def recognize(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        token = self._get_token()
        resp = requests.post(
            self.OCR_URL,
            params={"access_token": token},
            data={"image": image_b64},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "words_result" not in data:
            raise ValueError(f"百度 OCR 返回错误：{data}")
        return "\n".join(item["words"] for item in data["words_result"])
