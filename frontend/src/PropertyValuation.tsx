import { useEffect, useState } from 'react'
import { RefreshCw, Sparkles } from 'lucide-react'
import { getValuation } from './api'
import type { ValuationResponse } from './types'

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

export default function PropertyValuation({ propertyId }: { propertyId: string }) {
  const [request, setRequest] = useState(0)
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [result, setResult] = useState<ValuationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (request === 0) return
    const controller = new AbortController()
    setStatus('loading')
    setError(null)
    setResult(null)
    getValuation(propertyId, controller.signal)
      .then((value) => {
        setResult(value)
        setStatus('ready')
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : 'Estimate is unavailable.')
        setStatus('error')
      })
    return () => controller.abort()
  }, [propertyId, request])

  return (
    <section className="property-valuation" aria-label="Historical price estimate">
      <div className="valuation-heading">
        <h3>Historical price estimate</h3>
        {status === 'idle' && (
          <button className="secondary-button" type="button" onClick={() => setRequest(1)}>
            <Sparkles size={15} aria-hidden="true" /> Estimate
          </button>
        )}
        {status === 'error' && (
          <button className="secondary-button" type="button" onClick={() => setRequest((value) => value + 1)}>
            <RefreshCw size={15} aria-hidden="true" /> Retry
          </button>
        )}
      </div>
      {status === 'loading' && <p className="valuation-status" role="status">Estimating…</p>}
      {status === 'error' && <p className="valuation-status" role="alert">{error}</p>}
      {result && (
        <div className="valuation-result">
          <strong>{money.format(result.estimated_historical_price_usd)}</strong>
          <p>{result.disclaimer}</p>
          <p>{result.scope.charAt(0).toUpperCase() + result.scope.slice(1)}. Sales from {new Date(`${result.earliest_supported_sale_date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })} to {new Date(`${result.latest_supported_sale_date}T12:00:00Z`).toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })}.</p>
          <p>Held-out MAE {money.format(result.evaluation.held_out_test_mae_usd)}; mean underprediction {money.format(Math.abs(result.evaluation.held_out_test_mean_signed_error_usd))}.</p>
          <span>{result.model_version}</span>
        </div>
      )}
    </section>
  )
}
