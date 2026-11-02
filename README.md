# 🏔️ Rishikesh Urban Intelligence

Find out **where Rishikesh burns most, which neighbourhoods are under-served, and where to act first** – then explore it
all in an interactive, scroll-through dashboard (English or Hinglish).

* 🔥 **Heat** – land-surface temperature from Landsat 8/9 (Microsoft Planetary Computer, no login needed)
* 🌳 **Greenery** – NDVI and how much cooler greener cells are
* 🏥 **Amenity access** – hospitals, schools, markets, banks, transport, parks, water/toilets (your GeoPackage and/or OpenStreetMap)
* 🎓 **Education & health**, 💰 **economy**, 🚦 **mobility** indices (transparent proxies – or plug in your real census / survey columns)
* ⚠️ **Priority zones** – cells that are *both* hot *and* poorly served, with the people living there
* 📦 Outputs: dashboard (`.html`), 4 interactive Folium maps, results GeoPackage/CSV, overview PNG, `summary.json`

Three ways to use it: **web app** (upload a file in the browser), **command line**, or **Python / Colab**.

---

## 1 · Quick start (2 minutes, no data needed)

```bash
git clone https://github.com/YOUR_USER/rishikesh-urban-intelligence.git
cd rishikesh-urban-intelligence
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

rishikesh-urban run --config data/sample/config.sample.yaml   # offline demo
# → open output/demo/Rishikesh_Dashboard.html
```

> ⚠️ `data/sample/demo_city.gpkg` is **synthetic** (made-up wards, population, temperatures and amenities). It only shows the
> expected layer structure. Do not draw conclusions from it.

### Web app

```bash
rishikesh-urban serve            # http://127.0.0.1:8000
```

Upload a `.gpkg` (or tick *demo data*), pick options, press **Run analysis**. A progress bar and live log follow; when it
finishes you get the dashboard, maps and downloads. Jobs live in `./jobs` (override with `RUI_DATA_DIR`).

### Command line (your own data)

```bash
rishikesh-urban run my_city.gpkg --language English --out-dir output/my_city
rishikesh-urban run --gpkg my_city.gpkg --heat-column LST_C --no-use-ndvi
rishikesh-urban run --help        # every setting is a flag
```

No GeoPackage at all? `rishikesh-urban run` analyses a 10 km circle around Rishikesh using OpenStreetMap only
(no population numbers in that mode).

### Python / Google Colab

```python
from rishikesh_urban import Config, run_pipeline
res = run_pipeline(Config(gpkg="my_city.gpkg", language="Hinglish", out_dir="output"))
res.ctx.units.head()             # GeoDataFrame with every computed column
```
See [`notebooks/colab_quickstart.ipynb`](notebooks/colab_quickstart.ipynb). Your original notebook is preserved in
[`notebooks/original/`](notebooks/original/).

---

## 2 · Deploy it

The app is a standard Flask app served by gunicorn. **One worker, several threads** (job state is kept on disk and
analyses run in a background thread pool).

| Where | How |
|---|---|
| **Docker (anywhere)** | `docker build -t rishikesh-urban . && docker run -p 8000:8000 -v rui-data:/data rishikesh-urban` or `docker compose up --build` |
| **Render** | *New ▸ Blueprint* → pick the repo (`render.yaml` is included). Use ≥ 2 GB RAM for real Landsat runs. |
| **Railway / Heroku / Koyeb** | Uses the `Procfile`. Set `RUI_DATA_DIR` to a persistent volume if you want results to survive restarts. |
| **VPS (Ubuntu)** | `pip install .` then `gunicorn "rishikesh_urban.app:get_app()" --bind 0.0.0.0:8000 --workers 1 --threads 8 --timeout 300` behind nginx/Caddy. |

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | Port (Docker/Procfile) |
| `RUI_DATA_DIR` | `jobs` (`/data` in Docker) | Where uploads and results are stored |
| `RUI_MAX_UPLOAD_MB` | `300` | Upload size limit |
| `RUI_JOB_TTL_HOURS` | `24` | Old jobs are deleted after this long |
| `RUI_MAX_CONCURRENT_JOBS` | `1` | Analyses running at once (each can use ~1–2 GB RAM) |
| `RUI_USER` / `RUI_PASSWORD` | unset | Set both to require HTTP basic auth |

> 🔒 The app has **no login by default**. If you expose it publicly, set `RUI_USER`/`RUI_PASSWORD` (and use HTTPS), because
> anyone could otherwise trigger heavy computations.

The generated dashboard is a single HTML file you can also host on GitHub Pages / any static host. It loads Leaflet and
Chart.js from cdnjs and map tiles from CARTO/Esri, so viewers need internet access.

---

## 3 · Your data (GeoPackage)

Everything is optional; the more you give, the better the result. Layers are auto-detected by geometry/name:

| What | How it is detected | Used for |
|---|---|---|
| Study-area boundary | polygon layer named `*bound*`, `*aoi*`, `*study*`, `*area*` (else the first polygon layer) | extent |
| Analysis units (wards / grid) | polygon layer with a `pop_sum` / `population` / `pop` column (else a regular grid of `grid_size_m`) | the cells that are scored |
| Buildings | polygon layer with `build` in its name (else OpenStreetMap) | built-up share, economy proxy |
| Amenities | point layer with `amenit` or `poi` in its name (else OpenStreetMap) | access score, dashboard facilities |
| Roads | line layer with `road` in its name | mobility, road density, place names |
| Temperature | `heat_column` on the units layer (else computed from Landsat) | heat |

Any CRS works (reprojected to UTM 44N, `EPSG:32644`). Override auto-detection with `aoi_layer`, `units_layer`,
`amenity_layer`, `amenity_type_column`, `pop_column`, `heat_column`.

**Real indicators instead of proxies:** if your units layer has literacy / health / income / traffic columns, pass their names
(`literacy_column`, `health_column`, `income_column`, `traffic_column`). Otherwise the dashboard uses clearly labelled
proxy indices.

### All settings

Use CLI flags (`--walk-radius-m 800`), a YAML/JSON file (`--config`), a `Config(...)` object, or the web form.

| Setting | Default | Meaning |
|---|---|---|
| `gpkg` | `""` | GeoPackage path (blank = OSM-only circle around Rishikesh) |
| `out_dir` | `output` | Output folder |
| `aoi_layer`, `units_layer`, `amenity_layer` | `""` | Layer names (blank = auto) |
| `amenity_type_column`, `pop_column`, `heat_column` | `""` | Column names (blank = auto / Landsat) |
| `amenity_source` | `both` | `both` / `gpkg` / `osm` |
| `grid_size_m` | `500` | Grid cell size if there is no units layer |
| `years`, `season_start`, `season_end` | `2023,2024,2025`, `04-01`, `06-30` | Landsat window (pre-monsoon summer) |
| `max_cloud` | `30` | Max scene cloud cover % |
| `walk_radius_m` | `1000` | "Walking distance" for amenity access |
| `hot_percentile` | `90` | Hot = top 10 % of built-up cells |
| `low_amenity_percentile` | `25` | Under-served = bottom 25 % access score |
| `built_min_share` | `0.03` | Min. building footprint share to count a cell as built-up |
| `max_area_km2`, `fallback_radius_km` | `800`, `10` | Oversized study areas are replaced by a circle |
| `use_osm` | `true` | `false` = never call OpenStreetMap (fully offline vector analysis) |
| `use_ndvi` | `true` | Compute greenery from Landsat |
| `language` | `Hinglish` | `English` or `Hinglish` dashboard text |
| `literacy_column`, `health_column`, `income_column`, `traffic_column` | `""` | Real indicator columns |

### Outputs (`out_dir/`)

`Rishikesh_Dashboard.html` · `map_1_heat.html` · `map_2_low_amenities.html` · `map_3_priority.html` ·
`map_4_population.html` (if population exists) · `rishikesh_results.gpkg` (layers `units`, `amenities_used`) ·
`rishikesh_results.csv` · `rishikesh_by_place.csv` · `overview.png` · `summary.json`

---

## 4 · How it works

| Notebook step | Module |
|---|---|
| 3–4 Settings, study area & units | `config.py`, `units.py`, `io.py` |
| 5 Land-surface temperature (+ NDVI) | `heat.py` |
| 6 Built-up areas & place names | `places.py`, `osm.py` |
| 7 Amenities & access score | `amenities.py` |
| 8–9 Hot / under-served / priority flags, tables | `indices.py` |
| 10–11 Maps & overview | `maps.py` |
| 13 Story dashboard | `dashboard.py` + `templates/dashboard.html` |
| – Orchestration / CLI / web app | `pipeline.py`, `cli.py`, `app.py` |

**Access score** = 50 % share of amenity types within `walk_radius_m` + 50 % smooth distance-decay closeness.
**Priority cell** = hot **and** low-amenity (built-up only).

### Limitations (please read)

* Heat is **land-surface** temperature at ~30 m (thermal band natively 100 m) from ~10:30 am passes – it shows *relative* hot
  spots, not air temperature. Hills, the river, sand bars and bare ground all affect it; compare with satellite imagery.
* OpenStreetMap is **incomplete in India** – a "low amenity" cell can partly mean "not mapped". Supply your own amenity layer when you can.
* Education / health / economy / mobility are **proxy indices** unless you provide real columns; they describe *access and
  connectivity*, not literacy, health outcomes, income or traffic counts.
* Population comes from your layer (e.g. WorldPop) – a modelled estimate, not a census count.
* Forest / river / unbuilt cells are excluded from rankings so they are not mislabelled "under-served".

---

## 5 · Development

```bash
pip install -e ".[dev]"
pytest -q            # 18 tests: pipeline (EN/Hinglish, no-population, real columns, OSM down, OSM-only), web app, config
make demo            # offline demo run
```

The tests run fully offline (Landsat/OSM are mocked where needed). CI runs them on Python 3.10–3.12 and builds the Docker image.

```
src/rishikesh_urban/   package (pipeline, dashboard, CLI, Flask app, sample-data generator)
data/sample/           synthetic demo GeoPackage + example config
tests/                 pytest suite
notebooks/             Colab quick-start + your original notebook
```

### Troubleshooting

* **"No scenes found"** → widen `years`/season or raise `max_cloud`.
* **Overpass busy / OSM unavailable** → the run continues with your GeoPackage data (re-run later), or set `use_osm: false`.
* **Out of memory** → smaller study area, fewer `years`, or more RAM; keep `RUI_MAX_CONCURRENT_JOBS=1`.
* **Blank map in the dashboard** → the viewer needs internet (CDN scripts + tiles).

## Data & credits

Landsat Collection 2 Level-2 via [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com) ·
© [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors · basemaps © CARTO / Esri.

## License

MIT – see [LICENSE](LICENSE).
