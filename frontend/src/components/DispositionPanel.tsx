import { Card, CardContent, DataList } from '@pipecat-ai/voice-ui-kit'
import type { CallInsights } from '../api'
import { dispositionStyle } from '../disposition'

function formatDuration(startedAt: string, endedAt: string): string {
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime()
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const totalSec = Math.round(ms / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m}m ${s.toString().padStart(2, '0')}s`
}

interface DispositionPanelProps {
  insights: CallInsights
  onNewCall: () => void
  // True while the row is saved but the AI summary (a ~15-20s Bedrock call)
  // hasn't landed yet — shows skeleton placeholders instead of leaving the
  // summary/highlights/next-steps sections looking broken or empty.
  summaryPending?: boolean
}

export default function DispositionPanel({ insights, onNewCall, summaryPending }: DispositionPanelProps) {
  const style = dispositionStyle(insights.outcome)
  const lead = insights.lead_context
  const summary = insights.ai_summary

  const data: Record<string, string> = {
    Lead: lead?.lead_name || '—',
    Company: lead?.company_name || '—',
    Line: insights.phone_number || '—',
    Duration: formatDuration(insights.started_at, insights.ended_at),
    Sentiment: summaryPending ? '—' : summary?.lead_sentiment || '—',
  }
  if (!summaryPending && summary?.meeting_time) data['Meeting time'] = summary.meeting_time

  return (
    <div className="disposition-view">
      <div className="disposition-head">
        <div>
          <span className="brief-eyebrow">Disposition</span>
          <h1 className="brief-heading" style={{ marginTop: 4 }}>Call complete</h1>
        </div>
        <span
          className="disposition-badge"
          style={{ color: style.fg, background: style.bg, border: `1px solid ${style.border}` }}
        >
          {summaryPending ? <SmallSpinner /> : (
            <span className="dot" style={{ background: style.dot, color: style.dot }} />
          )}
          {summaryPending ? 'Generating summary…' : style.label}
        </span>
      </div>

      <Card className="disposition-card">
        <CardContent style={{ padding: 0 }}>
          <div className="disposition-section dl-mono">
            <div className="disposition-section-label">Call</div>
            <DataList data={data} />
          </div>

          <div className="disposition-section">
            <div className="disposition-section-label">Summary</div>
            {summaryPending ? (
              <SkeletonLines lines={3} />
            ) : (
              <p className="disposition-summary">{summary?.summary || 'No summary available.'}</p>
            )}
          </div>

          {summaryPending ? (
            <div className="disposition-section">
              <div className="disposition-section-label">Key highlights</div>
              <SkeletonLines lines={2} />
            </div>
          ) : summary?.key_highlights?.length > 0 && (
            <div className="disposition-section">
              <div className="disposition-section-label">Key highlights</div>
              <div className="highlight-list">
                {summary.key_highlights.map((h, i) => (
                  <div key={i} className="highlight-item">{h}</div>
                ))}
              </div>
            </div>
          )}

          {!summaryPending && summary?.next_steps && (
            <div className="disposition-section">
              <div className="disposition-section-label">Next steps</div>
              <p className="disposition-summary">{summary.next_steps}</p>
            </div>
          )}

          <div className="disposition-section">
            <div className="disposition-section-label">Transcript</div>
            <div className="transcript-body" style={{ maxHeight: 320 }}>
              {insights.transcript.split('\n').filter(Boolean).map((line, i) => {
                const [role, ...rest] = line.split(':')
                const isUser = role.trim().toLowerCase() === 'user'
                return (
                  <div key={i} className={`turn ${isUser ? 'user' : 'bot'}`}>
                    <span className="turn-role">{isUser ? 'You' : 'AI'}</span>
                    <span className="turn-text">{rest.join(':').trim()}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="disposition-actions">
        <button className="btn-outline" onClick={onNewCall}>Start another call</button>
      </div>
    </div>
  )
}

function SmallSpinner() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round">
      <path d="M21 12a9 9 0 11-6.22-8.56" style={{ animation: 'spin .8s linear infinite' }} />
    </svg>
  )
}

function SkeletonLines({ lines }: { lines: number }) {
  return (
    <div className="skeleton-lines">
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton-line" style={{ width: i === lines - 1 ? '70%' : '100%' }} />
      ))}
    </div>
  )
}