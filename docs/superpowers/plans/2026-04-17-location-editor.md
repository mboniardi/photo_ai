# Location Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere un modale con mappa Leaflet interattiva per correggere le coordinate geografiche di una foto, con geocoding/reverse geocoding via Nominatim.

**Architecture:** Il backend espone già `PUT /api/photos/{id}` con `latitude`, `longitude`, `location_name`; si aggiunge solo `location_source` a `PhotoUpdateRequest`. Il frontend aggiunge un modale Vue con mappa Leaflet (già inclusa via CDN), stato temporaneo `locationEditor`, funzioni JS per geocoding Nominatim e salvataggio.

**Tech Stack:** FastAPI (backend), Vue 3 setup() (frontend), Leaflet 1.9.4 (già incluso), Nominatim OpenStreetMap (geocoding gratuito, nessuna API key), pytest + FastAPI TestClient (test backend).

---

## File Structure

| File | Modifica |
|------|----------|
| `api/photos.py` | Aggiunta `location_source: Optional[str] = None` a `PhotoUpdateRequest` |
| `database/photos.py` | Nessuna modifica — `update_photo(**fields)` già accetta qualsiasi campo |
| `static/index.html` | Modale HTML, funzioni JS, pulsante nel lightbox |
| `tests/test_api_photos.py` | Test per `location_source` |

---

## Task 1: Backend — Aggiungi `location_source` a `PhotoUpdateRequest`

**Files:**
- Modify: `api/photos.py`
- Test: `tests/test_api_photos.py`

- [ ] **Step 1: Scrivi il test che fallisce**

Aggiungi questa classe in fondo a `tests/test_api_photos.py`:

```python
class TestUpdatePhotoLocation:
    def test_set_location_with_source(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.put(f"/api/photos/{pid}", json={
            "latitude": 30.0444,
            "longitude": 31.2357,
            "location_name": "Cairo, Egypt",
            "location_source": "manual",
        })
        assert resp.status_code == 200
        data = c.get(f"/api/photos/{pid}").json()
        assert data["latitude"] == pytest.approx(30.0444, abs=1e-4)
        assert data["longitude"] == pytest.approx(31.2357, abs=1e-4)
        assert data["location_name"] == "Cairo, Egypt"
        assert data["location_source"] == "manual"

    def test_location_source_not_required(self, client_with_photo):
        c, pid, _ = client_with_photo
        resp = c.put(f"/api/photos/{pid}", json={
            "latitude": 41.9028,
            "longitude": 12.4964,
            "location_name": "Roma, Italia",
        })
        assert resp.status_code == 200
```

- [ ] **Step 2: Esegui il test per verificare che fallisce**

```bash
cd /Users/mboniardi/Documents/svn/photo_catalog/photo_ai
pytest tests/test_api_photos.py::TestUpdatePhotoLocation -v
```

Output atteso: `FAILED` — `location_source` è un campo sconosciuto nel modello Pydantic (validation error 422) oppure semplicemente ignorato e non salvato.

- [ ] **Step 3: Implementa la modifica in `api/photos.py`**

Cambia `PhotoUpdateRequest` da:

```python
class PhotoUpdateRequest(BaseModel):
    is_favorite: Optional[int] = None
    is_trash: Optional[int] = None
    user_description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
```

a:

```python
class PhotoUpdateRequest(BaseModel):
    is_favorite: Optional[int] = None
    is_trash: Optional[int] = None
    user_description: Optional[str] = None
    location_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_source: Optional[str] = None
```

- [ ] **Step 4: Esegui i test per verificare che passano**

```bash
cd /Users/mboniardi/Documents/svn/photo_catalog/photo_ai
pytest tests/test_api_photos.py -v
```

Output atteso: tutti `PASSED`.

- [ ] **Step 5: Commit**

```bash
cd /Users/mboniardi/Documents/svn/photo_catalog/photo_ai
git add api/photos.py tests/test_api_photos.py
git commit -m "feat: add location_source field to PhotoUpdateRequest"
```

---

## Task 2: Frontend — Modale HTML

**Files:**
- Modify: `static/index.html` (sezione HTML, prima di `</div><!-- #app -->`)

Il modale usa le classi CSS `modal-overlay` / `modal` / `modal-title` / `modal-footer` / `btn-primary` / `btn-secondary` / `form-input` già esistenti nel CSS del file.

- [ ] **Step 1: Aggiungi il modale HTML prima di `</div><!-- #app -->`**

Trova la riga `</div><!-- #app -->` (attualmente riga ~1227) e inserisci prima di essa:

```html
    <!-- ─── LOCATION EDITOR MODAL ─── -->
    <div v-if="locationEditor.open" class="modal-overlay" @click.self="closeLocationEditor">
      <div class="modal" style="max-width:600px">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px">
          <div class="modal-title" style="margin-bottom:0">Modifica posizione</div>
          <button @click="closeLocationEditor" style="background:none;border:none;color:var(--muted);font-size:18px;cursor:pointer;padding:0 4px">✕</button>
        </div>

        <!-- Search -->
        <div class="form-group" style="margin-bottom:8px">
          <input
            class="form-input"
            v-model="locationEditor.searchQuery"
            @input="onLocationSearchInput"
            placeholder="Cerca un luogo…"
            style="width:100%"
          />
          <div v-if="locationEditor.searchError" style="color:var(--amber);font-size:12px;margin-top:4px">
            {{ locationEditor.searchError }}
          </div>
        </div>

        <!-- Map -->
        <div id="location-map" style="height:350px;border-radius:8px;overflow:hidden;margin-bottom:12px;border:1px solid var(--border)"></div>

        <!-- Info -->
        <div style="font-size:12px;color:var(--muted);margin-bottom:4px">
          <strong style="color:var(--text)">Luogo:</strong>
          {{ locationEditor.pendingName || '—' }}
        </div>
        <div style="font-size:12px;color:var(--muted);margin-bottom:16px">
          <strong style="color:var(--text)">Coordinate:</strong>
          <span v-if="locationEditor.pendingLat != null">
            {{ locationEditor.pendingLat.toFixed(4) }}° N, {{ locationEditor.pendingLon.toFixed(4) }}° E
          </span>
          <span v-else>—</span>
        </div>

        <div class="modal-footer">
          <button class="btn-secondary" @click="closeLocationEditor">Annulla</button>
          <button
            class="btn-primary"
            @click="saveLocation"
            :disabled="locationEditor.saving || locationEditor.pendingLat == null"
          >{{ locationEditor.saving ? 'Salvataggio…' : 'Salva posizione' }}</button>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Verifica visiva nel browser**

Apri l'app. Nessun cambiamento visivo atteso (il modale è nascosto). Verifica che non ci siano errori Vue in console.

---

## Task 3: Frontend — Funzioni JS

**Files:**
- Modify: `static/index.html` (sezione `<script>`, dentro `setup()`)

- [ ] **Step 1: Aggiungi lo stato `locationEditor` e le variabili Leaflet**

Trova il blocco `/* TOAST */` in cima a `setup()` (riga ~1255) e aggiungi subito dopo il blocco `/* USER */`:

```javascript
    /* LOCATION EDITOR */
    const locationEditor = reactive({
      open: false,
      photoId: null,
      pendingLat: null,
      pendingLon: null,
      pendingName: '',
      searchQuery: '',
      searchError: '',
      saving: false,
    });
    let _leafletMap = null;
    let _leafletMarker = null;
    let _searchDebounceTimer = null;
```

- [ ] **Step 2: Aggiungi le funzioni JS**

Trova la funzione `saveDescription()` (riga ~1571) e aggiungi subito dopo il blocco seguente:

```javascript
    function openLocationEditor() {
      if (!lightbox.photo) return;
      locationEditor.photoId   = lightbox.photo.id;
      locationEditor.pendingLat = lightbox.photo.latitude  ?? null;
      locationEditor.pendingLon = lightbox.photo.longitude ?? null;
      locationEditor.pendingName = lightbox.photo.location_name || '';
      locationEditor.searchQuery = '';
      locationEditor.searchError = '';
      locationEditor.saving = false;
      locationEditor.open = true;
      nextTick(() => { _initLeafletMap(); });
    }

    function closeLocationEditor() {
      locationEditor.open = false;
    }

    function _initLeafletMap() {
      if (!_leafletMap) {
        _leafletMap = L.map('location-map');
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '© OpenStreetMap contributors',
          maxZoom: 19,
        }).addTo(_leafletMap);
        _leafletMap.on('click', (e) => {
          _placePin(e.latlng.lat, e.latlng.lng);
          reverseGeocode(e.latlng.lat, e.latlng.lng);
        });
      }
      if (_leafletMarker) {
        _leafletMap.removeLayer(_leafletMarker);
        _leafletMarker = null;
      }
      if (locationEditor.pendingLat != null && locationEditor.pendingLon != null) {
        _leafletMap.setView([locationEditor.pendingLat, locationEditor.pendingLon], 13);
        _placePin(locationEditor.pendingLat, locationEditor.pendingLon);
      } else {
        _leafletMap.setView([20, 0], 2);
      }
      _leafletMap.invalidateSize();
    }

    function _placePin(lat, lon) {
      locationEditor.pendingLat = lat;
      locationEditor.pendingLon = lon;
      if (_leafletMarker) {
        _leafletMarker.setLatLng([lat, lon]);
      } else {
        _leafletMarker = L.marker([lat, lon], { draggable: true }).addTo(_leafletMap);
        _leafletMarker.on('dragend', (e) => {
          const pos = e.target.getLatLng();
          locationEditor.pendingLat = pos.lat;
          locationEditor.pendingLon = pos.lng;
          reverseGeocode(pos.lat, pos.lng);
        });
      }
    }

    async function reverseGeocode(lat, lon) {
      try {
        const resp = await fetch(
          `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`,
          { headers: { 'User-Agent': 'photo-catalog/1.0' } }
        );
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.display_name) locationEditor.pendingName = data.display_name;
      } catch { /* keep existing pendingName */ }
    }

    function onLocationSearchInput() {
      locationEditor.searchError = '';
      clearTimeout(_searchDebounceTimer);
      if (!locationEditor.searchQuery.trim()) return;
      _searchDebounceTimer = setTimeout(() => searchLocation(locationEditor.searchQuery), 500);
    }

    async function searchLocation(query) {
      try {
        const resp = await fetch(
          `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`,
          { headers: { 'User-Agent': 'photo-catalog/1.0' } }
        );
        if (!resp.ok) throw new Error('network');
        const data = await resp.json();
        if (!data.length) { locationEditor.searchError = 'Luogo non trovato'; return; }
        const { lat, lon, display_name } = data[0];
        _leafletMap.setView([parseFloat(lat), parseFloat(lon)], 13);
        _placePin(parseFloat(lat), parseFloat(lon));
        locationEditor.pendingName = display_name;
      } catch { locationEditor.searchError = 'Luogo non trovato'; }
    }

    async function saveLocation() {
      if (!locationEditor.photoId || locationEditor.pendingLat == null) return;
      locationEditor.saving = true;
      const result = await apiPut(`/api/photos/${locationEditor.photoId}`, {
        latitude: locationEditor.pendingLat,
        longitude: locationEditor.pendingLon,
        location_name: locationEditor.pendingName,
        location_source: 'manual',
      });
      locationEditor.saving = false;
      if (!result?.ok) {
        showToast('Errore nel salvataggio della posizione', 'error');
        return;
      }
      lightbox.photo.latitude      = locationEditor.pendingLat;
      lightbox.photo.longitude     = locationEditor.pendingLon;
      lightbox.photo.location_name = locationEditor.pendingName;
      locationEditor.open = false;
      showToast('Posizione aggiornata', 'success');
    }
```

- [ ] **Step 3: Esponi le funzioni nel `return` di `setup()`**

Trova la riga che contiene `saveDescription, toggleFavorite, toggleTrash, reanalyze,` (riga ~1987) e aggiungi prima della riga `scoreClass, scoreColor`:

```javascript
      locationEditor, openLocationEditor, closeLocationEditor,
      onLocationSearchInput, saveLocation,
```

- [ ] **Step 4: Verifica che non ci siano errori Vue in console**

Apri l'app nel browser, verifica console pulita.

---

## Task 4: Frontend — Pulsante "Modifica posizione" nel lightbox

**Files:**
- Modify: `static/index.html` (sezione lightbox, riga ~961)

- [ ] **Step 1: Aggiorna la sezione Location nel lightbox**

Trova il blocco (righe ~961-970):

```html
          <!-- Location -->
          <div v-if="lightbox.photo.location_name || lightbox.photo.latitude">
            <div class="lb-section-title">Location</div>
            <span style="font-size:12px">{{ lightbox.photo.location_name || 'Unknown' }}</span>
            <a
              v-if="lightbox.photo.latitude && lightbox.photo.longitude"
              :href="`https://www.openstreetmap.org/?mlat=${lightbox.photo.latitude}&mlon=${lightbox.photo.longitude}&zoom=14`"
              target="_blank"
              style="margin-left:8px; color:var(--amber); font-size:11px; text-decoration:none"
            >View map ↗</a>
          </div>
```

Sostituiscilo con:

```html
          <!-- Location -->
          <div>
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px">
              <div class="lb-section-title" style="margin-bottom:0">Location</div>
              <button
                @click="openLocationEditor"
                style="background:none;border:none;color:var(--muted);font-size:11px;cursor:pointer;padding:2px 6px;border-radius:4px;border:1px solid var(--border)"
                title="Modifica posizione"
              >✏ Modifica</button>
            </div>
            <span style="font-size:12px">{{ lightbox.photo.location_name || '—' }}</span>
            <a
              v-if="lightbox.photo.latitude && lightbox.photo.longitude"
              :href="`https://www.openstreetmap.org/?mlat=${lightbox.photo.latitude}&mlon=${lightbox.photo.longitude}&zoom=14`"
              target="_blank"
              style="margin-left:8px; color:var(--amber); font-size:11px; text-decoration:none"
            >View map ↗</a>
          </div>
```

- [ ] **Step 2: Test manuale — apertura modale**

1. Apri l'app
2. Clicca su una foto con coordinate nel lightbox → sezione Location mostra "✏ Modifica"
3. Clicca "✏ Modifica" → il modale si apre con la mappa centrata sulla posizione esistente e il pin posizionato
4. Verifica che "Luogo:" e "Coordinate:" mostrino i valori corretti

- [ ] **Step 3: Test manuale — foto senza coordinate**

1. Clicca su una foto senza coordinate
2. Sezione Location mostra "—" e il pulsante "✏ Modifica"
3. Apri il modale → mappa a vista mondiale (zoom 2), nessun pin, "Coordinate: —"

- [ ] **Step 4: Test manuale — click sulla mappa**

1. Apri il modale
2. Clicca su un punto sulla mappa → il pin appare, coordinate si aggiornano
3. Dopo ~1s il campo "Luogo:" si aggiorna con il nome del luogo via reverse geocoding

- [ ] **Step 5: Test manuale — ricerca testuale**

1. Digita "Piazza Navona Roma" nella barra di ricerca
2. Dopo 500ms la mappa si centra su Roma, il pin si sposta, "Luogo:" si aggiorna

- [ ] **Step 6: Test manuale — salvataggio**

1. Posiziona il pin su un luogo
2. Clicca "Salva posizione"
3. Il modale si chiude, la sezione Location nel lightbox mostra il nuovo nome
4. Chiudi e riapri la foto → la posizione è persistita

- [ ] **Step 7: Test manuale — drag del pin**

1. Apri il modale su una foto con coordinate
2. Trascina il pin su un'altra posizione
3. Al termine del drag, coordinate e nome si aggiornano

- [ ] **Step 8: Commit**

```bash
cd /Users/mboniardi/Documents/svn/photo_catalog/photo_ai
git add static/index.html
git commit -m "feat: add location editor modal with Leaflet map and Nominatim geocoding"
```
