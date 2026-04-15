"""
Test per services/image_processor.py.
Usa immagini PIL generate in memoria — nessun file su disco.
"""
import io
import pytest
from PIL import Image


def make_jpeg_bytes(width: int = 200, height: int = 100,
                    color: tuple = (255, 0, 0)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def make_png_bytes(width: int = 200, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), (0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def make_rgba_image() -> Image.Image:
    return Image.new("RGBA", (100, 100), (255, 0, 0, 128))


def make_large_image(side: int = 4000) -> Image.Image:
    return Image.new("RGB", (side, side), (100, 150, 200))


def save_to_tmp(tmp_path, img: Image.Image, suffix: str) -> str:
    path = str(tmp_path / f"img{suffix}")
    img.save(path)
    return path


class TestOpenAnyFormat:
    def test_opens_jpeg(self, tmp_path):
        from services.image_processor import open_any_format
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (100, 100)).save(path, "JPEG")
        img = open_any_format(path)
        assert isinstance(img, Image.Image)
        assert img.size == (100, 100)

    def test_opens_png(self, tmp_path):
        from services.image_processor import open_any_format
        path = str(tmp_path / "test.png")
        Image.new("RGB", (80, 60)).save(path, "PNG")
        img = open_any_format(path)
        assert img.size == (80, 60)

    def test_unsupported_extension_raises(self, tmp_path):
        from services.image_processor import open_any_format
        path = str(tmp_path / "test.xyz")
        with open(path, "w") as f:
            f.write("not an image")
        with pytest.raises(Exception):
            open_any_format(path)


class TestPrepareForAi:
    def test_returns_bytes(self, tmp_path):
        from services.image_processor import prepare_for_ai
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (100, 100)).save(path, "JPEG")
        result = prepare_for_ai(path)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_result_is_valid_jpeg(self, tmp_path):
        from services.image_processor import prepare_for_ai
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (100, 100)).save(path, "JPEG")
        result = prepare_for_ai(path)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_large_image_is_downscaled(self, tmp_path):
        from services.image_processor import prepare_for_ai
        path = str(tmp_path / "big.jpg")
        Image.new("RGB", (4000, 3000)).save(path, "JPEG")
        result = prepare_for_ai(path)
        img = Image.open(io.BytesIO(result))
        assert max(img.size) <= 1280

    def test_small_image_not_upscaled(self, tmp_path):
        from services.image_processor import prepare_for_ai
        path = str(tmp_path / "small.jpg")
        Image.new("RGB", (200, 150)).save(path, "JPEG")
        result = prepare_for_ai(path)
        img = Image.open(io.BytesIO(result))
        assert img.size == (200, 150)

    def test_rgba_converted_to_rgb(self, tmp_path):
        from services.image_processor import prepare_for_ai
        path = str(tmp_path / "rgba.png")
        Image.new("RGBA", (100, 100), (255, 0, 0, 128)).save(path, "PNG")
        result = prepare_for_ai(path)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGB"

    def test_respects_target_max_kb(self, tmp_path):
        """Immagine molto grande non deve superare TARGET_MAX_KB."""
        from services.image_processor import prepare_for_ai
        import config
        # Immagine 1280x1280 con gradiente per avere più entropia
        img = Image.new("RGB", (1280, 1280))
        pixels = img.load()
        for x in range(1280):
            for y in range(0, 1280, 10):
                pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
        path = str(tmp_path / "noisy.png")
        img.save(path, "PNG")
        result = prepare_for_ai(path)
        assert len(result) <= config.TARGET_MAX_KB * 1024

    def test_aspect_ratio_preserved(self, tmp_path):
        """Ridimensionamento deve mantenere le proporzioni."""
        from services.image_processor import prepare_for_ai
        path = str(tmp_path / "wide.jpg")
        Image.new("RGB", (4000, 1000)).save(path, "JPEG")
        result = prepare_for_ai(path)
        img = Image.open(io.BytesIO(result))
        w, h = img.size
        assert abs(w / h - 4.0) < 0.1


class TestGenerateThumbnail:
    def test_returns_bytes(self, tmp_path):
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (800, 600)).save(path, "JPEG")
        result = generate_thumbnail(path)
        assert isinstance(result, bytes) and len(result) > 0

    def test_result_is_valid_jpeg(self, tmp_path):
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (800, 600)).save(path, "JPEG")
        result = generate_thumbnail(path)
        img = Image.open(io.BytesIO(result))
        assert img.format == "JPEG"

    def test_max_side_is_default_400(self, tmp_path):
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (800, 600)).save(path, "JPEG")
        result = generate_thumbnail(path)
        img = Image.open(io.BytesIO(result))
        assert max(img.size) <= 400

    def test_custom_size(self, tmp_path):
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "test.jpg")
        Image.new("RGB", (800, 600)).save(path, "JPEG")
        result = generate_thumbnail(path, size=200)
        img = Image.open(io.BytesIO(result))
        assert max(img.size) <= 200

    def test_small_image_not_upscaled(self, tmp_path):
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "small.jpg")
        Image.new("RGB", (100, 80)).save(path, "JPEG")
        result = generate_thumbnail(path, size=400)
        img = Image.open(io.BytesIO(result))
        assert img.size == (100, 80)

    def test_orientation_6_corrected(self, tmp_path):
        """JPEG con Orientation=6 (rotate 90° CW): thumbnail deve essere portrait."""
        import piexif
        from services.image_processor import generate_thumbnail
        # Pixel grezzi: 200×100 (landscape). Con Orientation=6 la foto è portrait.
        path = str(tmp_path / "portrait.jpg")
        Image.new("RGB", (200, 100), (200, 100, 50)).save(path, "JPEG")
        exif_bytes = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
        piexif.insert(exif_bytes, path)

        result = generate_thumbnail(path)
        out = Image.open(io.BytesIO(result))
        assert out.height > out.width, (
            f"Atteso portrait (h>w), ottenuto {out.size}"
        )

    def test_orientation_8_corrected(self, tmp_path):
        """JPEG con Orientation=8 (rotate 90° CCW): thumbnail deve essere portrait."""
        import piexif
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "portrait8.jpg")
        Image.new("RGB", (200, 100), (50, 100, 200)).save(path, "JPEG")
        exif_bytes = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 8}})
        piexif.insert(exif_bytes, path)

        result = generate_thumbnail(path)
        out = Image.open(io.BytesIO(result))
        assert out.height > out.width, (
            f"Atteso portrait (h>w), ottenuto {out.size}"
        )

    def test_no_orientation_tag_unchanged(self, tmp_path):
        """JPEG senza tag Orientation: dimensioni invariate."""
        from services.image_processor import generate_thumbnail
        path = str(tmp_path / "normal.jpg")
        Image.new("RGB", (200, 100)).save(path, "JPEG")
        result = generate_thumbnail(path, size=400)
        out = Image.open(io.BytesIO(result))
        assert out.width > out.height  # landscape invariato
