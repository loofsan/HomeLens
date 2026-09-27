import { useEffect, useMemo, useState } from 'react'
import type { ComponentProps } from 'react'
import type { Layer, PathOptions } from 'leaflet'
import { GeoJSON, Pane } from 'react-leaflet'
import { getCrimeBeats } from './api'
import type { CrimeBeatFeature, CrimeBeatsResponse, CrimeCategory } from './types'

const COLORS = ['#fbe7d5', '#f6c29c', '#ec9462', '#d4643a', '#a8401f'] as const
const NO_DATA = '#c3cccb'

type GeoJsonData = ComponentProps<typeof GeoJSON>['data']

export function quantileBreaks(values: number[], classes = COLORS.length): number[] {
  const sorted = [...values].sort((left, right) => left - right)
  if (sorted.length === 0) return []
  const breaks: number[] = []
  for (let index = 1; index < classes; index += 1) {
    const position = (sorted.length - 1) * (index / classes)
    const lower = Math.floor(position)
    const upper = Math.ceil(position)
    const value = sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower)
    if (breaks.length === 0 || value > breaks[breaks.length - 1]) breaks.push(value)
  }
  return breaks
}

function colorFor(value: number | null, breaks: number[]): string {
  if (value === null) return NO_DATA
  const index = breaks.findIndex((limit) => value <= limit)
  return COLORS[index === -1 ? breaks.length : index]
}

function formatRate(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: value < 10 ? 1 : 0 })
}

export function useCrimeBeats(enabled: boolean, year: number | null, category: CrimeCategory) {
  const [data, setData] = useState<CrimeBeatsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    getCrimeBeats(year, category, controller.signal)
      .then(setData)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'The crime map could not be loaded.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [enabled, year, category])

  return { data, error, loading }
}

export function CrimePolygons({ data }: { data: CrimeBeatsResponse }) {
  const breaks = useMemo(
    () => quantileBreaks(
      data.features
        .map((feature) => feature.properties.per_km2)
        .filter((value): value is number => value !== null),
    ),
    [data],
  )
  const label = data.metadata.category === 'violent' ? 'violent' : 'property'
  return (
    <Pane name="crime-beats" style={{ zIndex: 350 }}>
      <GeoJSON
        key={`${data.metadata.year}-${data.metadata.category}`}
        data={data as unknown as GeoJsonData}
        style={(feature) => {
          const properties = (feature as unknown as CrimeBeatFeature).properties
          return {
            color: '#6f4a3c',
            weight: 1,
            opacity: 0.55,
            fillColor: colorFor(properties.per_km2, breaks),
            fillOpacity: properties.per_km2 === null ? 0.25 : 0.5,
            dashArray: properties.per_km2 === null ? '4 3' : undefined,
          } satisfies PathOptions
        }}
        onEachFeature={(feature, layer: Layer) => {
          const properties = (feature as unknown as CrimeBeatFeature).properties
          const text = properties.count === null
            ? `Beat ${properties.beat} · no linked reports`
            : `Beat ${properties.beat} · ${properties.count.toLocaleString()} ${label} offense records in ${data.metadata.year} · ${formatRate(properties.per_km2 ?? 0)} per km²`
          layer.bindTooltip(text, { sticky: true })
        }}
      />
    </Pane>
  )
}

export function CrimeLegend({
  data,
  error,
  loading,
  year,
  category,
  onYear,
  onCategory,
}: {
  data: CrimeBeatsResponse | null
  error: string | null
  loading: boolean
  year: number | null
  category: CrimeCategory
  onYear: (year: number) => void
  onCategory: (category: CrimeCategory) => void
}) {
  const breaks = useMemo(
    () => data
      ? quantileBreaks(
        data.features
          .map((feature) => feature.properties.per_km2)
          .filter((value): value is number => value !== null),
      )
      : [],
    [data],
  )
  const coverage = data?.metadata.coverage
  const shownYear = year ?? data?.metadata.year ?? ''
  const hasNoData = data?.features.some((feature) => feature.properties.per_km2 === null)
  return (
    <section className="crime-legend" aria-label="Crime by police beat">
      <div className="crime-legend-controls">
        <label>
          <span>Offenses</span>
          <select value={category} onChange={(event) => onCategory(event.target.value as CrimeCategory)}>
            <option value="violent">Violent</option>
            <option value="property">Property</option>
          </select>
        </label>
        <label>
          <span>Year</span>
          <select
            value={shownYear}
            disabled={!data}
            onChange={(event) => onYear(Number(event.target.value))}
          >
            {(data?.metadata.years ?? []).map((item) => (
              <option key={item.year} value={item.year}>
                {item.year}{item.complete ? '' : ' (partial)'}
              </option>
            ))}
          </select>
        </label>
      </div>
      {loading && <p role="status">Loading beat counts…</p>}
      {error && !loading && <p role="alert">{error}</p>}
      {data && !loading && !error && (
        <>
          <p className="crime-legend-title">Reported {data.metadata.category} offense records per km²</p>
          <ul className="crime-scale">
            {COLORS.slice(0, breaks.length + 1).map((color, index) => {
              const low = index === 0 ? 0 : breaks[index - 1]
              const high = breaks[index]
              return (
                <li key={color}>
                  <span className="crime-swatch" style={{ background: color }} aria-hidden="true" />
                  {high === undefined ? `Over ${formatRate(low)}` : index === 0 ? `Up to ${formatRate(high)}` : `${formatRate(low)}–${formatRate(high)}`}
                </li>
              )
            })}
            {hasNoData && (
              <li>
                <span className="crime-swatch is-empty" aria-hidden="true" />
                No linked reports
              </li>
            )}
          </ul>
          {coverage && !coverage.complete && (
            <p className="crime-warning">Partial year: reports through {coverage.last_report_date}.</p>
          )}
          <details>
            <summary>About this layer</summary>
            <p>{data.metadata.definition}.</p>
            <ul>
              {data.metadata.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
            <p>Source: {data.metadata.source}; beat boundaries from the City of Durham GIS police beats layer.</p>
          </details>
        </>
      )}
    </section>
  )
}
