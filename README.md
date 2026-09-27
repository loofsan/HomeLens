# HomeLens

HomeLens helps someone who is moving to Durham, North Carolina get a feel for a home and its neighborhood before they visit. You search past home sales on a map, open one, and see what the area around it is like: nearby places, street imagery, solar potential, who lives in the ZIP code, reported crime by police beat, how values in that ZIP have moved since the sale, and an experimental price estimate.

It runs on your own computer. It is a portfolio and learning project, not a public website, and it shows **past sales, not homes currently for sale**.

- [What it does](#what-it-does)
- [Why I built it](#why-i-built-it)
- [Try it on your computer](#try-it-on-your-computer)
- [Three hard problems and how I solved them](#three-hard-problems-and-how-i-solved-them)
- [More documents](#more-documents)

## What it does

| Feature | What you see |
| --- | --- |
| **Map and list search** | Every recorded sale on a map and in a list, kept in sync. Filter by price, beds, baths, ZIP, home type, size, and year built, or search just the area you are looking at. |
| **Search by description** | Type "townhouses built in 2010 or later under $350k". AI turns it into filters you can check before applying. If the request is vague it asks a question; if it asks for something the data can't answer (like "safe neighborhood"), it says so instead of guessing. |
| **Price estimate** | A machine learning estimate of what the home would have sold for, with the typical error shown next to it. Only offered for the areas and home types the model was tested on. |
| **Value since sale** | The sale price moved along the ZIP code's home value index, shown as a chart or a table. |
| **Area demographics** | Population, income, age, and race and ethnicity for the ZIP code, from the Census, with margins of error. |
| **Crime by police beat** | A shaded map layer of reported violent or property offenses per year, by Durham police beat. |
| **Nearby places** | Schools, parks, groceries, and more within a distance you choose, or type what you want ("coffee"). |
| **Street View and solar** | A street image turned to face the home, and the roof's solar potential with estimated savings and payback. |
| **Explore Durham** | Links to local events, parks, libraries, and the school lookup. |

Every section says where its numbers come from and what they can't tell you. When something isn't available, the app says so instead of filling the gap.

## Why I built it

HomeLens started as **Google Realtor**, a team project built in 60 hours for Google's "Data for Good" challenge during the 2025 Sprinternship. We wanted to help three kinds of people:

- **Families relocating:** "Are there good schools and parks nearby? Is it a safe place to raise kids?"
- **Out-of-state buyers:** "I can't fly out to see the house. I want to know what the area is actually like."
- **First-time buyers:** "I don't know anything about buying a house. I need something that guides me."

The prototype worked as a demo, but a 60-hour build leaves shortcuts: photos that weren't the actual homes, a crime heatmap built by geocoding arrest addresses, and price forecasts that were never tested against what actually happened.

I rebuilt it on my own to do it properly. Every number is traceable to a source, models are tested on data they never saw, and the app is honest about what it doesn't know.

## Try it on your computer

You need **Python 3.12 or newer**, **Node.js 22 or newer**, and **pnpm**. The steps below are for Windows PowerShell. On macOS or Linux, use `.venv/bin/python` instead of `.venv\Scripts\python`.

### Option 1: the quick demo (5 minutes, no data or keys)

This uses 24 made-up homes so you can click around right away.

**1. Start the server.** Open PowerShell in the project folder:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -m homelens.data.demo_catalog
$env:PROPERTY_CATALOG_PATH = "data/processed/demo_catalog.sqlite3"
.venv\Scripts\python -m flask --app homelens run
```

The `demo_catalog` line creates the fake homes and only needs to run once. It refuses to overwrite them, so skip it next time.

**2. Start the website.** Open a second PowerShell window in the project folder:

```powershell
cd frontend
pnpm install
pnpm dev
```

**3. Open the link** it prints, usually http://127.0.0.1:5173.

In the demo, the price estimate, Google features, and neighborhood data are turned off, because the homes aren't real.

### Option 2: with real Durham data

The real data isn't in this repository: some of it can't be redistributed, and some of it is large. Put these files in `data\raw`:

| File | What it is | Where it comes from |
| --- | --- | --- |
| `redfin_data.csv` | Sold homes in Durham County, 2020 to 2025 | A Redfin "sold homes" export |
| `durham_county_boundary.geojson` | The county outline | Durham open data, County Boundary layer |
| `DPD_Crime_(table_only).csv` | Reported offenses | Durham open data, DPD Crime table |
| `durham_police_beats.geojson` | Police beat shapes | Durham open data, Police Beats layer |
| `ACSDP5Y2024.DP05-*.csv`, `ACSDP5Y2024.DP03-*.csv` | ZIP code demographics and income | data.census.gov, ACS 5-Year Data Profiles DP05 and DP03 for the Durham ZIP codes |
| `zipcode_saleprice.csv` | Monthly home value index by ZIP | A Zillow Research ZIP download |

Then prepare everything once:

```powershell
.venv\Scripts\python -m homelens.data.property_catalog
.venv\Scripts\python -m homelens.data.crime_beats
.venv\Scripts\python -m homelens.data.acs_zcta
.venv\Scripts\python -m homelens.data.zip_index
```

Start the server in a fresh PowerShell window without the `PROPERTY_CATALOG_PATH` line, then start the website the same way as in Option 1. Any file you skip only turns off the feature that needs it; everything else keeps working. To also train the price estimate, follow the steps in the [design document](docs/DESIGN.md#appendix-rebuild-the-data-and-model).

### Optional: turn on the AI and Google features

Get your own keys and set them in the same PowerShell window before starting the server. Never put them in the code.

```powershell
$env:OPENAI_API_KEY = "your key"        # search by description
$env:GOOGLE_MAPS_API_KEY = "your key"   # nearby places, Street View, solar
```

The Google key needs the Places API (New), Street View Static API, and Solar API enabled, with billing and a spending limit set. Without keys, those sections say they aren't set up and everything else works.

### If something doesn't start

- **Port already in use:** run the server with `--port 5004`. Then, before `pnpm dev`, run `$env:VITE_API_TARGET = "http://127.0.0.1:5004"`.
- **Blank map:** the map tiles come from OpenStreetMap and need an internet connection.
- **Run the checks:** `.venv\Scripts\python -m pytest` for the server, and `pnpm run test:e2e` in `frontend` for the website.

## Three hard problems and how I solved them

These are the problems most likely to trip up anyone who builds a project like this on their own.

### 1. The crime "map" file had no locations in it

**Situation.** The prototype's most eye-catching feature was a crime heatmap. Durham publishes its police data as a 57 MB file named `City_Crime_(External_Use).geojson`, which looks like map data. When I checked it, all 128,560 records had **no coordinates at all**. The only location was a block address like "3700 MAYFAIR ST". The prototype had geocoded those addresses one by one, which puts dots where no specific incident happened and republishes addresses of real events.

**Task.** Show crime around a home in a way that is accurate, doesn't invent locations, and doesn't publish incident records.

**Action.**
- I audited every column and found a police `BEAT` code on each record.
- I downloaded the city's police beat boundaries and checked the match: 128,098 of 128,560 records (99.6%) pointed to a real beat.
- I counted offenses per beat per year, using the FBI's standard definitions of violent crime (murder, rape, robbery, aggravated assault) and property crime (burglary, theft, vehicle theft, arson).
- I used the report date for the year, because the file's own year column was `0` on 29,831 records (23%).
- I wrote down the gaps instead of hiding them:
  - The public table has only 3 homicide records in over four years, far too few.
  - It covers the city police area only.
  - One beat's reports use a different code (`SSA`), so that beat shows "no linked reports" instead of a misleading zero.

**Result.** The crime layer is a shaded map of 36 beats built from 51,951 of 51,966 relevant records. It is a 180 KB file with no addresses or incident IDs, and it includes a legend and notes explaining what the counts can and can't tell you.

### 2. A price model that looked great but would have misled people

**Situation.** The sales data is a Redfin export of 23,545 rows. It is easy to get an impressive accuracy number from data like this and ship it:
- 1,416 rows were exact duplicates, and 3,728 had no usable sale date.
- It includes a "$ per square foot" column, which is calculated from the price itself. Using it to predict price is cheating.
- A random train/test split would let the model learn from 2024 sales and then be "tested" on 2023.
- 276 sales carried a Durham ZIP code but were actually outside the county.

**Task.** Build a price estimate whose stated error is the error a real user would see.

**Action.**
- **Cleaning:** removed duplicates and dropped the price-derived column. I kept only homes inside the actual county boundary, not just the right ZIP codes.
- **Splitting by time:** trained on May 2020 to 2023, tuned on 2024, and kept January to May 2025 locked away for one final test.
- **Baseline first:** started with "predict the typical training price" so the model had something real to beat.
- **Looking past the average:** broke errors down by ZIP, home type, and price range. The most expensive 14% of homes caused **45% of all the error** and 85% of the squared error.
- **Rules before results:** switched the model's training objective to one suited to prices (Poisson), but only under a rule I wrote first: it had to cut high-price error by at least 10% without raising overall error more than 5%. It cut high-price error by 15%.

**Result.**
- On the locked 2025 sales, the model's typical miss is **$81,626**. The baseline misses by $157,216 on the same period.
- The model still tends to guess about $57,000 low, and the app says so.
- I built price ranges but **didn't ship them**: in testing, a range meant to cover 90% of sales covered only 49% of expensive homes.
- The estimate is only offered for the ZIP codes, home types, and date range the model was tested on.

### 3. The five-year forecast that couldn't beat "prices stay flat"

**Situation.** The prototype showed each home's value five years from now, using a forecasting method called ARIMA. The input file was named `zipcode_saleprice.csv`. Two problems appeared:
- It wasn't sale prices. Its columns and its smooth month-to-month values match Zillow's typical-home-value index.
- Nobody had checked whether the forecasts were right.

**Task.** Decide, with evidence, whether a five-year forecast deserves to be shown to someone making a big financial decision.

**Action.**
- **Relabeled the source:** called the data what it is instead of what the filename says.
- **Backtested:** pretended to stand at every January from 2006 to 2020 and forecast 1 to 5 years ahead. I compared seven methods, including ARIMA, against simply assuming prices stay flat.
- **Set a strict rule:** a forecast would only be shown if one method beat "prices stay flat" at every horizon, both in the period with the 2008 crash and in the later period.

**Result.**
- **No method passed.** In the period with the 2008 crash, "prices stay flat" was the most accurate. Trend methods only looked good in the pandemic run-up, because prices kept rising.
- Five-year misses ranged from 12% to 38%.
- So HomeLens shows no five-year forecast. Instead, it shows how the ZIP's values actually moved since the sale, labeled as an index adjustment, not an appraisal.

## More documents

- [Design document](docs/DESIGN.md): the machine learning and AI decisions, including methods, baselines, evaluations, and how the AI search works.
- [Findings](docs/FINDINGS.md): what the data and experiments showed.
- `notebooks/`: the experiments behind each decision, with their results saved.

Data sources: Redfin (sold homes), City of Durham and Durham County open data (boundaries, police beats, crime), U.S. Census Bureau American Community Survey, Zillow Research (home value index), OpenStreetMap (map tiles), and, when enabled, Google Maps Platform and OpenAI.
