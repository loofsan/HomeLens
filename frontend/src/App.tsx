import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  ArrowLeft,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  House,
  List,
  Map as MapIcon,
  MapPin,
  RefreshCw,
  RotateCcw,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import { getSale, searchSales } from './api'
import ConversationalSearch from './ConversationalSearch'
import MapPanel from './MapPanel'
import PropertyContext from './PropertyContext'
import PropertyValuation from './PropertyValuation'
import type {
  CatalogSource,
  HistoricalSale,
  InterpretedFilters,
  MapBounds,
  SearchFilters,
  SearchResponse,
} from './types'

const emptyFilters: SearchFilters = {
  minPrice: '',
  maxPrice: '',
  minBeds: '',
  minBaths: '',
  zip: '',
}

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})
const integer = new Intl.NumberFormat('en-US')
const dateFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
  timeZone: 'UTC',
})

function saleDate(value: string): string {
  return dateFormat.format(new Date(`${value}T12:00:00Z`))
}

function featureCount(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function SaleRow({
  sale,
  selected,
  onSelect,
}: {
  sale: HistoricalSale
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      className={`sale-row${selected ? ' is-selected' : ''}`}
      type="button"
      aria-pressed={selected}
      aria-label={`View ${sale.address}, sold ${saleDate(sale.sale_date)}`}
      onClick={onSelect}
    >
      <span className="sale-row-top">
        <strong>{money.format(sale.sold_price_usd)}</strong>
        <span className="sale-row-date">{saleDate(sale.sale_date)}</span>
      </span>
      <span className="sale-address">{sale.address}</span>
      <span className="sale-location">
        {sale.city}, {sale.state} {sale.zip}
      </span>
      <span className="sale-facts">
        {featureCount(sale.beds)} bd <span aria-hidden="true">·</span>{' '}
        {featureCount(sale.baths)} ba <span aria-hidden="true">·</span>{' '}
        {integer.format(sale.square_feet)} sq ft
      </span>
    </button>
  )
}

function SaleDetail({
  sale,
  source,
  description,
  loading,
  error,
  onRetry,
  onClose,
}: {
  sale: HistoricalSale | null
  source: CatalogSource | null
  description: string | null
  loading: boolean
  error: string | null
  onRetry: () => void
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    closeRef.current?.focus()
  }, [])

  return (
    <aside className="detail-panel" aria-label="Historical sale details">
      <div className="detail-topbar">
        <button
          ref={closeRef}
          className="icon-button detail-close"
          type="button"
          aria-label="Close sale details"
          title="Close sale details"
          onClick={onClose}
        >
          <ArrowLeft size={19} aria-hidden="true" />
        </button>
        <span className="detail-topbar-title">Sale details</span>
        <span className="historical-tag">Historical sale</span>
      </div>
      {loading && <div className="detail-state">Loading sale details…</div>}
      {error && (
        <div className="detail-state" role="alert">
          <p>{error}</p>
          <button className="secondary-button" type="button" onClick={onRetry}>
            <RefreshCw size={16} aria-hidden="true" /> Retry
          </button>
        </div>
      )}
      {!loading && !error && sale && (
        <div className="detail-body">
          <div className="detail-heading">
            <div className="detail-location">
              <MapPin size={15} aria-hidden="true" />
              {sale.city}, {sale.state} {sale.zip}
            </div>
            <h2>{sale.address}</h2>
            <p className="detail-kind">{sale.property_type}</p>
          </div>
          <div className="detail-price">
            <span>Sold price</span>
            <strong>{money.format(sale.sold_price_usd)}</strong>
            <span className="detail-sold-date">
              <CalendarDays size={16} aria-hidden="true" />
              Sold {saleDate(sale.sale_date)}
            </span>
          </div>
          <div className="detail-facts" aria-label="Property facts">
            <div>
              <strong>{featureCount(sale.beds)}</strong>
              <span>Beds</span>
            </div>
            <div>
              <strong>{featureCount(sale.baths)}</strong>
              <span>Baths</span>
            </div>
            <div>
              <strong>{integer.format(sale.square_feet)}</strong>
              <span>Sq ft</span>
            </div>
            <div>
              <strong>{sale.year_built}</strong>
              <span>Built</span>
            </div>
          </div>
          {description && (
            <section className="detail-summary" aria-label="Recorded sale summary">
              <h3>Recorded sale summary</h3>
              <p>{description}</p>
            </section>
          )}
          <PropertyValuation key={sale.id} propertyId={sale.id} />
          <PropertyContext propertyId={sale.id} />
          <div className="detail-source">
            <h3>Record source</h3>
            <p>{source?.name ?? 'Historical sold-home export'}</p>
            <p>
              Dataset through{' '}
              {source?.latest_sale_date
                ? saleDate(source.latest_sale_date)
                : 'an unknown date'}
            </p>
            <p className="source-caution">Not an active listing</p>
            {sale.source_url && (
              <a href={sale.source_url} target="_blank" rel="noreferrer noopener">
                View source record <ExternalLink size={15} aria-hidden="true" />
              </a>
            )}
          </div>
        </div>
      )}
    </aside>
  )
}

export default function App() {
  const [draft, setDraft] = useState<SearchFilters>(emptyFilters)
  const [filters, setFilters] = useState<SearchFilters>(emptyFilters)
  const [bounds, setBounds] = useState<MapBounds | null>(null)
  const [page, setPage] = useState(1)
  const [response, setResponse] = useState<SearchResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [filtersExpanded, setFiltersExpanded] = useState(true)
  const [retry, setRetry] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<HistoricalSale | null>(null)
  const [detailSource, setDetailSource] = useState<CatalogSource | null>(null)
  const [detailDescription, setDetailDescription] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailRetry, setDetailRetry] = useState(0)
  const [mobileView, setMobileView] = useState<'list' | 'map'>('list')
  const [mapReset, setMapReset] = useState(0)
  const resultListRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setResponse(null)
    searchSales(filters, page, bounds, controller.signal)
      .then((result) => {
        setResponse(result)
        setSelectedId((current) =>
          result.items.some((sale) => sale.id === current) ? current : null,
        )
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : 'Sales could not be loaded.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [filters, bounds, page, retry])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      setDetailSource(null)
      setDetailDescription(null)
      setDetailError(null)
      return
    }
    const controller = new AbortController()
    setDetail(null)
    setDetailDescription(null)
    setDetailLoading(true)
    setDetailError(null)
    getSale(selectedId, controller.signal)
      .then((result) => {
        setDetail(result.property)
        setDetailSource(result.source)
        setDetailDescription(result.description)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setDetailError(
          cause instanceof Error ? cause.message : 'Sale details could not be loaded.',
        )
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false)
      })
    return () => controller.abort()
  }, [selectedId, detailRetry])

  useEffect(() => {
    if (!selectedId) return
    document.getElementById(`sale-${selectedId}`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedId, mobileView])

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setSelectedId(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [])

  const items = response?.items ?? []
  const selected = useMemo(
    () => detail ?? items.find((sale) => sale.id === selectedId) ?? null,
    [detail, items, selectedId],
  )
  const source = response?.source ?? null
  const totalPages = Math.max(1, Math.ceil((response?.total ?? 0) / 40))

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (draft.zip && !/^\d{5}$/.test(draft.zip)) {
      setFormError('ZIP must be five digits.')
      return
    }
    if (
      draft.minPrice &&
      draft.maxPrice &&
      Number(draft.minPrice) > Number(draft.maxPrice)
    ) {
      setFormError('Minimum price must not exceed maximum price.')
      return
    }
    setFormError(null)
    setFilters({ ...draft })
    setPage(1)
    setSelectedId(null)
    resultListRef.current?.scrollTo({ top: 0 })
  }

  function applyInterpretedFilters(interpreted: InterpretedFilters) {
    const next: SearchFilters = {
      minPrice: interpreted.min_price === undefined ? '' : String(interpreted.min_price),
      maxPrice: interpreted.max_price === undefined ? '' : String(interpreted.max_price),
      minBeds: interpreted.min_beds === undefined ? '' : String(interpreted.min_beds),
      minBaths: interpreted.min_baths === undefined ? '' : String(interpreted.min_baths),
      zip: interpreted.zip ?? '',
    }
    setDraft(next)
    setFilters(next)
    setBounds(null)
    setPage(1)
    setSelectedId(null)
    setFormError(null)
    resultListRef.current?.scrollTo({ top: 0 })
  }

  function resetFilters() {
    setDraft({ ...emptyFilters })
    setFilters({ ...emptyFilters })
    setBounds(null)
    setPage(1)
    setSelectedId(null)
    setFormError(null)
    setFiltersExpanded(true)
    setMapReset((value) => value + 1)
  }

  function changePage(next: number) {
    setSelectedId(null)
    setPage(next)
    resultListRef.current?.scrollTo({ top: 0 })
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-icon"><House size={20} strokeWidth={2.2} aria-hidden="true" /></span>
          <span>HomeLens</span>
        </div>
        <div className="topbar-source">
          <span className="source-dot" aria-hidden="true" />
          <span>Historical sales</span>
          {source?.latest_sale_date && (
            <span className="source-through">through {saleDate(source.latest_sale_date)}</span>
          )}
        </div>
      </header>

      <main className={`workspace${selectedId ? ' has-detail' : ''}`}>
        <section
          className={`sidebar${mobileView === 'map' ? ' mobile-hidden' : ''}`}
          aria-label="Historical sale search"
        >
          <div className="search-heading">
            <div>
              <p className="eyebrow">Durham, North Carolina</p>
              <h1>Explore sold homes</h1>
            </div>
          </div>

          <ConversationalSearch
            onApply={applyInterpretedFilters}
            onPreview={() => setFiltersExpanded(false)}
          />

          <form className="filters" onSubmit={applyFilters}>
            <div className="filter-heading">
              <button
                className="filters-disclosure"
                type="button"
                aria-expanded={filtersExpanded}
                aria-controls="manual-filter-grid"
                onClick={() => setFiltersExpanded((value) => !value)}
              >
                <SlidersHorizontal size={17} aria-hidden="true" /> Filters
                <ChevronDown size={15} aria-hidden="true" className={filtersExpanded ? 'is-up' : ''} />
              </button>
              <button
                className="icon-button reset-button"
                type="button"
                onClick={resetFilters}
                aria-label="Reset filters and map area"
                title="Reset filters and map area"
              >
                <RotateCcw size={17} aria-hidden="true" />
              </button>
            </div>
            <div className="filter-grid" id="manual-filter-grid" hidden={!filtersExpanded}>
              <label>
                <span>Min price</span>
                <input
                  type="number"
                  min="0"
                  step="10000"
                  placeholder="No min"
                  value={draft.minPrice}
                  onChange={(event) => setDraft({ ...draft, minPrice: event.target.value })}
                />
              </label>
              <label>
                <span>Max price</span>
                <input
                  type="number"
                  min="0"
                  step="10000"
                  placeholder="No max"
                  value={draft.maxPrice}
                  onChange={(event) => setDraft({ ...draft, maxPrice: event.target.value })}
                />
              </label>
              <label>
                <span>Beds</span>
                <select
                  value={draft.minBeds}
                  onChange={(event) => setDraft({ ...draft, minBeds: event.target.value })}
                >
                  <option value="">Any</option>
                  {[1, 2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>{value}+</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Baths</span>
                <select
                  value={draft.minBaths}
                  onChange={(event) => setDraft({ ...draft, minBaths: event.target.value })}
                >
                  <option value="">Any</option>
                  {[1, 2, 3, 4].map((value) => (
                    <option key={value} value={value}>{value}+</option>
                  ))}
                </select>
              </label>
              <label className="zip-field">
                <span>ZIP code</span>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={5}
                  placeholder="Any ZIP"
                  value={draft.zip}
                  onChange={(event) => setDraft({ ...draft, zip: event.target.value })}
                />
              </label>
              <button className="apply-button" type="submit">
                <Search size={17} aria-hidden="true" /> Apply filters
              </button>
            </div>
            {filtersExpanded && formError && <p className="form-error" role="alert">{formError}</p>}
          </form>

          <div className="results-heading">
            <div>
              <strong>
                {loading
                  ? 'Loading sales'
                  : error
                    ? 'Sales unavailable'
                    : `${integer.format(response?.total ?? 0)} recorded sales`}
              </strong>
              <span>{bounds ? 'Within map area' : 'Durham County'}</span>
            </div>
            {bounds && (
              <button
                type="button"
                className="area-clear-inline"
                onClick={() => { setBounds(null); setPage(1) }}
              >
                Clear area <X size={14} aria-hidden="true" />
              </button>
            )}
          </div>

          <div className="results-scroll" ref={resultListRef}>
            {loading && (
              <div className="result-state" role="status">
                <div className="loading-line" /><div className="loading-line short" />
                <div className="loading-line" /><div className="loading-line short" />
              </div>
            )}
            {!loading && error && (
              <div className="result-state" role="alert">
                <p className="state-title">Sales are unavailable</p>
                <p>{error}</p>
                <button className="secondary-button" type="button" onClick={() => setRetry((value) => value + 1)}>
                  <RefreshCw size={16} aria-hidden="true" /> Retry
                </button>
              </div>
            )}
            {!loading && !error && response?.total === 0 && (
              <div className="result-state">
                <p className="state-title">No sales match</p>
                <p>Try a broader price range or another ZIP.</p>
                <button className="secondary-button" type="button" onClick={resetFilters}>
                  <RotateCcw size={16} aria-hidden="true" /> Clear filters
                </button>
              </div>
            )}
            {!loading && !error && items.map((sale) => (
              <div id={`sale-${sale.id}`} key={sale.id}>
                <SaleRow sale={sale} selected={selectedId === sale.id} onSelect={() => setSelectedId(sale.id)} />
              </div>
            ))}
          </div>

          {!loading && !error && (response?.total ?? 0) > 0 && (
            <div className="pagination">
              <button className="icon-button" type="button" aria-label="Previous page" title="Previous page" disabled={page <= 1} onClick={() => changePage(page - 1)}>
                <ChevronLeft size={19} aria-hidden="true" />
              </button>
              <span>Page {page} of {totalPages}</span>
              <button className="icon-button" type="button" aria-label="Next page" title="Next page" disabled={page >= totalPages} onClick={() => changePage(page + 1)}>
                <ChevronRight size={19} aria-hidden="true" />
              </button>
            </div>
          )}
        </section>

        <div className={`map-wrap${mobileView === 'list' ? ' mobile-hidden' : ''}`}>
          <MapPanel
            items={items}
            selected={selected}
            mode={mobileView}
            activeBounds={bounds !== null}
            resetToken={mapReset}
            onSelect={setSelectedId}
            onSearchArea={(area) => { setBounds(area); setPage(1); setSelectedId(null) }}
            onClearArea={() => { setBounds(null); setPage(1) }}
          />
        </div>

        {selectedId && (
          <SaleDetail
            key={selectedId}
            sale={detail}
            source={detailSource ?? source}
            description={detailDescription}
            loading={detailLoading}
            error={detailError}
            onRetry={() => setDetailRetry((value) => value + 1)}
            onClose={() => setSelectedId(null)}
          />
        )}

        <nav className="mobile-tabs" aria-label="Search views">
          <button type="button" className={mobileView === 'list' ? 'active' : ''} aria-current={mobileView === 'list' ? 'page' : undefined} onClick={() => setMobileView('list')}>
            <List size={19} aria-hidden="true" /> List
          </button>
          <button type="button" className={mobileView === 'map' ? 'active' : ''} aria-current={mobileView === 'map' ? 'page' : undefined} onClick={() => setMobileView('map')}>
            <MapIcon size={19} aria-hidden="true" /> Map
          </button>
        </nav>
      </main>
    </div>
  )
}
