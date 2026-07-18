import json
import os
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
from contract_agent.tools.prepare_images import (
    prepare_images_tool,
    _resize_to_limit,
    _save_jpeg_safe,
    MAX_DIMENSION,
    MAX_BASE64_BYTES,
    MIN_QUALITY,
    MIN_DIMENSION,
)


def _mock_pil_image(size=(1600, 1200)):
    """Create a MagicMock PIL Image that actually writes a file on .save()."""
    img = MagicMock(spec=Image.Image)
    img.size = size

    def _fake_save(path, fmt=None, quality=None, **kw):
        # Write a real (tiny) file so os.path.getsize succeeds
        Image.new("RGB", size).save(path, "JPEG", quality=quality or 25)

    img.save = _fake_save
    img.copy.return_value = img  # _save_jpeg_safe calls .copy()
    img.resize.return_value = img
    return img


def test_pdf_converted_to_images(tmp_path):
    mock_img1 = _mock_pil_image((1600, 1200))
    mock_img2 = _mock_pil_image((1600, 1200))

    with patch("contract_agent.tools.prepare_images.convert_from_path",
               return_value=[mock_img1, mock_img2]):
        result = prepare_images_tool.run(str(tmp_path / "contract.pdf"))

    paths = json.loads(result)
    assert isinstance(paths, list)
    assert len(paths) == 2
    assert all(p.endswith(".jpg") for p in paths)


def test_resize_to_limit_small_image():
    """Image within limits should not be resized."""
    img = Image.new("RGB", (100, 100))
    result = _resize_to_limit(img)
    assert result.size == (100, 100)


def test_resize_to_limit_large_image():
    """Image exceeding MAX_DIMENSION should be scaled down proportionally."""
    img = Image.new("RGB", (10000, 5000))
    result = _resize_to_limit(img)
    assert result.size == (MAX_DIMENSION, 600)  # scale = 1200/10000 = 0.12


def test_image_file_goes_through_ensure(tmp_path):
    """Image files are resized/re-encoded as JPEG, not returned raw."""
    img = Image.new("RGB", (200, 100))
    img_path = tmp_path / "scan.jpg"
    img.save(str(img_path), "JPEG")
    result = prepare_images_tool.run(str(img_path))
    paths = json.loads(result)
    assert isinstance(paths, list)
    assert len(paths) == 1
    assert paths[0].endswith(".jpg")


def test_unsupported_format(tmp_path):
    weird_path = tmp_path / "contract.docx"
    weird_path.write_bytes(b"fake docx")
    result = prepare_images_tool.run(str(weird_path))
    assert "不支持" in result or "unsupported" in result.lower()


# ---------------------------------------------------------------------------
# _save_jpeg_safe tests (use real PIL Images — file-size logic depends on them)
# ---------------------------------------------------------------------------

def test_save_jpeg_safe_small_image(tmp_path):
    """Small image at Q25 should fit under the base64 limit — no degradation."""
    img = Image.new("RGB", (200, 150), color=(255, 255, 255))
    out = str(tmp_path / "small.jpg")
    _save_jpeg_safe(img, out)

    assert os.path.getsize(out) <= int(MAX_BASE64_BYTES * 0.75)
    # Re-open — dimensions should be unchanged
    reloaded = Image.open(out)
    assert reloaded.size == (200, 150)


def test_save_jpeg_safe_quality_reduction(tmp_path):
    """A dense text-like image (many edges) may need quality reduction to fit."""
    from PIL import ImageDraw, ImageFont
    # Simulate a dense document page: 1200×900 with lots of text
    img = Image.new("RGB", (1200, 900), color=(248, 248, 240))
    draw = ImageDraw.Draw(img)
    # Small-font dense Chinese text — creates high-frequency content
    for y in range(5, 880, 12):
        line = "".join(chr(0x4E00 + (y * 37 + x * 13) % 20902) for x in range(80))
        draw.text((5, y), line, fill=(30, 30, 30))

    out = str(tmp_path / "dense_text.jpg")
    _save_jpeg_safe(img, out)

    assert os.path.getsize(out) <= int(MAX_BASE64_BYTES * 0.75)
    reloaded = Image.open(out)
    assert reloaded is not None


def test_save_jpeg_safe_dimension_shrink(tmp_path):
    """When min quality still too large, dimensions should be reduced."""
    from PIL import ImageDraw
    # 1200×1200 with a checkerboard-like watermark — hard to compress
    img = Image.new("RGB", (1200, 1200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Dense hatch pattern — every pixel alternates, worst realistic case
    for y in range(0, 1200, 2):
        for x in range(0, 1200, 2):
            draw.point((x, y), fill=(y % 256, x % 256, (x + y) % 256))

    out = str(tmp_path / "pattern.jpg")
    _save_jpeg_safe(img, out)

    raw_size = os.path.getsize(out)
    max_raw = int(MAX_BASE64_BYTES * 0.75)
    # If raw size still exceeds limit, at least dimensions must have shrunk
    if raw_size > max_raw:
        reloaded = Image.open(out)
        assert max(reloaded.size) < 1200, f"Expected shrink but size={reloaded.size}"
    else:
        assert raw_size <= max_raw


def test_save_jpeg_safe_at_min_dimension(tmp_path):
    """Image at MIN_DIMENSION should not loop forever even if still too large."""
    from PIL import ImageDraw
    img = Image.new("RGB", (MIN_DIMENSION, MIN_DIMENSION), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for y in range(0, MIN_DIMENSION, 2):
        for x in range(0, MIN_DIMENSION, 2):
            draw.point((x, y), fill=(y % 256, x % 256, (x + y) % 256))

    out = str(tmp_path / "min_dim.jpg")
    # Must not raise or hang — just ship it as-is
    _save_jpeg_safe(img, out)
    assert os.path.isfile(out)
