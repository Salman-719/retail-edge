/*
 * Main Vision Debug — end-to-end pipeline tester (VD2/VD3 redesign).
 * Route: /store/:slug/dev/e2e  (ships in production, super-admin gated — A4/A5)
 *
 * One unified floor map + progressive disclosure + coherent identity (one
 * color/number per global_id everywhere) + IEP3 deep-debug panels off the VD1 trace.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { usePageTitle } from '../components/PageMeta'
import {
  getStore, listCameras, getActiveVersion,
  devPipelineStart, devPipelineStop,
  getDevTracking, getDevIep3, getDevGpuStatus, getDevLocalGlobal, getDevReconTrace,
} from '../api'
import { makeIdentityMap, CAMERA_PALETTE } from '../lib/identityColors'
import ControlBar from '../components/devE2E/ControlBar'
import UnifiedFloorMap from '../components/devE2E/UnifiedFloorMap'
import CameraTile from '../components/devE2E/CameraTile'
import IdentityLegend from '../components/devE2E/IdentityLegend'
import LocalGlobalPanel from '../components/devE2E/recon/LocalGlobalPanel'
import MergeDecisionPanel from '../components/devE2E/recon/MergeDecisionPanel'
import ReidSimilarityPanel from '../components/devE2E/recon/ReidSimilarityPanel'
import SelectionScorePanel from '../components/devE2E/recon/SelectionScorePanel'

const shortId = (v) => (v ? String(v).slice(0, 8) : '—')

export default function DevE2E() {
  usePageTitle('Main Vision Debug')
  const { slug } = useParams()

  const [storeId, setStoreId] = useState('')
  const [cameras, setCameras] = useState([])
  const [camSlots, setCamSlots] = useState(Array(6).fill(''))
  const [numCams, setNumCams] = useState(2)
  const [zones, setZones] = useState([])
  const [floorPlan, setFloorPlan] = useState(null)
  const [frameUrls, setFrameUrls] = useState({})
  // 'idle' | 'local' | 'attached'
  //   local    — this page started a dev pipeline on the EEP host (laptop/testing)
  //   attached — observe the pipeline the Edge Agent is ALREADY running (cloud
  //              deployment); nothing is started or stopped, we only read.
  const [mode, setMode] = useState('idle')
  const running = mode !== 'idle'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [device, setDevice] = useState('cpu')
  const [gpu, setGpu] = useState(null)

  const [iep3, setIep3] = useState({ summary: {}, rows: [] })
  const [trackingByCam, setTrackingByCam] = useState({})
  const [mapping, setMapping] = useState([])
  const [trace, setTrace] = useState([])
  const [selectedBatch, setSelectedBatch] = useState(null)
  const [focusCam, setFocusCam] = useState(null)

  const identityRef = useRef(makeIdentityMap())

  // ── Load store / active version ──────────────────────────────────────────
  useEffect(() => {
    (async () => {
      try {
        const [store, cams, version] = await Promise.all([
          getStore(slug), listCameras(slug), getActiveVersion(slug).catch(() => null),
        ])
        setStoreId(store.id)
        const urls = {}, activePcIds = new Set()
        for (const cc of (version?.camera_configs || [])) {
          const pid = String(cc.physical_camera_id); activePcIds.add(pid)
          if (cc.frame_url) urls[pid] = cc.frame_url
        }
        setFrameUrls(urls); setZones(version?.zones || []); setFloorPlan(version?.floor_plan || null)
        const activeCams = (cams || []).filter((c) => activePcIds.size ? activePcIds.has(String(c.id)) : c.is_active)
        setCameras(activeCams)
        const slots = Array(6).fill(''); activeCams.slice(0, 6).forEach((c, i) => { slots[i] = String(c.id) }); setCamSlots(slots)
      } catch { setError('Failed to load store / cameras') }
      try { const g = await getDevGpuStatus(); setGpu(g); if (g.gpu_available) setDevice('gpu') } catch { setGpu({ gpu_available: false }) }
    })()
  }, [slug])

  const activeCamIds = () => camSlots.slice(0, numCams).filter(Boolean)
  const camIndexById = useMemo(() => {
    const m = {}; camSlots.forEach((s, i) => { if (s) m[String(s)] = i }); return m
  }, [camSlots])
  const camColorById = useMemo(() => {
    const m = {}; activeCamIds().forEach((id) => { m[id] = CAMERA_PALETTE[camIndexById[id] % CAMERA_PALETTE.length] }); return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camSlots, numCams])
  const camLabelById = useMemo(() => {
    const m = {}; camSlots.forEach((s, i) => { if (s) m[String(s)] = `Cam ${i + 1}` }); return m
  }, [camSlots])
  const camLabel = (id) => camLabelById[String(id)] || shortId(id)
  const nameOf = (id) => cameras.find((c) => String(c.id) === String(id))?.name || shortId(id)

  // ── Page-level polling (running) + one final fetch after stop ─────────────
  const refresh = useRef(async () => {})
  refresh.current = async () => {
    if (!storeId) return
    try { const d = await getDevIep3(storeId, 80); setIep3(d); for (const r of (d.rows || [])) identityRef.current.get(r.global_id) } catch {}
    try { const lg = await getDevLocalGlobal(storeId); setMapping(lg.rows || []); for (const r of (lg.rows || [])) identityRef.current.get(r.global_id) } catch {}
    try { const t = await getDevReconTrace(storeId, null, 2000); setTrace(t || []) } catch {}
    const ids = activeCamIds()
    const entries = await Promise.all(ids.map(async (id) => {
      try { const d = await getDevTracking(id, 60); return [id, d.rows || []] } catch { return [id, []] }
    }))
    setTrackingByCam(Object.fromEntries(entries))
  }

  useEffect(() => {
    if (!running || !storeId) return
    let alive = true
    const tick = () => { if (alive) refresh.current() }
    tick()
    const id = setInterval(tick, 2500)
    return () => { alive = false; clearInterval(id) }
  }, [running, storeId])

  // Batches present in the trace; default to the latest.
  const batches = useMemo(() => [...new Set(trace.map((e) => e.batch_number))].sort((a, b) => b - a), [trace])
  useEffect(() => { if (batches.length && (selectedBatch == null || !batches.includes(selectedBatch))) setSelectedBatch(batches[0]) }, [batches]) // eslint-disable-line
  const batchEvents = useMemo(() => trace.filter((e) => selectedBatch == null || e.batch_number === selectedBatch), [trace, selectedBatch])
  const hasTrace = trace.length > 0

  async function handleStart() {
    setError('')
    const ids = activeCamIds()
    if (!ids.length) { setError('Select at least one camera'); return }
    if (ids.some((id, i) => ids.indexOf(id) !== i)) { setError('Each camera can only be selected once'); return }
    identityRef.current = makeIdentityMap()
    setBusy(true)
    try {
      const res = await devPipelineStart({ store_id: storeId, camera_ids: ids, target_fps: 5.0, window_seconds: 60.0, device })
      const failed = (res.cameras || []).filter((c) => !c.ok)
      if (failed.length) setError('Some cameras failed: ' + failed.map((f) => `${shortId(f.camera_id)} (${f.stage}: ${f.error})`).join('; '))
      setMode('local')
    } catch (e) {
      const d = e?.response?.data?.detail
      if (d?.code === 'NO_GPU') { setError('No usable GPU — switch to CPU or run on a GPU machine.'); setDevice('cpu') }
      else setError(typeof d === 'string' ? d : (d?.error || 'Start failed'))
    } finally { setBusy(false) }
  }
  async function handleStop() {
    setBusy(true)
    try { await devPipelineStop({ store_id: storeId, camera_ids: activeCamIds() }) } catch {}
    setMode('idle'); setBusy(false)
    setTimeout(() => refresh.current(), 500) // final snapshot so panels/replay survive Stop
  }

  // Observe the pipeline the Edge Agent is already running (cloud deployment).
  // Starts NOTHING: it only turns on polling + the live WebSocket, so it is safe
  // to click against a production store.
  function handleAttach() {
    setError('')
    if (!activeCamIds().length) { setError('Select at least one camera'); return }
    identityRef.current = makeIdentityMap()
    setMode('attached')
  }
  function handleDetach() {
    setMode('idle')
    setTimeout(() => refresh.current(), 500)
  }

  const updateSlot = (i, v) => setCamSlots((prev) => prev.map((x, j) => (j === i ? v : x)))
  const slots = camSlots.slice(0, numCams)
  const gridClass = numCams === 6 ? 'grid-cols-1 md:grid-cols-2 xl:grid-cols-3' : numCams >= 2 ? 'grid-cols-1 lg:grid-cols-2' : 'grid-cols-1'
  const identity = identityRef.current
  const s = iep3.summary || {}
  const zoneTypes = [...new Set(zones.map((z) => z.type))]

  return (
    <div className="page-enter flex flex-col h-full overflow-hidden">
      <header className="bg-white border-b border-gray-200 px-6 py-3.5 shrink-0 flex items-center justify-between gap-4 flex-wrap sticky top-0 z-10">
        <div>
          <h1 className="page-title">Main Vision Debug</h1>
          <p className="page-subtitle">IEP1 → IEP2 → IEP3 · unified view</p>
        </div>
        <ControlBar
          numCams={numCams} setNumCams={setNumCams} device={device} setDevice={setDevice}
          gpu={gpu} running={running} busy={busy} storeId={storeId} onStart={handleStart} onStop={handleStop}
          mode={mode} onAttach={handleAttach} onDetach={handleDetach}
        />
      </header>

      {error && <div className="bg-red-50 border-b border-red-200 text-red-700 text-sm px-6 py-2 shrink-0">{error}</div>}

      <div className="flex-1 overflow-auto p-5 space-y-4">
        {/* Camera selectors */}
        <div className={`grid ${gridClass} gap-2`}>
          {slots.map((slot, i) => (
            <div key={i} className="flex items-center gap-3">
              <label className="text-sm font-medium text-gray-700 shrink-0 w-14">Cam {i + 1}</label>
              <select value={slot} onChange={(e) => updateSlot(i, e.target.value)} disabled={running}
                className="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white disabled:bg-gray-100">
                <option value="">— none —</option>
                {cameras.map((c) => <option key={c.id} value={String(c.id)}>{c.name || shortId(c.id)}</option>)}
              </select>
            </div>
          ))}
        </div>

        <IdentityLegend identity={identity} camColorById={camColorById} camLabelById={camLabelById} zoneTypes={zoneTypes} />

        {/* Centerpiece: unified floor map */}
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Unified Floor Map</h3>
          <UnifiedFloorMap
            floorPlan={floorPlan} zones={zones} trackingByCam={trackingByCam} globals={iep3.rows || []}
            camColorById={camColorById} camLabelById={camLabelById} identity={identity}
            focusCam={focusCam} onFocusCam={setFocusCam}
          />
        </div>

        {/* Camera feeds (compact, details on demand) */}
        {slots.some(Boolean) && (
          <div className={`grid ${gridClass} gap-4`}>
            {slots.map((slot, i) => !slot ? null : (
              <CameraTile
                key={`tile-${i}-${slot}`} label={`Cam ${i + 1}`} cameraId={slot} cameraName={nameOf(slot)}
                running={running} rows={trackingByCam[slot] || []} frameUrl={frameUrls[slot] || null}
                identity={identity} localGlobal={Object.fromEntries(mapping.map((m) => [`${m.camera_id}:${m.local_id}`, m.global_id]))}
                camColor={camColorById[slot]}
              />
            ))}
          </div>
        )}

        {/* IEP3 summary */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-2.5 flex items-center gap-5 text-xs text-gray-500">
          <span className="text-sm font-semibold text-gray-700">IEP3</span>
          <span>positions <b className="text-gray-700">{s.positions ?? 0}</b></span>
          <span>globals <b className="text-gray-700">{s.unique_globals ?? 0}</b></span>
          <span>cameras <b className="text-gray-700">{s.cameras ?? 0}</b></span>
        </div>

        {/* Deep-debug panels (VD3) */}
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-700">Reconciliation Trace</h3>
          {batches.length > 0 && (
            <select value={selectedBatch ?? ''} onChange={(e) => setSelectedBatch(Number(e.target.value))}
              className="border border-gray-300 rounded-lg px-2 py-1 text-xs">
              {batches.map((b) => <option key={b} value={b}>Batch {b}</option>)}
            </select>
          )}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <LocalGlobalPanel mapping={mapping} identity={identity} camLabel={camLabel} />
          <MergeDecisionPanel events={batchEvents} camLabel={camLabel} hasTrace={hasTrace} />
          <ReidSimilarityPanel events={batchEvents} camLabel={camLabel} hasTrace={hasTrace} />
          <SelectionScorePanel events={batchEvents} camLabel={camLabel} identity={identity} hasTrace={hasTrace} />
        </div>
      </div>
    </div>
  )
}
