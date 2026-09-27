import { useEffect, useState } from 'react'
import { TrendingUp } from 'lucide-react'
import { getValueTrend } from './api'
import type { ValueTrendPoint, ValueTrendResponse } from './types'

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const compact = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 0 })
const monthName = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })

function monthLabel(month: string): string {
  return monthName.format(new Date(`${month}-01T00:00:00Z`))
}

const REASONS: Record<string, string> = {
  zip_not_in_index: 'The supplied value index does not cover this ZIP code.',
  sale_after_index: 'This sale is newer than the last month of the value index.',
  sale_before_index: 'This sale is older than the first month of the value index.',
  index_missing: 'The value index has no figure for the sale month.',
}

function Chart({ points }: { points: ValueTrendPoint[] }) {
  const width = 320
  const height = 150
  const pad = { top: 12, right: 12, bottom: 24, left: 52 }
  const values = points.map((point) => point.adjusted_value_usd)
  const low = Math.min(...values)
  const high = Math.max(...values)
  const span = high - low || Math.max(high * 0.02, 1)
  const min = low - span * 0.15
  const max = high + span * 0.15
  const x = (index: number) =>
    pad.left + (points.length === 1 ? 0 : (index / (points.length - 1)) * (width - pad.left - pad.right))
  const y = (value: number) => pad.top + (1 - (value - min) / (max - min)) * (height - pad.top - pad.bottom)
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(point.adjusted_value_usd).toFixed(1)}`).join(' ')
  const ticks = [min + (max - min) * 0.15, (min + max) / 2, max - (max - min) * 0.15]
  const last = points.length - 1
  return (
    <svg className="trend-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Index-adjusted value from ${monthLabel(points[0].month)} to ${monthLabel(points[last].month)}`}>
      {ticks.map((tick) => (
        <g key={tick}>
          <line x1={pad.left} x2={width - pad.right} y1={y(tick)} y2={y(tick)} className="trend-grid" />
          <text x={pad.left - 6} y={y(tick) + 3} textAnchor="end" className="trend-axis">{compact.format(tick)}</text>
        </g>
      ))}
      <path d={path} className="trend-line" />
      <circle cx={x(0)} cy={y(points[0].adjusted_value_usd)} r="4" className="trend-sale" />
      <circle cx={x(last)} cy={y(points[last].adjusted_value_usd)} r="4" className="trend-latest" />
      <text x={pad.left} y={height - 6} className="trend-axis">{monthLabel(points[0].month)}</text>
      <text x={width - pad.right} y={height - 6} textAnchor="end" className="trend-axis">{monthLabel(points[last].month)}</text>
    </svg>
  )
}

export default function ValueTrend({ propertyId }: { propertyId: string }) {
  const [trend, setTrend] = useState<ValueTrendResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<'chart' | 'table'>('chart')

  useEffect(() => {
    const controller = new AbortController()
    setTrend(null)
    setError(null)
    getValueTrend(propertyId, controller.signal)
      .then(setTrend)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'The value trend could not be loaded.')
        }
      })
    return () => controller.abort()
  }, [propertyId])

  const points = trend?.points ?? []
  const yearly = points.filter((point, index) => index === 0 || index === points.length - 1 || point.month.endsWith('-01'))
  const change = trend?.index_change_pct ?? 0
  return (
    <section className="value-trend" aria-label="Value since sale">
      <div className="value-trend-heading">
        <h3><TrendingUp size={16} aria-hidden="true" /> Value since sale</h3>
        {trend?.status === 'available' && (
          <div className="trend-toggle" role="group" aria-label="Value trend view">
            <button type="button" aria-pressed={view === 'chart'} onClick={() => setView('chart')}>Chart</button>
            <button type="button" aria-pressed={view === 'table'} onClick={() => setView('table')}>Table</button>
          </div>
        )}
      </div>
      {!trend && !error && <p className="context-status" role="status">Loading value trend…</p>}
      {error && <p className="context-status" role="alert">{error}</p>}
      {trend?.status === 'unavailable' && (
        <p className="context-status">{REASONS[trend.reason ?? ''] ?? 'A value trend is not available for this record.'}</p>
      )}
      {trend?.status === 'available' && trend.latest_month && trend.sale_month && (
        <>
          <div className="trend-summary">
            <strong>{dollars.format(trend.latest_adjusted_value_usd ?? 0)}</strong>
            <span>
              Index-adjusted to {monthLabel(trend.latest_month)} · {change >= 0 ? '+' : '−'}{Math.abs(change).toLocaleString(undefined, { maximumFractionDigits: 1 })}% for ZIP {trend.zip} since {monthLabel(trend.sale_month)}
            </span>
          </div>
          {view === 'chart' ? (
            points.length > 1
              ? <Chart points={points} />
              : <p className="context-status">The sale month is the latest month in the index.</p>
          ) : (
            <table className="trend-table">
              <thead><tr><th scope="col">Month</th><th scope="col">Index-adjusted value</th></tr></thead>
              <tbody>
                {yearly.map((point) => (
                  <tr key={point.month}><td>{monthLabel(point.month)}</td><td>{dollars.format(point.adjusted_value_usd)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="context-caution">{trend.method_note}</p>
          <p className="context-scope">
            No five-year projection is shown. In backtests on this index from 2006 to 2025, no forecasting method, including the ARIMA approach used by the original prototype, beat assuming no change reliably across 1–5 year horizons.
          </p>
          <p className="context-copyright">Source: {trend.series_label}; exact Zillow series variant not confirmed.</p>
        </>
      )}
    </section>
  )
}
