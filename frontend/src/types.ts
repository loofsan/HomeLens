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
}

export type SearchFilters = {
  minPrice: string
  maxPrice: string
  minBeds: string
  minBaths: string
  zip: string
}

export type MapBounds = {
  south: number
  west: number
  north: number
  east: number
}
