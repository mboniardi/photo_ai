"""
Revisione dei doppioni sospetti tra foto Google e foto NAS.

L'import registra qui i casi in cui non sa decidere se una foto dell'archivio
sia gia' nel catalogo. Unire due foto diverse ne perderebbe una per sempre,
tenerne una in piu' costa poco: la decisione spetta a chi guarda.
"""
from typing import Optional

from database import get_db
from services import derivati
from services.takeout_import import coordinate_vincono


class SospettoNonTrovato(LookupError):
    """Il sospetto (o una delle due foto) non esiste."""


class SospettoGiaRisolto(ValueError):
    """Il sospetto non e' piu' 'pending': qualcuno l'ha gia' deciso."""


def elenca_sospetti(db_path: Optional[str], stato: str = "pending") -> list:
    """Sospetti nello stato dato, con le due foto affiancate."""
    with get_db(db_path) as conn:
        righe = conn.execute(
            """
            SELECT s.id, s.motivo, s.distanza, s.stato, s.creato_at,
                   s.photo_id_google, g.filename AS filename_google,
                   g.folder_path AS album_google,
                   s.photo_id_nas, n.filename AS filename_nas,
                   n.folder_path AS album_nas
            FROM doppioni_sospetti s
            JOIN photos g ON g.id = s.photo_id_google
            JOIN photos n ON n.id = s.photo_id_nas
            WHERE s.stato = ?
            ORDER BY s.id
            """,
            (stato,),
        ).fetchall()
    return [dict(r) for r in righe]


def risolvi(db_path: Optional[str], sospetto_id: int, stessa_foto: bool) -> dict:
    """
    stessa_foto=True: le coordinate Google passano alla riga NAS (solo se la
    precedenza lo consente), la riga Google sparisce coi suoi derivati.
    stessa_foto=False: la riga Google resta e solo ora entra in coda AI.
    Un sospetto si risolve una volta sola; un errore annulla tutto.
    """
    with get_db(db_path) as conn:
        # Con le chiavi esterne attive la riga Google non si potrebbe togliere
        # finche' il sospetto la cita, e il sospetto resta come traccia della
        # decisione. Il pragma vale solo fuori da una transazione.
        conn.execute("PRAGMA foreign_keys=OFF")
        nuovo_stato = "risolto" if stessa_foto else "respinto"
        # Prenotazione atomica: solo chi la vince prosegue (due click, due
        # richieste insieme). La scrittura apre la transazione.
        preso = conn.execute(
            "UPDATE doppioni_sospetti SET stato = ? WHERE id = ? AND stato = 'pending'",
            (nuovo_stato, sospetto_id),
        ).rowcount
        if not preso:
            esiste = conn.execute(
                "SELECT 1 FROM doppioni_sospetti WHERE id = ?", (sospetto_id,)
            ).fetchone()
            if esiste is None:
                raise SospettoNonTrovato(f"Sospetto {sospetto_id} inesistente")
            raise SospettoGiaRisolto(f"Sospetto {sospetto_id} gia' risolto")

        s = conn.execute(
            "SELECT photo_id_google, photo_id_nas FROM doppioni_sospetti WHERE id = ?",
            (sospetto_id,),
        ).fetchone()
        google = conn.execute(
            "SELECT id, latitude, longitude FROM photos WHERE id = ?",
            (s["photo_id_google"],),
        ).fetchone()
        nas = conn.execute(
            "SELECT id, location_source FROM photos WHERE id = ?",
            (s["photo_id_nas"],),
        ).fetchone()
        if google is None or nas is None:
            raise SospettoNonTrovato(f"Foto del sospetto {sospetto_id} mancante")

        coordinate = False
        if stessa_foto:
            if (google["latitude"] is not None and google["longitude"] is not None
                    and coordinate_vincono(nas["location_source"])):
                conn.execute(
                    "UPDATE photos SET latitude = ?, longitude = ?, "
                    "location_source = 'takeout', updated_at = datetime('now') WHERE id = ?",
                    (google["latitude"], google["longitude"], nas["id"]),
                )
                coordinate = True
            # Gli altri sospetti sulla stessa foto Google non hanno piu' oggetto.
            conn.execute(
                "UPDATE doppioni_sospetti SET stato = 'obsoleto' "
                "WHERE photo_id_google = ? AND stato = 'pending'",
                (google["id"],),
            )
            conn.execute("DELETE FROM analysis_queue WHERE photo_id = ?", (google["id"],))
            conn.execute("DELETE FROM photos WHERE id = ?", (google["id"],))
        else:
            # Stessa regola di add_to_queue: niente doppioni in coda.
            if not conn.execute(
                "SELECT 1 FROM analysis_queue WHERE photo_id = ? "
                "AND status IN ('pending', 'processing')", (google["id"],)
            ).fetchone():
                conn.execute(
                    "INSERT INTO analysis_queue (photo_id, priority, status) "
                    "VALUES (?, 5, 'pending')", (google["id"],))

    # I file non si annullano con la transazione: si toccano solo a commit fatto.
    if stessa_foto:
        derivati.cancella(google["id"])
    return {"id": sospetto_id, "stato": nuovo_stato,
            "stessa_foto": stessa_foto, "coordinate_passate": coordinate}
