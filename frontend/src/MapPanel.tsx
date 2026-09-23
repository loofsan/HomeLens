import { useEffect, useState } from 'react'
import type { Map as LeafletMap } from 'leaflet'
import {
  AttributionControl,
  CircleMarker,
  MapContainer,
  TileLayer,
  Tooltip,
  useMap,
  ZoomControl,
} from 'react-leaflet'
import { LocateFixed, X } from 'lucide-react'
import type { HistoricalSale, MapBounds } from './types'

const center: [number, number] = [36.025, -78.92]
const tileUrl =
  import.meta.env.VITE_MAP_TILE_URL ??
  'https://tile.openstreetmap.org/{z}/{x}/{y}.png'

function MapSync({
  selected,
  mode,
  resetToken,
  onMapReady,
}: {
  selected: HistoricalSale | null
  mode: 'list' | 'map'
  resetToken: number
  onMapReady: (map: LeafletMap) => void
}) {
  const map = useMap()

  useEffect(() => {
    onMapReady(map)
  }, [map, onMapReady])

  useEffect(() => {
    const frame = requestAnimationFrame(() => map.invalidateSize())
    return () => cancelAnimationFrame(frame)
  }, [map, mode])

  useEffect(() => {
    if (!selected) return
    const frame = requestAnimationFrame(() => {
      if (map.getContainer().offsetWidth === 0) return
      map.invalidateSize()
      map.flyTo([selected.latitude, selected.longitude], Math.max(map.getZoom(), 12), {
        duration: 0.35,
      })
    })
    return () => cancelAnimationFrame(frame)
  }, [map, mode, selected])

  useEffect(() => {
    if (resetToken > 0) map.setView(center, 11)
  }, [map, resetToken])

  return null
}

export default function MapPanel({
  items,
  synthetic,
  selected,
  mode,
  activeBounds,
  resetToken,
  onSelect,
  onSearchArea,
  onClearArea,
}: {
  items: HistoricalSale[]
  synthetic: boolean
  selected: HistoricalSale | null
  mode: 'list' | 'map'
  activeBounds: boolean
  resetToken: number
  onSelect: (id: string) => void
  onSearchArea: (bounds: MapBounds) => void
  onClearArea: () => void
}) {
  const [map, setMap] = useState<LeafletMap | null>(null)

  function searchArea() {
    if (!map) return
    const bounds = map.getBounds()
    onSearchArea({
      south: bounds.getSouth(),
      west: bounds.getWest(),
      north: bounds.getNorth(),
      east: bounds.getEast(),
    })
  }

  return (
    <section className="map-panel" aria-label={synthetic ? 'Synthetic demo map' : 'Historical sale map'}>
      <MapContainer
        className="property-map"
        center={center}
        zoom={11}
        zoomControl={false}
        attributionControl={false}
        scrollWheelZoom={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url={tileUrl}
        />
        <AttributionControl position="bottomleft" prefix={false} />
        <ZoomControl position="topleft" />
        <MapSync
          selected={selected}
          mode={mode}
          resetToken={resetToken}
          onMapReady={setMap}
        />
        {items.map((sale) => {
          const isSelected = selected?.id === sale.id
          return (
            <CircleMarker
              key={sale.id}
              center={[sale.latitude, sale.longitude]}
              radius={isSelected ? 11 : 8}
              pathOptions={{
                color: '#ffffff',
                weight: isSelected ? 3 : 2,
                fillColor: isSelected ? '#c7563c' : '#13786d',
                fillOpacity: 1,
              }}
              eventHandlers={{ click: () => onSelect(sale.id) }}
            >
              <Tooltip direction="top" offset={[0, -8]}>
                ${Math.round(sale.sold_price_usd).toLocaleString('en-US')}
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <div className="map-actions">
        <button className="map-search-button" type="button" onClick={searchArea}>
          <LocateFixed size={17} aria-hidden="true" />
          Search this area
        </button>
        {activeBounds && (
          <button
            className="map-clear-button"
            type="button"
            aria-label="Clear map area"
            title="Clear map area"
            onClick={onClearArea}
          >
            <X size={17} aria-hidden="true" />
          </button>
        )}
      </div>
      <div className="map-count">
        {items.length} {synthetic ? (items.length === 1 ? 'sample point' : 'sample points') : 'sales'} on this page
      </div>
    </section>
  )
}
