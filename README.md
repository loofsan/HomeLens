# HomeLens

HomeLens is a rebuild of the Google Realtor housing research prototype. The
original combined home search, neighborhood context, price forecasts, solar
analysis, and AI-assisted questions. The current application searches a local
catalog of historical Durham County sales; it does not show active listings.

## Quick local demo

This repository is for local testing and demos, not public deployment. No raw
dataset, model artifact, or API key is needed to try search, filters, map, and
details with 24 fictional examples. From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m homelens.data.demo_catalog
$env:PROPERTY_CATALOG_PATH = "data/processed/demo_catalog.sqlite3"
.venv\Scripts\python -m flask --app homelens run
```

Open a second PowerShell window at the repository root, then:

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Open the URL printed by Vite, normally `http://127.0.0.1:5173`. Use Python
3.12 or newer if 3.13 is unavailable. CI uses Node.js 24 and pnpm 11; this
local demo was also verified with Node.js 22.14 and pnpm 9.12. Map tiles need a
network connection. The generated SQLite file is ignored by Git and is separate
from `data/processed/property_catalog.sqlite3`. Generate it only once: the
command refuses to replace an existing file, so skip that line when restarting
the demo. All demo records and map points are illustrative, not real
homes or transactions. Valuation and Google property context are disabled for
them, even if credentials or a model artifact are configured. AI search remains
optional and needs each tester's own local `OPENAI_API_KEY`; manual filters work
without it. Use the separate historical catalog and offline model workflow below
only with data you are permitted to use. Do not commit datasets, artifacts, or
secrets.

If ports 5000 or 5173 are occupied, use free ports instead. For example, start
Flask from the repository root with the same `PROPERTY_CATALOG_PATH` setting:

```powershell
.venv\Scripts\python -m flask --app homelens run --port 5004
```

Then start the frontend from `frontend` in the second PowerShell window:

```powershell
$env:VITE_API_TARGET = "http://127.0.0.1:5004"
pnpm exec vite --host 127.0.0.1 --port 5180 --strictPort
```

Open `http://127.0.0.1:5180`. Keep `VITE_API_TARGET` aligned with the Flask
port you choose.

## Architecture

The API is a Flask application factory in `backend/homelens`. Each feature will
follow this dependency direction:

```text
HTTP route -> application service -> domain rules -> repository/provider port
                                                  -> database or external adapter
```

Routes validate requests and format responses. Services coordinate use cases.
Domain code owns housing rules and calculations. Adapters isolate MariaDB,
Google APIs, Census data, model artifacts, and other providers so a provider
failure does not become an implicit business rule. No provider or database is
required to start the current application.

Data and models have a separate path: ingest -> validate -> prepare features ->
train -> evaluate -> version artifact -> load for inference. Training will run
offline, never in an HTTP request. Evaluations will use temporal and geographic
checks where the data permits and report errors by property and location slice.

An LLM may interpret a search request or draft a description, but its output
will be schema-validated before deterministic filters, calculations, or provider
calls. It will not author SQL or decide access permissions. External calls will
have explicit timeouts and bounded retries when those integrations are added.

The first supported geography will be Durham County, matching the prototype's
data. Each capability has a clear boundary:

| Capability | Planned component | Required input |
| --- | --- | --- |
| Property search | Search service and property repository | Licensed property records |
| Crime and demographics | Neighborhood service and source adapters | Durham crime data and Census API |
| Nearby places, Street View, solar | Google API adapters | Property coordinates and API credentials |
| Value estimates | Offline training and inference service | Historical sales and a versioned model |
| Chat search and descriptions | Structured AI workflow | Validated property and neighborhood facts |

An unavailable provider will produce an explicit partial or error response for
its capability; it will not silently substitute invented data. Database schema,
API response shapes, and provider contracts will be specified in their feature
issues before implementation.

## Current API

`GET /api/health` returns HTTP 200 and `{"status":"ok"}`. This is a process
liveness check, not a database or provider readiness check.

## Historical property catalog

The supplied `data/raw/redfin_data.csv` is a sold-home export, not a feed of
currently available homes. The offline import creates a local SQLite catalog:

```powershell
.venv\Scripts\python -m homelens.data.property_catalog
```

The ignored `data/processed/property_catalog.sqlite3` holds validated historical
sales inside the supplied Durham County boundary. The ignored
`data/processed/property_catalog_audit.json` records source hashes, row
exclusions, date range, and schema version without publishing addresses. Each
record has a stable ID, sale date and price, home attributes, address, ZIP,
coordinates, optional validated Redfin URL, and a fixed `historical_sale` kind.
Re-running the import replaces the local snapshot transactionally. This catalog
is separate from the eight-ZIP modeling cohort; it is not an active-listing
service or a deployable data feed.
For an isolated local worktree, `PROPERTY_CATALOG_PATH` may point Flask to an
existing imported catalog outside that worktree; keep the catalog out of Git.

After importing, `GET /api/properties` searches the local historical sales.
Optional filters are `min_price`, `max_price`, `min_beds`, `min_baths`, `zip`,
and a complete `south`, `west`, `north`, `east` map rectangle. `page` starts at 1;
`page_size` defaults to 20 and is capped at 100. Results are ordered by sale
date (newest first) and stable record ID. `GET /api/properties/<id>` returns a
single sale or 404. Both successful responses include source vintage and
`active_listings: false`; each property has `record_kind: historical_sale` and a
sale date. Invalid filters return 400 with a structured field error. If the
local catalog is missing or incompatible, property routes return 503 without
affecting `/api/health`.

## Conversational search

`POST /api/search/interpret` accepts a JSON `query` and optionally a previous
`question` with its `answer`. It returns a validated filter preview, a
clarifying question, or an unsupported-condition message. Only sold price,
minimum beds/baths, and ZIP can be inferred. The route does not run SQL, search
the catalog, or generate property facts; applying a preview calls the existing
deterministic property search. Manual filters remain available without AI.
Property detail descriptions are assembled from the historical catalog record
only and carry the catalog source in the same response. They are not
model-authored or claims about current availability.

To enable the optional OpenAI adapter for a local demo, set `OPENAI_API_KEY` in
the backend process environment before starting Flask. `OPENAI_SEARCH_MODEL`
defaults to `gpt-4o-mini`. Keep keys out of Git; the browser never receives
the key. Requests use schema-constrained responses with bounded timeouts and
`store=false` as described in the [official OpenAI documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
Without a key, supported requests return 503 and manual search still works.

The executed `notebooks/search_intent_contract.ipynb` defines the supported,
ambiguous, and adversarial regression set. With a local key, run the offline
provider evaluation before relying on AI interpretation:

```powershell
.venv\Scripts\python -m homelens.services.search_evaluation
```

The ignored report at `data/processed/search_intent_evaluation.json` contains
aggregate pass counts and failed case IDs only. No live provider evaluation is
claimed until this command is run with a configured key. This repository is
intended for local testing and demos, not public deployment.

## Historical sale interface

The React/Vite interface searches the local catalog with price, beds, baths,
and ZIP filters. It synchronizes the result list with a map using supplied
coordinates, supports searching the visible map area, and shows responsive
sale details. It labels every result as historical and does not present these
records as available homes. Start the Flask API as described below, then in a
second PowerShell window run:

```powershell
cd frontend
pnpm install
pnpm dev
```

Open the URL printed by Vite. CI uses Node.js 24 and pnpm 11; the local demo
also ran with Node.js 22.14 and pnpm 9.12. The development server proxies
`/api` to Flask on port 5000 by default. Map tiles default to
[OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/) with
visible attribution; set `VITE_MAP_TILE_URL` to a compatible tile URL if using
another provider for a local demo and follow its usage terms.

For the frontend build and browser tests:

```powershell
cd frontend
pnpm run build
pnpm exec playwright install chromium
pnpm run test:e2e
```

The E2E tests stub API and tile responses, so they do not require the private
catalog or contact the public tile server. Frontend checks run in GitHub
Actions on pull requests.

## Optional Google context

Sale details can request nearby places, outdoor Street View imagery, and a
closest-building solar estimate on demand. The backend uses the recorded sale
coordinate and returns independent `available`, `unavailable`, or `error`
states from `GET /api/properties/<id>/context`. A Street View image is served
through `GET /api/properties/<id>/street-view/image`, so the API key never
appears in browser requests. Neither imagery nor the closest detected roof is
verified as belonging to the recorded home. These provider results are not
overlaid on the OpenStreetMap sale map.

For live results, enable billing and the Places API (New), Street View Static
API, and Solar API in a Google Maps
Platform project. Set `GOOGLE_MAPS_API_KEY` in the Flask server environment;
do not commit the key. The server makes bounded requests with a three-second
timeout per provider and does not persist provider content. Without a key,
each context section reports `not_configured` and catalog search still works.
The frontend E2E suite uses provider fakes; live provider behavior remains
unverified until credentials are configured.

Google Places content is displayed only in a separate, attributed list. For a
local demo with Places enabled, review the current [Google Maps attribution and Places policies](https://developers.google.com/maps/documentation/places/web-service/policies).

## Local development

Python 3.12 or newer is required. From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m flask --app homelens run
```

Visit `http://127.0.0.1:5000/api/health`. Use the Python version available on
your machine if it is not 3.13. The Flask command above is for local development.

Run the quality checks with:

```powershell
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy backend
.venv\Scripts\python -m pytest
```

The same checks run in GitHub Actions for pull requests on Python 3.12 and 3.13.

To reproduce the local data inventory and exploratory profile:

```powershell
.venv\Scripts\python -m homelens.data.inventory
.venv\Scripts\python -m homelens.data.eda
```

To audit the local crime and ACS exports without publishing incident records:

```powershell
.venv\Scripts\python -m homelens.data.neighborhood_inventory
```

The ignored `data/processed/neighborhood_inventory.json` records source hashes,
schema and date quality, duplicate-export checks, geometry coverage, and ACS
geographies. The supplied crime GeoJSON is a non-spatial copy of the crime
table; it cannot be joined to homes or ZIPs. The original DP05 export contains
United States figures; a separate Durham County export is also available.
Neither source currently supports neighborhood-level facts. Additional 2023
DP05 CSV exports can be placed alongside the original file; the audit checks
every matching export.

To prepare a county-only context summary from the Durham 2023 ACS 1-year DP05
export:

```powershell
.venv\Scripts\python -m homelens.data.acs_county
```

The ignored `data/processed/acs_county_context.json` contains selected
population, age, and housing-unit estimates with margins of error and explicit
unavailable values. It is Durham County context only, not a ZIP-level measure
or a property/model feature.

To audit crime `BEAT` codes against the [City of Durham Police Beats layer](https://webgis.durhamnc.gov/server/rest/services/PublicServices/Public_Safety/MapServer/8),
place its WGS84 GeoJSON export at `data/raw/durham_police_beats.geojson` and run:

```powershell
.venv\Scripts\python -m homelens.data.police_beats
```

The ignored `data/processed/police_beats_audit.json` reports polygon validity,
split beat codes, overlaps, and aggregate crime-code coverage. In the supplied
exports, 128,098 of 128,560 crime rows have a matching beat polygon; 454 have
no beat and 8 use `SSA`. Sixteen cross-beat polygon pairs overlap, each by less
than 0.000001% of the smaller feature. The [layer metadata](https://webgis.durhamnc.gov/server/rest/services/PublicServices/Public_Safety/MapServer/8/metadata)
was modified in 2026 but gives no historical effective dates. This audit does
not establish incident locations, historical beat boundaries, or property/ZIP-
level crime facts. No incident records are written.

To prepare the first residential modeling cohort and its audit:

```powershell
.venv\Scripts\python -m homelens.data.prepare
```

These commands read the CSVs in `data/raw` and write ignored outputs to
`data/processed`. The initial cohort uses three residential property types and
eight selected ZIPs, with training sales before 2024, validation sales in 2024,
and a partial-year 2025 test set. It is not a county-boundary validation. The
ZIP-level price-history metric is unverified and is not joined to the cohort.

To audit the selected ZIPs against the [Durham County Boundary layer](https://webgis.durhamnc.gov/server/rest/services/PublicServices/Administrative/MapServer/2),
query its geometry as WGS84 GeoJSON, place the resulting polygon at
`data/raw/durham_county_boundary.geojson`, and run:

```powershell
.venv\Scripts\python -m homelens.data.geography
```

The command writes an aggregate, ignored report to
`data/processed/geography_audit.json`; it does not alter the prepared cohort.
For the supplied sources, 18,117 of 18,400 deduplicated historical sales with
usable coordinates are inside the boundary. The eight-ZIP rule includes 276
outside-county sales and excludes 55 inside-county sales. This comparison covers
historical sales broadly, not just the prepared residential cohort. The
original cohort remains ZIP-based; its estimates must not be presented as
county-wide.

To evaluate the first offline valuation baselines after preparation:

```powershell
.venv\Scripts\python -m homelens.modeling.baseline
```

The ignored report at `data/processed/baseline_report.json` compares a training
median with a fixed tabular model on the temporal validation and test splits.
It reports errors by ZIP and property type. The results apply to the selected
study ZIPs, not to a verified county-wide population.
The report also includes training-defined price bands, aggregate ZIP/property
type intersections, and the share of error carried by the largest residuals.
Intersections below 30 sales report counts only. Positive signed error means
overprediction; negative signed error means underprediction. The 2025 test
split is descriptive and must not be used to tune a model.

Model experiments begin in an executed notebook before the selected procedure
is moved to tested Python modules. Install the notebook tools with
`.venv\Scripts\python -m pip install -e ".[dev,notebook]"`, then open
`notebooks/high_price_validation.ipynb` from the repository root after preparing
the cohort. Its saved outputs contain validation aggregates only; the 2025 test
split is excluded from the notebook.

To reproduce the fixed loss comparison and final held-out evaluation:

```powershell
.venv\Scripts\python -m homelens.modeling.loss_comparison
```

The ignored `data/processed/loss_comparison.json` records the validation-only
selection rule, both validation evaluations, the final 2025 comparison, and a
temporal interval coverage check. The simple global interval undercovers
high-price validation sales and is not approved for inference. Because 2024
validation also selected the model, this interval check is diagnostic rather
than an independent coverage guarantee. This workflow does not produce a
deployable model artifact.

The executed `notebooks/high_price_interval_calibration.ipynb` explores
inference-time relative and predicted-price-segmented intervals for the fixed
county-verified Poisson model. It calibrates on January-June 2024 and compares
methods on July-December 2024, without using the 2025 split for selection. To
reproduce the frozen 1% upper-tail / 9% lower-tail interval assessment after
preparing the county-verified cohort and comparison, run:

```powershell
.venv\Scripts\python -m homelens.modeling.uncertainty
```

The ignored `data/processed/uncertainty_report.json` contains aggregate
coverage and width by training-price band, property type, and ZIP; slices below
30 sales report counts only. On the fixed 2025 assessment, coverage was 90.8%
overall, 89.5% above the training-price p90, and 83.0% at or below the training
median. ZIP 27701 covered only 59.2% of 49 sales. The median interval width was
$323,459. These results and prior use of 2024 for point-model selection do not
support serving an uncertainty interval. The versioned artifact and API remain
point-estimate-only.

The executed `notebooks/interval_slice_diagnostics.ipynb` follows up with
inference-available predicted-price bands and ZIP grouping. It compares support,
coverage, and width using only the two halves of 2024. Reproduce its ignored
aggregate report after preparing the county-verified cohort and comparison:

```powershell
.venv\Scripts\python -m homelens.modeling.interval_slice_diagnostics
```

`data/processed/interval_slice_diagnostics.json` records group fallbacks and
small-slice suppression, not an inference artifact. None of the candidates is
approved for serving. The previously inspected 2025 outcomes cannot provide a
fresh final test for a new method; that will require a later, untouched cohort.

The executed `notebooks/county_cohort_validation.ipynb` compares the original
ZIP cohort, a broad county cohort, and the eight study ZIPs restricted to the
county polygon. It records aggregate exclusions, ZIP-label conflicts, split
counts, and 2024 validation error slices. The 2025 split appears as counts only.
The selected procedure keeps the study ZIPs inside Durham County; the 47
inside-county sales with other ZIP labels remain diagnostic because only 8 are
in 2024 validation.

To reproduce the selected county-verified cohort and its fixed-model comparison:

```powershell
.venv\Scripts\python -m homelens.data.prepare --county-verified-study-zips
.venv\Scripts\python -m homelens.modeling.county_comparison
```

These commands write ignored county-cohort and comparison reports under
`data/processed`. The comparison uses 2024 validation for the geography check
and reports the selected model's 2025 test performance descriptively. The
selected geography is a verified subset of Durham County, not the whole county.

To export the fixed, train-only Poisson model after preparing the selected cohort
and comparison, run:

```powershell
.venv\Scripts\python -m homelens.modeling.export
```

The ignored `models/valuation_v1` directory contains a joblib model and JSON
metadata with source, boundary, cohort, and model checksums, library versions,
supported feature ranges, and held-out aggregate errors. Export fails if the
cohort or evaluation differs from the accepted comparison, and it will not
overwrite an existing version directory. Only load artifacts generated in a
trusted local workspace; joblib uses pickle. Restart the backend after export
so the artifact is loaded once at startup. Missing or incompatible artifacts
leave property search available but make valuation return HTTP 503.
For a local worktree that reuses an existing ignored artifact, set
`VALUATION_ARTIFACT_PATH` to its directory before starting Flask.

`GET /api/properties/<id>/valuation` returns a point estimate for a supported
historical sale in the selected eight ZIPs, inside the same county boundary and
source catalog, with a sale date from May 21, 2020 through May 20, 2025 and features within
the training ranges. Unsupported records return HTTP 422. The estimate is not
a current market value or appraisal. The 2025 held-out MAE was $81,625.74 and
mean signed error was -$56,951.48 (underprediction). No prediction interval is
served while high-price calibration remains unresolved.

## Next slices

1. Establish the property data contract and import a permitted dataset.
2. Add validated search filters and persistence behind repository interfaces.
3. Add neighborhood, Census, Places, Street View, and solar adapters.
4. Build reproducible valuation baselines, evaluations, and versioned inference.
5. Add structured AI search and descriptions with regression evaluations.
