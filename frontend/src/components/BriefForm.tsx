import { useState } from 'react'
import { Card, CardContent, Input, Textarea } from '@pipecat-ai/voice-ui-kit'
import type { LeadBrief } from '../api'

const EMPTY_BRIEF: LeadBrief = {
  lead_name: '',
  company_name: '',
  role: '',
  industry: '',
  use_case: '',
  phone_number: '',
  lead_summary: '',
}

interface BriefFormProps {
  onStart: (brief: LeadBrief) => Promise<void>
  starting: boolean
  error: string | null
}

export default function BriefForm({ onStart, starting, error }: BriefFormProps) {
  const [brief, setBrief] = useState<LeadBrief>(EMPTY_BRIEF)

  const set = (field: keyof LeadBrief) => (
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>
  ) => setBrief(b => ({ ...b, [field]: e.target.value }))

  const canStart = brief.lead_name.trim() !== '' && brief.company_name.trim() !== ''

  return (
    <div className="brief-view">
      <span className="brief-eyebrow">Brief</span>
      <h1 className="brief-heading">Who are we calling?</h1>
      <p className="brief-sub">
        This context is handed to the agent before the line connects — it opens the call already knowing who it's talking to.
      </p>

      {error && <div className="brief-error">{error}</div>}

      <Card className="brief-card">
        <CardContent>
          <div className="brief-group">
            <span className="brief-group-label">Who</span>
            <div className="brief-row">
              <div className="brief-field">
                <label htmlFor="lead_name">Lead name</label>
                <Input
                  id="lead_name"
                  placeholder="Alice Chen"
                  value={brief.lead_name}
                  onChange={set('lead_name')}
                />
              </div>
              <div className="brief-field">
                <label htmlFor="company_name">Company</label>
                <Input
                  id="company_name"
                  placeholder="Acme Robotics"
                  value={brief.company_name}
                  onChange={set('company_name')}
                />
              </div>
            </div>
            <div className="brief-row">
              <div className="brief-field">
                <label htmlFor="role">Role</label>
                <Input
                  id="role"
                  placeholder="VP of Sales"
                  value={brief.role}
                  onChange={set('role')}
                />
              </div>
              <div className="brief-field mono">
                <label htmlFor="phone_number">Line</label>
                <Input
                  id="phone_number"
                  placeholder="+1 555 123 4567"
                  value={brief.phone_number}
                  onChange={set('phone_number')}
                />
              </div>
            </div>
          </div>

          <div className="brief-group">
            <span className="brief-group-label">Context</span>
            <div className="brief-row">
              <div className="brief-field">
                <label htmlFor="industry">Industry</label>
                <Input
                  id="industry"
                  placeholder="Robotics"
                  value={brief.industry}
                  onChange={set('industry')}
                />
              </div>
              <div className="brief-field">
                <label htmlFor="use_case">Relevant use case</label>
                <Input
                  id="use_case"
                  placeholder="Outbound prospecting automation"
                  value={brief.use_case}
                  onChange={set('use_case')}
                />
              </div>
            </div>
            <div className="brief-field">
              <label htmlFor="lead_summary">Lead summary</label>
              <Textarea
                id="lead_summary"
                placeholder="Series B robotics company scaling their SDR team..."
                value={brief.lead_summary}
                onChange={set('lead_summary')}
                rows={3}
              />
            </div>
          </div>

          <div className="brief-actions">
            <button
              className="btn-primary"
              disabled={!canStart || starting}
              onClick={() => onStart(brief)}
            >
              {starting && <SpinnerIcon />}
              {starting ? 'Preparing call…' : 'Start call'}
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function SpinnerIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 11-6.22-8.56" style={{ animation: 'spin .8s linear infinite' }} />
    </svg>
  )
}