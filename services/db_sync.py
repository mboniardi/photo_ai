"""
Sincronizzazione DB tra locale (VM) e NAS.
Funzioni chiamate all'avvio e dallo scheduler APScheduler.
"""
import os
import shutil
from datetime import datetime
from typing import Optional
import config


def load_db_from_nas(
    local_db: Optional[str] = None,
    remote_db: Optional[str] = None,
) -> bool:
    """
    Copia REMOTE_DB → LOCAL_DB se il file remoto esiste.
    Crea la directory locale se necessario.
    Ritorna True se la copia è avvenuta.
    """
    local  = local_db  or config.LOCAL_DB
    remote = remote_db or config.REMOTE_DB

    if not os.path.exists(remote):
        return False

    if os.path.abspath(remote) == os.path.abspath(local):
        return False

    if dirname := os.path.dirname(local):
        os.makedirs(dirname, exist_ok=True)
    shutil.copy2(remote, local)
    return True


def backup_db_to_nas(
    local_db: Optional[str] = None,
    remote_db: Optional[str] = None,
    backup_dir: Optional[str] = None,
) -> None:
    """
    Backup atomico LOCAL_DB → REMOTE_DB.
    Crea anche una copia datata in backup_dir.
    """
    local  = local_db  or config.LOCAL_DB
    remote = remote_db or config.REMOTE_DB
    bdir   = backup_dir or os.path.join(
        os.path.dirname(remote), "photo_ai.db.backup"
    )

    if not os.path.exists(local):
        return

    if dirname := os.path.dirname(remote):
        os.makedirs(dirname, exist_ok=True)
    os.makedirs(bdir, exist_ok=True)

    # Scrittura atomica tramite file tmp + rename (POSIX)
    tmp = remote + ".tmp"
    shutil.copy2(local, tmp)
    os.replace(tmp, remote)

    # Backup datato
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dated = os.path.join(bdir, f"photo_ai_{ts}.db")
    shutil.copy2(local, dated)


def prune_old_backups(backup_dir: str, keep: int = 10) -> None:
    """
    Elimina i backup più vecchi in backup_dir, conserva solo gli ultimi `keep`.
    Ordina per nome file (che contiene il timestamp YYYYMMDD_HHMMSS).
    """
    if not os.path.isdir(backup_dir):
        return
    files = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("photo_ai_") and f.endswith(".db")]
    )
    to_delete = files[:-keep] if len(files) > keep else []
    for name in to_delete:
        os.remove(os.path.join(backup_dir, name))
