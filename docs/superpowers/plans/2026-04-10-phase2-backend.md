# Phase 2 — Backend Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare tutti i servizi backend e le route FastAPI per rendere l'app funzionante senza frontend e senza auth.

**Architecture:** Servizi sync (sqlite3 + PIL) esposti via FastAPI; worker AI asincrono (asyncio) con rate limiter; coda AI persistita in SQLite. Nessun ORM, nessun server DB esterno.

**Tech Stack:** FastAPI, uvicorn, sqlite3, Pillow, piexif, pillow-heif, rawpy, httpx, apscheduler, google-generativeai, ollama, pytest, fastapi.testclient

---

## Prerequisiti

- Fase 1 completata: `config.py`, `database/`, `services/image_processor.py`, `services/exif_reader.py`, 96 test green.
- Venv attivo: `.venv/bin/pip install fastapi uvicorn[standard] httpx apscheduler pytest-asyncio`
- Run test suite: `.venv/bin/pytest` → 96 passed prima di iniziare.

---

## File Map

```
services/
  db_sync.py          # CREA — caricamento DB dal NAS + backup periodico
  scanner.py          # CREA — scan filesystem, deduplicazione, EXIF
  geocoder.py         # CREA — reverse geocoding Nominatim (async)
  ai/
    base.py           # CREA — AIEngine ABC + dataclass PhotoAnalysis
    gemini.py         # CREA — implementazione Gemini
    ollama.py         # CREA — implementazione Ollama
  queue_worker.py     # CREA — worker asyncio, rate limiter, retry
api/
  __init__.py         # già esiste (vuoto)
  settings.py         # CREA — GET/PUT /api/settings, POST /api/settings/test-ai
  folders.py          # CREA — GET/POST/PUT/DELETE /api/folders, POST rescan
  photos.py           # CREA — GET list/detail/image/thumbnail, PUT
  queue.py            # CREA — GET status, POST add/pause/resume, DELETE
main.py               # MODIFICA — app completa, startup, /health
tests/
  test_db_sync.py     # CREA
  test_scanner.py     # CREA
  test_geocoder.py    # CREA
  test_ai_base.py     # CREA
  test_queue_worker.py # CREA
  test_api_settings.py # CREA
  test_api_folders.py  # CREA
  test_api_photos.py   # CREA
  test_api_queue.py    # CREA
  test_main.py         # CREA
```

---

## Task 1: services/db_sync.py

**Files:**
- Create: `services/db_sync.py`
- Create: `tests/test_db_sync.py`

### Interfaccia pubblica

```python
def load_db_from_nas(local_db: str = None, remote_db: str = None) -> bool
    """Copia REMOTE_DB → LOCAL_DB se esiste. Ritorna True se copiato."""

def backup_db_to_nas(local_db: str = None, remote_db: str = None,
                     backup_dir: str = None) -> None
    """Backup atomico LOCAL_DB → REMOTE_DB + copia datata in backup_dir."""

def prune_old_backups(backup_dir: str, keep: int = 10) -> None
    """Elimina i backup più vecchi, conserva solo gli ultimi `keep`."""
```

- [ ] **Step 1.1: Installa dipendenza**
```bash
.venv/bin/pip install apscheduler
```

- [ ] **Step 1.2: Scrivi il test (RED)**

Crea `tests/test_db_sync.py`:
```python
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
            time.sleep(0.01)  # mtime diverso
        prune_old_backups(backup_dir, keep=3)
        remaining = sorted(os.listdir(backup_dir))
        # Devono restare i 3 più recenti (nomi più grandi alfabeticamente)
        assert remaining == sorted(names)[-3:]
```

- [ ] **Step 1.3: Verifica RED**
```bash
.venv/bin/pytest tests/test_db_sync.py -v --tb=no -q
```
Atteso: tutti FAILED con `ModuleNotFoundError: No module named 'services.db_sync'`

- [ ] **Step 1.4: Implementa `services/db_sync.py`**
```python
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

    os.makedirs(os.path.dirname(local), exist_ok=True)
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

    os.makedirs(os.path.dirname(remote), exist_ok=True)
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
        [f for f in os.listdir(backup_dir) if f.endswith(".db")]
    )
    to_delete = files[:-keep] if len(files) > keep else []
    for name in to_delete:
        os.remove(os.path.join(backup_dir, name))
```

- [ ] **Step 1.5: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_db_sync.py -v
```
Atteso: tutti PASSED

- [ ] **Step 1.6: Verifica suite completa**
```bash
.venv/bin/pytest --tb=short -q
```
Atteso: 0 failed

- [ ] **Step 1.7: Commit**
```bash
git add services/db_sync.py tests/test_db_sync.py
git commit -m "feat: services/db_sync — caricamento DB da NAS e backup atomico"
```

---

## Task 2: services/scanner.py

**Files:**
- Create: `services/scanner.py`
- Create: `tests/test_scanner.py`

### Interfaccia pubblica

```python
@dataclass
class ScanResult:
    new: int           # foto nuove inserite nel DB
    skipped: int       # già presenti (stesso path+size+date)
    errors: int        # file non leggibili
    new_photo_ids: list[int]

def scan_folder(folder_path: str, db_path: str = None) -> ScanResult
```

- [ ] **Step 2.1: Scrivi il test (RED)**

Crea `tests/test_scanner.py`:
```python
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
```

- [ ] **Step 2.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_scanner.py -v --tb=no -q
```
Atteso: tutti FAILED

- [ ] **Step 2.3: Implementa `services/scanner.py`**
```python
"""
Scan del filesystem per indicizzare foto nel DB (§6.2).
- Ricorsivo nelle sottocartelle
- Deduplicazione: skip se stesso file_path + file_size + exif_date
- Chiama exif_reader per estrarre metadati
"""
import os
from dataclasses import dataclass, field
from typing import Optional

from database.photos import insert_photo, get_photos, count_photos
from services.exif_reader import read_exif
import config

# Estensioni supportate (minuscolo)
SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".heic", ".heif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2",
    ".png",
}

_EXT_TO_FORMAT = {
    ".jpg": "jpg", ".jpeg": "jpg",
    ".heic": "heic", ".heif": "heic",
    ".cr2": "raw", ".cr3": "raw", ".nef": "raw",
    ".arw": "raw", ".dng": "raw", ".orf": "raw", ".rw2": "raw",
    ".png": "png",
}


@dataclass
class ScanResult:
    new: int = 0
    skipped: int = 0
    errors: int = 0
    new_photo_ids: list = field(default_factory=list)


def scan_folder(folder_path: str, db_path: Optional[str] = None) -> ScanResult:
    """
    Scansiona ricorsivamente folder_path.
    Inserisce nel DB i nuovi file; skippa quelli già indicizzati
    con stesso path + size + exif_date.
    Ritorna un ScanResult con i contatori.
    """
    result = ScanResult()

    # Indice veloce dei file già presenti: file_path → (file_size, exif_date)
    existing = {
        row["file_path"]: (row["file_size"], row["exif_date"])
        for row in get_photos(db_path, folder_path=folder_path, limit=100000)
    }

    for dirpath, _, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTS:
                continue

            abs_path = os.path.join(dirpath, fname)
            try:
                current_size = os.path.getsize(abs_path)
                meta = read_exif(abs_path)
                current_date = meta.get("exif_date")

                # Deduplicazione
                if abs_path in existing:
                    prev_size, prev_date = existing[abs_path]
                    if prev_size == current_size and prev_date == current_date:
                        result.skipped += 1
                        continue

                photo_id = insert_photo(
                    db_path,
                    file_path=abs_path,
                    folder_path=folder_path,
                    filename=fname,
                    format=_EXT_TO_FORMAT.get(ext, ext.lstrip(".")),
                    file_size=current_size,
                    width=meta.get("width"),
                    height=meta.get("height"),
                    exif_date=current_date,
                    camera_make=meta.get("camera_make"),
                    camera_model=meta.get("camera_model"),
                    lens_model=meta.get("lens_model"),
                    focal_length=meta.get("focal_length"),
                    aperture=meta.get("aperture"),
                    shutter_speed=meta.get("shutter_speed"),
                    iso=meta.get("iso"),
                    latitude=meta.get("latitude"),
                    longitude=meta.get("longitude"),
                    location_source="exif" if meta.get("latitude") else None,
                )
                result.new += 1
                result.new_photo_ids.append(photo_id)

            except Exception:
                result.errors += 1

    return result
```

- [ ] **Step 2.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_scanner.py -v
```
Atteso: tutti PASSED

- [ ] **Step 2.5: Verifica suite completa**
```bash
.venv/bin/pytest --tb=short -q
```
Atteso: 0 failed

- [ ] **Step 2.6: Commit**
```bash
git add services/scanner.py tests/test_scanner.py
git commit -m "feat: services/scanner — indicizzazione filesystem con deduplicazione"
```

---

## Task 3: services/geocoder.py

**Files:**
- Create: `services/geocoder.py`
- Create: `tests/test_geocoder.py`

### Interfaccia pubblica

```python
async def reverse_geocode(lat: float, lon: float) -> Optional[str]
    """Chiama Nominatim e ritorna 'Città, Paese' o None."""
```

- [ ] **Step 3.1: Installa dipendenza**
```bash
.venv/bin/pip install httpx pytest-asyncio
```

Aggiorna `pytest.ini` — rimuovi `asyncio_mode = auto` e aggiungi (già presente ma non funzionava senza pytest-asyncio):
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
```

- [ ] **Step 3.2: Scrivi il test (RED)**

Crea `tests/test_geocoder.py`:
```python
"""
Test per services/geocoder.py.
Nominatim è un servizio esterno: lo mocker con pytest monkeypatch su httpx.
"""
import pytest
import httpx


class TestReverseGeocode:
    async def test_returns_city_country(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(url, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self):
                    return {
                        "address": {
                            "city": "Roma",
                            "country": "Italia",
                        }
                    }
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(41.9028, 12.4964)
        assert result == "Roma, Italia"

    async def test_returns_none_on_http_error(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(url, **kwargs):
            raise httpx.RequestError("timeout", request=None)

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(0.0, 0.0)
        assert result is None

    async def test_returns_none_when_no_city(self, monkeypatch):
        from services.geocoder import reverse_geocode

        async def mock_get(url, **kwargs):
            class FakeResp:
                status_code = 200
                def json(self):
                    return {"address": {}}  # nessuna città
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        result = await reverse_geocode(0.0, 0.0)
        assert result is None

    async def test_uses_correct_nominatim_url(self, monkeypatch):
        from services.geocoder import reverse_geocode
        captured = {}

        async def mock_get(url, **kwargs):
            captured["url"] = url
            class FakeResp:
                status_code = 200
                def json(self): return {"address": {"city": "X", "country": "Y"}}
                def raise_for_status(self): pass
            return FakeResp()

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        await reverse_geocode(45.0, 9.0)
        assert "nominatim.openstreetmap.org" in captured["url"]
        assert "45.0" in captured["url"]
        assert "9.0" in captured["url"]
```

- [ ] **Step 3.3: Verifica RED**
```bash
.venv/bin/pytest tests/test_geocoder.py -v --tb=no -q
```
Atteso: tutti FAILED

- [ ] **Step 3.4: Implementa `services/geocoder.py`**
```python
"""
Reverse geocoding tramite Nominatim/OSM (gratuito, §6.4).
Ritorna una stringa "Città, Paese" o None.
User-Agent obbligatorio per Nominatim (policy OSM).
"""
from typing import Optional
import httpx

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_HEADERS = {"User-Agent": "PhotoAIManager/1.0 (personal-use)"}
_TIMEOUT = 10.0


async def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """
    Chiama Nominatim per ottenere il nome del luogo da coordinate.
    Ritorna 'Città, Paese' o None in caso di errore o risposta vuota.
    Il risultato deve essere cachato dal chiamante (nel DB photos).
    """
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
        "accept-language": "it",
    }
    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT) as client:
            resp = await client.get(_NOMINATIM_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    address = data.get("address", {})
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("county")
    )
    country = address.get("country")

    if not city and not country:
        return None
    if city and country:
        return f"{city}, {country}"
    return city or country
```

- [ ] **Step 3.5: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_geocoder.py -v
```
Atteso: tutti PASSED

- [ ] **Step 3.6: Verifica suite completa**
```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 3.7: Commit**
```bash
git add services/geocoder.py tests/test_geocoder.py pytest.ini
git commit -m "feat: services/geocoder — reverse geocoding Nominatim con mock"
```

---

## Task 4: services/ai/base.py

**Files:**
- Create: `services/ai/base.py`
- Create: `tests/test_ai_base.py`

Nessuna logica da testare (classe astratta + dataclass), ma verifichiamo che l'interfaccia sia corretta e non istanziabile direttamente.

- [ ] **Step 4.1: Scrivi il test (RED)**

Crea `tests/test_ai_base.py`:
```python
"""Test per services/ai/base.py — interfaccia astratta AIEngine."""
import pytest


class TestAIEngineInterface:
    def test_cannot_instantiate_directly(self):
        from services.ai.base import AIEngine
        with pytest.raises(TypeError):
            AIEngine()

    def test_concrete_subclass_must_implement_analyze(self):
        from services.ai.base import AIEngine

        class Incomplete(AIEngine):
            async def embed(self, text): return []

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass_must_implement_embed(self):
        from services.ai.base import AIEngine

        class Incomplete(AIEngine):
            async def analyze(self, image_bytes, location_hint=""): ...

        with pytest.raises(TypeError):
            Incomplete()

    def test_complete_subclass_instantiates(self):
        from services.ai.base import AIEngine

        class Complete(AIEngine):
            async def analyze(self, image_bytes, location_hint=""): ...
            async def embed(self, text): return []

        engine = Complete()
        assert engine is not None


class TestPhotoAnalysis:
    def test_overall_score_formula(self):
        from services.ai.base import PhotoAnalysis
        a = PhotoAnalysis(
            description="Test",
            technical_score=7.0,
            aesthetic_score=9.0,
            subject="paesaggio",
            atmosphere="serena",
            colors=["blu", "verde"],
            strengths="buona luce",
            weaknesses=None,
            ai_engine="gemini",
        )
        # overall = round(0.35*7 + 0.65*9, 1) = round(2.45 + 5.85, 1) = 8.3
        assert a.overall_score == pytest.approx(8.3, abs=0.05)

    def test_overall_score_computed_at_init(self):
        from services.ai.base import PhotoAnalysis
        a = PhotoAnalysis(
            description="x", technical_score=5.0, aesthetic_score=5.0,
            subject="x", atmosphere="x", colors=[], strengths="x",
            weaknesses=None, ai_engine="gemini",
        )
        assert a.overall_score == pytest.approx(5.0, abs=0.05)
```

- [ ] **Step 4.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_ai_base.py -v --tb=no -q
```

- [ ] **Step 4.3: Implementa `services/ai/base.py`**
```python
"""
Interfaccia astratta per i motori AI (§6.5, §6.6).
Gemini e Ollama implementano AIEngine.
PhotoAnalysis è il dataclass di ritorno da analyze().
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PhotoAnalysis:
    """Risultato strutturato dell'analisi visiva AI di una foto."""
    description: str
    technical_score: float          # 1-10
    aesthetic_score: float          # 1-10
    subject: str                    # soggetto principale (3-5 parole)
    atmosphere: str                 # una parola (romantica, serena, …)
    colors: list                    # colori dominanti
    strengths: str
    weaknesses: Optional[str]
    ai_engine: str                  # 'gemini' | 'ollama'

    # Campi facoltativi (riconoscimento luogo)
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Calcolato automaticamente alla creazione
    overall_score: float = field(init=False)

    def __post_init__(self):
        # Formula §6.6: overall = round(0.35*T + 0.65*E, 1)
        self.overall_score = round(
            0.35 * self.technical_score + 0.65 * self.aesthetic_score, 1
        )


class AIEngine(ABC):
    """
    Interfaccia astratta per motori AI di analisi fotografica.
    Implementata da GeminiEngine (services/ai/gemini.py)
    e OllamaEngine (services/ai/ollama.py).
    """

    @abstractmethod
    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        """
        Analizza un'immagine JPEG (bytes) e ritorna un PhotoAnalysis.
        location_hint: stringa opzionale con il nome del luogo noto
                       (usata nel prompt se la foto ha location_source='exif').
        """

    @abstractmethod
    async def embed(self, text: str) -> list:
        """
        Genera l'embedding vettoriale di un testo.
        Ritorna una lista di float (768 dimensioni per text-embedding-004).
        """
```

- [ ] **Step 4.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_ai_base.py -v
```

- [ ] **Step 4.5: Commit**
```bash
git add services/ai/base.py tests/test_ai_base.py
git commit -m "feat: services/ai/base — AIEngine ABC e PhotoAnalysis dataclass"
```

---

## Task 5: services/ai/gemini.py

**Files:**
- Create: `services/ai/gemini.py`
- Create: `tests/test_ai_gemini.py`

I test reali verso Gemini sono skippati senza API key. Il focus è sul parsing del JSON e sulla gestione degli errori.

- [ ] **Step 5.1: Installa dipendenza**
```bash
.venv/bin/pip install google-generativeai
```

- [ ] **Step 5.2: Scrivi il test (RED)**

Crea `tests/test_ai_gemini.py`:
```python
"""
Test per services/ai/gemini.py.
I test di integrazione reale sono skippati se GEMINI_API_KEY non è impostata.
I test di parsing usano mock.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


VALID_JSON_RESPONSE = json.dumps({
    "descrizione": "Un paesaggio montano al tramonto.",
    "punteggio_tecnico": 8,
    "punteggio_estetico": 9,
    "soggetto": "montagna al tramonto",
    "atmosfera": "romantica",
    "colori_dominanti": ["arancione", "viola", "blu"],
    "punti_di_forza": "Ottima luce dorata.",
    "punti_di_debolezza": None,
    "luogo_riconosciuto": None,
    "luogo_lat": None,
    "luogo_lon": None,
})


class TestParseAiResponse:
    def test_parses_valid_json(self):
        from services.ai.gemini import _parse_response
        result = _parse_response(VALID_JSON_RESPONSE)
        assert result["descrizione"] == "Un paesaggio montano al tramonto."
        assert result["punteggio_tecnico"] == 8
        assert result["colori_dominanti"] == ["arancione", "viola", "blu"]

    def test_strips_markdown_fences(self):
        from services.ai.gemini import _parse_response
        wrapped = f"```json\n{VALID_JSON_RESPONSE}\n```"
        result = _parse_response(wrapped)
        assert result["punteggio_estetico"] == 9

    def test_raises_on_invalid_json(self):
        from services.ai.gemini import _parse_response
        with pytest.raises(ValueError):
            _parse_response("non è json")

    def test_raises_on_missing_required_field(self):
        from services.ai.gemini import _parse_response
        incomplete = json.dumps({"descrizione": "solo questo"})
        with pytest.raises(ValueError):
            _parse_response(incomplete)


class TestBuildPrompt:
    def test_prompt_without_location(self):
        from services.ai.gemini import _build_prompt
        prompt = _build_prompt(location_hint="")
        assert "JSON" in prompt
        assert "luogo_riconosciuto" in prompt
        assert "[SE DISPONIBILE" not in prompt

    def test_prompt_with_location(self):
        from services.ai.gemini import _build_prompt
        prompt = _build_prompt(location_hint="Venezia, Italia")
        assert "Venezia, Italia" in prompt


class TestGeminiEngineInterface:
    def test_implements_aiengine(self):
        from services.ai.gemini import GeminiEngine
        from services.ai.base import AIEngine
        assert issubclass(GeminiEngine, AIEngine)

    def test_requires_api_key(self):
        from services.ai.gemini import GeminiEngine
        with pytest.raises(ValueError, match="API key"):
            GeminiEngine(api_key="")
```

- [ ] **Step 5.3: Verifica RED**
```bash
.venv/bin/pytest tests/test_ai_gemini.py -v --tb=no -q
```

- [ ] **Step 5.4: Implementa `services/ai/gemini.py`**
```python
"""
Implementazione AIEngine per Google Gemini (§6.6).
Modelli: gemini-1.5-flash (visione), text-embedding-004 (embedding).
"""
import json
import re
from typing import Optional

import google.generativeai as genai

from services.ai.base import AIEngine, PhotoAnalysis

_REQUIRED_FIELDS = {
    "descrizione", "punteggio_tecnico", "punteggio_estetico",
    "soggetto", "atmosfera", "colori_dominanti",
    "punti_di_forza", "punti_di_debolezza",
    "luogo_riconosciuto", "luogo_lat", "luogo_lon",
}

_VISION_MODEL   = "gemini-1.5-flash"
_EMBED_MODEL    = "models/text-embedding-004"


class GeminiEngine(AIEngine):
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key Gemini obbligatoria")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(_VISION_MODEL)

    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        import asyncio
        prompt = _build_prompt(location_hint)
        image_part = {"mime_type": "image/jpeg", "data": image_bytes}
        # genai è sync — esegui in executor per non bloccare l'event loop
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: self._model.generate_content([prompt, image_part])
        )
        data = _parse_response(response.text)
        return PhotoAnalysis(
            description=data["descrizione"],
            technical_score=float(data["punteggio_tecnico"]),
            aesthetic_score=float(data["punteggio_estetico"]),
            subject=data["soggetto"],
            atmosphere=data["atmosfera"],
            colors=data["colori_dominanti"] or [],
            strengths=data["punti_di_forza"] or "",
            weaknesses=data.get("punti_di_debolezza"),
            ai_engine="gemini",
            location_name=data.get("luogo_riconosciuto"),
            latitude=data.get("luogo_lat"),
            longitude=data.get("luogo_lon"),
        )

    async def embed(self, text: str) -> list:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: genai.embed_content(
                model=_EMBED_MODEL,
                content=text,
                task_type="retrieval_document",
            )
        )
        return result["embedding"]


def _build_prompt(location_hint: str) -> str:
    location_section = ""
    if location_hint:
        location_section = f"\n[SE DISPONIBILE: La foto è stata scattata a: {location_hint}]"

    return f"""Sei un critico fotografico esperto. Analizza questa fotografia e rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo aggiuntivo, nessun markdown, nessun delimitatore).

{{
  "descrizione": "Descrizione dettagliata in italiano, 3-5 frasi. Descrivi soggetto, composizione, luce, colori, atmosfera. Sii specifico e evocativo.",
  "punteggio_tecnico": <intero 1-10: messa a fuoco, esposizione corretta, rumore, nitidezza, bilanciamento bianco>,
  "punteggio_estetico": <intero 1-10: composizione, uso della luce, impatto emotivo, creatività, equilibrio visivo>,
  "soggetto": "<soggetto principale in 3-5 parole>",
  "atmosfera": "<una parola: es. romantica, drammatica, serena, malinconica, vivace, misteriosa>",
  "colori_dominanti": ["<colore1>", "<colore2>", "<colore3>"],
  "punti_di_forza": "<cosa funziona bene, 1-2 frasi>",
  "punti_di_debolezza": "<cosa potrebbe migliorare, 1-2 frasi, oppure null se non ci sono problemi evidenti>",
  "luogo_riconosciuto": "<nome del luogo specifico se riconoscibile, altrimenti null>",
  "luogo_lat": <latitudine approssimativa se luogo riconosciuto, altrimenti null>,
  "luogo_lon": <longitudine approssimativa se luogo riconosciuto, altrimenti null>
}}{location_section}

Scala di valutazione:
1-3: Foto con problemi tecnici/estetici significativi
4-5: Foto nella media, accettabile
6-7: Foto buona, sopra la media
8-9: Foto eccellente, da conservare
10: Capolavoro fotografico (rarissimo)"""


def _parse_response(text: str) -> dict:
    """
    Estrae il JSON dalla risposta del modello.
    Rimuove eventuali code fence markdown.
    Lancia ValueError se il JSON non è valido o mancano campi obbligatori.
    """
    # Rimuovi markdown code fences ```json ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Risposta AI non è JSON valido: {e}\nTesto: {text[:200]}") from e

    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Campi mancanti nella risposta AI: {missing}")

    return data
```

- [ ] **Step 5.5: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_ai_gemini.py -v
```

- [ ] **Step 5.6: Commit**
```bash
git add services/ai/gemini.py tests/test_ai_gemini.py
git commit -m "feat: services/ai/gemini — GeminiEngine con parsing JSON e prompt strutturato"
```

---

## Task 6: services/ai/ollama.py

**Files:**
- Create: `services/ai/ollama.py`
- Create: `tests/test_ai_ollama.py`

- [ ] **Step 6.1: Installa dipendenza**
```bash
.venv/bin/pip install ollama
```

- [ ] **Step 6.2: Scrivi il test (RED)**

Crea `tests/test_ai_ollama.py`:
```python
"""
Test per services/ai/ollama.py.
Ollama è locale: mock del client ollama.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

VALID_JSON = json.dumps({
    "descrizione": "Un gatto su un divano.",
    "punteggio_tecnico": 6,
    "punteggio_estetico": 7,
    "soggetto": "gatto su divano",
    "atmosfera": "serena",
    "colori_dominanti": ["grigio", "beige"],
    "punti_di_forza": "Buona composizione.",
    "punti_di_debolezza": None,
    "luogo_riconosciuto": None,
    "luogo_lat": None,
    "luogo_lon": None,
})


class TestOllamaEngineInterface:
    def test_implements_aiengine(self):
        from services.ai.ollama import OllamaEngine
        from services.ai.base import AIEngine
        assert issubclass(OllamaEngine, AIEngine)

    def test_instantiates_with_defaults(self):
        from services.ai.ollama import OllamaEngine
        engine = OllamaEngine()
        assert engine is not None

    def test_custom_models(self):
        from services.ai.ollama import OllamaEngine
        engine = OllamaEngine(
            vision_model="moondream",
            embed_model="nomic-embed-text",
            base_url="http://localhost:11434",
        )
        assert engine._vision_model == "moondream"


class TestOllamaAnalyze:
    async def test_returns_photo_analysis(self, monkeypatch):
        from services.ai.ollama import OllamaEngine
        from services.ai.base import PhotoAnalysis

        async def mock_chat(**kwargs):
            return {"message": {"content": VALID_JSON}}

        engine = OllamaEngine()
        monkeypatch.setattr(engine._client, "chat", mock_chat)
        result = await engine.analyze(b"fake_jpeg_bytes")
        assert isinstance(result, PhotoAnalysis)
        assert result.technical_score == 6
        assert result.ai_engine == "ollama"


class TestOllamaEmbed:
    async def test_returns_list_of_floats(self, monkeypatch):
        from services.ai.ollama import OllamaEngine

        async def mock_embeddings(**kwargs):
            return {"embedding": [0.1, 0.2, 0.3]}

        engine = OllamaEngine()
        monkeypatch.setattr(engine._client, "embeddings", mock_embeddings)
        result = await engine.embed("testo di prova")
        assert isinstance(result, list)
        assert result[0] == pytest.approx(0.1)
```

- [ ] **Step 6.3: Verifica RED**
```bash
.venv/bin/pytest tests/test_ai_ollama.py -v --tb=no -q
```

- [ ] **Step 6.4: Implementa `services/ai/ollama.py`**
```python
"""
Implementazione AIEngine per Ollama locale (§3).
Modelli default: llava (visione), nomic-embed-text (embedding).
Nessun rate limit: elaborazione continua.
"""
import base64
import json
from typing import Optional

import ollama

from services.ai.base import AIEngine, PhotoAnalysis
from services.ai.gemini import _build_prompt, _parse_response

_DEFAULT_VISION_MODEL = "llava"
_DEFAULT_EMBED_MODEL  = "nomic-embed-text"
_DEFAULT_BASE_URL     = "http://localhost:11434"


class OllamaEngine(AIEngine):
    def __init__(
        self,
        vision_model: str = _DEFAULT_VISION_MODEL,
        embed_model: str = _DEFAULT_EMBED_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
    ):
        self._vision_model = vision_model
        self._embed_model  = embed_model
        self._client = ollama.AsyncClient(host=base_url)

    async def analyze(
        self,
        image_bytes: bytes,
        location_hint: str = "",
    ) -> PhotoAnalysis:
        prompt = _build_prompt(location_hint)
        img_b64 = base64.b64encode(image_bytes).decode()

        response = await self._client.chat(
            model=self._vision_model,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [img_b64],
            }],
        )
        text = response["message"]["content"]
        data = _parse_response(text)

        return PhotoAnalysis(
            description=data["descrizione"],
            technical_score=float(data["punteggio_tecnico"]),
            aesthetic_score=float(data["punteggio_estetico"]),
            subject=data["soggetto"],
            atmosphere=data["atmosfera"],
            colors=data["colori_dominanti"] or [],
            strengths=data["punti_di_forza"] or "",
            weaknesses=data.get("punti_di_debolezza"),
            ai_engine="ollama",
            location_name=data.get("luogo_riconosciuto"),
            latitude=data.get("luogo_lat"),
            longitude=data.get("luogo_lon"),
        )

    async def embed(self, text: str) -> list:
        response = await self._client.embeddings(
            model=self._embed_model,
            prompt=text,
        )
        return response["embedding"]
```

- [ ] **Step 6.5: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_ai_ollama.py -v
```

- [ ] **Step 6.6: Commit**
```bash
git add services/ai/ollama.py tests/test_ai_ollama.py
git commit -m "feat: services/ai/ollama — OllamaEngine per analisi locale senza rate limit"
```

---

## Task 7: services/queue_worker.py

**Files:**
- Create: `services/queue_worker.py`
- Create: `tests/test_queue_worker.py`

Il worker processa la coda AI: prende il prossimo `pending`, chiama `prepare_for_ai` + `engine.analyze` + `engine.embed`, salva nel DB, attende il rate limit.

- [ ] **Step 7.1: Scrivi il test (RED)**

Crea `tests/test_queue_worker.py`:
```python
"""
Test per services/queue_worker.py.
Usa un AIEngine fake per non chiamare API reali.
"""
import json
import pytest
from PIL import Image
import io
from unittest.mock import AsyncMock

from services.ai.base import AIEngine, PhotoAnalysis


def make_fake_engine() -> AIEngine:
    """Engine mock che ritorna sempre la stessa analisi."""
    class FakeEngine(AIEngine):
        async def analyze(self, image_bytes, location_hint=""):
            return PhotoAnalysis(
                description="Foto di test",
                technical_score=7.0,
                aesthetic_score=8.0,
                subject="oggetto test",
                atmosphere="serena",
                colors=["rosso", "blu"],
                strengths="buona",
                weaknesses=None,
                ai_engine="fake",
            )
        async def embed(self, text):
            return [0.1] * 768
    return FakeEngine()


def make_jpeg_file(tmp_path, name: str = "test.jpg") -> str:
    path = str(tmp_path / name)
    Image.new("RGB", (100, 100), (200, 100, 50)).save(path, "JPEG")
    return path


class TestQueueWorkerProcessNext:
    async def test_processes_pending_item(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo
        from database.queue import add_to_queue, get_queue_item

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        qid = add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        processed = await worker.process_next()

        assert processed is True
        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "done"

    async def test_saves_analysis_to_photo(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        assert photo["description"] == "Foto di test"
        assert photo["technical_score"] == 7.0
        assert photo["analyzed_at"] is not None

    async def test_saves_embedding(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker
        from database.photos import insert_photo, get_photo_by_id
        from database.queue import add_to_queue

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        add_to_queue(tmp_db, photo_id=pid)
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        await worker.process_next()

        photo = get_photo_by_id(tmp_db, pid)
        embedding = json.loads(photo["embedding"])
        assert len(embedding) == 768

    async def test_returns_false_when_queue_empty(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db,
                             rpm_limit=None)
        processed = await worker.process_next()
        assert processed is False

    async def test_marks_error_after_max_attempts(self, tmp_path, tmp_db):
        from services.queue_worker import QueueWorker, MAX_ATTEMPTS
        from database.photos import insert_photo
        from database.queue import add_to_queue, get_queue_item

        class FailingEngine(AIEngine):
            async def analyze(self, image_bytes, location_hint=""):
                raise RuntimeError("API error")
            async def embed(self, text): return []

        photo_path = make_jpeg_file(tmp_path)
        pid = insert_photo(tmp_db,
                           file_path=photo_path,
                           folder_path=str(tmp_path),
                           filename="test.jpg",
                           format="jpg",
                           file_size=100,
                           width=100,
                           height=100)
        qid = add_to_queue(tmp_db, photo_id=pid)

        worker = QueueWorker(engine=FailingEngine(), db_path=tmp_db,
                             rpm_limit=None)
        # Chiama MAX_ATTEMPTS volte
        for _ in range(MAX_ATTEMPTS):
            await worker.process_next()

        item = get_queue_item(tmp_db, qid)
        assert item["status"] == "error"
        assert item["attempts"] == MAX_ATTEMPTS


class TestQueueWorkerPauseResume:
    def test_initial_state_not_running(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db)
        assert worker.is_running is False
        assert worker.is_paused is False

    def test_pause_sets_flag(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db)
        worker.pause()
        assert worker.is_paused is True

    def test_resume_clears_flag(self, tmp_db):
        from services.queue_worker import QueueWorker
        worker = QueueWorker(engine=make_fake_engine(), db_path=tmp_db)
        worker.pause()
        worker.resume()
        assert worker.is_paused is False
```

- [ ] **Step 7.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_queue_worker.py -v --tb=no -q
```

- [ ] **Step 7.3: Implementa `services/queue_worker.py`**
```python
"""
Worker asincrono per la coda di analisi AI (§6.5).
- Un solo job alla volta (nessuna concorrenza verso l'AI)
- Rate limiter configurabile (default 12 RPM per Gemini gratuito)
- Retry automatico fino a MAX_ATTEMPTS
- Sopravvive ai riavvii: reset_stale_processing() all'avvio
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Optional

from services.ai.base import AIEngine
from services.image_processor import prepare_for_ai
from database.queue import (
    get_next_pending, update_queue_status,
    increment_attempts, get_queue_item, reset_stale_processing,
)
from database.photos import get_photo_by_id, update_photo
import config

MAX_ATTEMPTS = 3


class QueueWorker:
    """
    Worker che consuma la coda analysis_queue.
    Chiamare start() per avviare il loop asincrono,
    stop() per fermarsi, pause()/resume() per sospendere.
    """

    def __init__(
        self,
        engine: AIEngine,
        db_path: Optional[str] = None,
        rpm_limit: Optional[int] = None,
    ):
        self._engine   = engine
        self._db_path  = db_path
        self._rpm      = rpm_limit  # None = nessun limite (Ollama)
        self.is_running = False
        self.is_paused  = False
        self._task: Optional[asyncio.Task] = None
        self.current_photo_name: Optional[str] = None

    async def start(self) -> None:
        """Avvia il loop del worker in background."""
        self.is_running = True
        reset_stale_processing(self._db_path)
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Ferma il worker."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def pause(self) -> None:
        self.is_paused = True

    def resume(self) -> None:
        self.is_paused = False

    async def process_next(self) -> bool:
        """
        Processa il prossimo item pending dalla coda.
        Ritorna True se ha processato qualcosa, False se la coda era vuota.
        """
        item = get_next_pending(self._db_path)
        if item is None:
            return False

        qid      = item["id"]
        photo_id = item["photo_id"]
        attempts = item["attempts"]

        # Skippa se ha già raggiunto il limite tentativi
        if attempts >= MAX_ATTEMPTS:
            update_queue_status(self._db_path, qid, "error",
                                error_msg="Superato limite tentativi")
            return True

        photo = get_photo_by_id(self._db_path, photo_id)
        if photo is None:
            update_queue_status(self._db_path, qid, "error",
                                error_msg="Foto non trovata nel DB")
            return True

        update_queue_status(self._db_path, qid, "processing")
        self.current_photo_name = photo["filename"]

        try:
            # Prepara immagine per AI
            image_bytes = prepare_for_ai(photo["file_path"])

            # Location hint se disponibile
            location_hint = photo["location_name"] or ""

            # Analisi AI
            analysis = await self._engine.analyze(image_bytes, location_hint)

            # Embedding: testo = descrizione + soggetto + atmosfera + luogo
            embed_text = " ".join(filter(None, [
                analysis.description,
                analysis.subject,
                analysis.atmosphere,
                analysis.location_name or photo["location_name"],
            ]))
            embedding = await self._engine.embed(embed_text)

            # Aggiorna la foto nel DB
            update_photo(
                self._db_path,
                photo_id,
                description=analysis.description,
                technical_score=analysis.technical_score,
                aesthetic_score=analysis.aesthetic_score,
                overall_score=analysis.overall_score,
                subject=analysis.subject,
                atmosphere=analysis.atmosphere,
                colors=json.dumps(analysis.colors, ensure_ascii=False),
                strengths=analysis.strengths,
                weaknesses=analysis.weaknesses,
                ai_engine=analysis.ai_engine,
                embedding=json.dumps(embedding),
                analyzed_at=datetime.now().isoformat(timespec="seconds"),
            )

            # Se l'AI ha riconosciuto un luogo e la foto non ne aveva uno
            if analysis.location_name and not photo["location_name"]:
                update_photo(
                    self._db_path,
                    photo_id,
                    location_name=analysis.location_name,
                    latitude=analysis.latitude,
                    longitude=analysis.longitude,
                    location_source="ai",
                )

            update_queue_status(self._db_path, qid, "done")

        except Exception as e:
            increment_attempts(self._db_path, qid)
            current = get_queue_item(self._db_path, qid)
            if current["attempts"] >= MAX_ATTEMPTS:
                update_queue_status(self._db_path, qid, "error",
                                    error_msg=str(e)[:500])
            else:
                update_queue_status(self._db_path, qid, "pending")

        finally:
            self.current_photo_name = None

        return True

    async def _run_loop(self) -> None:
        """Loop principale: consuma la coda rispettando il rate limit."""
        while self.is_running:
            if self.is_paused:
                await asyncio.sleep(2)
                continue

            t_start = time.monotonic()
            processed = await self.process_next()

            if not processed:
                await asyncio.sleep(5)  # coda vuota: riprova tra 5s
                continue

            if self._rpm:
                # Rispetta il rate limit: attendi il tempo residuo nel minuto
                elapsed = time.monotonic() - t_start
                interval = 60.0 / self._rpm
                wait = max(0.0, interval - elapsed)
                if wait > 0:
                    await asyncio.sleep(wait)
```

- [ ] **Step 7.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_queue_worker.py -v
```

- [ ] **Step 7.5: Verifica suite completa**
```bash
.venv/bin/pytest --tb=short -q
```

- [ ] **Step 7.6: Commit**
```bash
git add services/queue_worker.py tests/test_queue_worker.py
git commit -m "feat: services/queue_worker — worker AI asincrono con retry e rate limit"
```

---

## Task 8: main.py skeleton + /health

**Files:**
- Modify: `main.py`
- Create: `tests/test_main.py`

Costruisci l'app FastAPI minimale con `/health` e la logica di startup. Le route API vengono aggiunte nei task successivi.

- [ ] **Step 8.1: Installa dipendenze**
```bash
.venv/bin/pip install fastapi uvicorn httpx
```

- [ ] **Step 8.2: Scrivi il test (RED)**

Crea `tests/test_main.py`:
```python
"""Test per main.py — /health e startup."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient con DB temporaneo."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app)


class TestHealthEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_has_status_field(self, client):
        data = client.get("/health").json()
        assert "status" in data

    def test_has_version(self, client):
        data = client.get("/health").json()
        assert "version" in data

    def test_has_uptime(self, client):
        data = client.get("/health").json()
        assert "uptime_s" in data
        assert isinstance(data["uptime_s"], (int, float))
```

- [ ] **Step 8.3: Verifica RED**
```bash
.venv/bin/pytest tests/test_main.py -v --tb=no -q
```

- [ ] **Step 8.4: Implementa `main.py`**
```python
"""
Entry point FastAPI — Photo AI Manager.
Avvia il server con: uvicorn main:app --host 0.0.0.0 --port 8080
"""
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from database.models import init_db

START_TIME = time.time()

app = FastAPI(
    title="Photo AI Manager",
    version=config.APP_VERSION,
    docs_url="/api/docs",
)

# Startup: inizializza il DB locale
@app.on_event("startup")
async def on_startup():
    Path(config.LOCAL_DB).parent.mkdir(parents=True, exist_ok=True)
    init_db(config.LOCAL_DB)


@app.get("/health", tags=["system"])
async def health():
    """Readiness check usato dallo script di deploy (§16)."""
    db_ok  = Path(config.LOCAL_DB).exists()
    nas_ok = Path(config.APP_DATA_PATH).exists()
    return {
        "status":   "ok" if (db_ok and nas_ok) else "degraded",
        "db":       "ok" if db_ok  else "missing",
        "nas":      "ok" if nas_ok else "not_mounted",
        "version":  config.APP_VERSION,
        "uptime_s": int(time.time() - START_TIME),
    }
```

- [ ] **Step 8.5: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_main.py -v
```

- [ ] **Step 8.6: Commit**
```bash
git add main.py tests/test_main.py
git commit -m "feat: main.py — FastAPI app skeleton con /health endpoint"
```

---

## Task 9: api/settings.py

**Files:**
- Create: `api/settings.py`
- Create: `tests/test_api_settings.py`

- [ ] **Step 9.1: Scrivi il test (RED)**

Crea `tests/test_api_settings.py`:
```python
"""Test per api/settings.py — GET/PUT /api/settings."""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app)


class TestGetSettings:
    def test_returns_200(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200

    def test_returns_dict(self, client):
        data = client.get("/api/settings").json()
        assert isinstance(data, dict)


class TestPutSettings:
    def test_saves_ai_engine(self, client):
        client.put("/api/settings", json={"ai_engine": "ollama"})
        data = client.get("/api/settings").json()
        assert data.get("ai_engine") == "ollama"

    def test_saves_multiple_keys(self, client):
        client.put("/api/settings", json={
            "ai_engine": "gemini",
            "analysis_rpm_limit": "12",
        })
        data = client.get("/api/settings").json()
        assert data["ai_engine"] == "gemini"
        assert data["analysis_rpm_limit"] == "12"

    def test_returns_200(self, client):
        resp = client.put("/api/settings", json={"ai_engine": "gemini"})
        assert resp.status_code == 200
```

- [ ] **Step 9.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_api_settings.py -v --tb=no -q
```

- [ ] **Step 9.3: Implementa `api/settings.py` e aggiungi router a `main.py`**

`api/settings.py`:
```python
"""Route /api/settings — lettura e aggiornamento impostazioni app."""
from fastapi import APIRouter
from database.settings import get_all_settings, set_setting
import config

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings():
    """Ritorna tutte le impostazioni come dizionario."""
    return get_all_settings(config.LOCAL_DB)


@router.put("")
def put_settings(body: dict):
    """Aggiorna le impostazioni ricevute. Valori come stringhe."""
    for key, value in body.items():
        set_setting(config.LOCAL_DB, key=key, value=str(value))
    return {"ok": True}
```

Aggiorna `main.py` aggiungendo dopo `START_TIME = time.time()`:
```python
from api.settings import router as settings_router
```
E dopo la definizione di `app`:
```python
app.include_router(settings_router)
```

- [ ] **Step 9.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_api_settings.py -v
```

- [ ] **Step 9.5: Commit**
```bash
git add api/settings.py main.py tests/test_api_settings.py
git commit -m "feat: api/settings — GET/PUT /api/settings"
```

---

## Task 10: api/folders.py

**Files:**
- Create: `api/folders.py`
- Create: `tests/test_api_folders.py`

- [ ] **Step 10.1: Scrivi il test (RED)**

Crea `tests/test_api_folders.py`:
```python
"""Test per api/folders.py."""
import os
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    init_db(db)
    from main import app
    return TestClient(app), tmp_path


def make_photo_dir(tmp_path):
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    Image.new("RGB", (100, 80)).save(str(photo_dir / "a.jpg"), "JPEG")
    Image.new("RGB", (100, 80)).save(str(photo_dir / "b.jpg"), "JPEG")
    return str(photo_dir)


class TestGetFolders:
    def test_empty_list(self, client):
        c, _ = client
        resp = c.get("/api/folders")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_added_folder(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        folders = c.get("/api/folders").json()
        assert len(folders) == 1
        assert folders[0]["folder_path"] == photo_dir


class TestScanFolder:
    def test_returns_scan_result(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        resp = c.post("/api/folders/scan", json={"folder_path": photo_dir})
        assert resp.status_code == 200
        data = resp.json()
        assert data["new"] == 2

    def test_folder_created_in_db(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        folders = c.get("/api/folders").json()
        assert any(f["folder_path"] == photo_dir for f in folders)

    def test_nonexistent_path_returns_400(self, client):
        c, _ = client
        resp = c.post("/api/folders/scan",
                      json={"folder_path": "/nonexistent/path/xyz"})
        assert resp.status_code == 400

    def test_rescan_updates_counts(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        # Aggiungi una nuova foto
        Image.new("RGB", (50, 50)).save(str(tmp_path / "photos" / "c.jpg"), "JPEG")
        resp = c.post(f"/api/folders/rescan",
                      json={"folder_path": photo_dir})
        assert resp.status_code == 200
        data = resp.json()
        assert data["new"] == 1


class TestPutFolder:
    def test_update_display_name(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        resp = c.put("/api/folders/meta",
                     json={"folder_path": photo_dir,
                           "display_name": "Le Mie Foto"})
        assert resp.status_code == 200
        folders = c.get("/api/folders").json()
        assert folders[0]["display_name"] == "Le Mie Foto"


class TestDeleteFolder:
    def test_removes_from_list(self, client):
        c, tmp_path = client
        photo_dir = make_photo_dir(tmp_path)
        c.post("/api/folders/scan", json={"folder_path": photo_dir})
        resp = c.delete("/api/folders",
                        json={"folder_path": photo_dir})
        assert resp.status_code == 200
        assert c.get("/api/folders").json() == []
```

- [ ] **Step 10.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_api_folders.py -v --tb=no -q
```

- [ ] **Step 10.3: Implementa `api/folders.py`**
```python
"""Route /api/folders."""
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.folders import (
    get_all_folders, insert_folder, get_folder_by_path,
    update_folder, update_folder_counts, delete_folder,
)
from services.scanner import scan_folder
import config

router = APIRouter(prefix="/api/folders", tags=["folders"])


class ScanRequest(BaseModel):
    folder_path: str
    display_name: Optional[str] = None
    default_location_name: Optional[str] = None
    default_latitude: Optional[float] = None
    default_longitude: Optional[float] = None
    auto_analyze: int = 0


class FolderUpdateRequest(BaseModel):
    folder_path: str
    display_name: Optional[str] = None
    default_location_name: Optional[str] = None
    default_latitude: Optional[float] = None
    default_longitude: Optional[float] = None
    auto_analyze: Optional[int] = None


class FolderDeleteRequest(BaseModel):
    folder_path: str


@router.get("")
def list_folders():
    return [dict(f) for f in get_all_folders(config.LOCAL_DB)]


@router.post("/scan")
def scan_and_add_folder(req: ScanRequest):
    if not os.path.isdir(req.folder_path):
        raise HTTPException(status_code=400,
                            detail=f"Path non trovato: {req.folder_path}")
    # Crea la cartella nel DB se non esiste
    if get_folder_by_path(config.LOCAL_DB, req.folder_path) is None:
        insert_folder(
            config.LOCAL_DB,
            folder_path=req.folder_path,
            display_name=req.display_name,
            default_location_name=req.default_location_name,
            default_latitude=req.default_latitude,
            default_longitude=req.default_longitude,
            auto_analyze=req.auto_analyze,
        )
    result = scan_folder(req.folder_path, db_path=config.LOCAL_DB)
    # Aggiorna contatori
    from database.photos import count_photos
    total    = count_photos(config.LOCAL_DB, folder_path=req.folder_path)
    analyzed = count_photos(config.LOCAL_DB, folder_path=req.folder_path,
                            analyzed_only=True)
    update_folder_counts(config.LOCAL_DB, req.folder_path, total, analyzed)
    return {"new": result.new, "skipped": result.skipped, "errors": result.errors}


@router.post("/rescan")
def rescan_folder(req: FolderDeleteRequest):
    if not os.path.isdir(req.folder_path):
        raise HTTPException(status_code=400,
                            detail=f"Path non trovato: {req.folder_path}")
    result = scan_folder(req.folder_path, db_path=config.LOCAL_DB)
    from database.photos import count_photos
    total    = count_photos(config.LOCAL_DB, folder_path=req.folder_path)
    analyzed = count_photos(config.LOCAL_DB, folder_path=req.folder_path,
                            analyzed_only=True)
    update_folder_counts(config.LOCAL_DB, req.folder_path, total, analyzed)
    return {"new": result.new, "skipped": result.skipped, "errors": result.errors}


@router.put("/meta")
def update_folder_meta(req: FolderUpdateRequest):
    fields = {k: v for k, v in req.dict().items()
              if k != "folder_path" and v is not None}
    update_folder(config.LOCAL_DB, req.folder_path, **fields)
    return {"ok": True}


@router.delete("")
def remove_folder(req: FolderDeleteRequest):
    delete_folder(config.LOCAL_DB, req.folder_path)
    return {"ok": True}
```

Aggiorna `main.py` aggiungendo:
```python
from api.folders import router as folders_router
app.include_router(folders_router)
```

- [ ] **Step 10.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_api_folders.py -v
```

- [ ] **Step 10.5: Commit**
```bash
git add api/folders.py main.py tests/test_api_folders.py
git commit -m "feat: api/folders — scan, list, update, delete cartelle"
```

---

## Task 11: api/photos.py

**Files:**
- Create: `api/photos.py`
- Create: `tests/test_api_photos.py`

- [ ] **Step 11.1: Scrivi il test (RED)**

Crea `tests/test_api_photos.py`:
```python
"""Test per api/photos.py."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_photo(tmp_path, monkeypatch):
    """Client con una foto già inserita nel DB."""
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo
    init_db(db)

    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (800, 600), (100, 150, 200)).save(photo_path, "JPEG")
    pid = insert_photo(db,
                       file_path=photo_path,
                       folder_path=str(tmp_path),
                       filename="test.jpg",
                       format="jpg",
                       file_size=50000,
                       width=800,
                       height=600)
    from main import app
    return TestClient(app), pid, photo_path


class TestListPhotos:
    def test_returns_200(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get("/api/photos")
        assert resp.status_code == 200

    def test_returns_list(self, client_with_photo):
        c, pid, _ = client_with_photo
        data = c.get("/api/photos").json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_filter_by_folder(self, client_with_photo, tmp_path):
        c, pid, photo_path = client_with_photo
        resp = c.get(f"/api/photos?folder_path={tmp_path}")
        assert len(resp.json()) == 1

    def test_pagination(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get("/api/photos?limit=10&offset=0")
        assert resp.status_code == 200


class TestGetPhoto:
    def test_returns_photo(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.jpg"

    def test_404_for_missing(self, client_with_photo):
        c, _, _ = client_with_photo
        resp = c.get("/api/photos/99999")
        assert resp.status_code == 404


class TestUpdatePhoto:
    def test_set_favorite(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.put(f"/api/photos/{pid}", json={"is_favorite": 1})
        assert resp.status_code == 200
        data = c.get(f"/api/photos/{pid}").json()
        assert data["is_favorite"] == 1

    def test_set_user_description(self, client_with_photo):
        c, pid, _ = client_with_photo
        c.put(f"/api/photos/{pid}",
              json={"user_description": "La mia foto preferita"})
        data = c.get(f"/api/photos/{pid}").json()
        assert data["user_description"] == "La mia foto preferita"


class TestThumbnail:
    def test_returns_jpeg_bytes(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/thumbnail")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    def test_thumbnail_is_valid_image(self, client_with_photo):
        import io
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/thumbnail")
        img = Image.open(io.BytesIO(resp.content))
        assert max(img.size) <= 400


class TestImageEndpoint:
    def test_returns_image(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.get(f"/api/photos/{pid}/image")
        assert resp.status_code == 200
        assert "image" in resp.headers["content-type"]
```

- [ ] **Step 11.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_api_photos.py -v --tb=no -q
```

- [ ] **Step 11.3: Implementa `api/photos.py`**
```python
"""Route /api/photos."""
import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

from database.photos import get_photos, get_photo_by_id, update_photo, count_photos
from services.image_processor import generate_thumbnail
import config

router = APIRouter(prefix="/api/photos", tags=["photos"])


class PhotoUpdateRequest(BaseModel):
    is_favorite: Optional[int] = None
    is_trash: Optional[int] = None
    user_description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@router.get("")
def list_photos(
    folder_path: Optional[str] = None,
    sort_by: str = "overall_score",
    sort_desc: bool = True,
    min_score: Optional[float] = None,
    is_favorite: Optional[bool] = None,
    is_trash: Optional[bool] = None,
    analyzed: Optional[bool] = None,
    format: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    photos = get_photos(
        config.LOCAL_DB,
        folder_path=folder_path,
        sort_by=sort_by,
        sort_desc=sort_desc,
        min_score=min_score,
        is_favorite=is_favorite,
        is_trash=is_trash,
        analyzed_only=analyzed,
        format=format,
        limit=limit,
        offset=offset,
    )
    return [dict(p) for p in photos]


@router.get("/{photo_id}")
def get_photo(photo_id: int):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    return dict(photo)


@router.put("/{photo_id}")
def update_photo_fields(photo_id: int, req: PhotoUpdateRequest):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    fields = {k: v for k, v in req.dict().items() if v is not None}
    if fields:
        update_photo(config.LOCAL_DB, photo_id, **fields)
    return {"ok": True}


@router.get("/{photo_id}/thumbnail")
def get_thumbnail(photo_id: int, size: int = 400):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    if not os.path.exists(photo["file_path"]):
        raise HTTPException(status_code=404, detail="File non trovato sul disco")
    jpeg_bytes = generate_thumbnail(photo["file_path"], size=size)
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "max-age=86400"},
    )


@router.get("/{photo_id}/image")
def get_original_image(photo_id: int):
    photo = get_photo_by_id(config.LOCAL_DB, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Foto non trovata")
    if not os.path.exists(photo["file_path"]):
        raise HTTPException(status_code=404, detail="File non trovato sul disco")
    with open(photo["file_path"], "rb") as f:
        content = f.read()
    ext = os.path.splitext(photo["file_path"])[1].lower()
    media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return Response(content=content, media_type=media)
```

Aggiorna `main.py`:
```python
from api.photos import router as photos_router
app.include_router(photos_router)
```

- [ ] **Step 11.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_api_photos.py -v
```

- [ ] **Step 11.5: Commit**
```bash
git add api/photos.py main.py tests/test_api_photos.py
git commit -m "feat: api/photos — list/detail/thumbnail/update/download"
```

---

## Task 12: api/queue.py

**Files:**
- Create: `api/queue.py`
- Create: `tests/test_api_queue.py`

- [ ] **Step 12.1: Scrivi il test (RED)**

Crea `tests/test_api_queue.py`:
```python
"""Test per api/queue.py."""
import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture
def client_with_photo(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("LOCAL_DB", db)
    import config, importlib
    importlib.reload(config)
    from database.models import init_db
    from database.photos import insert_photo
    init_db(db)
    photo_path = str(tmp_path / "test.jpg")
    Image.new("RGB", (100, 100)).save(photo_path, "JPEG")
    pid = insert_photo(db,
                       file_path=photo_path,
                       folder_path=str(tmp_path),
                       filename="test.jpg",
                       format="jpg",
                       file_size=1000,
                       width=100,
                       height=100)
    from main import app
    return TestClient(app), pid


class TestQueueStatus:
    def test_returns_200(self, client_with_photo):
        c, _ = client_with_photo
        resp = c.get("/api/queue/status")
        assert resp.status_code == 200

    def test_has_required_fields(self, client_with_photo):
        c, _ = client_with_photo
        data = c.get("/api/queue/status").json()
        for field in ["pending", "processing", "done", "error", "is_running"]:
            assert field in data, f"Campo mancante: {field}"


class TestAddToQueue:
    def test_add_photo(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/queue/add",
                      json={"photo_ids": [pid], "priority": 5})
        assert resp.status_code == 200

    def test_queue_count_increases(self, client_with_photo):
        c, pid = client_with_photo
        c.post("/api/queue/add", json={"photo_ids": [pid], "priority": 5})
        data = c.get("/api/queue/status").json()
        assert data["pending"] == 1

    def test_add_folder(self, client_with_photo, tmp_path, monkeypatch):
        c, pid = client_with_photo
        import config
        resp = c.post("/api/queue/add-folder",
                      json={"folder_path": str(tmp_path)})
        assert resp.status_code == 200


class TestPauseResume:
    def test_pause_returns_200(self, client_with_photo):
        c, _ = client_with_photo
        assert c.post("/api/queue/pause").status_code == 200

    def test_resume_returns_200(self, client_with_photo):
        c, _ = client_with_photo
        assert c.post("/api/queue/resume").status_code == 200


class TestDeleteQueueItem:
    def test_removes_pending_item(self, client_with_photo):
        c, pid = client_with_photo
        resp = c.post("/api/queue/add",
                      json={"photo_ids": [pid], "priority": 5})
        # Recupera l'id dalla coda tramite status (semplificato: usiamo DB diretto)
        import config
        from database.queue import get_next_pending
        item = get_next_pending(config.LOCAL_DB)
        del_resp = c.delete(f"/api/queue/{item['id']}")
        assert del_resp.status_code == 200
        data = c.get("/api/queue/status").json()
        assert data["pending"] == 0
```

- [ ] **Step 12.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_api_queue.py -v --tb=no -q
```

- [ ] **Step 12.3: Implementa `api/queue.py`**
```python
"""Route /api/queue — gestione coda analisi AI."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.queue import (
    add_to_queue, get_queue_counts, remove_queue_item,
    get_next_pending,
)
from database.photos import get_photos, count_photos
import config

router = APIRouter(prefix="/api/queue", tags=["queue"])

# Riferimento globale al worker (impostato da main.py al startup)
_worker = None


def set_worker(worker) -> None:
    global _worker
    _worker = worker


class AddRequest(BaseModel):
    photo_ids: list
    priority: int = 5


class FolderQueueRequest(BaseModel):
    folder_path: str
    priority: int = 5


class DeleteRequest(BaseModel):
    folder_path: str


@router.get("/status")
def queue_status():
    counts = get_queue_counts(config.LOCAL_DB)
    return {
        **counts,
        "is_running": _worker.is_running if _worker else False,
        "is_paused":  _worker.is_paused  if _worker else False,
        "current_photo": _worker.current_photo_name if _worker else None,
    }


@router.post("/add")
def add_photos_to_queue(req: AddRequest):
    added = 0
    for pid in req.photo_ids:
        add_to_queue(config.LOCAL_DB, photo_id=pid, priority=req.priority)
        added += 1
    return {"added": added}


@router.post("/add-folder")
def add_folder_to_queue(req: FolderQueueRequest):
    photos = get_photos(
        config.LOCAL_DB,
        folder_path=req.folder_path,
        analyzed_only=False,
        limit=100000,
    )
    added = 0
    for photo in photos:
        if photo["analyzed_at"] is None:
            add_to_queue(config.LOCAL_DB,
                         photo_id=photo["id"],
                         priority=req.priority)
            added += 1
    return {"added": added}


@router.post("/pause")
def pause_queue():
    if _worker:
        _worker.pause()
    return {"ok": True}


@router.post("/resume")
def resume_queue():
    if _worker:
        _worker.resume()
    return {"ok": True}


@router.delete("/{queue_id}")
def delete_queue_item(queue_id: int):
    remove_queue_item(config.LOCAL_DB, queue_id)
    return {"ok": True}
```

Aggiorna `main.py` con il router e il worker (si aggiunge la gestione del worker dinamicamente in Fase 2):
```python
from api.queue import router as queue_router, set_worker
app.include_router(queue_router)
```

- [ ] **Step 12.4: Verifica GREEN**
```bash
.venv/bin/pytest tests/test_api_queue.py -v
```

- [ ] **Step 12.5: Commit**
```bash
git add api/queue.py main.py tests/test_api_queue.py
git commit -m "feat: api/queue — status, add, pause/resume, delete"
```

---

## Task 13: main.py — Integrazione finale

**Files:**
- Modify: `main.py`

Integra tutti i router, avvia il worker AI allo startup, gestisce SIGTERM per il backup finale.

- [ ] **Step 13.1: Scrivi il test (RED)**

Aggiungi a `tests/test_main.py`:
```python
class TestAllRoutersRegistered:
    def test_settings_route_exists(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code != 404

    def test_folders_route_exists(self, client):
        resp = client.get("/api/folders")
        assert resp.status_code != 404

    def test_photos_route_exists(self, client):
        resp = client.get("/api/photos")
        assert resp.status_code != 404

    def test_queue_route_exists(self, client):
        resp = client.get("/api/queue/status")
        assert resp.status_code != 404
```

- [ ] **Step 13.2: Verifica RED**
```bash
.venv/bin/pytest tests/test_main.py -v --tb=no -q
```
I nuovi test passano già se i router sono registrati. Se non li vedi fallire, controlla che `client` punti al db temporaneo.

- [ ] **Step 13.3: Scrivi `main.py` finale**
```python
"""
Entry point FastAPI — Photo AI Manager.
Avvia il server con:
  uvicorn main:app --host 0.0.0.0 --port 8080
"""
import signal
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from database.models import init_db
from services.db_sync import load_db_from_nas, backup_db_to_nas
from api.settings import router as settings_router
from api.folders  import router as folders_router
from api.photos   import router as photos_router
from api.queue    import router as queue_router, set_worker

START_TIME = time.time()

app = FastAPI(
    title="Photo AI Manager",
    version=config.APP_VERSION,
    docs_url="/api/docs",
)

# ── Router API ────────────────────────────────────────────────────
app.include_router(settings_router)
app.include_router(folders_router)
app.include_router(photos_router)
app.include_router(queue_router)

# ── Static files (SPA Vue 3 — Fase 5) ────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ── Lifecycle ─────────────────────────────────────────────────────
@app.on_event("startup")
async def on_startup():
    # 1. Prepara directory locale
    Path(config.LOCAL_DB).parent.mkdir(parents=True, exist_ok=True)

    # 2. Carica DB dal NAS (se disponibile)
    loaded = load_db_from_nas()
    if loaded:
        print(f"DB caricato dal NAS: {config.REMOTE_DB}")
    else:
        print("DB non trovato sul NAS — avvio con database vuoto")

    # 3. Inizializza schema (idempotente)
    init_db(config.LOCAL_DB)

    # 4. Reset item bloccati in 'processing' (riavvio imprevisto)
    from database.queue import reset_stale_processing
    reset_stale_processing(config.LOCAL_DB)

    # 5. Avvia backup periodico con APScheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from services.db_sync import backup_db_to_nas as _backup
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _backup,
        "interval",
        minutes=config.BACKUP_INTERVAL_MIN,
        id="db_backup",
    )
    scheduler.start()
    app.state.scheduler = scheduler

    # 6. Backup al SIGTERM
    def _on_sigterm(signum, frame):
        backup_db_to_nas()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _on_sigterm)


@app.on_event("shutdown")
async def on_shutdown():
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown(wait=False)
    backup_db_to_nas()


# ── Health ────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    """Readiness check usato dallo script di deploy (§16)."""
    db_ok  = Path(config.LOCAL_DB).exists()
    nas_ok = Path(config.APP_DATA_PATH).exists()
    return {
        "status":   "ok" if (db_ok and nas_ok) else "degraded",
        "db":       "ok" if db_ok  else "missing",
        "nas":      "ok" if nas_ok else "not_mounted",
        "version":  config.APP_VERSION,
        "uptime_s": int(time.time() - START_TIME),
    }
```

- [ ] **Step 13.4: Verifica GREEN (tutta la suite)**
```bash
.venv/bin/pytest -v --tb=short
```
Atteso: 0 failed

- [ ] **Step 13.5: Smoke test avvio server**
```bash
LOCAL_DB=/tmp/test_photo_ai.db .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8081 &
sleep 2
curl -s http://127.0.0.1:8081/health | python3 -m json.tool
kill %1
```
Atteso: JSON con `"status": "degraded"` (NAS non montato è normale in dev)

- [ ] **Step 13.6: Commit finale Fase 2**
```bash
git add main.py tests/test_main.py
git commit -m "feat: main.py — integrazione completa Fase 2, startup/shutdown, backup scheduler"
```

---

## Self-Review

### Copertura spec

| Sezione spec | Task che la copre |
|---|---|
| §6.1 Gestione cartelle | Task 10 (api/folders) |
| §6.2 Indicizzazione scan | Task 2 (scanner) |
| §6.3 Estrazione EXIF | Fase 1 già fatto |
| §6.4 Geolocalizzazione (reverse geocoding) | Task 3 (geocoder) |
| §6.5 Coda analisi AI | Task 7 (queue_worker) + Task 12 (api/queue) |
| §6.6 Prompt AI | Task 5 (gemini), Task 6 (ollama) |
| §8 API REST (folders/photos/queue/settings) | Task 9-12 |
| §10 Thumbnail in memoria / Cache-Control | Task 11 (api/photos thumbnail) |
| §10 WAL mode + indici | Fase 1 già fatto |
| §13 prepare_for_ai | Fase 1 già fatto |
| §15 Persistenza DB NAS / backup | Task 1 (db_sync) + Task 13 (main startup) |
| §16 /health endpoint | Task 8 |

### Fuori scope Fase 2 (rimandato)

- `api/export.py` (ZIP streaming) → Fase 3
- `api/search.py` (embedding search) → Fase 3
- Auth Google OAuth2 → Fase 4
- Frontend Vue 3 → Fase 5

### Note di tipo/firma

- `QueueWorker` usa `set_worker()` in `api/queue.py` — in questa Fase 2 il worker non viene avviato automaticamente (nessuna API key di default). Per avviarlo: chiamare `worker.start()` in `on_startup` dopo aver letto le impostazioni dal DB.
- `StaticFiles` in `main.py` richiede che `static/index.html` esista — c'è già come stub.
