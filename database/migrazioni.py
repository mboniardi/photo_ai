"""
Migrazioni leggere dello schema SQLite.
init_db() esegue solo CREATE TABLE IF NOT EXISTS: le colonne nuove su un
database esistente vanno aggiunte esplicitamente con assicura_colonne().
"""
from typing import Optional
from database import get_db

# Il nome della tabella non puo' essere un parametro legato: si interpola,
# quindi sono ammessi solo nomi noti.
TABELLE_AMMESSE = {"photos", "folders", "analysis_queue", "settings", "doppioni_sospetti"}


def assicura_colonne(db_path: Optional[str], tabella: str, colonne: dict[str, str]) -> list[str]:
    """
    Aggiunge con ALTER TABLE ... ADD COLUMN solo le colonne assenti.
    `colonne` mappa nome -> definizione SQL (es. {"phash": "TEXT"}).
    Ritorna i nomi delle colonne effettivamente aggiunte.
    """
    if tabella not in TABELLE_AMMESSE:
        raise ValueError(f"Tabella non ammessa: {tabella!r}")
    aggiunte: list[str] = []
    with get_db(db_path) as conn:
        esistenti = {r[1] for r in conn.execute(f"PRAGMA table_info({tabella})")}
        for nome, definizione in colonne.items():
            if nome not in esistenti:
                conn.execute(f"ALTER TABLE {tabella} ADD COLUMN {nome} {definizione}")
                aggiunte.append(nome)
    return aggiunte
