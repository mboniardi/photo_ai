"""Test per services/scanner.py."""
import io
import os
import pytest
from PIL import Image
import piexif


def make_jpeg(path: str, width: int = 100, height: int = 80,
              exif_date: str = None) -> None:
    """Salva un JPEG con EXIF opzionale al path indicato."""
    img = Image.new("RGB", (width, height), (100, 150, 200))
    if exif_date:
        exif_dict = {
            "Exif": {
                piexif.ExifIFD.DateTimeOriginal: exif_date.encode()
            }
        }
        img.save(path, "JPEG", exif=piexif.dump(exif_dict))
    else:
        img.save(path, "JPEG")


class TestScanFolder:
    def test_finds_jpeg_files(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        make_jpeg(str(tmp_path / "a.jpg"))
        make_jpeg(str(tmp_path / "b.jpg"))
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        assert result.new == 2

    def test_skips_non_image_files(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        (tmp_path / "readme.txt").write_text("hello")
        make_jpeg(str(tmp_path / "photo.jpg"))
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        assert result.new == 1

    def test_skips_already_indexed(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        make_jpeg(str(tmp_path / "photo.jpg"))
        result1 = scan_folder(str(tmp_path), db_path=tmp_db)
        result2 = scan_folder(str(tmp_path), db_path=tmp_db)
        assert result1.new == 1
        assert result2.new == 0
        assert result2.skipped == 1

    def test_returns_new_photo_ids(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        make_jpeg(str(tmp_path / "a.jpg"))
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        assert len(result.new_photo_ids) == 1
        assert isinstance(result.new_photo_ids[0], int)

    def test_stores_correct_folder_path(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        from database.photos import get_photo_by_id
        make_jpeg(str(tmp_path / "photo.jpg"))
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        photo = get_photo_by_id(tmp_db, result.new_photo_ids[0])
        assert photo["folder_path"] == str(tmp_path)

    def test_stores_file_size(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        from database.photos import get_photo_by_id
        path = str(tmp_path / "photo.jpg")
        make_jpeg(path)
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        photo = get_photo_by_id(tmp_db, result.new_photo_ids[0])
        assert photo["file_size"] == os.path.getsize(path)

    def test_stores_dimensions(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        from database.photos import get_photo_by_id
        make_jpeg(str(tmp_path / "photo.jpg"), width=320, height=240)
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        photo = get_photo_by_id(tmp_db, result.new_photo_ids[0])
        assert photo["width"] == 320
        assert photo["height"] == 240

    def test_stores_exif_date(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        from database.photos import get_photo_by_id
        make_jpeg(str(tmp_path / "photo.jpg"),
                  exif_date="2023:07:15 14:32:00")
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        photo = get_photo_by_id(tmp_db, result.new_photo_ids[0])
        assert photo["exif_date"] == "2023-07-15T14:32:00"

    def test_scans_subdirectories(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        subdir = tmp_path / "sub"
        subdir.mkdir()
        make_jpeg(str(subdir / "photo.jpg"))
        result = scan_folder(str(tmp_path), db_path=tmp_db)
        assert result.new == 1

    def test_rescan_detects_changed_file(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        path = str(tmp_path / "photo.jpg")
        make_jpeg(path, width=100)
        scan_folder(str(tmp_path), db_path=tmp_db)
        # Sovrascrivi con file diverso (size cambia)
        make_jpeg(path, width=800)
        result2 = scan_folder(str(tmp_path), db_path=tmp_db)
        assert result2.new == 1  # reindexed

    def test_rescan_preserves_user_flags(self, tmp_path, tmp_db):
        from services.scanner import scan_folder
        from database.photos import get_photo_by_id, update_photo
        path = str(tmp_path / "photo.jpg")
        make_jpeg(path, width=100)
        result1 = scan_folder(str(tmp_path), db_path=tmp_db)
        pid = result1.new_photo_ids[0]
        # Set user flag
        update_photo(tmp_db, pid, is_favorite=1)
        # Change the file
        make_jpeg(path, width=800)
        result2 = scan_folder(str(tmp_path), db_path=tmp_db)
        # User flag must survive re-index
        photo = get_photo_by_id(tmp_db, result2.new_photo_ids[0])
        assert photo["is_favorite"] == 1
