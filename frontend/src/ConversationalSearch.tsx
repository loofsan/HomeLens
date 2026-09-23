import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, Search, Sparkles } from 'lucide-react'
import { interpretSearch } from './api'
import type { InterpretedFilters, SearchIntentResponse } from './types'

const dollars = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

function filterLabels(filters: InterpretedFilters): string[] {
  const labels: string[] = []
  if (filters.min_price !== undefined) labels.push(`From ${dollars.format(filters.min_price)}`)
  if (filters.max_price !== undefined) labels.push(`Up to ${dollars.format(filters.max_price)}`)
  if (filters.min_beds !== undefined) labels.push(`${filters.min_beds}+ beds`)
  if (filters.min_baths !== undefined) labels.push(`${filters.min_baths}+ baths`)
  if (filters.zip) labels.push(`ZIP ${filters.zip}`)
  return labels
}

export default function ConversationalSearch({
  onApply,
  onPreview,
}: {
  onApply: (filters: InterpretedFilters) => void
  onPreview: () => void
}) {
  const [query, setQuery] = useState('')
  const [answer, setAnswer] = useState('')
  const [result, setResult] = useState<SearchIntentResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => () => controller.current?.abort(), [])

  async function run(question: string | null, clarification: string | null) {
    controller.current?.abort()
    const next = new AbortController()
    controller.current = next
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      const interpreted = await interpretSearch(query.trim(), question, clarification, next.signal)
      if (!next.signal.aborted) {
        setResult(interpreted)
        setAnswer('')
        if (interpreted.status === 'ready') onPreview()
      }
    } catch (cause: unknown) {
      if (!next.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Search could not be interpreted.')
      }
    } finally {
      if (!next.signal.aborted) setLoading(false)
    }
  }

  function submitQuery(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (query.trim().length >= 5) void run(null, null)
  }

  function submitAnswer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (result?.status === 'clarify' && result.question && answer.trim()) {
      void run(result.question, answer.trim())
    }
  }

  return (
    <section className="conversational-search" aria-label="Search by description">
      <div className="conversational-heading">
        <Sparkles size={16} aria-hidden="true" />
        <h2>Search by description</h2>
      </div>
      <form className="conversational-form" onSubmit={submitQuery}>
        <label className="sr-only" htmlFor="search-description">Describe your search</label>
        <input
          id="search-description"
          type="text"
          maxLength={400}
          placeholder="3+ beds under $400k in 27703"
          value={query}
          onChange={(event) => {
            controller.current?.abort()
            setQuery(event.target.value)
            setResult(null)
            setError(null)
            setLoading(false)
            setAnswer('')
          }}
        />
        <button type="submit" aria-label="Interpret search" title="Interpret search" disabled={loading || query.trim().length < 5}>
          <Search size={17} aria-hidden="true" />
        </button>
      </form>
      {loading && <p className="conversational-state" role="status">Interpreting search…</p>}
      {error && <p className="conversational-state" role="alert">{error}</p>}
      {result?.status === 'unsupported' && (
        <p className="conversational-state" role="status">{result.message}</p>
      )}
      {result?.status === 'clarify' && (
        <form className="conversational-clarification" onSubmit={submitAnswer}>
          <label htmlFor="search-clarification">{result.question}</label>
          <div>
            <input
              id="search-clarification"
              type="text"
              maxLength={200}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
            />
            <button type="submit" aria-label="Continue search" title="Continue search" disabled={!answer.trim()}>
              <ArrowRight size={17} aria-hidden="true" />
            </button>
          </div>
        </form>
      )}
      {result?.status === 'ready' && (
        <div className="conversational-preview">
          <div className="conversational-preview-label">Search filters</div>
          <p>{filterLabels(result.filters).join(' · ')}</p>
          <button type="button" onClick={() => onApply(result.filters)}>
            <Search size={15} aria-hidden="true" /> Apply search
          </button>
        </div>
      )}
    </section>
  )
}
