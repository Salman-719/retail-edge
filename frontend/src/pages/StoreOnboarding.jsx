import React, { useEffect, useState, useRef } from 'react'
import useStore from '../store'
import { listStores, createStore, setCurrentStoreId, loadProject } from '../api'

// Method 1 — Standard (Floor Plan + Homography)
import Step1_Upload from '../steps/Step1_Upload'
import Step2_Scale from '../steps/Step2_Scale'
import Step3_Zones from '../steps/Step3_Zones'
import Step4_Cameras from '../steps/Step4_Cameras'
import Step5_Videos from '../steps/Step5_Videos'
import Step6_Correspondence from '../steps/Step6_Correspondence'
import Step7_Homography from '../steps/Step7_Homography'
import Step8_Save from '../steps/Step8_Save'
import Step9_TestMode from '../steps/Step9_TestMode'

// Method 2 — Calibration Files
import Step0_MethodSelect from '../steps/Step0_MethodSelect'
import CalibStep1_CamerasAndFiles from '../steps/CalibStep1_CamerasAndFiles'
import CalibStep2_WorldBounds from '../steps/CalibStep2_WorldBounds'
import CalibStep3_Zones from '../steps/CalibStep3_Zones'
import CalibStep4_Videos from '../steps/CalibStep4_Videos'
import CalibStep5_Save from '../steps/CalibStep5_Save'
import CalibStep6_TestMode from '../steps/CalibStep6_TestMode'

// ── Method 1 steps ────────────────────────────────────────────────────────────

const STANDARD_STEPS = [
  { n: 1, label: 'Floor Plan Upload' },
  { n: 2, label: 'Scale & Origin' },
  { n: 3, label: 'Zones & Obstacles' },
  { n: 4, label: 'Camera Registration' },
  { n: 5, label: 'Camera Videos' },
  { n: 6, label: 'Point Correspondence' },
  { n: 7, label: 'Compute Homography' },
  { n: 8, label: 'Save Configuration' },
  { n: 9, label: 'Test Mode & Heatmap' },
]

const STANDARD_STEP_COMPONENTS = {
  1: Step1_Upload,
  2: Step2_Scale,
  3: Step3_Zones,
  4: Step4_Cameras,
  5: Step5_Videos,
  6: Step6_Correspondence,
  7: Step7_Homography,
  8: Step8_Save,
  9: Step9_TestMode,
}

// ── Method 2 steps ────────────────────────────────────────────────────────────

const CALIB_STEPS = [
  { n: 1, label: 'Camera Setup & Files' },
  { n: 2, label: 'World Map Bounds' },
  { n: 3, label: 'Draw Zones' },
  { n: 4, label: 'Camera Videos' },
  { n: 5, label: 'Save Configuration' },
  { n: 6, label: 'Test Mode & Heatmap' },
]

// ── Store selector overlay ────────────────────────────────────────────────────

function StoreSelector({ onSelected }) {
  const [stores, setStores] = useState([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    listStores().then(setStores).catch(() => {})
  }, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setLoading(true)
    setError(null)
    try {
      // Create with default method; method is chosen in the onboarding pre-screen
      const store = await createStore(newName.trim(), 'standard')
      onSelected(store, true /* isNew */)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 flex items-center justify-center p-12 bg-gray-50">
      <div className="bg-white rounded-2xl shadow-lg border p-8 max-w-md w-full">
        <h2 className="text-2xl font-bold text-gray-800 mb-1">Select a Store</h2>
        <p className="text-gray-500 text-sm mb-6">Choose an existing store or create a new one to begin onboarding.</p>

        {stores.length > 0 && (
          <div className="mb-6">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Existing Stores</p>
            <div className="space-y-2">
              {stores.map(s => (
                <button
                  key={s.id}
                  onClick={() => onSelected(s, false)}
                  className="w-full text-left px-4 py-3 rounded-xl border border-gray-200 hover:border-blue-400 hover:bg-blue-50 transition flex items-center gap-3"
                >
                  <span className="text-xl">🏪</span>
                  <span className="font-medium text-gray-800">{s.name}</span>
                  {s.onboarding_method && s.onboarding_method !== 'standard' && (
                    <span className="ml-auto text-xs text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">
                      {s.onboarding_method === 'calibration' ? 'Calib Files' : s.onboarding_method}
                    </span>
                  )}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-3 my-4">
              <div className="flex-1 border-t" /><span className="text-xs text-gray-400">or</span><div className="flex-1 border-t" />
            </div>
          </div>
        )}

        <div className="flex gap-2">
          <input
            type="text"
            placeholder="New store name…"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            className="flex-1 border rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button
            onClick={handleCreate}
            disabled={loading || !newName.trim()}
            className="px-5 py-2.5 bg-blue-600 text-white rounded-xl text-sm font-medium disabled:opacity-40 hover:bg-blue-700 transition"
          >
            {loading ? '…' : 'Create'}
          </button>
        </div>
        {error && <p className="text-red-600 text-xs mt-2">{error}</p>}
      </div>
    </div>
  )
}

// ── Method 2 — step component renderer ───────────────────────────────────────

function CalibStepRenderer({ step, onBack, onNext }) {
  switch (step) {
    case 1: return <CalibStep1_CamerasAndFiles onNext={onNext} />
    case 2: return <CalibStep2_WorldBounds onBack={onBack} onNext={onNext} />
    case 3: return <CalibStep3_Zones onBack={onBack} onNext={onNext} />
    case 4: return <CalibStep4_Videos onBack={onBack} onNext={onNext} />
    case 5: return <CalibStep5_Save onBack={onBack} onNext={onNext} />
    case 6: return <CalibStep6_TestMode onBack={onBack} />
    default: return null
  }
}

// ── Main component ────────────────────────────────────────────────────────────

export default function StoreOnboarding() {
  const {
    activeStoreId, activeStoreName, setActiveStore,
    currentStep, setStep, maxReachedStep,
    loadProject: hydrateProject,
    resetOnboarding,
    floorPlanUrl,
    onboardingMethod, setOnboardingMethod,
  } = useStore()

  const importRef = useRef()
  const [dbReloading, setDbReloading] = useState(false)
  // showMethodSelect: true for a freshly created store that has not yet picked a method
  const [showMethodSelect, setShowMethodSelect] = useState(false)

  const handleReloadFromDb = async () => {
    setDbReloading(true)
    try {
      const data = await loadProject()
      if (data) hydrateProject(data)
      else alert('No saved data found for this store.')
    } catch (e) {
      alert(e.message)
    } finally {
      setDbReloading(false)
    }
  }

  const handleStoreSelected = async (store, isNew = false) => {
    setCurrentStoreId(store.id)
    setActiveStore(store.id, store.name)
    resetOnboarding()

    if (isNew) {
      // Brand-new store: skip loadProject (nothing to load), go straight to method selection
      setShowMethodSelect(true)
      return
    }

    // Existing store: load saved data and let hydrateProject set onboardingMethod from DB
    try {
      const data = await loadProject()
      if (data) hydrateProject(data)
    } catch (_) {}
  }

  const handleMethodSelected = (method) => {
    setOnboardingMethod(method)
    setShowMethodSelect(false)
    setStep(1)
  }

  const handleImportFile = (e) => {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const data = JSON.parse(ev.target.result)
        hydrateProject(data)
      } catch {
        alert('Invalid project file — expected JSON.')
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  // ── No store selected ───────────────────────────────────────────────────────
  if (!activeStoreId) {
    return (
      <div className="flex-1 flex flex-col">
        <header className="bg-white border-b px-8 py-4">
          <h2 className="text-lg font-semibold text-gray-800">Store Onboarding</h2>
          <p className="text-sm text-gray-500">Configure floor plan, zones, cameras and run tracking tests</p>
        </header>
        <StoreSelector onSelected={handleStoreSelected} />
      </div>
    )
  }

  // ── Method selection pre-screen (new stores only) ───────────────────────────
  if (showMethodSelect) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b px-8 py-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800">{activeStoreName}</h2>
            <p className="text-xs text-gray-500">Choose onboarding method</p>
          </div>
          <button
            onClick={() => { setActiveStore(null, null); setShowMethodSelect(false) }}
            className="text-xs text-blue-500 hover:underline"
          >
            Switch store
          </button>
        </header>
        <div className="flex-1 overflow-auto">
          <Step0_MethodSelect onMethodSelected={handleMethodSelected} />
        </div>
      </div>
    )
  }

  // ── Method 1 — Standard ─────────────────────────────────────────────────────
  if (!onboardingMethod || onboardingMethod === 'standard') {
    const StepComponent = STANDARD_STEP_COMPONENTS[currentStep] ?? STANDARD_STEP_COMPONENTS[1]

    return (
      <div className="flex flex-1 overflow-hidden">
        {/* Wizard sidebar */}
        <aside className="w-56 flex flex-col py-5 px-3 border-r bg-white shrink-0 overflow-y-auto">
          <div className="mb-4 px-1">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Store</p>
            <p className="text-sm font-semibold text-gray-800 mt-0.5 truncate">{activeStoreName}</p>
            <button
              onClick={() => setActiveStore(null, null)}
              className="text-xs text-blue-500 hover:underline"
            >
              Switch store
            </button>
          </div>

          <div className="mb-3 px-1">
            <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">Standard method</span>
          </div>

          <nav className="flex flex-col gap-0.5 flex-1">
            {STANDARD_STEPS.map(step => {
              const active = step.n === currentStep
              const done = step.n < maxReachedStep
              const accessible = step.n <= maxReachedStep
              return (
                <button
                  key={step.n}
                  onClick={() => accessible && setStep(step.n)}
                  className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs text-left transition-colors ${
                    active ? 'bg-blue-600 text-white font-semibold' :
                    done ? 'text-gray-600 hover:bg-gray-100 cursor-pointer' :
                    accessible ? 'text-gray-500 hover:bg-gray-100 cursor-pointer' :
                    'text-gray-300 cursor-not-allowed'
                  }`}
                >
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                    active ? 'bg-white text-blue-600' :
                    done ? 'bg-green-500 text-white' :
                    accessible ? 'bg-blue-100 text-blue-700' :
                    'bg-gray-200 text-gray-400'
                  }`}>
                    {done ? '✓' : step.n}
                  </span>
                  <span className="truncate">{step.label}</span>
                </button>
              )
            })}
          </nav>

          <div className="pt-3 border-t mt-3 space-y-1">
            <button
              onClick={handleReloadFromDb}
              disabled={dbReloading}
              className="w-full text-xs px-2.5 py-2 rounded-lg text-left text-blue-600 hover:bg-blue-50 transition flex items-center gap-2 disabled:opacity-50"
            >
              <span>🔄</span> {dbReloading ? 'Loading…' : 'Reload from DB'}
            </button>
            <button
              onClick={() => importRef.current?.click()}
              className="w-full text-xs px-2.5 py-2 rounded-lg text-left text-gray-500 hover:bg-gray-100 transition flex items-center gap-2"
            >
              <span>📂</span> Import JSON
            </button>
            <input ref={importRef} type="file" accept=".json" className="hidden" onChange={handleImportFile} />
          </div>
        </aside>

        {/* Step content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <header className="bg-white border-b px-8 py-3 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-gray-800">
                Step {currentStep}: {STANDARD_STEPS[currentStep - 1]?.label}
              </h2>
              <p className="text-xs text-gray-500">Step {currentStep} of {STANDARD_STEPS.length}</p>
            </div>
            {floorPlanUrl && (
              <span className="text-xs text-green-600 font-medium">● Floor plan loaded</span>
            )}
          </header>
          <div className="flex-1 overflow-auto p-6">
            <StepComponent />
          </div>
        </div>
      </div>
    )
  }

  // ── Method 2 — Calibration Files ────────────────────────────────────────────
  const calibStepIndex = Math.min(Math.max(currentStep, 1), CALIB_STEPS.length) - 1
  const calibStep = CALIB_STEPS[calibStepIndex]

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Wizard sidebar */}
      <aside className="w-56 flex flex-col py-5 px-3 border-r bg-white shrink-0 overflow-y-auto">
        <div className="mb-4 px-1">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Store</p>
          <p className="text-sm font-semibold text-gray-800 mt-0.5 truncate">{activeStoreName}</p>
          <button
            onClick={() => setActiveStore(null, null)}
            className="text-xs text-blue-500 hover:underline"
          >
            Switch store
          </button>
        </div>

        <div className="mb-3 px-1">
          <span className="text-xs bg-indigo-100 text-indigo-600 px-2 py-0.5 rounded">Calibration Files</span>
        </div>

        <nav className="flex flex-col gap-0.5 flex-1">
          {CALIB_STEPS.map(step => {
            const active = step.n === currentStep
            const done = step.n < maxReachedStep
            const accessible = step.n <= maxReachedStep
            return (
              <button
                key={step.n}
                onClick={() => accessible && setStep(step.n)}
                className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs text-left transition-colors ${
                  active ? 'bg-indigo-600 text-white font-semibold' :
                  done ? 'text-gray-600 hover:bg-gray-100 cursor-pointer' :
                  accessible ? 'text-gray-500 hover:bg-gray-100 cursor-pointer' :
                  'text-gray-300 cursor-not-allowed'
                }`}
              >
                <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  active ? 'bg-white text-indigo-600' :
                  done ? 'bg-green-500 text-white' :
                  accessible ? 'bg-indigo-100 text-indigo-700' :
                  'bg-gray-200 text-gray-400'
                }`}>
                  {done ? '✓' : step.n}
                </span>
                <span className="truncate">{step.label}</span>
              </button>
            )
          })}
        </nav>

        <div className="pt-3 border-t mt-3 space-y-1">
          <button
            onClick={handleReloadFromDb}
            disabled={dbReloading}
            className="w-full text-xs px-2.5 py-2 rounded-lg text-left text-blue-600 hover:bg-blue-50 transition flex items-center gap-2 disabled:opacity-50"
          >
            <span>🔄</span> {dbReloading ? 'Loading…' : 'Reload from DB'}
          </button>
          <button
            onClick={() => importRef.current?.click()}
            className="w-full text-xs px-2.5 py-2 rounded-lg text-left text-gray-500 hover:bg-gray-100 transition flex items-center gap-2"
          >
            <span>📂</span> Import JSON
          </button>
          <input ref={importRef} type="file" accept=".json" className="hidden" onChange={handleImportFile} />
        </div>
      </aside>

      {/* Step content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b px-8 py-3 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-800">
              Step {currentStep}: {calibStep?.label}
            </h2>
            <p className="text-xs text-gray-500">Step {currentStep} of {CALIB_STEPS.length}</p>
          </div>
          <span className="text-xs text-indigo-600 font-medium bg-indigo-50 px-2 py-0.5 rounded">Calibration Files method</span>
        </header>
        <div className="flex-1 overflow-auto p-6">
          <CalibStepRenderer
            step={currentStep}
            onBack={() => setStep(Math.max(1, currentStep - 1))}
            onNext={() => setStep(Math.min(CALIB_STEPS.length, currentStep + 1))}
          />
        </div>
      </div>
    </div>
  )
}
