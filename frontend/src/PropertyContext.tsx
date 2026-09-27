import { useEffect, useRef, useState } from 'react'
import { ExternalLink, MapPin, RefreshCw, Sun, View } from 'lucide-react'
import { getNearbyPlaces, getPropertyContext } from './api'
import type {
  ContextSection,
  NearbyPlace,
  PropertyContextResponse,
  SolarData,
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

function Solar({ section }: { section: ContextSection<SolarData> }) {
  return (
    <section className="context-subsection" aria-label="Solar context">
      <h4><Sun size={16} aria-hidden="true" /> Nearby roof solar</h4>
      {section.status === 'available' && section.data ? (
        <>
          <div className="solar-stats">
            <div><strong>{section.data.max_array_panels_count}</strong><span>Max modeled panels</span></div>
            <div><strong>{section.data.max_array_capacity_kw.toLocaleString()} kW</strong><span>Indicative capacity</span></div>
          </div>
          <p className="context-scope">
            Closest detected building · {section.data.building_distance_m} m away
            {section.data.imagery_date ? ` · imagery ${section.data.imagery_date}` : ''}
            {section.data.imagery_quality ? ` · ${section.data.imagery_quality.toLowerCase()} quality` : ''}
          </p>
          <p className="context-caution">
            This roof is not verified as belonging to the recorded property. No financial estimate is implied.
          </p>
          {section.data.postal_code_matches === false && (
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
