# HomeLens findings

What the data and experiments showed. Each finding says where it comes from so it can be checked. For why the experiments were set up this way, see [DESIGN.md](DESIGN.md).

**At a glance**

- A ZIP code isn't a location: 276 "Durham ZIP" sales were outside Durham County.
- The price model is off by about **$82k on a typical 2025 sale**, roughly half the error of a simple baseline, but it **guesses low** and struggles with expensive homes.
- Price ranges and five-year forecasts **didn't pass testing**, so neither is shown.
- The city's crime "map" file has **no locations**, and the public table **under-counts homicides**.
- Several files **aren't what their names say**.

---

## 1. Data quality

| Finding | Numbers | Source |
| --- | --- | --- |
| Many rows in the sales export aren't usable | Of 23,545 rows: 1,416 exact duplicates, 3,728 without a usable sale date, 1,006 non-residential types | `homelens.data.prepare` audit |
| ZIP codes don't match the county line | 276 sales in "Durham" ZIP codes are outside Durham County; 55 in-county sales carry other ZIP codes | `homelens.data.geography` |
| The searchable catalog | 17,087 sales inside the county, May 21, 2020 to May 20, 2025 | `homelens.data.property_catalog` audit |
| A price column leaks the answer | "$ per square foot" is calculated from the sale price, so it can't be used to predict price | EDA |
| The ZIP "sale price" file isn't sale prices | It has Zillow Research's column layout and smooth monthly values, like Zillow's home value index; the exact series is unconfirmed | `notebooks/zip_value_outlook.ipynb` |
| The crime "GeoJSON" has no geometry | All 128,560 features have empty locations; only block addresses and police beat codes are included | `homelens.data.neighborhood_inventory` |
| The crime file's year column is unreliable | The year is `0` on 29,831 records (23%); the report date is used instead | Neighborhood inventory |
| The first Census file was the wrong geography | The original demographics export was for the whole United States, not Durham | Neighborhood inventory |

## 2. Price estimate

**Overall (January–May 2025 sales, used once for the final test):**

| | Typical miss (MAE) | Median miss | Leans |
| --- | --- | --- | --- |
| Baseline: always guess the training median | $157,216 | $88,000 | $110k low |
| Shipped model | **$81,626** | **$45,241** | **$57k low** |

**What stands out**

- **It beats the baseline by about half.** The home's features clearly carry information about price.
- **It guesses low, consistently.**
  - It averages $57k under the actual price in 2025 and $49k under in 2024.
  - The most likely reason: it was trained on 2020–2023 sales and has no feature for *when* a home sold, while prices kept rising.
- **Expensive homes cause most of the error.** On 2024 validation, homes over $600k were 14% of sales but 45% of the absolute error and 85% of the squared error.
- **A different training objective helped.** Switching from absolute-error loss to Poisson loss cut high-price error by 15%, from $250k to $212k, with no loss overall.

**Error by home type (2025):**

| Home type | Sales | Typical miss |
| --- | --- | --- |
| Condo | 33 | $29,998 |
| Townhouse | 218 | $38,611 |
| Single-family | 759 | $96,225 |

**Error by ZIP code (2025):**

| ZIP | Sales | Typical miss | Leans |
| --- | --- | --- | --- |
| 27713 | 79 | $39,630 | $36k low |
| 27703 | 391 | $53,374 | $32k low |
| 27704 | 143 | $56,673 | $38k low |
| 27712 | 89 | $93,243 | $88k low |
| 27701 | 49 | $95,376 | $6k low |
| 27705 | 136 | $107,658 | $86k low |
| 27707 | 115 | **$191,123** | **$143k low** |
| 27503 | 8 | Too few sales to report | |

27707, which has many high-priced homes, is where the model is least reliable.

## 3. Price ranges

| Test | Coverage (target 90%) |
| --- | --- |
| Simple dollar range, all homes (late 2024) | 89.6% |
| Simple dollar range, homes over $600k (late 2024) | **49.3%** |
| Final candidate, all homes (2025) | 90.8% |
| Final candidate, ZIP 27701 (2025) | **59.2%** |

The final candidate's typical width was $323,459. **Conclusion:** no range is shown until one can be tested on fresh sales.

## 4. Five-year value outlook

From `notebooks/zip_value_outlook.ipynb`: 8 ZIP codes, forecasts made from every January 2006–2020.

**Average five-year miss:**

| Method | 2006–2015 starts (incl. 2008 crash) | 2016–2020 starts (incl. pandemic run-up) |
| --- | --- | --- |
| No change | **17.3%** | 38.3% |
| Damped 1-year trend | 19.7% | 22.8% |
| ARIMA (prototype's approach) | 21.6% | 27.9% |
| 1-year trend | 22.4% | **12.4%** |
| 5-year trend | 25.3% | 19.5% |

**What stands out**

- **No method wins in both periods.** The best method depends on which kind of market you are in, which you can't know in advance.
- **"No change" wins when a downturn follows.** Trend methods win only when prices keep climbing.
- **Every method was too low in 2016–2020.** They all under-forecast the run-up, some by nearly 40%.
- **Conclusion:** no forecast is shown. The app shows value since sale instead.

**How the ZIP index moved (from the file):**

- **Since 2001:** values rose 123% (27703) to 261% (27701).
- **Since January 2020:** values rose 43% to 62%.
- **Recent peaks:** 27701 and 27703 peaked in July 2022 and were 1.7% and 3.1% below that peak in April 2025. Most other ZIPs were within 1% of their highs.

## 5. Crime by police beat

From `homelens.data.crime_beats`, using the City of Durham Police Department's public crime table.

| Finding | Numbers |
| --- | --- |
| Records that link to a police beat | 128,098 of 128,560 (99.6%) |
| In-scope violent and property records counted | 51,951 of 51,966 (12 have no beat; 3 use code `SSA`) |
| Violent offense records per year | 1,533 (2022), 1,476 (2023), 1,459 (2024), 1,294 (2025) |
| Property offense records per year | 9,143 (2022), 10,893 (2023), 11,236 (2024), 10,877 (2025) |
| Homicide records in the whole table | **3** in more than four years, implausibly low for a city of Durham's size, so the public table appears to leave some offenses out |
| Most violent records in 2025 | Beats 114, 223, and 412 (72 each) |
| Most violent records per km² in 2025 | Beat 513 (about 82 per km²), a small District 5 beat under 1 km² |

Raw counts and counts per km² tell different stories: large beats have more reports because they are bigger. The map shades by counts per km², and the hover label shows both.

## 6. Area demographics

From the Census 2020–2024 ACS 5-year estimates for the 13 ZIP code areas in the catalog.

| Finding | Numbers |
| --- | --- |
| Median household income | $69,668 (27704) to $128,683 (27517) |
| Median age | 34.3 (27560) to 48.3 (27503) |
| Largest single group | Varies: e.g. 27704 is 45.9% Black, non-Hispanic |
| No residents | 27709 (Research Triangle Park) reports zero population, so it shows as unavailable |
| Race and ethnicity add up | The shares used (Hispanic of any race plus non-Hispanic single races and multiracial) sum to 100% ± rounding in every ZIP |

## 7. AI search

- **The test set.** 24 requests: 12 with exact expected filters, 3 that should get a question back, and 9 that should be refused.
- **The automated tests** (with a fake model) confirm the rules:
  - vague requests get a question;
  - any unsupported condition refuses the whole request;
  - reversed ranges (like a minimum above the maximum) get a question;
  - lot size, safety, schools, and prompt injection are refused before any AI call.
- **Live accuracy with a real model hasn't been measured yet.** It needs an API key, and `homelens.services.search_evaluation` is ready to run.

## 8. What the original prototype got wrong, and what changed

| Prototype | What I found | HomeLens now |
| --- | --- | --- |
| Crime heatmap from geocoded arrest addresses | The file has no coordinates, and geocoding invents locations | Counts per police beat, with limits stated |
| Five-year ARIMA projection | No method reliably beats "no change" | No forecast; value since sale instead |
| "Median house price" ZIP data | It's a Zillow-style home value index | Labeled as an index |
| AI-written home descriptions | They can include made-up details | Built directly from the sale record |
| Stock photos of homes | Not the actual house | Street View turned to face the home, labeled as nearby imagery |
| Price predictions shown without their error | The error depends heavily on ZIP and price | Error shown with every estimate; homes outside the model's scope get no estimate |
