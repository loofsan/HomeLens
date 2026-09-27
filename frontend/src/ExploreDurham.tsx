import { ExternalLink } from 'lucide-react'

const LINKS = [
  { label: 'Events in Durham', source: 'Discover Durham', href: 'https://www.discoverdurham.com/events/' },
  { label: 'Downtown events', source: 'Downtown Durham Inc.', href: 'https://downtowndurham.com/downtown-events/' },
  { label: 'Parks and trails', source: 'Durham Parks & Recreation', href: 'https://www.dprplaymore.org/' },
  { label: 'Library branches and programs', source: 'Durham County Library', href: 'https://durhamcountylibrary.org/' },
  { label: 'Assigned public schools by address', source: 'City of Durham & Durham County', href: 'https://maps.durhamnc.gov/address/' },
] as const

export default function ExploreDurham() {
  return (
    <section className="explore-area" aria-label="Explore Durham">
      <h3>Explore Durham</h3>
      <p>Community and event pages from local organizations. These open external sites that HomeLens does not check or control.</p>
      <ul>
        {LINKS.map((link) => (
          <li key={link.href}>
            <a href={link.href} target="_blank" rel="noopener noreferrer">
              <span>{link.label}</span>
              <ExternalLink size={14} aria-hidden="true" />
            </a>
            <span className="explore-source">{link.source}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
