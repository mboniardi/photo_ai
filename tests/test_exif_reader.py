"""
Test per services/exif_reader.py.
Crea JPEG con dati EXIF noti usando piexif per verificare
che la lettura sia corretta per ogni tipo di dato.
"""
import io
import struct
import pytest
from PIL import Image
import piexif


def make_jpeg_with_exif(
    width: int = 100,
    height: int = 80,
    exif_dict: dict = None,
) -> bytes:
    """Crea un JPEG in memoria con i dati EXIF forniti."""
    img = Image.new("RGB", (width, height), (128, 64, 32))
    buf = io.BytesIO()
    if exif_dict:
        exif_bytes = piexif.dump(exif_dict)
        img.save(buf, "JPEG", exif=exif_bytes)
    else:
        img.save(buf, "JPEG")
    return buf.getvalue()


def save_jpeg(tmp_path, jpeg_bytes: bytes, name: str = "test.jpg") -> str:
    path = str(tmp_path / name)
    with open(path, "wb") as f:
        f.write(jpeg_bytes)
    return path


def rational(numerator: int, denominator: int = 1) -> tuple:
    return (numerator, denominator)


# ── EXIF dict con dati noti ───────────────────────────────────────

def make_full_exif() -> dict:
    """EXIF con tutti i campi rilevanti valorizzati."""
    gps_lat_dms = [rational(41), rational(54), rational(3600 * 28 // 100)]
    gps_lon_dms = [rational(12), rational(29), rational(3600 * 55 // 100)]
    return {
        "0th": {
            piexif.ImageIFD.Make: b"Canon",
            piexif.ImageIFD.Model: b"EOS R5",
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2023:07:15 14:32:00",
            piexif.ExifIFD.LensModel: b"RF 24-70mm F2.8L",
            piexif.ExifIFD.FocalLength: rational(35),
            piexif.ExifIFD.FNumber: rational(28, 10),
            piexif.ExifIFD.ExposureTime: rational(1, 120),
            piexif.ExifIFD.ISOSpeedRatings: 200,
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: gps_lat_dms,
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: gps_lon_dms,
        },
    }


class TestReadExifJpeg:
    def test_returns_dict(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif())
        result = read_exif(path)
        assert isinstance(result, dict)

    def test_reads_dimensions(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(width=640, height=480))
        result = read_exif(path)
        assert result["width"] == 640
        assert result["height"] == 480

    def test_reads_camera_make(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["camera_make"] == "Canon"

    def test_reads_camera_model(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["camera_model"] == "EOS R5"

    def test_reads_date(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["exif_date"] == "2023-07-15T14:32:00"

    def test_reads_iso(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["iso"] == 200

    def test_reads_focal_length(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["focal_length"] == pytest.approx(35.0, abs=0.5)

    def test_reads_aperture(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        # FNumber 28/10 = 2.8
        assert result["aperture"] == pytest.approx(2.8, abs=0.01)

    def test_reads_shutter_speed(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["shutter_speed"] == "1/120"

    def test_reads_lens_model(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["lens_model"] == "RF 24-70mm F2.8L"

    def test_gps_north_east(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=make_full_exif()))
        result = read_exif(path)
        assert result["latitude"] is not None
        assert result["longitude"] is not None
        assert result["latitude"] > 0   # Nord
        assert result["longitude"] > 0  # Est

    def test_gps_south_west(self, tmp_path):
        from services.exif_reader import read_exif
        exif = make_full_exif()
        exif["GPS"][piexif.GPSIFD.GPSLatitudeRef] = b"S"
        exif["GPS"][piexif.GPSIFD.GPSLongitudeRef] = b"W"
        path = save_jpeg(tmp_path, make_jpeg_with_exif(exif_dict=exif))
        result = read_exif(path)
        assert result["latitude"] < 0   # Sud → negativo
        assert result["longitude"] < 0  # Ovest → negativo

    def test_no_exif_returns_dimensions_only(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif())
        result = read_exif(path)
        assert result["width"] == 100
        assert result["height"] == 80
        assert result.get("camera_make") is None
        assert result.get("latitude") is None

    def test_reads_file_size(self, tmp_path):
        from services.exif_reader import read_exif
        import os
        path = save_jpeg(tmp_path, make_jpeg_with_exif())
        result = read_exif(path)
        assert result["file_size"] == os.path.getsize(path)


class TestReadExifPng:
    def test_returns_dimensions(self, tmp_path):
        from services.exif_reader import read_exif
        path = str(tmp_path / "test.png")
        Image.new("RGB", (320, 240)).save(path, "PNG")
        result = read_exif(path)
        assert result["width"] == 320
        assert result["height"] == 240

    def test_no_camera_exif(self, tmp_path):
        from services.exif_reader import read_exif
        path = str(tmp_path / "test.png")
        Image.new("RGB", (100, 100)).save(path, "PNG")
        result = read_exif(path)
        assert result.get("camera_make") is None
        assert result.get("latitude") is None


class TestExifOrientation:
    """Il tag Orientation deve essere letto e le dimensioni corrette per swap."""

    def _jpeg_with_orientation(self, tmp_path, width: int, height: int, orientation: int) -> str:
        path = str(tmp_path / f"orient_{orientation}.jpg")
        img = Image.new("RGB", (width, height), (100, 150, 200))
        buf = io.BytesIO()
        exif_bytes = piexif.dump({"0th": {piexif.ImageIFD.Orientation: orientation}})
        img.save(buf, "JPEG", exif=exif_bytes)
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return path

    def test_reads_orientation_tag(self, tmp_path):
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 6)
        result = read_exif(path)
        assert result["exif_orientation"] == 6

    def test_no_orientation_is_none(self, tmp_path):
        from services.exif_reader import read_exif
        path = save_jpeg(tmp_path, make_jpeg_with_exif(width=200, height=100))
        result = read_exif(path)
        assert result["exif_orientation"] is None

    def test_orientation_6_swaps_dimensions(self, tmp_path):
        """Orientation=6 (ruota 90° CW): dimensioni logiche = (100, 200)."""
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 6)
        result = read_exif(path)
        assert result["width"] == 100
        assert result["height"] == 200

    def test_orientation_8_swaps_dimensions(self, tmp_path):
        """Orientation=8 (ruota 90° CCW): dimensioni logiche = (100, 200)."""
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 8)
        result = read_exif(path)
        assert result["width"] == 100
        assert result["height"] == 200

    def test_orientation_5_swaps_dimensions(self, tmp_path):
        """Orientation=5 (transpose): dimensioni logiche = (100, 200)."""
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 5)
        result = read_exif(path)
        assert result["width"] == 100
        assert result["height"] == 200

    def test_orientation_7_swaps_dimensions(self, tmp_path):
        """Orientation=7 (transverse): dimensioni logiche = (100, 200)."""
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 7)
        result = read_exif(path)
        assert result["width"] == 100
        assert result["height"] == 200

    def test_orientation_3_no_swap(self, tmp_path):
        """Orientation=3 (180°): dimensioni invariate."""
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 3)
        result = read_exif(path)
        assert result["width"] == 200
        assert result["height"] == 100

    def test_orientation_1_no_swap(self, tmp_path):
        """Orientation=1 (normale): dimensioni invariate."""
        from services.exif_reader import read_exif
        path = self._jpeg_with_orientation(tmp_path, 200, 100, 1)
        result = read_exif(path)
        assert result["width"] == 200
        assert result["height"] == 100


class TestGpsConversion:
    """Test della funzione di conversione DMS → decimale."""
    def test_decimal_degrees_positive(self):
        from services.exif_reader import dms_to_decimal
        # 41° 54' 0" N = 41.9
        result = dms_to_decimal([(41, 1), (54, 1), (0, 1)], "N")
        assert result == pytest.approx(41.9, abs=0.01)

    def test_decimal_degrees_negative_south(self):
        from services.exif_reader import dms_to_decimal
        result = dms_to_decimal([(33, 1), (52, 1), (0, 1)], "S")
        assert result == pytest.approx(-33.8667, abs=0.01)

    def test_decimal_degrees_negative_west(self):
        from services.exif_reader import dms_to_decimal
        result = dms_to_decimal([(118, 1), (15, 1), (0, 1)], "W")
        assert result == pytest.approx(-118.25, abs=0.01)
