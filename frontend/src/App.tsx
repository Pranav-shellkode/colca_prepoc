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

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws'
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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
    <SafeProvider client={pcClient}>
      <PipecatClientAudio />
      <VoiceApp />
    </SafeProvider>
  )
}

// ── Types ─────────────────────────────────────────────────────────────────────

type AgentState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking'

interface Session {
  id: string
  title: string
  created_at: string
}

interface HistoricalMessage {
  role: string
  content: string
  created_at: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yestStart  = new Date(todayStart.getTime() - 86400000)
  if (d >= todayStart) return `Today ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  if (d >= yestStart)  return `Yesterday ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

// ── Main component ────────────────────────────────────────────────────────────

function VoiceApp() {
  const client = usePipecatClient()
  const transportState = usePipecatClientTransportState()
  const { messages } = usePipecatConversation()
  const [agentState, setAgentState] = useState<AgentState>('idle')
  const [toolActive, setToolActive] = useState(false)
  const [toolName, setToolName] = useState('')
  const transcriptEndRef = useRef<HTMLDivElement>(null)

  // Session history state
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [histMessages, setHistMessages] = useState<HistoricalMessage[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const isConnected  = transportState === 'ready' || transportState === 'connected'
  const isConnecting = transportState === 'connecting' || transportState === 'authenticating'

  // ── Agent state events ────────────────────────────────────────────────────

  useRTVIClientEvent(RTVIEvent.BotStartedSpeaking,  useCallback(() => setAgentState('speaking'),  []))
  useRTVIClientEvent(RTVIEvent.BotStoppedSpeaking,  useCallback(() => setAgentState('listening'), []))
  useRTVIClientEvent(RTVIEvent.UserStartedSpeaking, useCallback(() => setAgentState('listening'), []))
  useRTVIClientEvent(RTVIEvent.UserStoppedSpeaking, useCallback(() => setAgentState('thinking'),  []))
  useRTVIClientEvent(RTVIEvent.BotLlmStarted,       useCallback(() => setAgentState('thinking'),  []))
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

  // ── Connection state tracking ─────────────────────────────────────────────

  const prevConnected = useRef(false)

  useEffect(() => {
    if (isConnecting) { setAgentState('connecting'); return }
    if (!isConnected) {
      setAgentState('idle')
      // Refresh sessions after a session ends
      if (prevConnected.current) fetchSessions()
    }
    prevConnected.current = isConnected
  }, [isConnected, isConnecting])

  // ── Session data ──────────────────────────────────────────────────────────

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/sessions`)
      if (res.ok) setSessions(await res.json())
    } catch { /* backend not yet running */ }
  }, [])

  useEffect(() => { fetchSessions() }, [fetchSessions])

  const selectSession = useCallback(async (id: string) => {
    setSelectedId(id)
    try {
      const res = await fetch(`${API_URL}/sessions/${id}/messages`)
      if (res.ok) setHistMessages(await res.json())
    } catch { setHistMessages([]) }
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedId(null)
    setHistMessages([])
  }, [])

  // ── Live transcript scroll ────────────────────────────────────────────────

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, histMessages])

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleConnect = useCallback(async () => {
    clearSelection()
    try { await client?.connect({ wsUrl: WS_URL }) } catch (e) { console.error(e) }
  }, [client, clearSelection])

  const handleDisconnect = useCallback(async () => {
    try { await client?.disconnect() } catch (e) { console.error(e) }
  }, [client])

  // ── Render ────────────────────────────────────────────────────────────────

  const statusMap: Record<AgentState, string> = {
    idle:       'Ready to connect',
    connecting: 'Connecting…',
    listening:  'Listening',
    thinking:   'Thinking…',
    speaking:   'Speaking',
  }

  const botBarColor = agentState === 'speaking' ? '#a78bfa' : '#6366f1'
  const viewingHistory = selectedId !== null

  return (
    <div className="shell">
      {/* ── Nav ─────────────────────────────────────── */}
      <header className="nav">
        <div className="nav-brand">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarOpen(o => !o)}
            title="Toggle history"
          >
            <MenuIcon />
          </button>
          <OrbIcon />
          <span className="nav-title">Voice AI</span>
        </div>
        <div className="nav-actions">
          {isConnected ? (
            <button className="btn-end" onClick={handleDisconnect}>
              <PhoneOffIcon />
              End Session
            </button>
          ) : (
            <button className="btn-start" onClick={handleConnect} disabled={isConnecting}>
              {isConnecting ? <SpinnerIcon /> : <PhoneIcon />}
              {isConnecting ? 'Connecting…' : 'Start Session'}
            </button>
          )}
        </div>
      </header>

      {/* ── Body ────────────────────────────────────── */}
      <div className="body">

        {/* ── Sidebar ───────────────────────────────── */}
        <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
          <div className="sidebar-head">
            <span className="sidebar-title">History</span>
            {sessions.length > 0 && (
              <span className="sidebar-count">{sessions.length}</span>
            )}
          </div>

          {sessions.length === 0 ? (
            <div className="sidebar-empty">No sessions yet</div>
          ) : (
            <ul className="session-list">
              {sessions.map(s => (
                <li key={s.id}>
                  <button
                    className={`session-item ${selectedId === s.id ? 'active' : ''}`}
                    onClick={() => selectSession(s.id)}
                  >
                    <span className="session-item-title">{s.title}</span>
                    <span className="session-item-date">{formatDate(s.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* ── Main ──────────────────────────────────── */}
        <main className="main">

          {viewingHistory ? (
            /* ── Historical view ───────────────────── */
            <div className="history-view">
              <div className="history-head">
                <button className="back-btn" onClick={clearSelection}>
                  <ChevronLeftIcon />
                  Back to live
                </button>
                <span className="history-title">
                  {sessions.find(s => s.id === selectedId)?.title ?? 'Session'}
                </span>
              </div>
              <div className="transcript">
                <div className="transcript-label">Transcript</div>
                <div className="transcript-body">
                  {histMessages.length === 0 ? (
                    <div className="transcript-empty">No messages in this session.</div>
                  ) : (
                    histMessages.map((m, i) => (
                      <div key={i} className={`turn ${m.role === 'user' ? 'user' : 'bot'}`}>
                        <span className="turn-role">{m.role === 'user' ? 'You' : 'AI'}</span>
                        <span className="turn-text">{m.content}</span>
                      </div>
                    ))
                  )}
                  <div ref={transcriptEndRef} />
                </div>
              </div>
            </div>
          ) : (
            /* ── Live voice view ───────────────────── */
            <>
              {/* Visualizer card */}
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
                      barColor="#818cf8"
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

              {/* Mic toggle */}
              <PipecatClientMicToggle disabled={!isConnected}>
                {({ disabled, isMicEnabled, onClick }) => (
                  <button
                    className={`mic-btn ${isMicEnabled ? 'on' : 'off'}`}
                    onClick={onClick}
                    disabled={disabled}
                  >
                    {isMicEnabled ? <MicOnIcon /> : <MicOffIcon />}
                    {isMicEnabled ? 'Microphone On' : 'Microphone Muted'}
                  </button>
                )}
              </PipecatClientMicToggle>

              {!isConnected && !isConnecting && messages.length === 0 && (
                <p className="hint">
                  Press <strong>Start Session</strong> to begin your voice conversation.
                </p>
              )}

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

// ── Small components ──────────────────────────────────────────────────────────

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

function OrbIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
      <defs>
        <linearGradient id="og" x1="0" y1="0" x2="28" y2="28" gradientUnits="userSpaceOnUse">
          <stop stopColor="#6366f1" />
          <stop offset="1" stopColor="#a78bfa" />
        </linearGradient>
      </defs>
      <rect width="28" height="28" rx="9" fill="url(#og)" />
      <rect x="11" y="7" width="6" height="10" rx="3" fill="white" />
      <path d="M8 14a6 6 0 0012 0" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="14" y1="20" x2="14" y2="23" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
      <line x1="10" y1="23" x2="18" y2="23" stroke="white" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function MenuIcon() {
  return (
    <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" viewBox="0 0 24 24">
      <line x1="3" y1="6"  x2="21" y2="6" />
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

function PhoneIcon() {
  return (
    <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 014.69 12 19.79 19.79 0 011.61 3.42 2 2 0 013.6 1.27h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L7.91 8.91a16 16 0 006.18 6.18l.91-.91a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" />
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

function SpinnerIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
      <path d="M21 12a9 9 0 11-6.22-8.56" style={{ animation: 'spin .8s linear infinite' }} />
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
