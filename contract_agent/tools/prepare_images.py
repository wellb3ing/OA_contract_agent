import json
import os
import tempfile
from langchain_core.tools import Tool
from pdf2image import convert_from_path
from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
PDF_EXTENSIONS = {".pdf"}

# MCP OCR server payload limit ≈ 30 KB base64.  Must be very conservative.
# 72 DPI produces ~600×500 px pages → JPEG Q25 → ~20-25 KB base64.
PDF_DPI = 72
MAX_DIMENSION = 1200
JPEG_QUALITY = 25
MAX_BASE64_BYTES = 28 * 1024  # safe ceiling for MCP OCR (limit is ~30 KB base64)
MIN_QUALITY = 5
MIN_DIMENSION = 400
SHRINK_FACTOR = 0.85  # scale factor per retry when min quality still too large


def _resize_to_limit(image: Image.Image) -> Image.Image:
    """Scale the image so its longest edge does not exceed MAX_DIMENSION."""
    w, h = image.size
    longest = max(w, h)
    if longest <= MAX_DIMENSION:
        return image
    scale = MAX_DIMENSION / longest
    new_size = (int(w * scale), int(h * scale))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _save_jpeg_safe(image: Image.Image, out_path: str) -> None:
    """Save *image* as JPEG, iteratively reducing quality / dimensions so the
    base64 payload stays under ``MAX_BASE64_BYTES`` (MCP OCR hard limit)."""
    quality = JPEG_QUALITY
    img = image.copy()
    # Base64 inflates raw bytes by ~4/3; keep the raw file under 3/4 of the limit
    max_raw = int(MAX_BASE64_BYTES * 0.75)

    for _ in range(12):  # safety cap — at most 12 save attempts
        img.save(out_path, "JPEG", quality=quality)
        raw_size = os.path.getsize(out_path)
        if raw_size <= max_raw:
            return

        # Strategy: reduce quality first (biggest impact per step), then shrink
        if quality > MIN_QUALITY:
            quality = max(quality - 5, MIN_QUALITY)
            continue

        w, h = img.size
        longest = max(w, h)
        if longest <= MIN_DIMENSION:
            return  # already at minimum — ship it as-is rather than loop forever

        new_w = max(int(w * SHRINK_FACTOR), MIN_DIMENSION)
        new_h = max(int(h * SHRINK_FACTOR), MIN_DIMENSION)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        quality = MIN_QUALITY  # stay at floor quality after shrinking


def _ensure_image(file_path: str) -> str:
    """Load a single image, resize, save as JPEG (size-safe), return new path."""
    img = Image.open(file_path)
    img = img.convert("RGB")
    img = _resize_to_limit(img)
    tmp_dir = tempfile.mkdtemp()
    out_path = os.path.join(tmp_dir, "page_1.jpg")
    _save_jpeg_safe(img, out_path)
    return out_path


def _prepare_images(file_path: str) -> str:
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()

    if ext in IMAGE_EXTENSIONS:
        try:
            resized = _ensure_image(file_path)
        except Exception as e:
            return f"图片预处理失败：{e}"
        return json.dumps([resized])

    if ext in PDF_EXTENSIONS:
        try:
            pages = convert_from_path(file_path, dpi=PDF_DPI)
        except Exception as e:
            return f"PDF 转图片失败：{e}"

        tmp_dir = tempfile.mkdtemp()
        image_paths = []
        for i, page in enumerate(pages, start=1):
            page = _resize_to_limit(page)
            img_path = os.path.join(tmp_dir, f"page_{i}.jpg")
            _save_jpeg_safe(page, img_path)
            image_paths.append(img_path)
        return json.dumps(image_paths)

    return f"不支持的文件格式：{ext}，支持 PDF 和图片（JPG/PNG/BMP/TIFF）"


prepare_images_tool = Tool(
    name="prepare_images",
    func=_prepare_images,
    description=(
        "将合同文件（PDF 或图片）转换为适合 OCR 的图片列表。"
        "输入：本地文件路径字符串。"
        "输出：JSON 字符串，包含图片路径列表，例如 [\"/tmp/xxx/page_1.jpg\"]。"
    ),
)
