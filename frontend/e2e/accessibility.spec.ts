import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { mockBackend, sales } from './mocks'

async function violations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  return results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    targets: violation.nodes.map((node) => node.target.join(' ')).slice(0, 4),
  }))
}

async function mockContextAndCrime(page: Page) {
  await page.route('**/api/properties/*/context', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      property_id: sales[1].id,
      coordinate_source: 'historical_sale_catalog',
      nearby_places: {
        status: 'available', reason: null, source: 'Google Maps Places API (New)',
        coverage: { category: 'everyday', radius_m: 1500 },
        data: { places: [{ name: 'Duke Park', type: 'park', distance_m: 430, maps_url: 'https://maps.google.com/?cid=1', attributions: [] }] },
      },
      street_view: { status: 'unavailable', reason: 'not_covered', source: 'Google Maps Street View Static API', coverage: {}, data: null },
      solar: {
        status: 'available', reason: null, source: 'Google Maps Solar API', coverage: {},
        data: {
          building_distance_m: 9, imagery_date: '2022-05-07', imagery_quality: 'HIGH',
          max_array_panels_count: 10, panel_capacity_watts: 400, max_array_capacity_kw: 4,
          postal_code_matches: true, max_array_area_m2: 60, max_sunshine_hours_per_year: 1600,
          carbon_offset_kg_per_mwh: 600, panel_lifetime_years: 20,
          financial_scenarios: [{
            monthly_bill_usd: 100, is_default_bill: true, panels_count: 8, yearly_energy_dc_kwh: 4800,
            solar_percentage: 95, net_metering_allowed: true, lifetime_cost_without_solar_usd: 36000,
            lifetime_remaining_bill_usd: 5000, upfront_cost_usd: 19000, incentives_usd: 5700,
            out_of_pocket_cost_usd: 13300, payback_years: 12, savings_year1_usd: 1000,
            savings_lifetime_usd: 23000, financially_viable: true,
          }],
        },
      },
    }),
  }))
  await page.route('**/api/crime/beats?*', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      type: 'FeatureCollection',
      metadata: {
        year: 2025,
        coverage: { year: 2025, complete: true, first_report_date: '2025-01-01', last_report_date: '2025-12-31' },
        years: [{ year: 2025, complete: true, first_report_date: '2025-01-01', last_report_date: '2025-12-31' }],
        category: 'violent', category_label: 'Violent offenses', definition: 'FBI violent crime',
        source: 'City of Durham Police Department crime table', source_layer: 'https://example.org',
        excluded_rows: {}, notes: ['Counts describe whole beats.'],
      },
      features: [1, 2, 3].map((index) => ({
        type: 'Feature',
        properties: { beat: `11${index}`, district: 'D1', area_km2: 2, count: index * 10, per_km2: index * 5 },
        geometry: { type: 'Polygon', coordinates: [[[-79 + index * 0.02, 36], [-78.99 + index * 0.02, 36], [-78.99 + index * 0.02, 36.01], [-79 + index * 0.02, 36]]] },
      })),
    }),
  }))
}

test('main views have no WCAG A/AA violations', async ({ page }, testInfo) => {
  await mockBackend(page)
  await mockContextAndCrime(page)
  const found: Record<string, unknown> = {}
  await page.goto('/')
  await expect(page.getByText('3 recorded sales')).toBeVisible()
  found.landing = await violations(page)

  await page.getByRole('button', { name: 'More filters' }).click()
  await page.getByLabel('Describe your search').fill('Sold homes under $400,000 with at least 3 beds in 27703')
  await page.getByRole('button', { name: 'Interpret search' }).click()
  await expect(page.getByRole('button', { name: 'Apply search' })).toBeVisible()
  found.filtersAndPreview = await violations(page)

  await page.getByRole('button', { name: /View 2 Main St/ }).click()
  await page.getByRole('button', { name: 'Load context' }).click()
  await expect(page.getByText('Duke Park')).toBeVisible()
  await expect(page.getByText('$506,200')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Area demographics' }).getByText(/No census profile/)).toBeVisible()
  found.detail = await violations(page)
  await page.getByRole('button', { name: 'Close sale details' }).click()

  if (testInfo.project.name === 'mobile') {
    await page.getByRole('button', { name: 'Map', exact: true }).click()
  }
  await page.getByRole('button', { name: 'Crime by beat' }).click()
  await page.getByText('About this layer').click()
  await expect(page.getByText('Counts describe whole beats.')).toBeVisible()
  found.crimeLayer = await violations(page)

  expect(found).toEqual({ landing: [], filtersAndPreview: [], detail: [], crimeLayer: [] })
})

test('keyboard users can search, open, and close a sale without a pointer', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === 'mobile', 'Keyboard flow is checked on desktop')
  await mockBackend(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.getByText('3 recorded sales')).toBeVisible()
  await page.getByLabel('Min price').focus()
  await page.keyboard.type('300000')
  await page.keyboard.press('Enter')
  await expect(page.getByText('2 recorded sales')).toBeVisible()
  const row = page.getByRole('button', { name: /View 1 Main St/ })
  await row.focus()
  await expect(row).toBeFocused()
  await page.keyboard.press('Enter')
  const detail = page.getByRole('complementary', { name: 'Historical sale details' })
  await expect(detail).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(detail).toHaveCount(0)
})
