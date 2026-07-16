export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'

// Dev-only: the backend gates /calls* behind a static X-API-Key header. In a
// real deployment this call would be made by the upstream server, not the
// browser — see the note in README about moving this behind a BFF.
const API_KEY = import.meta.env.VITE_API_KEY || ''

export type Disposition = 'Interested' | 'Not Interested' | 'Follow-up Required' | 'Meeting Booked'

export interface LeadBrief {
  lead_name: string
  company_name: string
  role: string
  industry: string
  use_case: string
  phone_number: string
  lead_summary: string
}

export interface LeadContext {
  lead_name: string
  company_name: string
  role: string
  industry: string
  use_case: string
  phone_number: string
  lead_summary: string
  product_details: Record<string, unknown>
  enriched_data: Record<string, unknown>
}

export interface AiSummary {
  summary: string
  key_points: string[]
  key_highlights: string[]
  outcome: Disposition
  meeting_booked: boolean
  meeting_time: string | null
  lead_sentiment: 'positive' | 'neutral' | 'negative'
  next_steps: string
}

export interface CallListItem {
  call_id: string
  phone_number: string | null
  lead_context: LeadContext | null
  started_at: string
  ended_at: string
  outcome: Disposition | null
  created_at: string
}

export interface CallInsights {
  call_id: string
  session_id: string
  phone_number: string | null
  started_at: string
  ended_at: string
  transcript: string
  outcome: Disposition | null
  ai_summary: AiSummary
  lead_context: LeadContext | null
}

function headers(): HeadersInit {
  const h: HeadersInit = { 'Content-Type': 'application/json' }
  if (API_KEY) h['X-API-Key'] = API_KEY
  return h
}

export async function createCallContext(brief: LeadBrief): Promise<{ call_id: string }> {
  const res = await fetch(`${API_URL}/calls/context`, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(brief),
  })
  if (!res.ok) throw new Error(`Failed to prepare call context (${res.status})`)
  return res.json()
}

export async function listCalls(): Promise<CallListItem[]> {
  const res = await fetch(`${API_URL}/calls`, { headers: headers() })
  if (!res.ok) throw new Error(`Failed to list calls (${res.status})`)
  return res.json()
}

export async function getCallInsights(callId: string): Promise<CallInsights> {
  const res = await fetch(`${API_URL}/calls/${callId}/insights`, { headers: headers() })
  if (!res.ok) throw new Error(`Failed to fetch insights (${res.status})`)
  return res.json()
}

export function wsUrlForCall(callId: string | null): string {
  if (!callId) return WS_URL
  const sep = WS_URL.includes('?') ? '&' : '?'
  return `${WS_URL}${sep}call_id=${encodeURIComponent(callId)}`
}