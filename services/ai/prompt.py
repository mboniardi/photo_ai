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


def _estrai_json(text: str):
    """Toglie gli eventuali delimitatori markdown e decodifica il JSON."""
    ripulito = re.sub(r"^```(?:json)?\s*", "", (text or "").strip(), flags=re.MULTILINE)
    ripulito = re.sub(r"\s*```$", "", ripulito.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(ripulito)
    except json.JSONDecodeError as e:
        raise ValueError(f"Risposta AI non è JSON valido: {e}\nTesto: {(text or '')[:200]}") from e


def parse_response(text: str) -> dict:
    """
    Estrae il JSON dalla risposta del modello, rimuovendo eventuali code fence.
    Solleva ValueError se il JSON non è valido o mancano campi obbligatori.
    """
    data = _estrai_json(text)

    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(f"Campi mancanti nella risposta AI: {missing}")

    return data


def build_location_prompt(n: int) -> str:
    """
    Chiede SOLO il luogo, guardando molte fotografie insieme.

    Una fotografia isolata di un muro inciso e' irriconoscibile; in mezzo ad
    altre sette dello stesso tempio diventa ovvia. Misurato: da sola il modello
    rispondeva null, in gruppo ha identificato il luogo esatto.
    """
    return f"""Ti invio {n} fotografie scattate dalla stessa persona nello STESSO LUOGO, a pochi minuti l'una dall'altra.

Identifica il luogo. Se lo riconosci anche in una sola di esse, vale per tutte.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, senza testo aggiuntivo e senza markdown:
{{"luogo_riconosciuto": "<nome del luogo specifico, oppure null se non lo riconosci>", "luogo_lat": <latitudine approssimativa o null>, "luogo_lon": <longitudine approssimativa o null>}}"""


def parse_location_response(text: str) -> dict:
    """Estrae il luogo dalla risposta. Solleva ValueError se il JSON non e' valido."""
    data = _estrai_json(text)
    if not isinstance(data, dict):
        raise ValueError(f"Risposta luogo non e' un oggetto JSON: {text[:200]}")
    return {
        "luogo_riconosciuto": data.get("luogo_riconosciuto"),
        "luogo_lat": data.get("luogo_lat"),
        "luogo_lon": data.get("luogo_lon"),
    }


def build_group_prompt(n: int, luogo: str, min_caratteri: int = 350) -> str:
    """
    Descrive un blocco di fotografie di cui il luogo e' GIA' NOTO.

    Le due leve che allungano le descrizioni: il luogo dato libera il modello
    dal doverlo dedurre, e il requisito esplicito di lunghezza lo costringe a
    spendere quel budget in dettaglio. Misurato: da 246 a 617 caratteri.
    """
    return f"""Sei un critico fotografico esperto.

Ti invio {n} fotografie scattate dalla stessa persona nello stesso luogo, a pochi minuti l'una dall'altra.
IL LUOGO E' GIA' NOTO E CERTO: {luogo}. Non devi identificarlo: usalo per arricchire ogni descrizione con il contesto storico e geografico.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, senza testo aggiuntivo e senza markdown:
{{
  "foto": [
    {{
      "n": <indice progressivo da 1, nell'ordine in cui hai ricevuto le foto>,
      "descrizione": "<4-5 frasi in italiano, ALMENO {min_caratteri} caratteri. Descrivi concretamente: soggetti presenti (persone, animali, oggetti), azioni in corso, dettagli visivi specifici di QUESTA foto (materiali, colori, iscrizioni, luce), composizione, e il contesto storico del luogo.>",
      "punteggio_tecnico": <intero 1-10: messa a fuoco, esposizione, rumore, nitidezza>,
      "punteggio_estetico": <intero 1-10: composizione, luce, impatto emotivo, equilibrio>,
      "soggetto": "<soggetto principale in 3-5 parole>",
      "atmosfera": "<una parola>",
      "colori_dominanti": ["<colore1>", "<colore2>", "<colore3>"],
      "punti_di_forza": "<cosa funziona bene, 1-2 frasi>",
      "punti_di_debolezza": "<cosa potrebbe migliorare, 1-2 frasi, oppure null>"
    }}
  ]
}}

L'array "foto" deve contenere ESATTAMENTE {n} elementi, uno per ogni foto ricevuta, nello stesso ordine.
Ogni descrizione deve superare i {min_caratteri} caratteri: e' un requisito, non un suggerimento.
Due foto dello stesso posto devono avere descrizioni chiaramente diverse fra loro."""


def parse_group_response(text: str, attese: int) -> list:
    """
    Estrae e VALIDA le voci di un blocco.

    La validazione e' rigida di proposito: un blocco accettato a meta' scrive
    la descrizione della foto 3 sulla foto 7. Meglio scartare tutto il blocco e
    ricadere sulle chiamate singole — costa tempo, mai dati sbagliati.
    """
    data = _estrai_json(text)
    voci = data.get("foto") if isinstance(data, dict) else None
    if not isinstance(voci, list):
        raise ValueError(f"Risposta di gruppo senza array 'foto': {text[:200]}")
    if len(voci) != attese:
        raise ValueError(f"Attese {attese} voci, ricevute {len(voci)}")

    indici = sorted(v.get("n") for v in voci)
    if indici != list(range(1, attese + 1)):
        raise ValueError(f"indici incompleti o duplicati: {indici}")

    descrizioni = [(v.get("descrizione") or "").strip() for v in voci]
    if not all(descrizioni):
        raise ValueError("Una o piu' descrizioni sono vuote")
    if len(set(descrizioni)) != attese:
        raise ValueError("Le descrizioni non sono distinte fra loro")

    for v in voci:
        mancanti = {"punteggio_tecnico", "punteggio_estetico"} - set(v.keys())
        if mancanti:
            raise ValueError(f"Campi mancanti nella voce {v.get('n')}: {mancanti}")

    return sorted(voci, key=lambda v: v["n"])
