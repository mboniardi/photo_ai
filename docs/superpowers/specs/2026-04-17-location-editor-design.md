# Design: Location Editor per Foto

**Data:** 2026-04-17  
**Stato:** Approvato

---

## Sommario

Aggiungere la possibilità di correggere manualmente le coordinate geografiche di una foto tramite un modale con mappa interattiva Leaflet + geocoding Nominatim (OpenStreetMap). Zero dipendenze a pagamento, zero API key.

---

## UI del Modale

Il modale si apre dal pannello dettaglio del lightbox tramite un pulsante "Modifica posizione" (icona matita) accanto alla sezione location esistente.

**Dimensioni:** 600×520px  
**Struttura:**

```
┌─────────────────────────────────────────────────────┐
│  Modifica posizione                              [×] │
├─────────────────────────────────────────────────────┤
│  [🔍 Cerca un luogo...                            ] │
│                                                     │
│  ┌───────────────────────────────────────────────┐  │
│  │                                               │  │
│  │            MAPPA LEAFLET (400px)              │  │
│  │                 [📍 pin drag]                 │  │
│  │                                               │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  Luogo rilevato: [Cairo, Egypt              ] (read)│
│  Coordinate:     45.4654° N, 9.1859° E      (read)  │
│                                                     │
│          [Annulla]          [Salva posizione]        │
└─────────────────────────────────────────────────────┘
```

**Comportamenti dell'apertura:**
- Se la foto ha già coordinate → mappa centrata su di esse, pin posizionato
- Se la foto non ha coordinate → vista mondiale (zoom 2), nessun pin finché l'utente non interagisce

---

## Interazioni Utente

| Azione | Effetto |
|--------|---------|
| Click sulla mappa | Sposta pin → aggiorna coordinate → trigger reverse geocoding |
| Drag del pin | Stessa logica di click (su `dragend`, non durante il drag) |
| Digitare nella barra di ricerca | Debounce 500ms → forward geocoding Nominatim → centra mappa, sposta pin |
| "Salva posizione" | `PUT /api/photos/{id}` con `{latitude, longitude, location_name}` → chiude modale → aggiorna lightbox |
| "Annulla" o [×] | Scarta modifiche temporanee, chiude modale |

---

## Architettura Tecnica

### Frontend (index.html)

**Dipendenze aggiunte (CDN, in `<head>`):**
```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

**Nuovo modale:** `#location-editor-modal`  
- Input ricerca (`#location-search`)  
- Div mappa (`#location-map`)  
- Label "Luogo rilevato" (`#location-detected`)  
- Label coordinate (`#location-coords`)  
- Bottoni Annulla / Salva

**Funzioni JavaScript:**

- `openLocationEditor(photoId, lat, lon)` — lazy-init mappa Leaflet, posiziona pin se coordinate presenti
- `reverseGeocode(lat, lon)` — `fetch` Nominatim `/reverse` → aggiorna `#location-detected`
- `searchLocation(query)` — `fetch` Nominatim `/search` → sposta mappa e pin al primo risultato
- `saveLocation()` — `apiPut(/api/photos/{id}, {latitude, longitude, location_name})` → aggiorna UI lightbox

**Variabili di stato temporanee:**  
`pendingLat`, `pendingLon`, `pendingName` — scartate su Annulla, persistite su Salva.

**Lazy init:** Leaflet viene inizializzato solo alla prima apertura del modale, non al caricamento della pagina.

### Backend

**Nessuna modifica agli endpoint esistenti** — `PUT /api/photos/{id}` accetta già `latitude`, `longitude`, `location_name`.

**Unica aggiunta backend:**  
Aggiungere `location_source: Optional[str]` a `PhotoUpdateRequest` (api/photos.py) e propagarlo in `update_photo()` (database/photos.py), per tracciare `"manual"` quando la posizione è impostata dall'utente.

### Nominatim — Policy di utilizzo

- Header `User-Agent: photo-catalog/1.0` obbligatorio in tutte le richieste
- Rate limit: 1 req/sec → garantito da debounce 500ms (ricerca) e trigger solo su `dragend` (reverse)
- Endpoint base: `https://nominatim.openstreetmap.org/`

---

## Gestione Errori

| Scenario | Comportamento |
|----------|---------------|
| Nominatim non raggiungibile (ricerca) | Messaggio "Luogo non trovato" sotto l'input, pin non si sposta |
| Reverse geocoding fallito | Coordinate salvabili comunque, `location_name` mantiene il valore `pendingName` precedente (non si azzera) |
| Salvataggio API fallito | Toast di errore "Errore nel salvataggio della posizione", modale rimane aperto |
| Chiusura senza salvare | Variabili temporanee scartate, nessuna modifica persistita |

---

## Tracciamento Origine Location

Il campo `location_source` viene impostato a `"manual"` al salvataggio. Valori esistenti: `"exif"`, `"takeout"`. Questo permette in futuro di proteggere le coordinate manuali da sovrascritture automatiche (es. re-import Takeout).

---

## File Coinvolti

| File | Modifica |
|------|----------|
| `static/index.html` | Aggiunta CDN Leaflet, modale HTML, funzioni JS |
| `api/photos.py` | Aggiunta `location_source` a `PhotoUpdateRequest` |
| `database/photos.py` | Propagazione `location_source` in `update_photo()` |
