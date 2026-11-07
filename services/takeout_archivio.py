"""
Lettura di un archivio Google Takeout.

Modulo puro: nessun database, nessuna rete. Scompatta gli ZIP scaricati e
descrive le foto contenute, accoppiando ciascuna al suo JSON di accompagnamento
(l'unico posto in cui Google esporta le coordinate GPS).
"""
import json
import math
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import config
from services.scanner import SUPPORTED_EXTS

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp"}

# Convenzione recente dei sidecar: "<foto>.supplemental-metadata.json".
# Takeout tronca il suffisso quando il nome è lungo (".supplemental-metad.json").
_SUFFISSO_SUPPLEMENTAL = "supplemental-metadata"


@dataclass
class Voce:
    percorso_file: str
    nome: str
    album: str
    scattata_il: Optional[str]
    latitudine: Optional[float]
    longitudine: Optional[float]


@dataclass
class Contenuto:
    voci: list = field(default_factory=list)
    video_saltati: int = 0
    gemelli_scartati: int = 0
    json_illeggibili: int = 0


def scompatta(zip_paths: list, destinazione: str) -> str:
    """
    Estrae tutti gli ZIP nella stessa destinazione e ritorna la destinazione.

    Protegge dal "zip slip": prima di scrivere qualunque cosa verifica ogni voce
    di ogni archivio; se una ha percorso assoluto, risale con ".." o, risolta
    con realpath (quindi anche attraverso i symlink), cade fuori dalla
    destinazione, solleva ValueError e non scrive nulla.
    """
    os.makedirs(destinazione, exist_ok=True)
    radice_reale = os.path.realpath(destinazione)

    da_estrarre = []
    for zip_path in zip_paths:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                nome = info.filename
                if (nome.startswith(("/", "\\")) or os.path.isabs(nome)
                        or (len(nome) > 1 and nome[1] == ":")):
                    raise ValueError(f"Percorso assoluto nell'archivio: {nome!r}")
                if ".." in nome.replace("\\", "/").split("/"):
                    raise ValueError(f"Percorso che risale nell'archivio: {nome!r}")
                bersaglio = os.path.realpath(os.path.join(radice_reale, nome))
                if os.path.commonpath([radice_reale, bersaglio]) != radice_reale:
                    raise ValueError(f"Percorso fuori dalla destinazione: {nome!r}")
                da_estrarre.append((zip_path, info, bersaglio))

    # Ogni archivio si apre una sola volta, per tutte le sue voci
    per_zip = {}
    for zip_path, info, bersaglio in da_estrarre:
        per_zip.setdefault(zip_path, []).append((info, bersaglio))
    for zip_path, voci in per_zip.items():
        with zipfile.ZipFile(zip_path) as zf:
            for info, bersaglio in voci:
                if info.is_dir():
                    os.makedirs(bersaglio, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(bersaglio), exist_ok=True)
                with zf.open(info) as src, open(bersaglio, "wb") as dst:
                    while True:
                        blocco = src.read(1024 * 1024)
                        if not blocco:
                            break
                        dst.write(blocco)
    return destinazione


def _trova_sidecar(nome: str, json_nella_cartella: set) -> Optional[str]:
    """Nome del sidecar di `nome` tra i JSON della cartella, o None."""
    for candidato in (f"{nome}.{_SUFFISSO_SUPPLEMENTAL}.json", f"{nome}.json"):
        if candidato in json_nella_cartella:
            return candidato
    prefisso = f"{nome}."
    for candidato in sorted(json_nella_cartella):
        if not (candidato.startswith(prefisso) and candidato.endswith(".json")):
            continue
        centro = candidato[len(prefisso):-len(".json")]
        if centro and _SUFFISSO_SUPPLEMENTAL.startswith(centro):
            return candidato
    return None


def _nome_originale(nome: str) -> Optional[str]:
    """
    Per un file modificato ("X-edited.jpg", "X-modificato.jpg") ritorna il nome
    dell'originale ("X.jpg"); None se non è un file modificato. I suffissi
    stanno in config e si leggono a ogni chiamata.
    """
    stem, ext = os.path.splitext(nome)
    for suffisso in config.TAKEOUT_SUFFISSI_MODIFICATO:
        if suffisso and stem.endswith(suffisso) and len(stem) > len(suffisso):
            return stem[:-len(suffisso)] + ext
    return None


def _istante_iso(dati: dict) -> Optional[str]:
    """
    `photoTakenTime.timestamp` (secondi epoch, di solito stringa) in ISO 8601
    UTC senza fuso, come `photos.exif_date`. Campo non verificato su un archivio
    reale: qualunque forma inattesa dà None.
    """
    try:
        grezzo = dati.get("photoTakenTime")
        if not isinstance(grezzo, dict):
            return None
        ts = grezzo.get("timestamp")
        if isinstance(ts, bool) or not isinstance(ts, (int, float, str)):
            return None
        secondi = int(float(ts))
        return datetime.fromtimestamp(secondi, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def _coordinate(dati: dict):
    """(lat, lon) da `geoData`; (None, None) se assenti, malformate, non valide o 0/0."""
    geo = dati.get("geoData")
    if not isinstance(geo, dict):
        return None, None
    lat, lon = geo.get("latitude"), geo.get("longitude")
    try:
        if isinstance(lat, bool) or isinstance(lon, bool):
            return None, None
        lat, lon = float(lat), float(lon)
    except (ValueError, TypeError):
        return None, None
    # NaN/Infinity (json li accetta) e valori fuori range non sono coordinate
    if not (math.isfinite(lat) and math.isfinite(lon)
            and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None, None
    # 0/0 in Google Foto significa "non georeferenziata" (come in api/takeout.py)
    if lat == 0.0 and lon == 0.0:
        return None, None
    return lat, lon


def _leggi_sidecar(cartella: str, nome_json: Optional[str]) -> Optional[dict]:
    """Contenuto del sidecar come dict, o None se manca o è illeggibile."""
    if nome_json is None:
        return None
    try:
        with open(os.path.join(cartella, nome_json), "r", encoding="utf-8") as fh:
            dati = json.load(fh)
    except (OSError, ValueError):
        return None
    return dati if isinstance(dati, dict) else None


def leggi(radice: str) -> Contenuto:
    """Cammina la directory scompattata e descrive le foto trovate."""
    contenuto = Contenuto()
    for cartella, _sottocartelle, files in sorted(os.walk(radice)):
        album = os.path.relpath(cartella, radice)
        json_nella_cartella = {f for f in files if f.lower().endswith(".json")}

        immagini = []
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in VIDEO_EXTS:
                contenuto.video_saltati += 1
            elif ext in SUPPORTED_EXTS:
                immagini.append(f)

        # Di una coppia X.jpg / X-edited.jpg si tiene la versione modificata
        presenti = set(immagini)
        scartati = set()
        for f in immagini:
            originale = _nome_originale(f)
            if originale in presenti:
                scartati.add(originale)
        contenuto.gemelli_scartati += len(scartati)

        for f in immagini:
            if f in scartati:
                continue
            nome_json = _trova_sidecar(f, json_nella_cartella)
            if nome_json is None:
                # Takeout dà il JSON alla sola foto originale, non alla -edited
                originale = _nome_originale(f)
                if originale is not None:
                    nome_json = _trova_sidecar(originale, json_nella_cartella)
            dati = _leggi_sidecar(cartella, nome_json)
            if dati is None:
                contenuto.json_illeggibili += 1
                lat = lon = scattata_il = None
            else:
                lat, lon = _coordinate(dati)
                scattata_il = _istante_iso(dati)
            contenuto.voci.append(Voce(
                percorso_file=os.path.join(cartella, f),
                nome=f,
                album=album,
                scattata_il=scattata_il,
                latitudine=lat,
                longitudine=lon,
            ))
    return contenuto
