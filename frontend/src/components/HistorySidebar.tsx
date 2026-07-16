import { LED } from '@pipecat-ai/voice-ui-kit'
import type { CallListItem, Disposition } from '../api'

const LED_CLASS: Record<string, string> = {
  'Meeting Booked': 'led-violet',
  Interested: 'led-green',
  'Follow-up Required': 'led-amber',
  'Not Interested': 'led-slate',
}

function ledClass(outcome: Disposition | null | undefined): string {
  return (outcome && LED_CLASS[outcome]) || 'led-pending'
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yestStart = new Date(todayStart.getTime() - 86400000)
  if (d >= todayStart) return `Today ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  if (d >= yestStart) return `Yesterday ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

interface HistorySidebarProps {
  calls: CallListItem[]
  selectedId: string | null
  sidebarOpen: boolean
  onSelect: (callId: string) => void
}

export default function HistorySidebar({ calls, selectedId, sidebarOpen, onSelect }: HistorySidebarProps) {
  return (
    <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
      <div className="sidebar-head">
        <span className="sidebar-title">History</span>
        {calls.length > 0 && <span className="sidebar-count">{calls.length}</span>}
      </div>

      {calls.length === 0 ? (
        <div className="sidebar-empty">No calls yet</div>
      ) : (
        <ul className="session-list">
          {calls.map(c => {
            const name = c.lead_context?.lead_name || c.phone_number || 'Unknown lead'
            const company = c.lead_context?.company_name
            return (
              <li key={c.call_id}>
                <button
                  className={`session-item ${selectedId === c.call_id ? 'active' : ''}`}
                  onClick={() => onSelect(c.call_id)}
                >
                  <div className="call-item">
                    <span className="call-item-led">
                      <LED on classNames={{ on: ledClass(c.outcome) }} />
                    </span>
                    <div className="call-item-body">
                      <span className="session-item-title">{name}</span>
                      {company && <span className="call-item-company">{company}</span>}
                      <span className="session-item-date">{formatDate(c.created_at)}</span>
                    </div>
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </aside>
  )
}