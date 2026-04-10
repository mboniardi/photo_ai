"""
Test per config.py.
Verifica valori di default e lettura da variabili d'ambiente.
"""
import os
import importlib
import pytest


def reload_config(env_overrides: dict):
    """Ricarica config con variabili d'ambiente sovrascritte."""
    old = {k: os.environ.pop(k, None) for k in env_overrides}
    os.environ.update(env_overrides)
    import config
    importlib.reload(config)
    # ripristina
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return config


class TestDefaults:
    def test_app_port_default(self):
        import config
        assert config.APP_PORT == 8080

    def test_max_side_px_default(self):
        import config
        assert config.MAX_SIDE_PX == 1280

    def test_jpeg_quality_default(self):
        import config
        assert config.JPEG_QUALITY == 85

    def test_target_max_kb_default(self):
        import config
        assert config.TARGET_MAX_KB == 800

    def test_thumbnail_size_default(self):
        import config
        assert config.THUMBNAIL_SIZE == 400

    def test_thumbnail_quality_default(self):
        import config
        assert config.THUMBNAIL_QUALITY == 82


class TestEnvOverrides:
    def test_app_port_from_env(self):
        cfg = reload_config({"APP_PORT": "9090"})
        assert cfg.APP_PORT == 9090

    def test_max_side_px_from_env(self):
        cfg = reload_config({"MAX_SIDE_PX": "1024"})
        assert cfg.MAX_SIDE_PX == 1024

    def test_gemini_api_key_from_env(self):
        cfg = reload_config({"GEMINI_API_KEY": "test-key-123"})
        assert cfg.GEMINI_API_KEY == "test-key-123"

    def test_app_data_path_from_env(self):
        cfg = reload_config({"APP_DATA_PATH": "/mnt/nas/data"})
        assert cfg.APP_DATA_PATH == "/mnt/nas/data"


class TestDerivedPaths:
    def test_local_db_is_string(self):
        import config
        assert isinstance(config.LOCAL_DB, str)
        assert config.LOCAL_DB.endswith(".db")

    def test_remote_db_contains_app_data_path(self):
        cfg = reload_config({"APP_DATA_PATH": "/mnt/test_nas"})
        assert cfg.REMOTE_DB.startswith("/mnt/test_nas")

    def test_remote_db_ends_with_db(self):
        import config
        assert config.REMOTE_DB.endswith(".db")
