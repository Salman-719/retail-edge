import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import api from '../api'
import { usePageTitle } from '../components/PageMeta'

// ─── Mock data ────────────────────────────────────────────────────────────────

// MOCK: replace with GET /store/{slug}/agent/reports?type=daily
const MOCK_DAILY_REPORTS = [
  { id: 'd1', date: '2026-05-27', title: 'Daily Summary — May 27', body: 'Total visitors: 214. Peak hour: 14:00–15:00 (42 people). Checkout zone had the longest average dwell time at 4.2 min. 2 queue alerts triggered, both resolved within 5 minutes.' },
  { id: 'd2', date: '2026-05-26', title: 'Daily Summary — May 26', body: 'Total visitors: 189. Quieter Monday — traffic 12% below weekly average. Entrance zone saw highest throughput. No alerts triggered.' },
  { id: 'd3', date: '2026-05-25', title: 'Daily Summary — May 25', body: 'Total visitors: 301. Sunday peak — busiest day of the week. Overcrowding alert at 16:30 in Produce zone, lasted 8 minutes. Staff coverage adequate.' },
  { id: 'd4', date: '2026-05-24', title: 'Daily Summary — May 24', body: 'Total visitors: 267. Saturday. Strong afternoon traffic 13:00–17:00. Checkout queue alerts ×3. Average resolution time: 3 min.' },
]

// MOCK: replace with GET /store/{slug}/agent/reports?type=weekly
const MOCK_WEEKLY_REPORTS = [
  { id: 'w1', date: '2026-05-19 – 2026-05-25', title: 'Weekly Summary — Week 21', body: 'Total weekly visitors: 1,482. Busiest day: Sunday (301). Slowest day: Monday (189). Zone with highest dwell time: Checkout (avg 4.1 min). 7 alerts total, avg resolution 4.2 min. Staff coverage score: 94%.' },
  { id: 'w2', date: '2026-05-12 – 2026-05-18', title: 'Weekly Summary — Week 20', body: 'Total weekly visitors: 1,339. Down 6% vs prior week. Notable: CAM-03 offline Wednesday–Thursday, reduced coverage. Entrance zone throughput highest at 38% of total traffic.' },
]

// Fallback when the agent API is unreachable
const FALLBACK_RESPONSE = "I'm currently unavailable. Please try again later."

// ─── Report modal ─────────────────────────────────────────────────────────────

function ReportModal({ report, onClose }) {
  useEffect(() => {
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg">
        <div className="px-6 py-4 border-b border-gray-200 flex items-start justify-between gap-4">
          <div>
            <h3 className="font-semibold text-gray-900">{report.title}</h3>
            <p className="text-xs text-gray-400 mt-0.5">{report.date}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none shrink-0">✕</button>
        </div>
        <div className="px-6 py-5 text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
          {report.body}
        </div>
        <div className="px-6 pb-5">
          <button
            onClick={onClose}
            className="w-full py-2 rounded-lg text-sm font-medium border border-gray-300 text-gray-700 hover:bg-gray-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Report panel ─────────────────────────────────────────────────────────────

function ReportPanel() {
  const [tab, setTab] = useState('daily')
  const [viewing, setViewing] = useState(null)
  const [demoBanner, setDemoBanner] = useState(true)

  const reports = tab === 'daily' ? MOCK_DAILY_REPORTS : MOCK_WEEKLY_REPORTS

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 shrink-0">
        {['daily', 'weekly'].map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2.5 text-sm font-medium capitalize transition-colors border-b-2 ${
              tab === t
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'daily' ? 'Daily Reports' : 'Weekly Reports'}
          </button>
        ))}
      </div>

      {/* Demo data banner */}
      {demoBanner && (
        <div className="bg-amber-50 border-b border-amber-200 text-amber-800 text-xs px-4 py-2 flex items-center justify-between shrink-0">
          <span>Showing sample reports.</span>
          <button onClick={() => setDemoBanner(false)} className="ml-3 text-amber-600 hover:text-amber-900 leading-none">✕</button>
        </div>
      )}

      {/* Report list */}
      {/* MOCK: replace with GET /store/{slug}/agent/reports?type={tab} */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
        {reports.map(r => (
          <div key={r.id} className="px-4 py-3 hover:bg-gray-50 transition-colors">
            <p className="text-sm font-medium text-gray-900 leading-snug">{r.title}</p>
            <p className="text-xs text-gray-400 mt-0.5">{r.date}</p>
            <button
              onClick={() => setViewing(r)}
              className="mt-2 text-xs px-3 py-1 rounded border border-blue-200 text-blue-600 hover:bg-blue-50 transition-colors"
            >
              View
            </button>
          </div>
        ))}
      </div>

      {viewing && <ReportModal report={viewing} onClose={() => setViewing(null)} />}
    </div>
  )
}

// ─── Inline chart ─────────────────────────────────────────────────────────────

function InlineChart({ chart }) {
  // chart: { title, data: [{ label, value }] }
  return (
    <div className="mt-2 bg-white border border-gray-200 rounded-lg p-3">
      {chart.title && (
        <p className="text-xs font-semibold text-gray-600 mb-2">{chart.title}</p>
      )}
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={chart.data} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip contentStyle={{ fontSize: 11, borderRadius: 6 }} />
          <Bar dataKey="value" fill="#3b82f6" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function Bubble({ msg }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
        {!isUser && (
          <span className="text-xs text-gray-400 ml-1">AI Assistant</span>
        )}
        <div className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-sm'
            : 'bg-gray-100 text-gray-800 rounded-bl-sm'
        }`}>
          {msg.text}
        </div>
        {msg.chart && <InlineChart chart={msg.chart} />}
        <span className={`text-[10px] text-gray-400 mx-1 ${isUser ? 'self-end' : 'self-start'}`}>{msg.ts}</span>
      </div>
    </div>
  )
}

// ─── Typing indicator ─────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-gray-100 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-1.5">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-gray-400"
            style={{ animation: `bounce 1s ease-in-out ${i * 0.15}s infinite` }}
          />
        ))}
      </div>
    </div>
  )
}

// ─── Chat panel ───────────────────────────────────────────────────────────────

function ChatPanel({ slug }) {
  const [messages, setMessages] = useState([
    {
      id: 'init',
      role: 'assistant',
      text: 'Hello! I\'m your RetailVision AI assistant. Ask me anything about your store — traffic patterns, zone performance, alert history, or staffing.',
      ts: now(),
      chart: null,
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [convId] = useState(() => crypto.randomUUID())
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')

    const userMsg = { id: crypto.randomUUID(), role: 'user', text, ts: now(), chart: null }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      // POST /api/agent/chat — expects { message, conversation_id }
      // Response: { message: string, chart?: { title, data: [{ label, value }] } }
      const res = await api.post(`/store/${slug}/agent/chat`, {
        message: text,
        conversation_id: convId,
      })
      const data = res.data
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: data.message || FALLBACK_RESPONSE,
        ts: now(),
        chart: data.chart || null,
      }])
    } catch {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        text: FALLBACK_RESPONSE,
        ts: now(),
        chart: null,
      }])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Message history */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-0">
        {messages.map(msg => <Bubble key={msg.id} msg={msg} />)}
        {loading && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="shrink-0 border-t border-gray-200 px-4 py-3 bg-white flex items-end gap-2">
        <textarea
          ref={inputRef}
          rows={1}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about your store…"
          className="flex-1 resize-none border border-gray-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent leading-snug"
          style={{ maxHeight: 120, overflowY: 'auto' }}
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={!input.trim() || loading}
          className="shrink-0 px-4 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-semibold hover:bg-blue-700 disabled:opacity-40 transition-colors"
        >
          Send
        </button>
      </div>
    </div>
  )
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function now() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AIAgent() {
  const { slug } = useParams()
  usePageTitle('AI Assistant')

  return (
    <>
      {/* Bounce keyframe injected once */}
      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); opacity: 0.4; }
          50%       { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>

      <div className="page-enter flex flex-col h-full overflow-hidden">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
          <h1 className="page-title">AI Assistant</h1>
          <p className="page-subtitle">Natural language retail analytics assistant</p>
        </header>

        {/* Two-panel layout */}
        <div className="flex flex-1 min-h-0 overflow-hidden">

          {/* Left: Reports — 30% */}
          <div className="shrink-0 border-r border-gray-200 bg-white flex flex-col" style={{ width: '30%' }}>
            <div className="px-4 pt-4 pb-2 shrink-0">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Reports</h2>
            </div>
            <ReportPanel />
          </div>

          {/* Right: Chat — 70% */}
          <div className="flex-1 flex flex-col bg-gray-50 min-w-0">
            <ChatPanel slug={slug} />
          </div>

        </div>
      </div>
    </>
  )
}
