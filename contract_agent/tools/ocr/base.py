from abc import ABC, abstractmethod


class OCRProvider(ABC):
    @abstractmethod
    def recognize(self, image_path: str) -> str:
        """识别单张图片，返回识别出的原始文字字符串。"""
        pass
