import React, { useEffect, useRef } from 'react'
import useStore from './store'
import { loadProject } from './api'
import Step1_Upload from './steps/Step1_Upload'
import Step2_Scale from './steps/Step2_Scale'
import Step3_Zones from './steps/Step3_Zones'
import Step4_Cameras from './steps/Step4_Cameras'
import Step5_Videos from './steps/Step5_Videos'
import Step6_Correspondence from './steps/Step6_Correspondence'
import Step7_Homography from './steps/Step7_Homography'
import Step8_Save from './steps/Step8_Save'
import Step9_TestMode from './steps/Step9_TestMode'

const STEPS = [
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

const STEP_COMPONENTS = {
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

export default function App() {
  const { currentStep, setStep, maxReachedStep, loadProject: hydrateProject, floorPlanUrl } = useStore()
  const importRef = useRef()

  useEffect(() => {
    loadProject().then(data => {
      if (data) hydrateProject(data)
    }).catch(() => {})
  }, [])

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

  const StepComponent = STEP_COMPONENTS[currentStep]

  return (
    <div className="flex min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside className="w-64 flex flex-col py-6 px-4 shrink-0" style={{ background: '#1B3A5C' }}>
        <div className="mb-6">
          <h1 className="text-xl font-bold text-white">RetailVision AI</h1>
          <p className="text-xs text-blue-200 mt-1">Store Onboarding Tool</p>
        </div>

        <nav className="flex flex-col gap-1 flex-1">
          {STEPS.map(step => {
            const active = step.n === currentStep
            const done = step.n < maxReachedStep
            const accessible = step.n <= maxReachedStep
            return (
              <button
                key={step.n}
                onClick={() => accessible && setStep(step.n)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left transition-colors ${
                  active ? 'bg-blue-600 text-white font-semibold' :
                  done ? 'text-blue-200 hover:bg-blue-900 cursor-pointer' :
                  accessible ? 'text-blue-300 hover:bg-blue-900 cursor-pointer' :
                  'text-gray-400 cursor-not-allowed'
                }`}
              >
                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                  active ? 'bg-white text-blue-600' :
                  done ? 'bg-green-500 text-white' :
                  accessible ? 'bg-blue-500 text-white' :
                  'bg-gray-600 text-gray-300'
                }`}>
                  {done ? '✓' : step.n}
                </span>
                <span className="truncate">{step.label}</span>
              </button>
            )
          })}
        </nav>

        {/* Import project button — accessible from any step */}
        <div className="pt-4 border-t border-blue-900 mt-4">
          <button
            onClick={() => importRef.current?.click()}
            className="w-full text-xs px-3 py-2 rounded-lg text-left transition flex items-center gap-2 text-blue-200 hover:bg-blue-800"
            style={{ background: '#162d47' }}
          >
            <span>📂</span> Import Project
          </button>
          <input
            ref={importRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImportFile}
          />
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b px-8 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-gray-800">
              Step {currentStep}: {STEPS[currentStep - 1].label}
            </h2>
            <p className="text-sm text-gray-500">Step {currentStep} of 9</p>
          </div>
          <div className="text-sm text-gray-400">
            {floorPlanUrl && <span className="text-green-600 font-medium">● Floor plan loaded</span>}
          </div>
        </header>
        <div className="flex-1 overflow-auto p-6">
          <StepComponent />
        </div>
      </main>
    </div>
  )
}
