export type HistoricalSale = {
  id: string
  record_kind: 'historical_sale'
  sale_date: string
  sold_price_usd: number
  beds: number
  baths: number
  square_feet: number
  year_built: number
  property_type: string
  address: string
  city: string
  state: 'NC'
  zip: string
  latitude: number
  longitude: number
  source_url: string | null
}

export type CatalogSource = {
  name: string
  latest_sale_date: string | null
  source_sha256: string
  boundary_sha256: string
  record_kind: 'historical_sale'
  active_listings: false
  synthetic: boolean
}

export type SearchResponse = {
  items: HistoricalSale[]
  total: number
  page: number
  page_size: number
  source: CatalogSource
}

export type DetailResponse = {
  property: HistoricalSale
  source: CatalogSource
  description: string
}

export type ValuationResponse = {
  property_id: string
  estimated_historical_price_usd: number
  model_version: string
  scope: string
  earliest_supported_sale_date: string
  latest_supported_sale_date: string
  evaluation: {
    held_out_test_mae_usd: number
    held_out_test_mean_signed_error_usd: number
  }
  prediction_interval: null
  disclaimer: string
}

export type PropertyTypeSlug = 'single_family' | 'townhouse' | 'condo'

export type SearchFilters = {
  minPrice: string
  maxPrice: string
  minBeds: string
  minBaths: string
  zip: string
  propertyType: PropertyTypeSlug | ''
  minSqft: string
  maxSqft: string
  minYearBuilt: string
  maxYearBuilt: string
}

export type InterpretedFilters = {
  min_price?: number
  max_price?: number
  min_beds?: number
  min_baths?: number
  zip?: string
  property_type?: PropertyTypeSlug
  min_sqft?: number
  max_sqft?: number
  min_year_built?: number
  max_year_built?: number
}

export type SearchIntentResponse = {
  status: 'ready' | 'clarify' | 'unsupported'
  filters: InterpretedFilters
  question: string | null
  message: string | null
}

export type MapBounds = {
  south: number
  west: number
  north: number
  east: number
}

export type ContextSection<T> = {
  status: 'available' | 'unavailable' | 'error'
  reason: string | null
  source: string
  coverage: Record<string, unknown>
  data: T | null
}

export type NearbyPlace = {
  name: string
  type: string | null
  distance_m: number
  maps_url: string | null
  attributions: { provider: string; url: string | null }[]
}

export type StreetViewData = {
  captured: string | null
  copyright: string | null
  distance_m: number
  heading_deg: number | null
  image_url: string
  maps_url: string
}

export type SolarData = {
  building_distance_m: number
  imagery_date: string | null
  imagery_quality: 'HIGH' | 'MEDIUM' | 'BASE' | null
  max_array_panels_count: number
  panel_capacity_watts: number
  max_array_capacity_kw: number
  postal_code_matches: boolean | null
  max_array_area_m2: number | null
  max_sunshine_hours_per_year: number | null
  carbon_offset_kg_per_mwh: number | null
  panel_lifetime_years: number | null
  financial_scenarios: SolarScenario[]
}

export type SolarScenario = {
  monthly_bill_usd: number
  is_default_bill: boolean
  panels_count: number | null
  yearly_energy_dc_kwh: number | null
  solar_percentage: number | null
  net_metering_allowed: boolean | null
  lifetime_cost_without_solar_usd: number | null
  lifetime_remaining_bill_usd: number | null
  upfront_cost_usd: number
  incentives_usd: number | null
  out_of_pocket_cost_usd: number | null
  payback_years: number | null
  savings_year1_usd: number | null
  savings_lifetime_usd: number | null
  financially_viable: boolean | null
}

export type PropertyContextResponse = {
  property_id: string
  coordinate_source: 'historical_sale_catalog'
  nearby_places: ContextSection<{ places: NearbyPlace[] }>
  street_view: ContextSection<StreetViewData>
  solar: ContextSection<SolarData>
}

export type CrimeCategory = 'violent' | 'property'

export type CrimeYear = {
  year: number
  complete: boolean
  first_report_date: string
  last_report_date: string
}

export type CrimeBeatFeature = {
  type: 'Feature'
  properties: {
    beat: string
    district: string | null
    area_km2: number
    count: number | null
    per_km2: number | null
  }
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown }
}

export type CrimeBeatsResponse = {
  type: 'FeatureCollection'
  metadata: {
    year: number
    coverage: CrimeYear
    years: CrimeYear[]
    category: CrimeCategory
    category_label: string
    definition: string
    source: string
    source_layer: string
    excluded_rows: Record<string, number>
    notes: string[]
  }
  features: CrimeBeatFeature[]
}
