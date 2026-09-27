# HomeLens design document: machine learning and AI

This document explains the machine learning and AI decisions in HomeLens: what I chose, what I compared it against, how I tested it, and why some things were deliberately **not** shipped. For what the experiments found, see [FINDINGS.md](FINDINGS.md).

**Contents**

1. [Principles](#1-principles)
2. [The data the models learn from](#2-the-data-the-models-learn-from)
3. [Price estimate](#3-price-estimate)
4. [Price ranges (not shipped)](#4-price-ranges-not-shipped)
5. [Five-year value outlook (not shipped)](#5-five-year-value-outlook-not-shipped)
6. [AI search by description](#6-ai-search-by-description)
7. [AI for nearby places](#7-ai-for-nearby-places)
8. [Where I chose not to use AI](#8-where-i-chose-not-to-use-ai)
9. [Neighborhood data decisions](#9-neighborhood-data-decisions)
10. [What I would do next](#10-what-i-would-do-next)
11. [Appendix: rebuild the data and model](#appendix-rebuild-the-data-and-model)

---

## 1. Principles

These rules shaped every decision below.

- **Test on the future, not on shuffled data.** Housing prices move over time, so every model is trained on older sales and tested on newer ones.
- **Beat a simple baseline or don't ship.** Every model is compared with the simplest reasonable alternative first.
- **Write the rule before seeing the result.** When choosing between options, I wrote the decision rule first so I couldn't pick whatever looked best afterwards. Where an early exploratory look came first, the notebook says so.
- **Touch the final test set once.** The 2025 sales were used for one final report, never to choose anything.
- **Look past the average.** Every evaluation is broken down by ZIP code, home type, and price range. Slices with fewer than 30 homes report counts only, because their averages are too noisy to trust.
- **Experiment in a notebook first, then move it into tested code.** Each decision has an executed notebook in `notebooks/` with its results saved.
- **The AI never touches the database directly.** A language model may read a request, but its answer is checked against a strict schema, and only regular code runs the search.
- **Say "unavailable" instead of guessing.** If a feature can't give a trustworthy answer for a home, it says why.

## 2. The data the models learn from

The source is a Redfin export of sold homes in Durham County: 23,545 rows.

**Cleaning steps, in order:**

| Step | Rows removed | Why |
| --- | --- | --- |
| Exact duplicate rows | 1,416 | The same sale exported twice would count twice |
| Missing or invalid sale date | 3,728 | Can't place the sale in time, so can't split by time |
| Not a house, townhouse, or condo | 1,006 | Too few land, multi-family, or mobile-home sales to learn from |
| Missing or impossible features | 64 | e.g. under 300 sq ft, or built after it was sold |
| Outside the eight study ZIP codes | 51 | Too few sales elsewhere |
| Outside the actual county boundary | 239 more (for the final model) | A ZIP code label isn't a location. 276 "Durham ZIP" sales were outside the county, and 55 in-county sales carried other ZIPs |

**Features the model uses:** beds, baths, square feet, year built, home type, and ZIP code.

**Deliberately excluded:**
- **"$ per square foot"**: it's calculated from the sale price, so using it would leak the answer into the question.
- **The ZIP value index**: its source wasn't verified when the model was built, and joining it safely would require using only months before each sale.
- **Sale date**: left out of the first model on purpose. This is the most likely reason the model guesses low on newer sales (see [FINDINGS.md](FINDINGS.md)).

**Time split:**

| Set | Sales dates | Homes | Used for |
| --- | --- | --- | --- |
| Train | May 2020 – Dec 2023 | 13,102 | Fitting the model |
| Validation | 2024 | 2,928 | Choosing between options |
| Test | Jan – May 2025 | 1,010 | One final report, never for choices |

## 3. Price estimate

### What it predicts

The price a historical sale would have sold for, given its features. It is **not** a current market value or an appraisal, and the app says so.

### Baseline

**"Predict the training median ($352,000) for every home."** This is the simplest estimate that uses no features at all. If a model can't clearly beat it, the features aren't adding anything.

### Model choice: gradient-boosted trees

I used scikit-learn's `HistGradientBoostingRegressor` with a fixed, modest configuration: 100 rounds, learning rate 0.1, 15 leaves per tree, at least 20 homes per leaf, and light regularization.

Why this model:
- **It handles categories natively.** ZIP code and home type work without one-hot encoding.
- **It captures non-linear effects.** A fourth bedroom matters differently in a condo than in a large house.
- **It is right-sized for about 13,000 rows.** Deep learning would overfit, and plain linear regression would miss the interactions.
- **It is fast and deterministic.** It trains in seconds with a fixed random seed, so results are reproducible.

I did **not** tune hyperparameters. With one validation year, heavy tuning mostly fits that year's quirks. The settings were fixed up front, and the effort went into evaluation instead.

### Metrics

| Metric | Why it's reported |
| --- | --- |
| **Mean absolute error (MAE), in dollars** | The main number. "Typically off by $X" is what a user understands, and it isn't dominated by a few mansions. |
| **Mean signed error** | Shows whether the model leans high or low. An unbiased average can hide a lean. |
| **Median and 90th-percentile absolute error** | Shows the typical case and the bad case separately. |
| **Share of error by price band** | Shows *which* homes the error comes from. |
| **RMSE** | Kept for reference. It's inflated by rare, very expensive homes. |

### The loss decision: absolute error vs. Poisson

The first model was trained to minimize absolute error. Breaking its validation errors down by price band showed that the most expensive 14% of homes (over $600,000) caused 45% of the absolute error and 85% of the squared error.

I compared it with a **Poisson loss**, which suits positive, right-skewed targets like prices, using a rule written in advance. The candidate had to:
- cut error on high-priced homes by **at least 10%**, and
- raise overall error by **no more than 5%**.

**Poisson passed.** High-price error fell from $250,076 to $212,102, a 15% drop. Overall validation error also fell, from $78,569 to $74,463.

### County check

The first cohort was defined by ZIP code. A GIS check against the county boundary showed that ZIP labels and real locations disagree. So I rebuilt the cohort from the eight study ZIPs **clipped to the county polygon** and confirmed on 2024 validation data that the fixed Poisson model still behaved the same before exporting it.

### Final result (2025 test, used once)

| | Typical miss (MAE) | Leans |
| --- | --- | --- |
| Baseline (training median) | $157,216 | $110k low |
| **Shipped model** | **$81,626** | **$57k low** |

### How it is served

- **Offline training.** The model is trained offline and saved as a versioned file with its settings, library versions, data checksums, and test results. The server refuses to load it if any of these don't match.
- **Loaded once.** It loads once at startup, and training never happens during a request.
- **Scoped.** It only answers for homes like the ones it was tested on: the eight ZIP codes, the three home types, sale dates from May 2020 to May 2025, and features within the training ranges. Anything else gets a clear "outside the model's study area" message.
- **Error shown with the estimate.** The app shows the estimate with its test error and the fact that it tends to guess low.

## 4. Price ranges (not shipped)

A single number hides uncertainty, so I tried to add a range like "80% likely between $X and $Y".

**Method.** I calibrated the range on January to June 2024 and checked it on July to December 2024, using several approaches:
- a flat dollar range
- a range proportional to price
- ranges that depend on the predicted price band
- ranges grouped by ZIP

**Why none shipped:**
- A flat 90% range covered 90% of homes overall but **only 49% of homes over $600,000**.
- The final candidate, a lopsided range proportional to the estimate, covered 90.8% of 2025 sales overall, but only **59% of sales in ZIP 27701**, and its typical width was **$323,459**, too wide to be useful.
- The 2024 data had already been used to pick the model, so any range tuned on it isn't an independent guarantee.

**Decision:** no range until one can be tested on a fresh set of sales, such as 2026.

## 5. Five-year value outlook (not shipped)

The prototype projected values five years out. I tested whether that is possible with the data I have. Details are in `notebooks/zip_value_outlook.ipynb`.

**The data.** `zipcode_saleprice.csv` is not sale prices. Its columns and its smooth monthly values match Zillow's typical-home-value index (ZHVI), for 8 ZIPs from February 2001 to April 2025. I label it that way everywhere.

**Methods compared.** All forecasts are made on the log of the index:
- **No change** (the baseline)
- **Straight-line trend** over the full history, 10 years, 5 years, or 1 year
- **A damped 1-year trend**, which slowly flattens
- **ARIMA(2,0,0) on monthly changes**, the closest simple version of the prototype's method

**Test design.** I stood at each January from 2006 to 2020 and forecast 1 to 5 years ahead using only earlier months:
- **Development period:** 2006 to 2015, which includes the 2008 crash.
- **Holdout period:** 2016 to 2020, which leads into the pandemic run-up.

**Decision rule.** Pick the method with the lowest average error on development. Show a forecast only if it beats "no change" at every horizon in **both** periods. An exploratory run came first, and the notebook says so.

**Result.** "No change" won on development, so no forecast is shown.

Instead, the app shows **value since sale**: the sale price multiplied by how much the ZIP's index changed since the sale month. It is labeled as an index adjustment that assumes the home moved with its ZIP. It isn't a forecast or an appraisal.

## 6. AI search by description

Users can type a request like "3+ beds under $400k in 27703" instead of filling in filters.

### How it works

```text
User text
  -> quick check for things the data can't answer (safety, schools, lot size, "for sale", SQL...)
  -> vague price check ("around $400k" -> ask a question)
  -> language model returns JSON that must match a strict schema
  -> server re-checks every field (types, ranges, min <= max)
  -> user sees the filters and clicks "Apply search"
  -> normal search code runs the query
```

### Design choices

| Choice | Why |
| --- | --- |
| **The model outputs filters, not SQL or answers** | The worst it can do is propose wrong filters, which the user sees before applying. |
| **Strict schema (Pydantic, extra fields forbidden)** | Only these fields can come back: price range, minimum beds and baths, ZIP, home type, square-foot range, and year-built range. |
| **Three outcomes: ready, clarify, unsupported** | A good search tool should ask when a request is vague and say "I can't do that" when the data can't answer it. It shouldn't silently drop part of the request. |
| **Fail closed** | If the model lists *any* unsupported condition, the whole request is refused. This way "3 beds in a safe neighborhood" never quietly becomes "3 beds". |
| **Rules before the model** | Obvious unsupported requests (crime, schools, lot size, active listings, prompt injection) are refused before any API call. It's cheaper and it can't be talked out of the rule. |
| **User confirms before searching** | The preview shows exactly which filters will be applied. |
| **Manual filters always work** | AI is optional. Without a key, the rest of the app is unchanged. |

### Model and settings

- **Model:** OpenAI's `gpt-4o-mini` by default, because it supports schema-constrained output and is cheap enough to try many times.
- **Swappable provider:** the provider sits behind its own adapter, so it could be swapped for Gemini, like the original prototype, without touching the search logic.
- **Privacy:** requests are sent with `store=false`, so the provider doesn't keep them.
- **Latency cap:** a 12-second timeout and no automatic retries, so a slow provider can't hang the page.
- **Key handling:** the API key stays on the server and never reaches the browser.

### How it is evaluated

**The regression set.** A fixed set of 24 test requests lives in `tests/fixtures/search_intent_cases.json` and is documented in `notebooks/search_intent_contract.ipynb`:

- **12 "ready" requests** with exact expected filters. These include the four example searches shown in the app; a test fails if the app ever lists an example that isn't in this set.
- **3 "clarify" requests**, such as "Homes around $400k" and "A big house with 4 bedrooms".
- **9 "unsupported" requests**, including safety, schools, pools, lot size, home style, another city, active listings, and a prompt-injection attempt.

**How it runs:**
- **Automated tests:** they run the whole set against a fake provider on every change, so the rules and checks are always tested.
- **Live check:** `python -m homelens.services.search_evaluation` runs the same set against the real model and saves pass counts and failed case IDs.

**Not yet measured:** the live model's accuracy hasn't been measured, because that needs a key. Until the live run is done, AI search should be treated as unverified.

## 7. AI for nearby places

The prototype used Gemini to turn "somewhere to get coffee" into a Google Places type. HomeLens does this in two steps:

1. **Keywords first.** Fixed keyword lists map text to 12 categories, such as "coffee" to restaurants and cafes, or "daycare" to childcare. This covers most requests with no API call and is fully testable.
2. **Model only as a fallback.** When no keyword matches and a key is set, the model must pick one of the same 12 categories or none.

If the text matches more than one category, the user is shown the options instead of getting a guess. The model only chooses a category; the places themselves come from Google.

## 8. Where I chose not to use AI

- **Home descriptions.** The prototype had Gemini write realtor-style descriptions. HomeLens builds them directly from the sale record. A language model can make up details, such as "updated kitchen", that no one verified, and a buyer might rely on them.
- **Demographics and crime.** These are shown as sourced numbers with their limits. They are never summarized or interpreted by a model.
- **Price estimate and value trend.** These are plain statistical methods whose errors are measured, not generated text.

## 9. Neighborhood data decisions

These aren't machine learning, but they follow the same rule: show only what the data supports.

- **Crime.**
  - The city's crime file has no coordinates, so crime is counted per police beat. Addresses are never geocoded.
  - The categories follow FBI definitions, written as crime codes in the file.
  - Counts are shown per square kilometer so large beats don't look worse just for being large.
  - A year counts as complete only if the data covers January 1 to December 31.
- **Demographics.**
  - These come from ACS 5-year estimates for ZIP Code Tabulation Areas, the Census version of ZIP codes.
  - Each value is shown with its margin of error. Values the Census suppressed stay unavailable.
  - Race and Hispanic origin use the categories that add up to 100%, so no one is counted twice.
  - Demographics are never used as model features, to avoid building a price model on race or income data.
- **Google data.**
  - Street View and solar describe the nearest image and building, which may not be the actual home, and the app says so.
  - Places results are kept in a list rather than drawn on the OpenStreetMap map, to follow Google's display rules.

## 10. What I would do next

- **Run the live AI search evaluation** once a key is available, and fix any failing cases notebook-first.
- **Add a time feature** such as sale month, or retrain regularly, to reduce the model's tendency to guess low on newer sales.
- **Test price ranges on fresh data,** such as 2026 sales, before shipping any.
- **Revisit the forecast** with a longer, confirmed Zillow series and a rule written before any look at the results.
- **Swap in Gemini** behind the same adapter to match the original prototype, and compare both on the same 24-case set.

---

## Appendix: rebuild the data and model

Run these from the project folder after placing the raw files in `data\raw`. The README lists the files and where they come from. Every command writes to `data\processed` or `models\`, which Git ignores.

**App data**

```powershell
.venv\Scripts\python -m homelens.data.property_catalog      # clean sales inside the county -> search catalog
.venv\Scripts\python -m homelens.data.crime_beats           # offense counts per police beat and year
.venv\Scripts\python -m homelens.data.acs_zcta              # ZIP code demographics from the Census exports
.venv\Scripts\python -m homelens.data.zip_index             # ZIP home value index for "value since sale"
```

**Price model**

```powershell
.venv\Scripts\python -m homelens.data.prepare --county-verified-study-zips
.venv\Scripts\python -m homelens.modeling.county_comparison
.venv\Scripts\python -m homelens.modeling.export            # writes models\valuation_v1 (won't overwrite)
```

**Audits and experiments behind the decisions**

```powershell
.venv\Scripts\python -m homelens.data.inventory             # what each raw file contains
.venv\Scripts\python -m homelens.data.eda                   # sales and ZIP series profile
.venv\Scripts\python -m homelens.data.geography             # ZIP labels vs. the county boundary
.venv\Scripts\python -m homelens.data.police_beats          # crime records vs. police beat shapes
.venv\Scripts\python -m homelens.data.prepare               # first ZIP-based cohort
.venv\Scripts\python -m homelens.modeling.baseline          # median baseline vs. first model
.venv\Scripts\python -m homelens.modeling.loss_comparison   # absolute error vs. Poisson rule
.venv\Scripts\python -m homelens.modeling.uncertainty       # price range assessment
.venv\Scripts\python -m homelens.modeling.interval_slice_diagnostics
.venv\Scripts\python -m homelens.services.search_evaluation # live AI search check (needs OPENAI_API_KEY)
```

To open the notebooks, install the extras with `.venv\Scripts\python -m pip install -e ".[dev,notebook]"`.

**Server endpoints**

| Endpoint | Returns |
| --- | --- |
| `GET /api/properties` | Filtered, paged historical sales |
| `GET /api/properties/<id>` | One sale and its description |
| `GET /api/properties/<id>/valuation` | The price estimate, or why it's unsupported |
| `GET /api/properties/<id>/value-trend` | Value since sale on the ZIP index |
| `GET /api/properties/<id>/demographics` | ZIP code demographics |
| `GET /api/properties/<id>/context` | Nearby places, Street View, and solar |
| `GET /api/properties/<id>/context/nearby` | Nearby places for one category and distance |
| `GET /api/crime/beats` | Offense counts per police beat for a year and category |
| `POST /api/search/interpret` | AI search filters, a question, or "unsupported" |
| `POST /api/nearby/interpret` | A nearby category from free text |
| `GET /api/health` | Whether the server is running |

Settings (all optional) are environment variables: `OPENAI_API_KEY`, `OPENAI_SEARCH_MODEL`, `GOOGLE_MAPS_API_KEY`, `PROPERTY_CATALOG_PATH`, `VALUATION_ARTIFACT_PATH`, `CRIME_BEATS_PATH`, `ACS_ZCTA_PROFILES_PATH`, `ZIP_VALUE_INDEX_PATH`, and `VITE_MAP_TILE_URL`.
