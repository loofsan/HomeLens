import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import type { HistoricalSale } from '../src/types'

const source = {
  name: 'Redfin sold-home CSV export',
  latest_sale_date: '2025-05-20',
  source_sha256: 'a'.repeat(64),
  boundary_sha256: 'b'.repeat(64),
  record_kind: 'historical_sale',
  active_listings: false,
  synthetic: false,
} as const

const sales: HistoricalSale[] = [
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

const transparentPng = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII=',
  'base64',
)

async function mockBackend(
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

test('AI search previews filters, clarifies, and keeps manual search available', async ({ page }, testInfo) => {
  await mockBackend(page)
  await page.goto('/')
  await page.getByLabel('Describe your search').fill('Sold homes under $400,000 with at least 3 beds in 27703')
  await page.getByRole('button', { name: 'Interpret search' }).click()
  await expect(page.getByText('Up to $400,000 · 3+ beds · ZIP 27703')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Filters', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByRole('button', { name: /View 1 Main St/ })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('ai-search-preview.png') })
  await page.getByRole('button', { name: 'Apply search' }).click()
  await expect(page.getByText('1 recorded sales')).toBeVisible()
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await expect(page.getByLabel('ZIP code')).toHaveValue('27703')

  await page.getByLabel('Describe your search').fill('Homes around $400k')
  await page.getByRole('button', { name: 'Interpret search' }).click()
  await expect(page.getByText('What maximum price should I use?')).toBeVisible()
  await page.getByLabel('What maximum price should I use?').fill('$450k')
  await page.getByRole('button', { name: 'Continue search' }).click()
  await expect(page.getByText('Up to $450,000')).toBeVisible()
  await page.getByRole('button', { name: 'Apply search' }).click()
  await expect(page.getByText('2 recorded sales')).toBeVisible()

  await page.getByLabel('Describe your search').fill('Active listings under $500k')
  await page.getByRole('button', { name: 'Interpret search' }).click()
  await expect(page.getByText(/unsupported condition/)).toBeVisible()
  await page.getByLabel('Describe your search').fill('AI unavailable')
  await page.getByRole('button', { name: 'Interpret search' }).click()
  await expect(page.getByRole('alert').getByText(/not configured/)).toBeVisible()
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByLabel('Min price').fill('300000')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByText('1 recorded sales')).toBeVisible()
})

test('synthetic catalog stays visibly fictional and skips property providers', async ({ page }, testInfo) => {
  await mockBackend(page, { synthetic: true })
  const providerRequests: string[] = []
  page.on('request', (request) => {
    if (/\/(valuation|context|street-view\/image)$/.test(request.url())) {
      providerRequests.push(request.url())
    }
  })
  await page.goto('/')
  await expect(page.getByText('Synthetic demo')).toBeVisible()
  await expect(page.getByText('Fictional records')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Explore sample homes' })).toBeVisible()
  await expect(page.getByText('3 sample records')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Filters', exact: true })).toHaveAttribute('aria-expanded', 'false')
  await page.screenshot({ path: testInfo.outputPath('synthetic-list.png') })
  await page.getByRole('button', { name: /View Fictional example 01/ }).click()
  await expect(page.getByRole('complementary', { name: 'Synthetic demo details' })).toBeVisible()
  await expect(page.getByText('Sample price')).toBeVisible()
  await expect(page.getByText('Example date')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Sample record note' })).toContainText('not a recorded transaction')
  await expect(page.getByText(/No transaction occurred/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Estimate' })).toHaveCount(0)
  expect(providerRequests).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('synthetic-detail.png') })
  await page.getByRole('button', { name: 'Close sale details' }).click()
  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByLabel('ZIP code').fill('27703')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByRole('button', { name: 'Filters', exact: true })).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('1 sample record')).toBeVisible()
  if (testInfo.project.name === 'mobile') {
    await page.getByRole('button', { name: 'Map', exact: true }).click()
  }
  await expect(page.getByRole('region', { name: 'Synthetic demo map' })).toBeVisible()
  await expect(page.getByText('1 sample point on this page')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('synthetic-map.png') })
})

test('property detail shows a scoped estimate and explicit unsupported state', async ({ page }, testInfo) => {
  await mockBackend(page)
  await page.goto('/')
  await page.getByRole('button', { name: /View 1 Main St/ }).click()
  await page.getByRole('button', { name: 'Estimate' }).click()
  await expect(page.getByText('$321,000')).toBeVisible()
  await expect(page.getByText(/not a current market valuation/)).toBeVisible()
  await expect(page.getByText(/Held-out MAE/)).toBeVisible()
  await expect(page.getByText(/Sales from May 2020 to May 2025/)).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('valuation-detail.png') })
  await page.getByRole('button', { name: 'Close sale details' }).click()
  await page.getByRole('button', { name: /View 3 Main St/ }).click()
  await page.getByRole('button', { name: 'Estimate' }).click()
  await expect(page.getByRole('alert').getByText(/outside the model study area/)).toBeVisible()
})

test('search, inspect a sale, filter, and clear on desktop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop')
  await mockBackend(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Explore sold homes' })).toBeVisible()
  await expect(page.getByText('3 recorded sales')).toBeVisible()
  await expect(page.getByText('through May 20, 2025')).toBeVisible()
  await expect(page.locator('.leaflet-overlay-pane path.leaflet-interactive')).toHaveCount(3)
  await page.screenshot({ path: testInfo.outputPath('desktop-search.png') })

  await page.getByRole('button', { name: /View 1 Main St/ }).click()
  await expect(page.getByRole('complementary', { name: 'Historical sale details' })).toBeVisible()
  await expect(page.getByText('Not an active listing')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Recorded sale summary' })).toContainText('sold for $350,000')
  await expect(page.getByText('Sold May 20, 2025')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-detail.png') })
  await page.getByRole('button', { name: 'Close sale details' }).click()

  await page.getByLabel('Min price').fill('400000')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByText('1 recorded sales')).toBeVisible()
  await expect(page.getByRole('button', { name: /View 2 Main St/ })).toBeVisible()
  await page.getByRole('button', { name: 'Reset filters and map area' }).click()
  await expect(page.getByText('3 recorded sales')).toBeVisible()
})

test('map selection and map-area search stay synchronized', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop')
  await mockBackend(page)
  await page.goto('/')
  await expect(page.locator('.leaflet-overlay-pane path.leaflet-interactive')).toHaveCount(3)
  await page.locator('.leaflet-overlay-pane path.leaflet-interactive').nth(1).click()
  await expect(page.getByRole('complementary', { name: 'Historical sale details' })).toBeVisible()
  await expect(page.locator('.sale-row[aria-pressed="true"]')).toHaveCount(1)
  await page.getByRole('button', { name: 'Close sale details' }).click()
  await page.getByRole('button', { name: 'Search this area' }).click()
  await expect(page.getByText('Within map area')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('desktop-map-area.png') })
  await page.getByRole('button', { name: 'Clear map area' }).click()
  await expect(page.getByText('Durham County')).toBeVisible()
})

test('empty, unavailable, and paginated states', async ({ page }) => {
  await mockBackend(page, { initialFailures: 2, extraSales: 40 })
  await page.goto('/')
  await expect(page.getByText('Sales are unavailable', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByText('43 recorded sales')).toBeVisible()
  await expect(page.getByText('Page 1 of 2')).toBeVisible()
  await page.getByRole('button', { name: 'Next page' }).click()
  await expect(page.getByText('Page 2 of 2')).toBeVisible()
  await expect(page.locator('.sale-row')).toHaveCount(3)
  await page.getByLabel('ZIP code').fill('99999')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByText('No sales match')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page.getByText('43 recorded sales')).toBeVisible()

  await page.route('**/api/properties?**', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ error: { message: 'Historical sales are unavailable.' } }),
    }),
  )
  await page.getByLabel('ZIP code').fill('27703')
  await page.getByRole('button', { name: 'Apply filters' }).click()
  await expect(page.getByText('Sales unavailable', { exact: true })).toBeVisible()
  await expect(page.getByText('43 recorded sales')).toHaveCount(0)
  await expect(page.locator('.leaflet-overlay-pane path.leaflet-interactive')).toHaveCount(0)
})

test('mobile list, map, and sale details fit the viewport', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile')
  await mockBackend(page)
  await page.goto('/')
  await expect(page.getByText('3 recorded sales')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('mobile-list.png') })
  await page.getByRole('button', { name: 'Map', exact: true }).click()
  await expect(page.locator('.map-panel')).toBeVisible()
  await expect(page.locator('.leaflet-overlay-pane path.leaflet-interactive')).toHaveCount(3)
  await page.screenshot({ path: testInfo.outputPath('mobile-map.png') })
  await page.locator('.leaflet-overlay-pane path.leaflet-interactive').first().click()
  await expect(page.getByRole('complementary', { name: 'Historical sale details' })).toBeVisible()
  await expect(page.getByText('Not an active listing')).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('mobile-detail.png') })
  await page.getByRole('button', { name: 'Close sale details' }).click()
  await page.getByRole('button', { name: 'List', exact: true }).click()
  await expect(page.getByRole('button', { name: /View 1 Main St/ })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  expect(overflow).toBe(false)
})

test('property context loads on demand with partial and sourced states', async ({ page }, testInfo) => {
  await mockBackend(page)
  let calls = 0
  await page.route('**/api/properties/*/context', async (route) => {
    calls += 1
    const base = {
      property_id: sales[0].id,
      coordinate_source: 'historical_sale_catalog',
      nearby_places: {
        status: 'available', reason: null, source: 'Google Maps Places API (New)',
        coverage: { radius_m: 1500, distance_kind: 'straight_line' },
        data: { places: [{
          name: 'Duke Park', type: 'park', distance_m: 430,
          maps_url: 'https://maps.google.com/?cid=123',
          attributions: [{ provider: 'City of Durham', url: 'https://www.durhamnc.gov/' }],
        }] },
      },
      street_view: calls === 1 ? {
        status: 'unavailable', reason: 'not_covered', source: 'Google Maps Street View Static API',
        coverage: { radius_m: 50 }, data: null,
      } : {
        status: 'available', reason: null, source: 'Google Maps Street View Static API',
        coverage: { radius_m: 50 },
        data: {
          captured: '2023-08', copyright: 'Google', distance_m: 22,
          image_url: `/api/properties/${sales[0].id}/street-view/image`,
          maps_url: 'https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=36.025,-78.92',
        },
      },
      solar: calls === 1 ? {
        status: 'error', reason: 'provider_timeout', source: 'Google Maps Solar API',
        coverage: { property_match_verified: false }, data: null,
      } : {
        status: 'available', reason: null, source: 'Google Maps Solar API',
        coverage: { property_match_verified: false },
        data: {
          building_distance_m: 9, imagery_date: '2022-05-07', imagery_quality: 'HIGH',
          max_array_panels_count: 10, panel_capacity_watts: 400,
          max_array_capacity_kw: 4, postal_code_matches: true,
        },
      },
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(base) })
  })
  await page.route('**/api/properties/*/street-view/image', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: transparentPng }),
  )
  await page.goto('/')
  await expect(page.getByText('3 recorded sales')).toBeVisible()
  await page.getByRole('button', { name: /View 1 Main St/ }).click()
  await expect(page.getByRole('heading', { name: 'Nearby context' })).toBeVisible()
  expect(calls).toBe(0)
  await page.getByRole('button', { name: 'Load context' }).click()
  await expect(page.getByText('Duke Park')).toBeVisible()
  await expect(page.getByText('No coverage was found near this location.')).toBeVisible()
  await expect(page.getByText('The provider timed out.')).toBeVisible()
  await expect(page.getByText('City of Durham')).toBeVisible()
  await page.getByRole('button', { name: 'Refresh' }).click()
  await expect(page.getByText('Nearby imagery is not a verified photo of this home.')).toBeVisible()
  await expect(page.getByText('This roof is not verified as belonging to the recorded property. No financial estimate is implied.')).toBeVisible()
  await expect(page.getByText('4 kW')).toBeVisible()
  await expect(page.getByRole('link', { name: 'View Duke Park on Google Maps' })).toHaveAttribute('href', 'https://maps.google.com/?cid=123')
  await expect(page.locator('.street-view-image')).toBeVisible()
  await expect(page.locator('.context-attribution > span:first-child')).toHaveCount(3)
  await page.getByRole('region', { name: 'Solar context' }).scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath(`${testInfo.project.name}-context.png`) })
  expect(calls).toBe(2)
})
