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

export type SearchFilters = {
  minPrice: string
  maxPrice: string
  minBeds: string
  minBaths: string
  zip: string
}

export type InterpretedFilters = {
  min_price?: number
  max_price?: number
  min_beds?: number
  min_baths?: number
  zip?: string
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
}

export type PropertyContextResponse = {
  property_id: string
  coordinate_source: 'historical_sale_catalog'
  nearby_places: ContextSection<{ places: NearbyPlace[] }>
  street_view: ContextSection<StreetViewData>
  solar: ContextSection<SolarData>
}
