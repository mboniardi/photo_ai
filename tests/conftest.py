"""
Fixture condivise e configurazione pytest.
Aggiunge la root del progetto al sys.path in modo che
i moduli (config, database, services) siano importabili.
"""
import sys
import os
import sqlite3
import tempfile
import pytest

# Aggiungi la directory photo_ai/ al path degli import
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def tmp_db(tmp_path):
    """Database SQLite su file temporaneo, già inizializzato con lo schema."""
    from database.models import init_db
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


@pytest.fixture
def db_conn(tmp_db):
    """Connessione sqlite3 aperta sul db temporaneo (sync, row_factory=Row)."""
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _scrivi_jpeg(percorso):
    """Scrive un JPEG vero (minuscolo) in `percorso`."""
    from PIL import Image
    Image.new("RGB", (4, 4), (120, 80, 40)).save(percorso, "JPEG")


def _scrivi_sidecar(percorso, titolo, lat, lon, istante="1700000000"):
    """Scrive un sidecar JSON nella forma di Google Takeout."""
    import json
    contenuto = {
        "title": titolo,
        "photoTakenTime": {"timestamp": istante, "formatted": "n/d"},
        "geoData": {"latitude": lat, "longitude": lon,
                    "altitude": 0.0, "latitudeSpan": 0.0, "longitudeSpan": 0.0},
    }
    with open(percorso, "w", encoding="utf-8") as fh:
        json.dump(contenuto, fh)


@pytest.fixture
def fixture_takeout(tmp_path):
    """
    Finto archivio Google Takeout già scompattato; ritorna la radice.

    Struttura: Takeout/Google Foto/Vacanza/ con
      IMG_1.jpg  + IMG_1.jpg.supplemental-metadata.json  (45.4642, 9.19; convenzione recente)
      IMG_2.jpg  + IMG_2.jpg.json                         (0.0, 0.0 = non georeferenziata; convenzione vecchia)
      IMG_3.jpg  + JSON troncato                          (illeggibile)
      IMG_4.jpg  senza JSON
      IMG_9.jpg, IMG_9-edited.jpg + JSON del solo originale (come fa Takeout)
      clip.mp4   + JSON                                   (video, da saltare)
      metadata.json                                       (file d'album, non una foto)
    Per l'archivio vero i nomi dei campi `title` e `geoData` sono verificati;
    `photoTakenTime.timestamp` e la convenzione dei nomi sono assunti.
    """
    import os
    album = tmp_path / "Takeout" / "Google Foto" / "Vacanza"
    os.makedirs(album)
    d = str(album)

    _scrivi_jpeg(os.path.join(d, "IMG_1.jpg"))
    _scrivi_sidecar(os.path.join(d, "IMG_1.jpg.supplemental-metadata.json"),
                    "IMG_1.jpg", 45.4642, 9.19)

    _scrivi_jpeg(os.path.join(d, "IMG_2.jpg"))
    _scrivi_sidecar(os.path.join(d, "IMG_2.jpg.json"), "IMG_2.jpg", 0.0, 0.0)

    _scrivi_jpeg(os.path.join(d, "IMG_3.jpg"))
    with open(os.path.join(d, "IMG_3.jpg.json"), "w", encoding="utf-8") as fh:
        fh.write('{"title": "IMG_3.jpg", "geoData": {"latit')

    _scrivi_jpeg(os.path.join(d, "IMG_4.jpg"))

    _scrivi_jpeg(os.path.join(d, "IMG_9.jpg"))
    _scrivi_jpeg(os.path.join(d, "IMG_9-edited.jpg"))
    _scrivi_sidecar(os.path.join(d, "IMG_9.jpg.supplemental-metadata.json"),
                    "IMG_9.jpg", 41.9, 12.5)

    with open(os.path.join(d, "clip.mp4"), "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypmp42")
    _scrivi_sidecar(os.path.join(d, "clip.mp4.supplemental-metadata.json"),
                    "clip.mp4", 10.0, 10.0)

    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as fh:
        fh.write('{"title": "Vacanza"}')

    return str(tmp_path / "Takeout")
