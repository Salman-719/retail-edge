import React, { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  getActiveAlerts, resolveAlert, getActiveVersion, listEmployees,
  listAlertRules, createAlertRule, updateAlertRule, deleteAlertRule, getAlertRuleDefaults,
} from '../api'
import { usePageTitle } from '../components/PageMeta'
import AlertCard from '../components/alerts/AlertCard'
import AlertHistoryTable from '../components/alerts/AlertHistoryTable'
import RuleList from '../components/alerts/RuleList'
import RuleForm from '../components/alerts/RuleForm'

const POLL_MS = 20000
const TABS = [['active', 'Active'], ['history', 'History'], ['rules', 'Rules']]

export default function Alerts() {
  const { slug } = useParams()
  usePageTitle('Alerts')
  const [tab, setTab] = useState('active')

  // Shared option lists for the rule form.
  const [zoneOptions, setZoneOptions] = useState([])
  const [employeeOptions, setEmployeeOptions] = useState([])
  const [ruleDefaults, setRuleDefaults] = useState(null)
  useEffect(() => {
    getActiveVersion(slug).then((v) => setZoneOptions((v?.zones || []).map((z) => ({ id: z.id, name: z.name })))).catch(() => {})
    listEmployees(slug).then((e) => setEmployeeOptions((Array.isArray(e) ? e : e?.employees || []).map((x) => ({ id: x.id, name: x.name })))).catch(() => {})
    getAlertRuleDefaults(slug).then(setRuleDefaults).catch(() => {})
  }, [slug])

  // ── Active feed (polled) ──────────────────────────────────────────────────
  const [active, setActive] = useState([])
  const [activeLoading, setActiveLoading] = useState(true)
  const [dismissingId, setDismissingId] = useState(null)

  const loadActive = useCallback(() => {
    return getActiveAlerts(slug)
      .then((d) => setActive(Array.isArray(d) ? d : []))
      .catch(() => {})
      .finally(() => setActiveLoading(false))
  }, [slug])

  useEffect(() => {
    loadActive()
    const id = setInterval(loadActive, POLL_MS)
    return () => clearInterval(id)
  }, [loadActive])

  async function dismiss(alert) {
    setDismissingId(alert.id)
    setActive((list) => list.filter((a) => a.id !== alert.id)) // optimistic
    try {
      await resolveAlert(slug, alert.id)
    } catch {
      loadActive() // restore on failure
    } finally {
      setDismissingId(null)
    }
  }

  // ── Rules ─────────────────────────────────────────────────────────────────
  const [rules, setRules] = useState([])
  const [rulesLoading, setRulesLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editRule, setEditRule] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [serverError, setServerError] = useState('')

  const loadRules = useCallback(() => {
    setRulesLoading(true)
    return listAlertRules(slug).then(setRules).catch(() => setRules([])).finally(() => setRulesLoading(false))
  }, [slug])
  useEffect(() => { loadRules() }, [loadRules])

  async function submitRule(body) {
    setSubmitting(true); setServerError('')
    try {
      if (editRule) await updateAlertRule(slug, editRule.id, body)
      else await createAlertRule(slug, body)
      setFormOpen(false); setEditRule(null)
      await loadRules()
    } catch (e) {
      const d = e.response?.data?.detail
      setServerError(typeof d === 'string' ? d : d?.error || 'Failed to save rule')
    } finally {
      setSubmitting(false)
    }
  }

  async function toggleRule(rule) {
    setBusyId(rule.id)
    try { await updateAlertRule(slug, rule.id, { is_active: !rule.is_active }); await loadRules() }
    finally { setBusyId(null) }
  }

  async function removeRule(rule) {
    if (!window.confirm(`Delete rule "${rule.name}"?`)) return
    setBusyId(rule.id)
    try { await deleteAlertRule(slug, rule.id); await loadRules() }
    finally { setBusyId(null) }
  }

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">
      <header className="bg-white border-b border-gray-200 px-6 py-4 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="page-title">Alerts</h1>
          <p className="page-subtitle">Live alerts, history, and the rules that fire them</p>
        </div>
        {tab === 'rules' && (
          <button onClick={() => { setEditRule(null); setServerError(''); setFormOpen(true) }} className="btn-primary text-sm">
            + New rule
          </button>
        )}
      </header>

      <div className="px-6 pt-3 border-b border-gray-200 bg-white shrink-0 flex gap-1">
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === k ? 'border-blue-600 text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            {label}{k === 'active' && active.length > 0 && <span className="ml-1.5 text-[10px] bg-red-500 text-white px-1.5 py-0.5 rounded-full">{active.length}</span>}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {tab === 'active' && (
          activeLoading ? <div className="skeleton h-24 w-full rounded-xl" />
            : !active.length ? <div className="text-sm text-gray-400 bg-gray-50 rounded-lg p-8 text-center">No active alerts.</div>
            : <div className="space-y-3">{active.map((a) => <AlertCard key={a.id} alert={a} onDismiss={dismiss} dismissing={dismissingId === a.id} />)}</div>
        )}

        {tab === 'history' && <AlertHistoryTable slug={slug} />}

        {tab === 'rules' && (
          rulesLoading ? <div className="skeleton h-40 w-full rounded-xl" />
            : <RuleList rules={rules} onToggle={toggleRule} onEdit={(r) => { setEditRule(r); setServerError(''); setFormOpen(true) }} onDelete={removeRule} busyId={busyId} />
        )}
      </div>

      {formOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 px-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">{editRule ? 'Edit rule' : 'New alert rule'}</h3>
              <button onClick={() => { setFormOpen(false); setEditRule(null) }} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
            </div>
            <div className="px-6 py-4">
              <RuleForm
                rule={editRule} defaults={ruleDefaults} zoneOptions={zoneOptions} employeeOptions={employeeOptions}
                onSubmit={submitRule} onCancel={() => { setFormOpen(false); setEditRule(null) }}
                submitting={submitting} serverError={serverError}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
