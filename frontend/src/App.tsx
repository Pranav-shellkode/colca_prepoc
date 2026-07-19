import React, { useCallback, useEffect, useRef, useState } from 'react'
import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js'
import type { BotOutputText } from '@pipecat-ai/client-react'
import {
  PipecatClientAudio,
  PipecatClientMicToggle,
  PipecatClientProvider,
  VoiceVisualizer,
  usePipecatClient,
  usePipecatClientTransportState,
  usePipecatConversation,
  useRTVIClientEvent,
} from '@pipecat-ai/client-react'
import { WebSocketTransport, ProtobufFrameSerializer } from '@pipecat-ai/websocket-transport'

import {
  createCallContext,
  createOzonetelCall,
  getCallInsights,
  hangupOzonetelCall,
  listCalls,
  wsUrlForCall,
} from './api'
import type { CallInsights, CallListItem, LeadBrief } from './api'
import BriefForm from './components/BriefForm'
import DispositionPanel from './components/DispositionPanel'
import HistorySidebar from './components/HistorySidebar'

// The websocket transport's mic capture requests plain `{ audio: true }` with
// no way to pass constraints through PipecatClientOptions. Without echo
// cancellation, the bot's own TTS played back through speakers bleeds into
// the mic and gets transcribed as fake user speech, stalling turn detection.
if (navigator.mediaDevices?.getUserMedia) {
  const nativeGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
  navigator.mediaDevices.getUserMedia = (constraints?: MediaStreamConstraints) => {
    if (!constraints?.audio) return nativeGetUserMedia(constraints)
    const audio = constraints.audio === true ? {} : constraints.audio
    return nativeGetUserMedia({
      ...constraints,
      audio: {
        ...audio,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
  }
}

const pcClient = new PipecatClient({
  transport: new WebSocketTransport({
    serializer: new ProtobufFrameSerializer(),
    recorderSampleRate: 16000,
    playerSampleRate: 16000,
  }),
  enableMic: true,
  enableCam: false,
})

const SafeProvider = PipecatClientProvider as unknown as React.ComponentType<{
  client: PipecatClient
  children: React.ReactNode
}>

export default function App() {
  return (
    <div className="vkui-root dark">
      <SafeProvider client={pcClient}>
        <PipecatClientAudio />
        <VoiceApp />
      </SafeProvider>
    </div>
  )
}

// ── Types ─────────────────────────────────────────────────────────────────────

type AgentState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'
// 'call' is the browser-mic session (Pipecat websocket in this tab).
// 'dialing' is a real Ozonetel call — the audio is entirely between
// Ozonetel and the backend, so this tab has no live transport state for it,
// just a "call in progress" view that polls for the call to end.
type Stage = 'brief' | 'call' | 'dialing' | 'disposition'

// ── Main component ────────────────────────────────────────────────────────────

function VoiceApp() {
  const client = usePipecatClient()
  const transportState = usePipecatClientTransportState()
  const { messages } = usePipecatConversation()
  const [agentState, setAgentState] = useState<AgentState>('idle')
  const [toolActive, setToolActive] = useState(false)
  const [toolName, setToolName] = useState('')
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  // Call lifecycle state
  const [stage, setStage] = useState<Stage>('brief')
  const [currentCallId, setCurrentCallId] = useState<string | null>(null)
  const [currentBrief, setCurrentBrief] = useState<LeadBrief | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [insights, setInsights] = useState<CallInsights | null>(null)
  const [loadingInsights, setLoadingInsights] = useState(false)
  // True while the disposition row exists but the AI summary hasn't landed
  // yet (summarize_call is a ~15-20s Bedrock round trip) — drives the
  // "Generating summary…" indicator inside DispositionPanel instead of
  // blocking the whole view on it.
  const [summaryPending, setSummaryPending] = useState(false)

  // History sidebar state
  const [calls, setCalls] = useState<CallListItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [histInsights, setHistInsights] = useState<CallInsights | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const isConnected = transportState === 'ready' || transportState === 'connected'
  const isConnecting = transportState === 'connecting' || transportState === 'authenticating'

  // ── Agent state events ────────────────────────────────────────────────────

  useRTVIClientEvent(RTVIEvent.BotStartedSpeaking, useCallback(() => setAgentState('speaking'), []))
  useRTVIClientEvent(RTVIEvent.BotStoppedSpeaking, useCallback(() => setAgentState('listening'), []))
  useRTVIClientEvent(RTVIEvent.UserStartedSpeaking, useCallback(() => setAgentState('listening'), []))
  useRTVIClientEvent(RTVIEvent.UserStoppedSpeaking, useCallback(() => setAgentState('thinking'), []))
  useRTVIClientEvent(RTVIEvent.BotLlmStarted, useCallback(() => setAgentState('thinking'), []))
  useRTVIClientEvent(
    RTVIEvent.LLMFunctionCallStarted,
    useCallback((data: { function_name?: string }) => {
      setToolActive(true)
      setToolName((data?.function_name ?? '').replace(/_/g, ' '))
    }, [])
  )
  useRTVIClientEvent(
    RTVIEvent.LLMFunctionCallStopped,
    useCallback(() => setTimeout(() => setToolActive(false), 1800), [])
  )

  // ── History data ──────────────────────────────────────────────────────────

  const fetchCalls = useCallback(async () => {
    try {
      setCalls(await listCalls())
    } catch {
      /* backend not yet running, or no API key configured for this dev session */
    }
  }, [])

  useEffect(() => { fetchCalls() }, [fetchCalls])

  const viewHistoricalCall = useCallback(async (callId: string) => {
    setSelectedId(callId)
    setStage('brief') // leave any active call view; historical view renders independently below
    try {
      setHistInsights(await getCallInsights(callId))
    } catch {
      setHistInsights(null)
    }
  }, [])

  const clearHistorySelection = useCallback(() => {
    setSelectedId(null)
    setHistInsights(null)
  }, [])

  // ── Call lifecycle: brief -> connect -> disposition ──────────────────────

  // The backend now saves a "pending" row (transcript + basics, no AI
  // summary) synchronously right on disconnect, before it kicks off the
  // ~15-20s Bedrock summarization call — so the very first read here almost
  // always succeeds. A pending row has no outcome yet; poll every couple of
  // seconds until the real summary lands, updating the disposition view in
  // place instead of leaving the whole screen on a spinner.
  const isSummaryPending = (i: CallInsights | null) => !!i && !i.outcome

  const fetchInsightsUntilReady = useCallback(
    async (callId: string, onUpdate: (insights: CallInsights | null) => void) => {
      for (let attempt = 0; attempt < 20; attempt++) {
        try {
          const result = await getCallInsights(callId)
          onUpdate(result)
          if (!isSummaryPending(result)) return
        } catch {
          if (attempt === 0) onUpdate(null)
        }
        await new Promise(r => setTimeout(r, attempt === 0 ? 500 : 2000))
      }
    },
    []
  )

  const goToDisposition = useCallback((callId: string) => {
    setStage('disposition')
    setLoadingInsights(true)
    let summaryLanded = false
    fetchInsightsUntilReady(callId, result => {
      setInsights(result)
      setLoadingInsights(false)
      setSummaryPending(isSummaryPending(result))
      if (!isSummaryPending(result) && !summaryLanded) {
        summaryLanded = true
        fetchCalls()
      }
    })
  }, [fetchInsightsUntilReady, fetchCalls])

  // Browser test path: connects this tab's mic/speaker straight to the
  // pipeline over a websocket. Nothing rings — it's for trying out the
  // agent without touching real telephony.
  const handleStartBrowser = useCallback(async (brief: LeadBrief) => {
    setStarting(true)
    setStartError(null)
    try {
      const { call_id } = await createCallContext(brief)
      setCurrentCallId(call_id)
      setCurrentBrief(brief)
      clearHistorySelection()
      await client?.connect({ wsUrl: wsUrlForCall(call_id) })
      setStage('call')
    } catch (e) {
      setStartError(e instanceof Error ? e.message : 'Could not start the call.')
    } finally {
      setStarting(false)
    }
  }, [client, clearHistorySelection])

  // Real telephony path: Ozonetel dials brief.phone_number. The audio never
  // touches this browser tab — Ozonetel bridges straight to the backend's
  // /ws once the callee answers — so there's no transport to connect here,
  // just a "call in progress" view (see the dialing-poll effect below).
  const handleStartCall = useCallback(async (brief: LeadBrief) => {
    setStarting(true)
    setStartError(null)
    try {
      const { call_id } = await createOzonetelCall(brief)
      setCurrentCallId(call_id)
      setCurrentBrief(brief)
      clearHistorySelection()
      setStage('dialing')
    } catch (e) {
      setStartError(e instanceof Error ? e.message : 'Could not place the call.')
    } finally {
      setStarting(false)
    }
  }, [clearHistorySelection])

  const handleDisconnect = useCallback(async () => {
    try { await client?.disconnect() } catch (e) { console.error(e) }
  }, [client])

  const handleHangup = useCallback(async () => {
    if (!currentCallId) return
    try { await hangupOzonetelCall(currentCallId) } catch (e) { console.error(e) }
  }, [currentCallId])

  const handleNewCall = useCallback(() => {
    setStage('brief')
    setCurrentCallId(null)
    setCurrentBrief(null)
    setInsights(null)
  }, [])

  const prevConnected = useRef(false)

  useEffect(() => {
    if (isConnecting) { setAgentState('connecting'); return }
    if (!isConnected) {
      setAgentState('idle')
      if (prevConnected.current && currentCallId) {
        // Browser call just ended: move to the disposition view right away.
        // The pending row (transcript + basics) is usually already there by
        // the time we ask, so this resolves almost instantly; the AI
        // summary catches up a few seconds later via the polling loop.
        goToDisposition(currentCallId)
      }
    }
    prevConnected.current = isConnected
  }, [isConnected, isConnecting, currentCallId, goToDisposition])

  // Dialing-poll: a real Ozonetel call has no websocket in this tab to
  // watch, so instead poll for the call's insights row to appear at all —
  // that only happens once the /ws pipeline session (answered call) or the
  // /ozonetel/callback CDR (never answered) has run, i.e. the call is over.
  useEffect(() => {
    if (stage !== 'dialing' || !currentCallId) return
    let cancelled = false
    const callId = currentCallId
    const poll = async () => {
      while (!cancelled) {
        try {
          await getCallInsights(callId)
          if (!cancelled) goToDisposition(callId)
          return
        } catch {
          await new Promise(r => setTimeout(r, 3000))
        }
      }
    }
    poll()
    return () => { cancelled = true }
  }, [stage, currentCallId, goToDisposition])

  // ── Live transcript scroll ────────────────────────────────────────────────

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Render ────────────────────────────────────────────────────────────────

  const statusMap: Record<AgentState, string> = {
    idle: 'Ready to connect',
    connecting: 'Connecting…',
    listening: 'Listening',
    thinking: 'Thinking…',
    speaking: 'Speaking',
  }

  const botBarColor = agentState === 'speaking' ? '#fcc057' : '#2d7f74'
  const viewingHistory = selectedId !== null

  return (
    <div className="shell">
      {/* ── Nav ─────────────────────────────────────── */}
      <header className="nav">
        <div className="nav-brand">
          <button className="sidebar-toggle" onClick={() => setSidebarOpen(o => !o)} title="Toggle history">
            <MenuIcon />
          </button>
          <img src="/logo.svg" alt="Colca AI" className="nav-logo" />
        </div>

        {!viewingHistory && (
          <nav className="stage-nav">
            <StageStep label="Brief" active={stage === 'brief'} done={stage !== 'brief'} />
            <span className="stage-sep">/</span>
            <StageStep
              label={stage === 'dialing' ? 'Dialing' : 'On the line'}
              active={stage === 'call' || stage === 'dialing'}
              done={stage === 'disposition'}
            />
            <span className="stage-sep">/</span>
            <StageStep label="Disposition" active={stage === 'disposition'} done={false} />
          </nav>
        )}

        <div className="nav-actions">
          {isConnected && (
            <button className="btn-end" onClick={handleDisconnect}>
              <PhoneOffIcon />
              End call
            </button>
          )}
          {stage === 'dialing' && (
            <button className="btn-end" onClick={handleHangup}>
              <PhoneOffIcon />
              Hang up
            </button>
          )}
        </div>
      </header>

      {/* ── Body ────────────────────────────────────── */}
      <div className="body">
        <HistorySidebar
          calls={calls}
          selectedId={selectedId}
          sidebarOpen={sidebarOpen}
          onSelect={viewHistoricalCall}
        />

        {/* ── Main ──────────────────────────────────── */}
        <main className="main">
          {viewingHistory ? (
            <HistoricalView
              callId={selectedId}
              insights={histInsights}
              onBack={clearHistorySelection}
            />
          ) : stage === 'brief' ? (
            <BriefForm
              onStartBrowser={handleStartBrowser}
              onStartCall={handleStartCall}
              starting={starting}
              error={startError}
            />
          ) : stage === 'dialing' ? (
            <DialingView brief={currentBrief} onHangup={handleHangup} />
          ) : stage === 'disposition' ? (
            loadingInsights && !insights ? (
              <div className="hint">
                <SpinnerIcon />
                <span>Wrapping up the call…</span>
              </div>
            ) : insights ? (
              <DispositionPanel
                insights={insights}
                summaryPending={summaryPending}
                onNewCall={handleNewCall}
              />
            ) : (
              <div className="hint">
                Couldn't load this call's details. It may still be saving — check
                the history sidebar in a moment.
              </div>
            )
          ) : (
            /* ── On the line ────────────────────────── */
            <>
              {currentBrief && (
                <div className="call-meta">
                  <span className="call-item-led">
                    <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--indigo)', boxShadow: '0 0 8px var(--indigo)' }} />
                  </span>
                  <span className="call-meta-name">{currentBrief.lead_name}</span>
                  <span className="call-meta-sep">·</span>
                  <span className="call-meta-num">{currentBrief.company_name}</span>
                  {currentBrief.phone_number && (
                    <>
                      <span className="call-meta-sep">·</span>
                      <span className="call-meta-num">{currentBrief.phone_number}</span>
                    </>
                  )}
                </div>
              )}

              <div className={`viz-card state-${agentState}`}>
                <div className="viz-bot-wrap">
                  <div className={`viz-bot-ring state-${agentState}`}>
                    {isConnected ? (
                      <VoiceVisualizer
                        participantType="bot"
                        backgroundColor="transparent"
                        barColor={botBarColor}
                        barCount={22}
                        barGap={4}
                        barWidth={5}
                        barMaxHeight={72}
                        barLineCap="round"
                        barOrigin="center"
                      />
                    ) : (
                      <IdleBars count={22} />
                    )}
                  </div>
                  <span className="viz-bot-label">Assistant</span>
                </div>

                <div className="status-row">
                  <span className={`status-dot state-${agentState}`} />
                  <span className="status-text">{statusMap[agentState]}</span>
                  {toolActive && (
                    <span className="tool-chip">
                      <WrenchIcon />
                      {toolName}
                    </span>
                  )}
                </div>

                <div className="viz-user-row">
                  <span className="viz-user-label">You</span>
                  {isConnected ? (
                    <VoiceVisualizer
                      participantType="local"
                      backgroundColor="transparent"
                      barColor="#5fb8ab"
                      barCount={16}
                      barGap={3}
                      barWidth={3}
                      barMaxHeight={22}
                      barLineCap="round"
                      barOrigin="center"
                    />
                  ) : (
                    <IdleBars count={16} height={4} />
                  )}
                </div>
              </div>

              <PipecatClientMicToggle disabled={!isConnected}>
                {({ disabled, isMicEnabled, onClick }) => (
                  <button className={`mic-btn ${isMicEnabled ? 'on' : 'off'}`} onClick={onClick} disabled={disabled}>
                    {isMicEnabled ? <MicOnIcon /> : <MicOffIcon />}
                    {isMicEnabled ? 'Microphone On' : 'Microphone Muted'}
                  </button>
                )}
              </PipecatClientMicToggle>

              {messages.length > 0 && (
                <section className="transcript">
                  <div className="transcript-label">Live transcript</div>
                  <div className="transcript-body">
                    {messages.map((msg, i) => {
                      const isUser = msg.role === 'user'
                      return (
                        <div key={`${msg.createdAt}-${i}`} className={`turn ${isUser ? 'user' : 'bot'}`}>
                          <span className="turn-role">{isUser ? 'You' : 'AI'}</span>
                          <span className="turn-text">
                            {msg.parts?.map((part, j) => {
                              const t = part.text
                              if (t != null && typeof t === 'object' && 'spoken' in t) {
                                const bot = t as BotOutputText
                                return (
                                  <span key={j}>
                                    {bot.spoken}
                                    {bot.unspoken && <span className="unspoken">{bot.unspoken}</span>}
                                  </span>
                                )
                              }
                              return <span key={j}>{t as React.ReactNode}</span>
                            })}
                          </span>
                        </div>
                      )
                    })}
                    <div ref={transcriptEndRef} />
                  </div>
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}

// ── Dialing view (real Ozonetel call, no browser transport) ────────────────

function DialingView({ brief, onHangup }: { brief: LeadBrief | null; onHangup: () => void }) {
  return (
    <div className="dialing-view">
      <div className="dialing-ring">
        <PhoneRingIcon />
      </div>
      <h1 className="brief-heading">Calling {brief?.phone_number || 'the lead'}…</h1>
      <p className="hint" style={{ maxWidth: 380 }}>
        Ozonetel is placing the call. Once it's answered, the agent talks directly
        over the phone line — there's nothing to hear in this tab. This view
        updates automatically once the call ends.
      </p>
      {brief && (
        <div className="call-meta">
          <span className="call-item-led">
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--indigo)', boxShadow: '0 0 8px var(--indigo)' }} />
          </span>
          <span className="call-meta-name">{brief.lead_name}</span>
          <span className="call-meta-sep">·</span>
          <span className="call-meta-num">{brief.company_name}</span>
        </div>
      )}
      <button className="btn-outline" onClick={onHangup}>
        <PhoneOffIcon />
        Hang up
      </button>
    </div>
  )
}

// ── Historical call view ────────────────────────────────────────────────────

function HistoricalView({
  callId,
  insights,
  onBack,
}: {
  callId: string | null
  insights: CallInsights | null
  onBack: () => void
}) {
  return (
    <div className="history-view">
      <div className="history-head">
        <button className="back-btn" onClick={onBack}>
          <ChevronLeftIcon />
          Back to live
        </button>
        <span className="history-title">{callId}</span>
      </div>
      {insights ? (
        <DispositionPanel insights={insights} summaryPending={!insights.outcome} onNewCall={onBack} />
      ) : (
        <div className="transcript-empty">No insights found for this call.</div>
      )}
    </div>
  )
}

// ── Stage step chip ──────────────────────────────────────────────────────────

function StageStep({ label, active, done }: { label: string; active: boolean; done: boolean }) {
  return (
    <span className={`stage-step ${active ? 'active' : ''} ${done ? 'done' : ''}`}>{label}</span>
  )
}

// ── Small components ──────────────────────────────────────────────────────────

function SpinnerIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 11-6.22-8.56" style={{ animation: 'spin .8s linear infinite' }} />
    </svg>
  )
}

function IdleBars({ count = 12, height = 6 }: { count?: number; height?: number }) {
  return (
    <div className="idle-bars">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="idle-bar" style={{ height }} />
      ))}
    </div>
  )
}

// ── Icons ─────────────────────────────────────────────────────────────────────

function MenuIcon() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" viewBox="0 0 24 24">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  )
}

function ChevronLeftIcon() {
  return (
    <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <polyline points="15 18 9 12 15 6" />
    </svg>
  )
}

function PhoneRingIcon() {
  return (
    <svg width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" />
    </svg>
  )
}

function PhoneOffIcon() {
  return (
    <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M10.68 13.31a16 16 0 003.41 2.6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7 2 2 0 011.72 2v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 2 2 0 01-.35-.28M6.18 6.18A19.5 19.5 0 004.69 12a19.79 19.79 0 01-3.08 8.63A2 2 0 003.6 22.73h3a2 2 0 002-1.72 12.84 12.84 0 01.7-2.81 2 2 0 00-.45-2.11L7.91 15.09" />
      <line x1="23" y1="1" x2="1" y2="23" />
    </svg>
  )
}

function MicOnIcon() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

function MicOffIcon() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <line x1="1" y1="1" x2="23" y2="23" />
      <path d="M9 9v3a3 3 0 005.12 2.12M15 9.34V4a3 3 0 00-5.94-.6" />
      <path d="M17 16.95A7 7 0 015 12v-2m14 0v2a7 7 0 01-.11 1.23" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  )
}

function WrenchIcon() {
  return (
    <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
    </svg>
  )
}