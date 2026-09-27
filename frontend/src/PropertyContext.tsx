import { useEffect, useRef, useState } from 'react'
import { ExternalLink, MapPin, RefreshCw, Sun, View } from 'lucide-react'
import { getNearbyPlaces, getPropertyContext } from './api'
import type {
  ContextSection,
  NearbyPlace,
  PropertyContextResponse,
  SolarData,
  SolarScenario,
  StreetViewData,
} from './types'

function statusMessage(section: ContextSection<unknown>): string {
  if (section.reason === 'not_configured') return 'Google Maps context is not configured.'
  if (section.reason === 'provider_timeout') return 'The provider timed out.'
  if (section.reason === 'provider_limit') return 'The provider limit was reached.'
  if (section.reason === 'provider_denied') return 'The provider did not authorize this request.'
  if (section.reason === 'no_results') return 'No matching places were found in this area.'
  if (section.reason === 'not_covered') return 'No coverage was found near this location.'
  return 'This context is unavailable right now.'
}

function Attribution({ source }: { source: string }) {
  return (
    <div className="context-attribution">
      <span translate="no">Google Maps</span>
      <span>{source}</span>
    </div>
  )
}

const NEARBY_CATEGORIES = [
  { value: 'everyday', label: 'Everyday' },
  { value: 'schools', label: 'Schools' },
  { value: 'childcare', label: 'Childcare' },
  { value: 'parks', label: 'Parks' },
  { value: 'grocery', label: 'Grocery' },
  { value: 'restaurants', label: 'Restaurants' },
  { value: 'bars', label: 'Bars' },
  { value: 'shopping', label: 'Shopping' },
  { value: 'health', label: 'Health' },
  { value: 'libraries', label: 'Libraries' },
  { value: 'fitness', label: 'Gyms' },
  { value: 'transit', label: 'Transit' },
] as const

const NEARBY_RADII = [
  { value: 800, label: '800 m (0.5 mi)' },
  { value: 1500, label: '1.5 km (0.9 mi)' },
  { value: 3000, label: '3 km (1.9 mi)' },
  { value: 5000, label: '5 km (3.1 mi)' },
] as const

function distanceLabel(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toLocaleString()} km` : `${meters.toLocaleString()} m`
}

type NearbySection = ContextSection<{ places: NearbyPlace[] }>

function NearbyPlaces({ initial, propertyId }: { initial: NearbySection; propertyId: string }) {
  const [current, setCurrent] = useState<NearbySection>(initial)
  const [category, setCategory] = useState(String(initial.coverage.category ?? 'everyday'))
  const [radius, setRadius] = useState(Number(initial.coverage.radius_m ?? 1500))
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => () => controllerRef.current?.abort(), [])

  function load(nextCategory: string, nextRadius: number) {
    setCategory(nextCategory)
    setRadius(nextRadius)
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setLoading(true)
    setError(null)
    getNearbyPlaces(propertyId, nextCategory, nextRadius, controller.signal)
      .then(setCurrent)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'Nearby places could not be loaded.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
  }

  const shownRadius = Number(current.coverage.radius_m)
  const shownCategory = NEARBY_CATEGORIES.find((item) => item.value === current.coverage.category)
  return (
    <section className="context-subsection" aria-label="Nearby places">
      <h4><MapPin size={16} aria-hidden="true" /> Nearby places</h4>
      <div className="nearby-controls">
        <div className="nearby-chips" role="group" aria-label="Place category">
          {NEARBY_CATEGORIES.map((item) => (
            <button
              key={item.value}
              type="button"
              className="nearby-chip"
              aria-pressed={category === item.value}
              disabled={loading}
              onClick={() => load(item.value, radius)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <label className="nearby-radius">
          <span>Within</span>
          <select
            value={radius}
            disabled={loading}
            onChange={(event) => load(category, Number(event.target.value))}
          >
            {NEARBY_RADII.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </label>
      </div>
      {loading && <p className="context-status" role="status">Loading nearby places…</p>}
      {error && !loading && <p className="context-status" role="alert">{error}</p>}
      {!loading && !error && (current.status === 'available' && current.data ? (
        <>
          <p className="context-scope">
            {shownCategory ? `${shownCategory.label} · ` : ''}within {distanceLabel(shownRadius)} · straight-line distance
          </p>
          <ul className="nearby-list">
            {current.data.places.map((place, index) => (
              <li key={`${place.name}-${index}`}>
                <div className="nearby-main">
                  <div>
                    <strong>{place.name}</strong>
                    <span>{place.type?.replaceAll('_', ' ') ?? 'Place'} · {distanceLabel(place.distance_m)}</span>
                  </div>
                  {place.maps_url && (
                    <a href={place.maps_url} target="_blank" rel="noopener noreferrer" aria-label={`View ${place.name} on Google Maps`} title="View on Google Maps">
                      <ExternalLink size={16} aria-hidden="true" />
                    </a>
                  )}
                </div>
                {place.attributions.map((attribution, attributionIndex) => (
                  <div className="place-attribution" key={`${attribution.provider}-${attributionIndex}`}>
                    {attribution.url ? (
                      <a href={attribution.url} target="_blank" rel="noopener noreferrer">{attribution.provider}</a>
                    ) : attribution.provider}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        </>
      ) : <p className="context-status">{statusMessage(current)}</p>)}
      <Attribution source={current.source} />
    </section>
  )
}

const COMPASS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']

function compassDirection(heading: number): string {
  return COMPASS[Math.round((((heading % 360) + 360) % 360) / 45) % 8]
}

function StreetView({ section }: { section: ContextSection<StreetViewData> }) {
  const [imageFailed, setImageFailed] = useState(false)
  return (
    <section className="context-subsection" aria-label="Street View">
      <h4><View size={16} aria-hidden="true" /> Street View</h4>
      {section.status === 'available' && section.data ? (
        <>
          {!imageFailed && (
            <img
              className="street-view-image"
              src={section.data.image_url}
              alt={section.data.heading_deg === null
                ? 'Nearby outdoor Street View imagery; it may not show this home'
                : 'Nearby outdoor Street View imagery turned toward the recorded location; it may not show this home'}
              loading="lazy"
              onError={() => setImageFailed(true)}
            />
          )}
          {imageFailed && <p className="context-status">Street imagery could not be loaded.</p>}
          <p className="context-scope">
            {section.data.distance_m} m from the recorded coordinate
            {section.data.heading_deg !== null
              ? ` · facing ${compassDirection(section.data.heading_deg)} toward it`
              : ''}
            {section.data.captured ? ` · captured ${section.data.captured}` : ''}
          </p>
          <p className="context-caution">Nearby imagery is not a verified photo of this home.</p>
          <a className="context-link" href={section.data.maps_url} target="_blank" rel="noopener noreferrer">
            Open Street View <ExternalLink size={14} aria-hidden="true" />
          </a>
          {section.data.copyright && <p className="context-copyright">{section.data.copyright}</p>}
        </>
      ) : <p className="context-status">{statusMessage(section)}</p>}
      <Attribution source={section.source} />
    </section>
  )
}

const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

function money(value: number | null): string {
  return value === null ? 'Not reported' : dollars.format(value)
}

function SolarFinancials({ scenarios, lifetime }: { scenarios: SolarScenario[]; lifetime: number | null }) {
  const initial = Math.max(0, scenarios.findIndex((item) => item.is_default_bill))
  const [selected, setSelected] = useState(initial)
  const scenario = scenarios[selected] ?? scenarios[0]
  const years = lifetime ? `${lifetime} years` : 'panel lifetime'
  const rows: [string, string][] = [
    ['Share of electricity covered', scenario.solar_percentage === null ? 'Not reported' : `${Math.round(scenario.solar_percentage)}%`],
    ['Modeled panels', scenario.panels_count === null ? 'Not reported' : String(scenario.panels_count)],
    ['Installed cost', money(scenario.upfront_cost_usd)],
    ['Incentives', money(scenario.incentives_usd)],
    ['Out of pocket', money(scenario.out_of_pocket_cost_usd)],
    ['First-year savings', money(scenario.savings_year1_usd)],
    [`Savings over ${years}`, money(scenario.savings_lifetime_usd)],
    ['Payback', scenario.payback_years === null ? 'Does not pay back in the modeled period' : `${scenario.payback_years.toLocaleString(undefined, { maximumFractionDigits: 1 })} years`],
  ]
  return (
    <div className="solar-financials">
      <label className="solar-bill">
        <span>Monthly electric bill</span>
        <select value={selected} onChange={(event) => setSelected(Number(event.target.value))}>
          {scenarios.map((item, index) => (
            <option key={item.monthly_bill_usd} value={index}>
              {dollars.format(item.monthly_bill_usd)}{item.is_default_bill ? ' (typical for area)' : ''}
            </option>
          ))}
        </select>
      </label>
      <dl className="solar-rows">
        {rows.map(([label, value]) => (
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
        ))}
      </dl>
    </div>
  )
}

function Solar({ section }: { section: ContextSection<SolarData> }) {
  const data = section.data
  return (
    <section className="context-subsection" aria-label="Solar context">
      <h4><Sun size={16} aria-hidden="true" /> Nearby roof solar</h4>
      {section.status === 'available' && data ? (
        <>
          <div className="solar-stats">
            <div><strong>{data.max_array_panels_count}</strong><span>Max modeled panels</span></div>
            <div><strong>{data.max_array_capacity_kw.toLocaleString()} kW</strong><span>Indicative capacity</span></div>
            {data.max_array_area_m2 !== null && (
              <div><strong>{Math.round(data.max_array_area_m2).toLocaleString()} m²</strong><span>Usable roof area</span></div>
            )}
            {data.max_sunshine_hours_per_year !== null && (
              <div><strong>{Math.round(data.max_sunshine_hours_per_year).toLocaleString()} hrs</strong><span>Sunshine per year</span></div>
            )}
          </div>
          <p className="context-scope">
            Closest detected building · {data.building_distance_m} m away
            {data.imagery_date ? ` · imagery ${data.imagery_date}` : ''}
            {data.imagery_quality ? ` · ${data.imagery_quality.toLowerCase()} quality` : ''}
            {data.carbon_offset_kg_per_mwh !== null ? ` · grid carbon ${Math.round(data.carbon_offset_kg_per_mwh)} kg CO₂/MWh` : ''}
          </p>
          {data.financial_scenarios.length > 0 ? (
            <>
              <SolarFinancials scenarios={data.financial_scenarios} lifetime={data.panel_lifetime_years} />
              <p className="context-caution">
                Cash-purchase estimates modeled by the Google Solar API from its own local utility rates, installation costs, and incentives. They are not a quote, and this roof is not verified as belonging to the recorded property.
              </p>
            </>
          ) : (
            <p className="context-caution">
              No financial analysis is available for this building. This roof is not verified as belonging to the recorded property.
            </p>
          )}
          {data.postal_code_matches === false && (
            <p className="context-caution">The detected building has a different ZIP code.</p>
          )}
        </>
      ) : <p className="context-status">{statusMessage(section)}</p>}
      <Attribution source={section.source} />
    </section>
  )
}

export default function PropertyContext({ propertyId }: { propertyId: string }) {
  const [context, setContext] = useState<PropertyContextResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadCount, setLoadCount] = useState(0)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => () => controllerRef.current?.abort(), [])

  function loadContext() {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setLoading(true)
    setError(null)
    getPropertyContext(propertyId, controller.signal)
      .then((result) => {
        setContext(result)
        setLoadCount((count) => count + 1)
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : 'Context could not be loaded.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
  }

  return (
    <div className="property-context">
      <div className="context-heading">
        <h3>Nearby context</h3>
        <button className="secondary-button" type="button" onClick={loadContext} disabled={loading}>
          {context || error ? <RefreshCw size={15} aria-hidden="true" /> : <MapPin size={15} aria-hidden="true" />}
          {loading ? 'Loading…' : context || error ? 'Refresh' : 'Load context'}
        </button>
      </div>
      {loading && <p className="context-status" role="status">Loading nearby context…</p>}
      {error && !loading && <p className="context-status" role="alert">{error}</p>}
      {context && !loading && !error && (
        <div>
          <NearbyPlaces key={loadCount} initial={context.nearby_places} propertyId={propertyId} />
          <StreetView section={context.street_view} />
          <Solar section={context.solar} />
        </div>
      )}
    </div>
  )
}
