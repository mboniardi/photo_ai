"""
Test per database/settings.py — CRUD tabella settings.
"""


class TestGetSetting:
    def test_get_nonexistent_returns_default(self, tmp_db):
        from database.settings import get_setting
        value = get_setting(tmp_db, "ai_engine", default="gemini")
        assert value == "gemini"

    def test_get_nonexistent_no_default_returns_none(self, tmp_db):
        from database.settings import get_setting
        assert get_setting(tmp_db, "missing_key") is None


class TestSetSetting:
    def test_set_and_get(self, tmp_db):
        from database.settings import set_setting, get_setting
        set_setting(tmp_db, "ai_engine", "groq")
        assert get_setting(tmp_db, "ai_engine") == "groq"

    def test_upsert_updates_existing(self, tmp_db):
        from database.settings import set_setting, get_setting
        set_setting(tmp_db, "ai_engine", "gemini")
        set_setting(tmp_db, "ai_engine", "groq")
        assert get_setting(tmp_db, "ai_engine") == "groq"


class TestGetAllSettings:
    def test_returns_dict(self, tmp_db):
        from database.settings import set_setting, get_all_settings
        set_setting(tmp_db, "ai_engine", "gemini")
        set_setting(tmp_db, "gemini_api_key", "key123")
        settings = get_all_settings(tmp_db)
        assert isinstance(settings, dict)
        assert settings["ai_engine"] == "gemini"
        assert settings["gemini_api_key"] == "key123"
