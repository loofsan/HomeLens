import type {
  DetailResponse,
  MapBounds,
  PropertyContextResponse,
  SearchFilters,
  SearchResponse,
  ValuationResponse,
} from './types'

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(
      payload?.error?.message ?? 'Historical sales could not be loaded.',
    )
  }
  return response.json() as Promise<T>
}

export async function searchSales(
  filters: SearchFilters,
  page: number,
  bounds: MapBounds | null,
  signal: AbortSignal,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ page: String(page), page_size: '40' })
  if (filters.minPrice) params.set('min_price', filters.minPrice)
  if (filters.maxPrice) params.set('max_price', filters.maxPrice)
  if (filters.minBeds) params.set('min_beds', filters.minBeds)
  if (filters.minBaths) params.set('min_baths', filters.minBaths)
  if (filters.zip) params.set('zip', filters.zip)
  if (bounds) {
    for (const key of ['south', 'west', 'north', 'east'] as const) {
      params.set(key, String(bounds[key]))
    }
  }
  return readResponse<SearchResponse>(
    await fetch(`/api/properties?${params}`, { signal }),
  )
}

export async function getSale(
  id: string,
  signal: AbortSignal,
): Promise<DetailResponse> {
  return readResponse<DetailResponse>(
    await fetch(`/api/properties/${encodeURIComponent(id)}`, { signal }),
  )
}

export async function getPropertyContext(
  id: string,
  signal: AbortSignal,
): Promise<PropertyContextResponse> {
  return readResponse<PropertyContextResponse>(
    await fetch(`/api/properties/${encodeURIComponent(id)}/context`, { signal }),
  )
}

export async function getValuation(
  id: string,
  signal: AbortSignal,
): Promise<ValuationResponse> {
  return readResponse<ValuationResponse>(
    await fetch(`/api/properties/${encodeURIComponent(id)}/valuation`, { signal }),
  )
}
