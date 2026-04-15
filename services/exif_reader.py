"""
Lettura metadati EXIF per tutti i formati supportati (§6.3).

Formati:
  JPG/JPEG  → piexif + PIL
  HEIC/HEIF → pillow-heif + PIL ExifTags
  RAW       → rawpy metadata
  PNG       → PIL solo dimensioni (nessun EXIF standard)

La funzione pubblica principale è read_exif(path) → dict.
Tutti i campi assenti rimangono None.
"""
import os
from typing import Optional

from PIL import Image

# ── Estensioni per formato ────────────────────────────────────────
_JPEG_EXTS = {".jpg", ".jpeg"}
_PNG_EXTS = {".png"}
_HEIC_EXTS = {".heic", ".heif"}
_RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2"}


# ── API pubblica ──────────────────────────────────────────────────

def read_exif(path: str) -> dict:
    """
    Legge i metadati EXIF di un'immagine.
    Ritorna un dict con le chiavi della tabella photos (§5).
    I campi non disponibili hanno valore None.
    """
    ext = os.path.splitext(path)[1].lower()
    file_size = os.path.getsize(path)

    if ext in _JPEG_EXTS:
        meta = _read_jpeg(path)
    elif ext in _HEIC_EXTS:
        meta = _read_heic(path)
    elif ext in _RAW_EXTS:
        meta = _read_raw(path)
    elif ext in _PNG_EXTS:
        meta = _read_png(path)
    else:
        meta = _read_generic(path)

    meta["file_size"] = file_size
    return meta


def dms_to_decimal(
    dms: list,
    ref: str,
) -> float:
    """
    Converte coordinate GPS da DMS (gradi, minuti, secondi)
    in gradi decimali. ref deve essere 'N', 'S', 'E' o 'W'.
    dms è una lista di 3 tuple (numeratore, denominatore).
    """
    degrees = dms[0][0] / dms[0][1]
    minutes = dms[1][0] / dms[1][1] / 60.0
    seconds = dms[2][0] / dms[2][1] / 3600.0
    decimal = degrees + minutes + seconds
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


# ── Reader per formato ────────────────────────────────────────────

def _read_jpeg(path: str) -> dict:
    """Legge EXIF da JPEG usando piexif + PIL per le dimensioni."""
    meta = _empty_meta()

    # Dimensioni via PIL (più affidabile di EXIF per le dimensioni reali)
    with Image.open(path) as img:
        meta["width"], meta["height"] = img.size

    try:
        import piexif
        exif_data = piexif.load(path)
    except Exception:
        return meta  # JPEG senza EXIF

    ifd0 = exif_data.get("0th", {})

    # Orientamento
    orientation_val = ifd0.get(piexif.ImageIFD.Orientation)
    if orientation_val is not None:
        meta["exif_orientation"] = int(orientation_val)

    # Camera
    meta["camera_make"] = _decode(ifd0.get(piexif.ImageIFD.Make))
    meta["camera_model"] = _decode(ifd0.get(piexif.ImageIFD.Model))

    exif = exif_data.get("Exif", {})

    # Data scatto → ISO 8601
    raw_date = exif.get(piexif.ExifIFD.DateTimeOriginal)
    if raw_date:
        meta["exif_date"] = _parse_exif_date(raw_date)

    # Obiettivo
    meta["lens_model"] = _decode(exif.get(piexif.ExifIFD.LensModel))

    # Dati ottici
    focal = exif.get(piexif.ExifIFD.FocalLength)
    if focal:
        meta["focal_length"] = focal[0] / focal[1]

    fnumber = exif.get(piexif.ExifIFD.FNumber)
    if fnumber:
        meta["aperture"] = fnumber[0] / fnumber[1]

    exp = exif.get(piexif.ExifIFD.ExposureTime)
    if exp:
        meta["shutter_speed"] = _format_exposure(exp)

    iso = exif.get(piexif.ExifIFD.ISOSpeedRatings)
    if iso is not None:
        meta["iso"] = int(iso)

    # GPS
    gps = exif_data.get("GPS", {})
    lat_dms = gps.get(piexif.GPSIFD.GPSLatitude)
    lat_ref = _decode(gps.get(piexif.GPSIFD.GPSLatitudeRef))
    lon_dms = gps.get(piexif.GPSIFD.GPSLongitude)
    lon_ref = _decode(gps.get(piexif.GPSIFD.GPSLongitudeRef))

    if lat_dms and lat_ref and lon_dms and lon_ref:
        meta["latitude"] = dms_to_decimal(lat_dms, lat_ref)
        meta["longitude"] = dms_to_decimal(lon_dms, lon_ref)

    _apply_orientation_to_dims(meta)
    return meta


def _read_heic(path: str) -> dict:
    """Legge EXIF da HEIC/HEIF usando pillow-heif + PIL ExifTags."""
    meta = _empty_meta()
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        return meta

    try:
        with Image.open(path) as img:
            meta["width"], meta["height"] = img.size
            exif_data = img.getexif()
            if not exif_data:
                return meta

            from PIL.ExifTags import TAGS, GPSTAGS
            tag_map = {v: k for k, v in TAGS.items()}

            orientation_tag = tag_map.get("Orientation")
            if orientation_tag and exif_data.get(orientation_tag) is not None:
                meta["exif_orientation"] = int(exif_data[orientation_tag])

            make_tag = tag_map.get("Make")
            model_tag = tag_map.get("Model")
            if make_tag:
                meta["camera_make"] = _decode_safe(exif_data.get(make_tag))
            if model_tag:
                meta["camera_model"] = _decode_safe(exif_data.get(model_tag))

            dt_tag = tag_map.get("DateTimeOriginal")
            if dt_tag and exif_data.get(dt_tag):
                meta["exif_date"] = _parse_exif_date(exif_data[dt_tag])

            lens_tag = tag_map.get("LensModel")
            if lens_tag:
                meta["lens_model"] = _decode_safe(exif_data.get(lens_tag))

            focal_tag = tag_map.get("FocalLength")
            if focal_tag and exif_data.get(focal_tag):
                val = exif_data[focal_tag]
                meta["focal_length"] = float(val) if not isinstance(val, tuple) else val[0] / val[1]

            fn_tag = tag_map.get("FNumber")
            if fn_tag and exif_data.get(fn_tag):
                val = exif_data[fn_tag]
                meta["aperture"] = float(val) if not isinstance(val, tuple) else val[0] / val[1]

            exp_tag = tag_map.get("ExposureTime")
            if exp_tag and exif_data.get(exp_tag):
                val = exif_data[exp_tag]
                if isinstance(val, tuple):
                    meta["shutter_speed"] = _format_exposure(val)
                else:
                    meta["shutter_speed"] = str(val)

            iso_tag = tag_map.get("ISOSpeedRatings")
            if iso_tag and exif_data.get(iso_tag) is not None:
                meta["iso"] = int(exif_data[iso_tag])

            # GPS
            gps_tag = tag_map.get("GPSInfo")
            if gps_tag and exif_data.get(gps_tag):
                gps_info = exif_data[gps_tag]
                lat, lon = _extract_gps_from_pil(gps_info, GPSTAGS)
                if lat is not None:
                    meta["latitude"] = lat
                    meta["longitude"] = lon

        _apply_orientation_to_dims(meta)
    except Exception:
        pass

    return meta


def _read_raw(path: str) -> dict:
    """Legge metadati da file RAW tramite rawpy."""
    meta = _empty_meta()
    try:
        import rawpy
        with rawpy.imread(path) as raw:
            # Dimensioni: usa il sensore visibile
            meta["height"], meta["width"] = raw.sizes.iheight, raw.sizes.iwidth

            # rawpy espone i metadata EXIF come dizionario (se disponibili)
            # Nota: il supporto varia per modello/marca fotocamera
            if hasattr(raw, "metadata"):
                md = raw.metadata
                if md.camera_make:
                    meta["camera_make"] = md.camera_make.strip()
                if md.camera_model:
                    meta["camera_model"] = md.camera_model.strip()
                if md.timestamp:
                    from datetime import datetime
                    meta["exif_date"] = datetime.fromtimestamp(
                        md.timestamp
                    ).isoformat(timespec="seconds")
                if md.focal_len:
                    meta["focal_length"] = float(md.focal_len)
                if md.aperture:
                    meta["aperture"] = float(md.aperture)
                if md.iso_speed:
                    meta["iso"] = int(md.iso_speed)
                if md.shutter:
                    meta["shutter_speed"] = _format_exposure_float(md.shutter)
    except ImportError:
        # rawpy non installato: dimensioni via Pillow se possibile
        with Image.open(path) as img:
            meta["width"], meta["height"] = img.size
    except Exception:
        pass

    return meta


def _read_png(path: str) -> dict:
    """PNG: solo dimensioni (nessun EXIF standard)."""
    meta = _empty_meta()
    with Image.open(path) as img:
        meta["width"], meta["height"] = img.size
    return meta


def _read_generic(path: str) -> dict:
    """Fallback per formati sconosciuti: prova con PIL."""
    meta = _empty_meta()
    try:
        with Image.open(path) as img:
            meta["width"], meta["height"] = img.size
    except Exception:
        pass
    return meta


# ── Helpers privati ───────────────────────────────────────────────

# Orientazioni EXIF che implicano swap larghezza/altezza
_SWAP_ORIENTATIONS = {5, 6, 7, 8}


def _apply_orientation_to_dims(meta: dict) -> None:
    """
    Se exif_orientation richiede una rotazione di 90°/270°,
    scambia width e height in modo che il DB memorizzi le dimensioni logiche.
    """
    if meta.get("exif_orientation") in _SWAP_ORIENTATIONS:
        meta["width"], meta["height"] = meta["height"], meta["width"]


def _empty_meta() -> dict:
    """Dizionario con tutti i campi EXIF a None."""
    return {
        "width": None, "height": None,
        "exif_orientation": None,
        "exif_date": None,
        "camera_make": None, "camera_model": None, "lens_model": None,
        "focal_length": None, "aperture": None,
        "shutter_speed": None, "iso": None,
        "latitude": None, "longitude": None,
    }


def _decode(value) -> Optional[str]:
    """Decodifica bytes piexif in stringa, rimuovendo caratteri null."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00").strip()
    return str(value).strip()


def _decode_safe(value) -> Optional[str]:
    """Come _decode ma accetta anche stringhe dirette."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00").strip()
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip()


def _parse_exif_date(raw) -> Optional[str]:
    """
    Converte la data EXIF 'YYYY:MM:DD HH:MM:SS' in ISO 8601
    'YYYY-MM-DDTHH:MM:SS'.
    """
    if raw is None:
        return None
    s = _decode(raw) if isinstance(raw, bytes) else str(raw)
    try:
        # Formato EXIF: "2023:07:15 14:32:00"
        date_part, time_part = s.split(" ")
        date_iso = date_part.replace(":", "-")
        return f"{date_iso}T{time_part}"
    except Exception:
        return None


def _format_exposure(rational: tuple) -> str:
    """
    Formatta ExposureTime (numeratore, denominatore) come stringa leggibile.
    Es.: (1, 120) → "1/120"  — (1, 1) → "1"  — (2, 1) → "2"
    """
    num, den = rational
    if den == 1:
        return str(num)
    # Semplifica la frazione
    from math import gcd
    divisore = gcd(num, den)
    return f"{num // divisore}/{den // divisore}"


def _format_exposure_float(shutter: float) -> str:
    """Converte un valore float di ExposureTime in stringa leggibile."""
    if shutter >= 1.0:
        return str(round(shutter, 1))
    # Approssima la frazione
    den = round(1.0 / shutter)
    return f"1/{den}"


def _extract_gps_from_pil(gps_info: dict, GPSTAGS: dict):
    """
    Estrae lat/lon da un dizionario GPS PIL (tag numerici → valori).
    Ritorna (lat, lon) in gradi decimali o (None, None).
    """
    gps_by_name = {GPSTAGS.get(k, k): v for k, v in gps_info.items()}
    lat_dms = gps_by_name.get("GPSLatitude")
    lat_ref = gps_by_name.get("GPSLatitudeRef", "N")
    lon_dms = gps_by_name.get("GPSLongitude")
    lon_ref = gps_by_name.get("GPSLongitudeRef", "E")

    if not (lat_dms and lon_dms):
        return None, None

    def to_list_of_tuples(val):
        return [(int(v.numerator), int(v.denominator))
                if hasattr(v, "numerator") else (int(v[0]), int(v[1]))
                for v in val]

    try:
        lat = dms_to_decimal(to_list_of_tuples(lat_dms), lat_ref)
        lon = dms_to_decimal(to_list_of_tuples(lon_dms), lon_ref)
        return lat, lon
    except Exception:
        return None, None
