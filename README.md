# HomeLens

HomeLens is a rebuild of the Google Realtor housing research prototype. The
original combined home search, neighborhood context, price forecasts, solar
analysis, and AI-assisted questions. This repository begins with the backend;
the interface and data-driven features will be added in later issues.

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

## Next slices

1. Establish the property data contract and import a permitted dataset.
2. Add validated search filters and persistence behind repository interfaces.
3. Add neighborhood, Census, Places, Street View, and solar adapters.
4. Build reproducible valuation baselines, evaluations, and versioned inference.
5. Add structured AI search and descriptions with regression evaluations.
