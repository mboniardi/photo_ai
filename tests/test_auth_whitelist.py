"""Test per auth/whitelist.py."""
import pytest
from auth.whitelist import load_whitelist


class TestLoadWhitelist:
    def test_loads_emails(self, tmp_path):
        f = tmp_path / "emails.txt"
        f.write_text("mario@gmail.com\nanna@gmail.com\n", encoding="utf-8")
        wl = load_whitelist(str(f))
        assert "mario@gmail.com" in wl
        assert "anna@gmail.com" in wl

    def test_ignores_comments(self, tmp_path):
        f = tmp_path / "emails.txt"
        f.write_text("# commento\nmario@gmail.com\n", encoding="utf-8")
        wl = load_whitelist(str(f))
        assert len(wl) == 1
        assert "mario@gmail.com" in wl

    def test_ignores_blank_lines(self, tmp_path):
        f = tmp_path / "emails.txt"
        f.write_text("\nmario@gmail.com\n\n", encoding="utf-8")
        wl = load_whitelist(str(f))
        assert len(wl) == 1

    def test_normalizes_to_lowercase(self, tmp_path):
        f = tmp_path / "emails.txt"
        f.write_text("MARIO@GMAIL.COM\n", encoding="utf-8")
        wl = load_whitelist(str(f))
        assert "mario@gmail.com" in wl

    def test_returns_empty_frozenset_if_file_missing(self, tmp_path):
        wl = load_whitelist(str(tmp_path / "nonexistent.txt"))
        assert wl == frozenset()

    def test_returns_frozenset(self, tmp_path):
        f = tmp_path / "emails.txt"
        f.write_text("mario@gmail.com\n", encoding="utf-8")
        assert isinstance(load_whitelist(str(f)), frozenset)
