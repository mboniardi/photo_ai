"""
Prompt di analisi fotografica e parsing della risposta.
Condiviso da tutti i motori (Gemini, Groq, DeepSeek): nessun motore
deve dipendere da un altro motore.
"""
import json
import re

_REQUIRED_FIELDS = {
    "descrizione", "punteggio_tecnico", "punteggio_estetico",
    "soggetto", "atmosfera", "colori_dominanti",
    "punti_di_forza", "punti_di_debolezza",
    "luogo_riconosciuto", "luogo_lat", "luogo_lon",
}


def build_prompt(location_hint: str) -> str:
    location_section = ""
    if location_hint:
        location_section = f"\n[CONTESTO GEOGRAFICO: {location_hint} — usa queste informazioni per arricchire la descrizione con il contesto geografico e storico del luogo.]"

    return f"""Sei un critico fotografico esperto. Analizza questa fotografia e rispondi ESCLUSIVAMENTE con un oggetto JSON valido (nessun testo aggiuntivo, nessun markdown, nessun delimitatore).

Se riconosci il luogo specifico nella foto (monumento, città, sito storico, paesaggio noto), nominalo esplicitamente nella descrizione.

{{
  "descrizione": "Descrizione in italiano, 2-4 frasi. Descrivi concretamente: soggetti presenti (persone, animali, oggetti), azioni in corso, dettagli visivi rilevanti, contesto geografico o storico se riconoscibile. Evita descrizioni puramente atmosferiche. Se riconosci il luogo specifico nominalo esplicitamente (es. 'Il Tempio di Kom Ombo...' o 'La Torre Eiffel...').",
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


def parse_response(text: str) -> dict:
    """
    Estrae il JSON dalla risposta del modello, rimuovendo eventuali code fence.
    Solleva ValueError se il JSON non è valido o mancano campi obbligatori.
    """
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
