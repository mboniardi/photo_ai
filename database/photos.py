"""
CRUD per la tabella photos.
Ogni funzione accetta un db_path opzionale (usato nei test);
se omesso usa config.LOCAL_DB tramite get_db().
"""
from typing import Optional
from database import get_db


_ALLOWED_SORT_COLUMNS = frozenset({
    "id", "filename", "exif_date", "file_size", "width", "height",
    "overall_score", "technical_score", "aesthetic_score",
    "analyzed_at", "created_at", "updated_at", "folder_path",
})


def insert_photo(
    db_path: Optional[str] = None,
    *,
    file_path: str,
    folder_path: str,
    filename: str,
    format: Optional[str] = None,
    file_size: Optional[int] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    exif_orientation: Optional[int] = None,
    exif_date: Optional[str] = None,
    camera_make: Optional[str] = None,
    camera_model: Optional[str] = None,
    lens_model: Optional[str] = None,
    focal_length: Optional[float] = None,
    aperture: Optional[float] = None,
    shutter_speed: Optional[str] = None,
    iso: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    location_name: Optional[str] = None,
    location_source: Optional[str] = None,
) -> int:
    """Inserisce una nuova foto. Ritorna l'id assegnato."""
    with get_db(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO photos (
                file_path, folder_path, filename, format, file_size,
                width, height, exif_orientation, exif_date,
                camera_make, camera_model, lens_model,
                focal_length, aperture, shutter_speed, iso,
                latitude, longitude, location_name, location_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_path, folder_path, filename, format, file_size,
                width, height, exif_orientation, exif_date,
                camera_make, camera_model, lens_model,
                focal_length, aperture, shutter_speed, iso,
                latitude, longitude, location_name, location_source,
            ),
        )
        return cur.lastrowid


def get_photo_by_id(db_path: Optional[str], photo_id: int):
    """Ritorna il record photo come sqlite3.Row o None se non trovato."""
    with get_db(db_path) as conn:
        return conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()


def _filtri_foto(
    *,
    folder_path=None, is_favorite=None, is_trash=None, analyzed_only=None,
    min_score=None, format=None, date_from=None, date_to=None,
    location=None, orientation=None, has_location=None,
) -> tuple[list, list]:
    """
    Traduce i filtri della griglia in condizioni SQL e parametri.

    Estratta da get_photos perche' la usa anche la selezione di massa: i due
    elenchi devono per forza corrispondere, altrimenti "seleziona tutte le N"
    sceglierebbe foto diverse da quelle che stai guardando.
    """
    conditions: list = []
    params: list = []

    if folder_path is not None:
        conditions.append("folder_path = ?")
        params.append(folder_path)
    if is_favorite is True:
        conditions.append("is_favorite = 1")
    elif is_favorite is False:
        conditions.append("is_favorite = 0")
    if is_trash is True:
        conditions.append("is_trash = 1")
    elif is_trash is False:
        conditions.append("(is_trash = 0 OR is_trash IS NULL)")
    if analyzed_only is True:
        conditions.append("analyzed_at IS NOT NULL")
    if analyzed_only is False:
        conditions.append("analyzed_at IS NULL")
    if min_score is not None:
        conditions.append("overall_score >= ?")
        params.append(min_score)
    if format is not None:
        # Il client manda piu' formati separati da virgola: prima diventava
        # `format = 'jpg,png'` e non corrispondeva a niente.
        formati = [f.strip() for f in str(format).split(",") if f.strip()]
        if len(formati) == 1:
            conditions.append("format = ?")
            params.append(formati[0])
        elif formati:
            conditions.append("format IN (%s)" % ",".join("?" * len(formati)))
            params.extend(formati)
    if has_location is True:
        conditions.append("latitude IS NOT NULL")
    elif has_location is False:
        conditions.append("latitude IS NULL")
    if date_from is not None:
        conditions.append("substr(exif_date, 1, 10) >= ?")
        params.append(date_from)
    if date_to is not None:
        conditions.append("substr(exif_date, 1, 10) <= ?")
        params.append(date_to)
    if location is not None:
        conditions.append("location_name LIKE ?")
        params.append(f"%{location}%")
    if orientation == "horizontal":
        conditions.append("width > height")
    elif orientation == "vertical":
        conditions.append("height > width")
    elif orientation == "square":
        conditions.append("width = height")

    return conditions, params


def get_photos(
    db_path: Optional[str] = None,
    *,
    folder_path: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    is_trash: Optional[bool] = None,
    analyzed_only: Optional[bool] = None,
    min_score: Optional[float] = None,
    format: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    orientation: Optional[str] = None,
    has_location: Optional[bool] = None,
    sort_by: str = "id",
    sort_desc: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list:
    """
    Lista foto con filtri combinati (AND logico).
    Ritorna lista di sqlite3.Row.
    """
    if sort_by not in _ALLOWED_SORT_COLUMNS:
        sort_by = "id"

    conditions, params = _filtri_foto(
        folder_path=folder_path, is_favorite=is_favorite, is_trash=is_trash,
        analyzed_only=analyzed_only, min_score=min_score, format=format,
        date_from=date_from, date_to=date_to, location=location,
        orientation=orientation, has_location=has_location,
    )
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order = f"ORDER BY {sort_by} {'DESC' if sort_desc else 'ASC'}"

    with get_db(db_path) as conn:
        return conn.execute(
            f"SELECT * FROM photos {where} {order} LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()


def count_photos(
    db_path: Optional[str] = None,
    *,
    folder_path: Optional[str] = None,
    analyzed_only: Optional[bool] = None,
    is_trash: Optional[bool] = None,
) -> int:
    """Conta foto con filtri opzionali."""
    conditions = []
    params = []

    if folder_path is not None:
        conditions.append("folder_path = ?")
        params.append(folder_path)
    if analyzed_only is True:
        conditions.append("analyzed_at IS NOT NULL")
    if analyzed_only is False:
        conditions.append("analyzed_at IS NULL")
    if is_trash is True:
        conditions.append("is_trash = 1")
    elif is_trash is False:
        conditions.append("(is_trash = 0 OR is_trash IS NULL)")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db(db_path) as conn:
        row = conn.execute(
            f"SELECT COUNT(*) FROM photos {where}", params
        ).fetchone()
        return row[0]


def get_photo_id_by_path(db_path: Optional[str], file_path: str) -> Optional[int]:
    """Ritorna l'id del record photo con il dato file_path, o None se non trovato."""
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM photos WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row["id"] if row else None


def purge_trash(db_path: Optional[str]) -> int:
    """Rimuove definitivamente dal DB tutte le foto con is_trash=1. Ritorna il numero di record eliminati."""
    with get_db(db_path) as conn:
        cur = conn.execute("DELETE FROM photos WHERE is_trash = 1")
        return cur.rowcount


def delete_photo_by_path(db_path: Optional[str], file_path: str) -> None:
    """Rimuove il record photo con il dato file_path."""
    with get_db(db_path) as conn:
        conn.execute("DELETE FROM photos WHERE file_path = ?", (file_path,))


def update_photo(db_path: Optional[str], photo_id: int, **fields) -> None:
    """
    Aggiorna i campi specificati di una foto.
    Aggiorna automaticamente updated_at.
    """
    if not fields:
        return

    fields["updated_at"] = "datetime('now')"
    set_clause = ", ".join(
        f"{k} = datetime('now')" if k == "updated_at" else f"{k} = ?"
        for k in fields
    )
    values = [v for k, v in fields.items() if k != "updated_at"]
    values.append(photo_id)

    with get_db(db_path) as conn:
        conn.execute(
            f"UPDATE photos SET {set_clause} WHERE id = ?",
            values,
        )


def count_library_status(db_path: Optional[str] = None,
                         embedding_dim: int = 1024) -> dict:
    """
    Quanto manca alla libreria, non alla coda.

    La tabella analysis_queue e' un registro storico: le righe 'done' restano
    anche dopo che il lavoro e' finito, e non dicono nulla sulle foto mai
    accodate. Questi contatori guardano direttamente le foto.

    Un vettore di dimensione diversa da quella del modello in uso e' inservibile
    per la ricerca (search.py lo scarta), quindi conta come "da vettorizzare".
    """
    # Un embedding malformato farebbe fallire json_array_length: json_valid()
    # lo intercetta prima.
    dim = """
        CASE WHEN embedding IS NULL OR embedding = '' OR NOT json_valid(embedding)
             THEN -1 ELSE json_array_length(embedding) END
    """
    sql = f"""
        SELECT
            COUNT(*)                                            AS total,
            SUM(analyzed_at IS NULL)                            AS to_analyze,
            SUM(analyzed_at IS NOT NULL AND {dim} <> ?)         AS to_embed,
            SUM(analyzed_at IS NOT NULL AND {dim}  = ?)         AS complete
        FROM photos
        WHERE is_trash = 0 OR is_trash IS NULL
    """
    with get_db(db_path) as conn:
        row = conn.execute(sql, (embedding_dim, embedding_dim)).fetchone()

    return {k: int(row[k] or 0) for k in ("total", "to_analyze", "to_embed", "complete")}


def get_photos_for_geo_check(db_path: Optional[str] = None) -> list:
    """
    Le foto georeferenziate, in ordine di scatto: il materiale del controllo
    di coerenza geografica. Legge solo le colonne che servono.
    """
    with get_db(db_path) as conn:
        return conn.execute(
            """
            SELECT id, filename, exif_date, latitude, longitude,
                   location_name, location_source
            FROM photos
            WHERE latitude IS NOT NULL AND longitude IS NOT NULL
              AND exif_date IS NOT NULL
              AND (is_trash = 0 OR is_trash IS NULL)
            ORDER BY exif_date, id
            """
        ).fetchall()


def clear_analysis(db_path: Optional[str], photo_id: int) -> None:
    """
    Cancella l'analisi costruita sulla posizione sbagliata.

    L'embedding va via insieme alla descrizione: era calcolato su quel testo,
    e lasciarlo significherebbe continuare a trovare la foto cercando il posto
    sbagliato. Posizione e dati inseriti dall'utente non si toccano.
    """
    with get_db(db_path) as conn:
        conn.execute(
            """
            UPDATE photos SET
                description = NULL, subject = NULL, atmosphere = NULL,
                colors = NULL, strengths = NULL, weaknesses = NULL,
                technical_score = NULL, aesthetic_score = NULL,
                overall_score = NULL, embedding = NULL, analyzed_at = NULL,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (photo_id,),
        )


def get_unanalyzed_photo_ids(db_path: Optional[str] = None,
                             folder_path: Optional[str] = None) -> list[int]:
    """
    Gli id delle foto che non hanno ancora un'analisi, eventualmente limitati
    a una cartella.

    Senza limite arbitrario: il chiamante precedente usava `limit=10000`, che
    su una cartella piu' grande avrebbe troncato senza dirlo.
    """
    sql = ["SELECT id FROM photos WHERE analyzed_at IS NULL",
           "AND (is_trash = 0 OR is_trash IS NULL)"]
    params: list = []
    if folder_path:
        sql.append("AND folder_path = ?")
        params.append(folder_path)
    sql.append("ORDER BY id")
    with get_db(db_path) as conn:
        return [r["id"] for r in conn.execute(" ".join(sql), params)]


def get_photo_ids_for_selection(db_path: Optional[str] = None, **filtri) -> dict:
    """
    Gli id di tutte le foto che corrispondono ai filtri, senza limite di pagina,
    piu' quelli che hanno gia' una posizione.

    La griglia ne carica cento per volta: per selezionarne settecento dovresti
    scorrere sette volte. Qui si prendono in un colpo solo, e si riportano
    anche gli id gia' posizionati perche' l'interfaccia possa dire quante foto
    verrebbero sovrascritte — esattamente, anche dopo che ne hai deselezionata
    qualcuna a mano.
    """
    conditions, params = _filtri_foto(**filtri)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with get_db(db_path) as conn:
        righe = conn.execute(
            f"SELECT id, latitude FROM photos {where} ORDER BY id", params
        ).fetchall()
    return {
        "ids": [r["id"] for r in righe],
        "con_posizione": [r["id"] for r in righe if r["latitude"] is not None],
    }


def bulk_set_location(db_path: Optional[str] = None,
                      *,
                      photo_ids: list,
                      latitude: float,
                      longitude: float,
                      location_name: Optional[str] = None,
                      overwrite: bool = False) -> dict:
    """
    Assegna la stessa posizione a molte foto in una sola transazione.

    Una PUT per foto, come fanno le altre azioni di massa, significherebbe
    settecento richieste contemporanee contro un pool di quaranta thread.

    Con `overwrite` falso le foto che hanno gia' una posizione restano intatte:
    il GPS della fotocamera vale piu' di un punto scelto a mano per un gruppo.
    """
    if not photo_ids:
        return {"aggiornate": 0, "saltate": 0, "mancanti": []}

    segnaposto = ",".join("?" * len(photo_ids))
    with get_db(db_path) as conn:
        esistenti = {
            r["id"]: r["latitude"] for r in conn.execute(
                f"SELECT id, latitude FROM photos WHERE id IN ({segnaposto})",
                list(photo_ids),
            )
        }
        mancanti = [pid for pid in photo_ids if pid not in esistenti]
        if overwrite:
            da_scrivere = list(esistenti)
        else:
            da_scrivere = [pid for pid, lat in esistenti.items() if lat is None]

        if da_scrivere:
            conn.execute(
                f"""UPDATE photos
                    SET latitude = ?, longitude = ?, location_name = ?,
                        location_source = 'manual', updated_at = datetime('now')
                    WHERE id IN ({",".join("?" * len(da_scrivere))})""",
                [latitude, longitude, location_name] + da_scrivere,
            )

    return {
        "aggiornate": len(da_scrivere),
        "saltate": len(esistenti) - len(da_scrivere),
        "mancanti": mancanti,
    }


def mark_location_confirmed(db_path: Optional[str] = None,
                            *, photo_ids: list) -> int:
    """
    Dichiara buona la posizione che la foto ha gia': la marca 'manual' e
    nient'altro. Ritorna quante ne sono state marcate.

    Serve al caso opposto della correzione: la posizione attuale e' giusta ed
    e' la proposta a sbagliare. Descrizione, embedding e analisi non si toccano
    — non c'e' niente da rifare, quindi non si spende nulla.

    'manual' e' fra le origini affidabili, quindi il rilevatore smette di
    discutere questa foto e la usa come ancora per giudicare le vicine.
    """
    if not photo_ids:
        return 0
    segnaposto = ",".join("?" * len(photo_ids))
    with get_db(db_path) as conn:
        cur = conn.execute(
            f"""UPDATE photos
                SET location_source = 'manual', updated_at = datetime('now')
                WHERE id IN ({segnaposto}) AND latitude IS NOT NULL""",
            list(photo_ids),
        )
        return cur.rowcount
