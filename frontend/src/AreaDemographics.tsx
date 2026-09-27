import { useEffect, useState } from 'react'
import { Users } from 'lucide-react'
import { getDemographics } from './api'
import type { AcsMetric, AcsValue, DemographicsResponse } from './types'

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

const GROUPS = [
  ['white_alone_not_hispanic', 'White'],
  ['black_alone_not_hispanic', 'Black or African American'],
  ['hispanic_or_latino', 'Hispanic or Latino (any race)'],
  ['asian_alone_not_hispanic', 'Asian'],
  ['american_indian_alone_not_hispanic', 'American Indian and Alaska Native'],
  ['pacific_islander_alone_not_hispanic', 'Native Hawaiian and Pacific Islander'],
  ['other_race_alone_not_hispanic', 'Some other race'],
  ['two_or_more_races_not_hispanic', 'Two or more races'],
] as const

function formatValue(value: AcsValue | undefined, kind: 'count' | 'money' | 'years' | 'percent'): string {
  if (!value || value.value === null) return 'Not available'
  const number = kind === 'money'
    ? dollars.format(value.value)
    : kind === 'percent'
      ? `${value.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
      : value.value.toLocaleString(undefined, { maximumFractionDigits: 1 })
  const suffix = kind === 'years' ? ' years' : ''
  if (value.status === 'top_coded') return `${number}${suffix} or more`
  if (value.status === 'bottom_coded') return `${number}${suffix} or less`
  return `${number}${suffix}`
}

function margin(value: AcsValue | undefined, kind: 'count' | 'money' | 'years' | 'percent'): string | null {
  if (!value || value.value === null || value.status !== 'available') return null
  const text = kind === 'money'
    ? dollars.format(value.value)
    : value.value.toLocaleString(undefined, { maximumFractionDigits: 1 })
  return `±\u2060${text}${kind === 'percent' ? '\u00a0pts' : ''}`
}

function Stat({ label, metric, kind, usePercent = false }: {
  label: string
  metric: AcsMetric | undefined
  kind: 'count' | 'money' | 'years' | 'percent'
  usePercent?: boolean
}) {
  const value = usePercent ? metric?.percent : metric?.estimate
  const moe = usePercent ? metric?.percent_margin_of_error : metric?.estimate_margin_of_error
  const moeText = margin(moe, kind)
  return (
    <div>
      <strong>{formatValue(value, kind)}</strong>
      <span>{label}{moeText ? ` · ${moeText}` : ''}</span>
    </div>
  )
}

export default function AreaDemographics({ propertyId }: { propertyId: string }) {
  const [profile, setProfile] = useState<DemographicsResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setProfile(null)
    setError(null)
    getDemographics(propertyId, controller.signal)
      .then(setProfile)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'Area demographics could not be loaded.')
        }
      })
    return () => controller.abort()
  }, [propertyId])

  const metrics = profile?.metrics
  return (
    <section className="area-demographics" aria-label="Area demographics">
      <h3><Users size={16} aria-hidden="true" /> Area demographics</h3>
      {!profile && !error && <p className="context-status" role="status">Loading area profile…</p>}
      {error && <p className="context-status" role="alert">{error}</p>}
      {profile && profile.status === 'unavailable' && (
        <p className="context-status">
          {profile.reason === 'zcta_not_prepared'
            ? `No census profile has been prepared for ZIP ${profile.geography.id}.`
            : 'Area demographics are not available for this record.'}
        </p>
      )}
      {profile && profile.status === 'available' && metrics && (
        <>
          <p className="context-scope">
            ZIP code area {profile.geography.id} · {profile.period} ACS 5-year estimates
          </p>
          <div className="solar-stats">
            <Stat label="Population" metric={metrics.total_population} kind="count" />
            <Stat label="Median household income" metric={metrics.median_household_income_usd} kind="money" />
            <Stat label="Median age" metric={metrics.median_age_years} kind="years" />
            <Stat label="Under 18" metric={metrics.under_18} kind="percent" usePercent />
          </div>
          <h4 className="demographics-subheading">Race and ethnicity</h4>
          <ul className="demographics-bars">
            {GROUPS.map(([key, label]) => {
              const percent = metrics[key]?.percent
              const width = percent?.value ?? 0
              const moeText = margin(metrics[key]?.percent_margin_of_error, 'percent')
              return (
                <li key={key}>
                  <div>
                    <span>{label}</span>
                    <strong>{formatValue(percent, 'percent')}</strong>
                  </div>
                  <div className="demographics-track" aria-hidden="true">
                    <div style={{ width: `${Math.min(100, Math.max(0, width))}%` }} />
                  </div>
                  {moeText && <small>{moeText}</small>}
                </li>
              )
            })}
          </ul>
          <p className="context-caution">
            Survey estimates with 90% margins of error for the whole ZIP code area, not this home or street. {profile.geography.note}
          </p>
          <p className="context-copyright">Source: {profile.source}, {profile.dataset}.</p>
        </>
      )}
    </section>
  )
}
