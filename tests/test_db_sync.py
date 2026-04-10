"""Test per services/db_sync.py."""
import os
import sqlite3
import time
import pytest


def make_db(path: str) -> None:
    """Crea un SQLite minimale al path indicato."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES ('hello')")


class TestLoadDbFromNas:
    def test_copies_remote_to_local(self, tmp_path):
        from services.db_sync import load_db_from_nas
        remote = str(tmp_path / "remote.db")
        local  = str(tmp_path / "local.db")
        make_db(remote)
        result = load_db_from_nas(local_db=local, remote_db=remote)
        assert result is True
        assert os.path.exists(local)

    def test_returns_false_if_remote_missing(self, tmp_path):
        from services.db_sync import load_db_from_nas
        result = load_db_from_nas(
            local_db=str(tmp_path / "local.db"),
            remote_db=str(tmp_path / "nonexistent.db"),
        )
        assert result is False

    def test_local_has_same_data(self, tmp_path):
        from services.db_sync import load_db_from_nas
        remote = str(tmp_path / "remote.db")
        local  = str(tmp_path / "local.db")
        make_db(remote)
        load_db_from_nas(local_db=local, remote_db=remote)
        with sqlite3.connect(local) as conn:
            row = conn.execute("SELECT v FROM t").fetchone()
        assert row[0] == "hello"


class TestBackupDbToNas:
    def test_remote_db_updated(self, tmp_path):
        from services.db_sync import backup_db_to_nas
        local  = str(tmp_path / "local.db")
        remote = str(tmp_path / "remote.db")
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir)
        make_db(local)
        backup_db_to_nas(local_db=local, remote_db=remote, backup_dir=backup_dir)
        assert os.path.exists(remote)

    def test_dated_backup_created(self, tmp_path):
        from services.db_sync import backup_db_to_nas
        local      = str(tmp_path / "local.db")
        remote     = str(tmp_path / "remote.db")
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir)
        make_db(local)
        backup_db_to_nas(local_db=local, remote_db=remote, backup_dir=backup_dir)
        backups = os.listdir(backup_dir)
        assert len(backups) == 1
        assert backups[0].endswith(".db")

    def test_atomic_no_partial_file(self, tmp_path):
        """Il file remoto non deve mai essere parziale (scrittura atomica)."""
        from services.db_sync import backup_db_to_nas
        local      = str(tmp_path / "local.db")
        remote     = str(tmp_path / "remote.db")
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir)
        make_db(local)
        # Esegui due volte: il file tmp non deve restare
        backup_db_to_nas(local_db=local, remote_db=remote, backup_dir=backup_dir)
        backup_db_to_nas(local_db=local, remote_db=remote, backup_dir=backup_dir)
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert len(tmp_files) == 0


class TestPruneOldBackups:
    def test_keeps_only_latest(self, tmp_path):
        from services.db_sync import prune_old_backups
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir)
        # Crea 15 file con timestamp diversi
        for i in range(15):
            path = os.path.join(backup_dir, f"photo_ai_202401{i:02d}_120000.db")
            with open(path, "w") as f:
                f.write("x")
        prune_old_backups(backup_dir, keep=10)
        remaining = os.listdir(backup_dir)
        assert len(remaining) == 10

    def test_keeps_newest(self, tmp_path):
        from services.db_sync import prune_old_backups
        backup_dir = str(tmp_path / "backups")
        os.makedirs(backup_dir)
        names = []
        for i in range(5):
            name = f"photo_ai_202401{i+1:02d}_120000.db"
            path = os.path.join(backup_dir, name)
            with open(path, "w") as f:
                f.write("x")
            names.append(name)
        prune_old_backups(backup_dir, keep=3)
        remaining = sorted(os.listdir(backup_dir))
        # Devono restare i 3 più recenti (nomi più grandi alfabeticamente)
        assert remaining == sorted(names)[-3:]
