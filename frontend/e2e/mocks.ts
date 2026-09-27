import type { Page } from '@playwright/test'
import type { HistoricalSale } from '../src/types'

export const source = {
  name: 'Redfin sold-home CSV export',
  latest_sale_date: '2025-05-20',
  source_sha256: 'a'.repeat(64),
  boundary_sha256: 'b'.repeat(64),
  record_kind: 'historical_sale',
  active_listings: false,
  synthetic: false,
} as const

export const sales: HistoricalSale[] = [
  {
    id: `sale_${'a'.repeat(32)}`,
    record_kind: 'historical_sale',
    sale_date: '2025-05-20',
    sold_price_usd: 350000,
    beds: 3,
    baths: 2,
    square_feet: 1420,
    year_built: 1998,
    property_type: 'Townhouse',
    address: '1 Main St',
    city: 'Durham',
    state: 'NC',
    zip: '27703',
    latitude: 36.025,
    longitude: -78.92,
    source_url: 'https://www.redfin.com/NC/Durham/1-Main-St',
  },
  {
    id: `sale_${'b'.repeat(32)}`,
    record_kind: 'historical_sale',
    sale_date: '2024-06-01',
    sold_price_usd: 500000,
    beds: 4,
    baths: 3,
    square_feet: 2150,
    year_built: 2006,
    property_type: 'Single Family Residential',
    address: '2 Main St',
    city: 'Durham',
    state: 'NC',
    zip: '27705',
    latitude: 36.045,
    longitude: -78.95,
    source_url: null,
  },
  {
    id: `sale_${'c'.repeat(32)}`,
    record_kind: 'historical_sale',
    sale_date: '2023-01-01',
    sold_price_usd: 220000,
    beds: 2,
    baths: 1,
    square_feet: 980,
    year_built: 1984,
    property_type: 'Condo/Co-op',
    address: '3 Main St',
    city: 'Durham',
    state: 'NC',
    zip: '27517',
    latitude: 35.99,
    longitude: -78.9,
    source_url: null,
  },
]

export const transparentPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII=',
  'base64',
)

export async function mockBackend(
  page: Page,
  options: { initialFailures?: number; extraSales?: number; synthetic?: boolean } = {},
) {
  const baseSales = [
    ...sales,
    ...Array.from({ length: options.extraSales ?? 0 }, (_, index) => ({
      ...sales[0],
      id: `sale_${(index + 10).toString(16).padStart(32, '0')}`,
      address: `${index + 10} Sample St`,
      sale_date: '2022-05-01',
    })),
  ]
  const allSales = options.synthetic
    ? baseSales.map((sale, index) => ({
      ...sale,
      address: `Fictional example ${String(index + 1).padStart(2, '0')}`,
      source_url: null,
    }))
    : baseSales
  const catalogSource = options.synthetic
    ? { ...source, name: 'Synthetic HomeLens demo records', synthetic: true }
    : source
  let failuresRemaining = options.initialFailures ?? 0
  await page.route('https://tile.openstreetmap.org/**', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: transparentPng }),
  )
  await page.route('**/api/search/interpret', async (route) => {
    const payload = route.request().postDataJSON() as {
      query: string
      question?: string
      answer?: string
    }
    if (payload.query === 'AI unavailable') {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: { message: 'AI search is not configured. Use the filters below.' } }),
      })
      return
    }
    if (payload.query === 'Townhouses built in 1990 or later between 1,000 and 1,500 sq ft') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ready',
          filters: { property_type: 'townhouse', min_sqft: 1000, max_sqft: 1500, min_year_built: 1990 },
          question: null,
          message: null,
        }),
      })
      return
    }
    const unsupported = payload.query.startsWith('Active listings')
    const clarify = payload.query === 'Homes around $400k' && !payload.answer
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: unsupported ? 'unsupported' : clarify ? 'clarify' : 'ready',
        filters: unsupported || clarify ? {} : payload.answer ? { max_price: 450000 } : {
          max_price: 400000, min_beds: 3, zip: '27703',
        },
        question: clarify ? 'What maximum price should I use?' : null,
        message: unsupported ? 'This search supports historical sales by price, minimum beds or baths, and ZIP. That request includes an unsupported condition.' : null,
      }),
    })
  })
  await page.route('**/api/properties**', async (route) => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/valuation')) {
      const supported = url.pathname.includes(sales[0].id)
      await route.fulfill({
        status: supported ? 200 : 422,
        contentType: 'application/json',
        body: JSON.stringify(supported ? {
          property_id: sales[0].id,
          estimated_historical_price_usd: 321000,
          model_version: 'county-poisson-v1',
          scope: 'selected eight ZIPs inside Durham County boundary',
          earliest_supported_sale_date: '2020-05-21',
          latest_supported_sale_date: '2025-05-20',
          evaluation: {
            held_out_test_mae_usd: 81625.74,
            held_out_test_mean_signed_error_usd: -56951.48,
          },
          prediction_interval: null,
          disclaimer: 'Experimental estimate for a historical sale, not a current market valuation or appraisal.',
        } : { error: { code: 'valuation_unsupported', message: 'This ZIP is outside the model study area.' } }),
      })
      return
    }
    if (url.pathname.endsWith('/value-trend')) {
      const known = url.pathname.includes(sales[1].id)
      const common = {
        property_id: url.pathname.split('/')[3],
        zip: known ? '27705' : '27703',
        source: 'Supplied ZIP home value index (Zillow Research layout)',
        series_label: 'ZHVI-style typical home value index (Zillow Research layout)',
        variant_confirmed: false,
        method_note: "Index adjustment multiplies the recorded sale price by the ZIP index change since the sale month. It assumes this home's value moved with its ZIP's typical home value and is not an appraisal or current market value.",
        forecast: null,
        forecast_note: 'No forward projection is served. In the rolling-origin backtest in notebooks/zip_value_outlook.ipynb, no method beat a no-change baseline at every 1-5 year horizon on both development and holdout origins.',
      }
      const months = ['2024-06', '2024-09', '2025-01', '2025-04']
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(known ? {
          ...common,
          status: 'available',
          reason: null,
          sale_month: '2024-06',
          sale_price_usd: 500000,
          latest_month: '2025-04',
          latest_adjusted_value_usd: 506200,
          index_change_pct: 1.2,
          points: months.map((month, index) => ({
            month,
            index_value: 480000 + index * 2000,
            adjusted_value_usd: [500000, 502100, 504300, 506200][index],
          })),
        } : { ...common, status: 'unavailable', reason: 'sale_after_index' }),
      })
      return
    }
    if (url.pathname.endsWith('/demographics')) {
      const known = url.pathname.includes(sales[0].id)
      const metric = (estimate: number, moe: number, percent?: number, percentMoe?: number) => ({
        estimate: { value: estimate, status: 'available' },
        estimate_margin_of_error: { value: moe, status: 'available' },
        ...(percent === undefined ? {} : {
          percent: { value: percent, status: 'available' },
          percent_margin_of_error: { value: percentMoe, status: 'available' },
        }),
      })
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          property_id: url.pathname.split('/')[3],
          source: 'U.S. Census Bureau American Community Survey',
          geography: { kind: 'zcta', id: known ? '27703' : '27517', note: 'ZIP Code Tabulation Areas approximate USPS ZIP code delivery areas and may not match the recorded ZIP exactly.' },
          dataset: '2020-2024 ACS 5-Year Data Profiles DP05 and DP03',
          period: '2020-2024',
          status: known ? 'available' : 'unavailable',
          reason: known ? null : 'zcta_not_prepared',
          ...(known ? {
            metrics: {
              total_population: metric(58409, 1900),
              median_household_income_usd: metric(96900, 4100),
              median_age_years: metric(34.9, 0.8),
              under_18: metric(12800, 700, 21.9, 1.2),
              age_65_and_over: metric(6100, 500, 10.4, 0.9),
              white_alone_not_hispanic: metric(25800, 1100, 44.2, 2.0),
              black_alone_not_hispanic: metric(20600, 1300, 35.3, 2.2),
              hispanic_or_latino: metric(5100, 900, 8.7, 1.7),
              asian_alone_not_hispanic: metric(3700, 500, 6.3, 1.0),
              american_indian_alone_not_hispanic: metric(450, 200, 0.8, 0.3),
              pacific_islander_alone_not_hispanic: {
                estimate: { value: null, status: 'unavailable', source_token: '-' },
                estimate_margin_of_error: { value: null, status: 'unavailable', source_token: '**' },
                percent: { value: null, status: 'unavailable', source_token: '-' },
                percent_margin_of_error: { value: null, status: 'unavailable', source_token: '**' },
              },
              other_race_alone_not_hispanic: metric(300, 150, 0.5, 0.3),
              two_or_more_races_not_hispanic: metric(2400, 400, 4.2, 0.8),
            },
          } : {}),
        }),
      })
      return
    }
    if (url.pathname !== '/api/properties') {
      const sale = allSales.find((item) => url.pathname.endsWith(item.id))
      await route.fulfill({
        status: sale ? 200 : 404,
        contentType: 'application/json',
        body: JSON.stringify(
          sale
            ? { property: sale, source: catalogSource, description: options.synthetic ? 'Synthetic example for interface testing; not a recorded transaction.' : `This ${sale.property_type.toLowerCase()} at ${sale.address} sold for $${sale.sold_price_usd.toLocaleString()} on ${sale.sale_date}.` }
            : { error: { code: 'property_not_found', message: 'Sale not found.' } },
        ),
      })
      return
    }
    if (failuresRemaining > 0) {
      failuresRemaining -= 1
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: { message: 'Historical sales are unavailable.' } }),
      })
      return
    }
    const params = url.searchParams
    const matching = allSales
      .filter((sale) => !params.has('min_price') || sale.sold_price_usd >= Number(params.get('min_price')))
      .filter((sale) => !params.has('max_price') || sale.sold_price_usd <= Number(params.get('max_price')))
      .filter((sale) => !params.has('min_beds') || sale.beds >= Number(params.get('min_beds')))
      .filter((sale) => !params.has('min_baths') || sale.baths >= Number(params.get('min_baths')))
      .filter((sale) => !params.has('zip') || sale.zip === params.get('zip'))
      .filter((sale) => !params.has('property_type') || sale.property_type === {
        single_family: 'Single Family Residential', townhouse: 'Townhouse', condo: 'Condo/Co-op',
      }[params.get('property_type') as string])
      .filter((sale) => !params.has('min_sqft') || sale.square_feet >= Number(params.get('min_sqft')))
      .filter((sale) => !params.has('max_sqft') || sale.square_feet <= Number(params.get('max_sqft')))
      .filter((sale) => !params.has('min_year_built') || sale.year_built >= Number(params.get('min_year_built')))
      .filter((sale) => !params.has('max_year_built') || sale.year_built <= Number(params.get('max_year_built')))
      .filter((sale) => {
        if (!params.has('south')) return true
        return (
          sale.latitude >= Number(params.get('south')) &&
          sale.latitude <= Number(params.get('north')) &&
          sale.longitude >= Number(params.get('west')) &&
          sale.longitude <= Number(params.get('east'))
        )
      })
      .sort((left, right) => right.sale_date.localeCompare(left.sale_date) || left.id.localeCompare(right.id))
    const pageNumber = Number(params.get('page') ?? 1)
    const pageSize = Number(params.get('page_size') ?? 40)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: matching.slice((pageNumber - 1) * pageSize, pageNumber * pageSize),
        total: matching.length,
        page: pageNumber,
        page_size: pageSize,
        source: catalogSource,
      }),
    })
  })
}
