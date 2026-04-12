/**
 * CalibStep1_CamerasAndFiles — Method 2 Step 1
 *
 * Combines camera registration and XML calibration file upload.
 * For each camera: user provides a name, then uploads intr_*.xml + extr_*.xml.
 * Camera height is NOT asked here — it is derived from the calibration as C[2],
 * where C = -R^T @ t (OpenCV convention).
 * The server parses the files and returns the intrinsic/extrinsic data + warnings.
 * User confirms → data is saved to DB.
 */
import React, { useState, useRef } from 'react'
import useStore from '../store'
import { createCamera, parseCalibrationFiles, saveCalibrationFiles } from '../api'

function CameraCard({ cam, onRemove, onCalibrate }) {
  const [intrFile, setIntrFile] = useState(null)
  const [extrFile, setExtrFile] = useState(null)
  // Default to 0.01 — dataset uses centimetres; multiply by 0.01 to get metres.
  const [scaleFactor, setScaleFactor] = useState(0.01)
  const [parsed, setParsed] = useState(null)
  const [warnings, setWarnings] = useState([])
  const [status, setStatus] = useState('idle')  // idle | parsing | parsed | saving | saved | error
  const [error, setError] = useState(null)
  const intrRef = useRef()
  const extrRef = useRef()

  async function handleParse() {
    if (!intrFile || !extrFile) return
    setStatus('parsing')
    setError(null)
    try {
      const result = await parseCalibrationFiles(cam.id, intrFile, extrFile, scaleFactor)
      setParsed(result)
      setWarnings(result.warnings ?? [])
      setStatus('parsed')
    } catch (e) {
      setError(e.message)
      setStatus('error')
    }
  }

  async function handleConfirm() {
    if (!parsed) return
    setStatus('saving')
    setError(null)
    try {
      await saveCalibrationFiles(cam.id, {
        intrinsic_matrix: parsed.intrinsic_matrix,
        dist_coeffs: parsed.dist_coeffs,
        rotation_matrix: parsed.rotation_matrix,
        translation_vector: parsed.translation_vector,
        image_width: parsed.image_width,
        image_height: parsed.image_height,
      })
      onCalibrate(cam.id, {
        calibrationMethod: 'calibration_files',
        calibrationStatus: 'ok',
        cameraWorldXYZ: parsed.camera_world_xyz,
        // Back-fill height from C[2] (Z component of camera world centre)
        heightMeters: parsed.camera_world_xyz[2],
      })
      setStatus('saved')
    } catch (e) {
      setError(e.message)
      setStatus('error')
    }
  }

  const isSaved = status === 'saved'

  return (
    <div className={`border rounded-xl p-5 bg-white shadow-sm ${isSaved ? 'border-green-400' : 'border-gray-200'}`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <span className="font-semibold text-gray-800">{cam.name}</span>
        </div>
        <div className="flex items-center gap-2">
          {isSaved && (
            <span className="text-green-600 text-sm font-medium flex items-center gap-1">
              <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414L8.414 15l-4.121-4.121a1 1 0 011.414-1.414L8.414 12.172l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
              </svg>
              Calibrated
            </span>
          )}
          {!isSaved && (
            <button onClick={() => onRemove(cam.id)} className="text-gray-400 hover:text-red-500 text-xs">Remove</button>
          )}
        </div>
      </div>

      {!isSaved && (
        <>
          {/* File pickers */}
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Intrinsic XML (intr_*.xml)</label>
              <div
                onClick={() => intrRef.current?.click()}
                className={`border-2 border-dashed rounded-lg p-3 text-center cursor-pointer text-xs transition-colors ${intrFile ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-300 hover:border-blue-300 text-gray-400'}`}
              >
                {intrFile ? intrFile.name : 'Click to select'}
                <input ref={intrRef} type="file" accept=".xml" className="hidden" onChange={e => setIntrFile(e.target.files[0])} />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Extrinsic XML (extr_*.xml)</label>
              <div
                onClick={() => extrRef.current?.click()}
                className={`border-2 border-dashed rounded-lg p-3 text-center cursor-pointer text-xs transition-colors ${extrFile ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-300 hover:border-blue-300 text-gray-400'}`}
              >
                {extrFile ? extrFile.name : 'Click to select'}
                <input ref={extrRef} type="file" accept=".xml" className="hidden" onChange={e => setExtrFile(e.target.files[0])} />
              </div>
            </div>
          </div>

          {/* Scale factor */}
          <div className="flex items-center gap-3 mb-3">
            <label className="text-xs text-gray-600 whitespace-nowrap">tvec unit:</label>
            <select
              value={scaleFactor}
              onChange={e => setScaleFactor(parseFloat(e.target.value))}
              className="text-xs border rounded px-2 py-1 bg-white"
            >
              <option value={0.01}>cm → m (×0.01) — default</option>
              <option value={0.001}>mm → m (×0.001)</option>
              <option value={1.0}>already in metres (×1.0)</option>
            </select>
          </div>

          {/* Parse button */}
          <button
            onClick={handleParse}
            disabled={!intrFile || !extrFile || status === 'parsing'}
            className="w-full py-2 rounded-lg text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed mb-3"
          >
            {status === 'parsing' ? 'Parsing…' : 'Parse Files'}
          </button>

          {/* Parse result */}
          {status === 'parsed' && parsed && (
            <div className="bg-gray-50 rounded-lg p-3 text-xs mb-3">
              <div className="font-medium text-gray-700 mb-2">Parsed successfully</div>
              <div className="grid grid-cols-2 gap-1 text-gray-600">
                <span>Camera centre (world):</span>
                <span className="font-mono">
                  [{parsed.camera_world_xyz.map(v => v.toFixed(3)).join(', ')}] m
                </span>
                <span>Height (C[2]):</span>
                <span className="font-mono">{parsed.camera_world_xyz[2].toFixed(3)} m</span>
                <span>Image size:</span>
                <span className="font-mono">{parsed.image_width} × {parsed.image_height}</span>
                <span>Focal length:</span>
                <span className="font-mono">
                  fx={parsed.intrinsic_matrix[0][0].toFixed(1)}, fy={parsed.intrinsic_matrix[1][1].toFixed(1)}
                </span>
              </div>
              {warnings.length > 0 && (
                <div className="mt-2 space-y-1">
                  {warnings.map((w, i) => (
                    <div key={i} className="flex items-start gap-1 text-amber-700 bg-amber-50 rounded p-2">
                      <span className="shrink-0">⚠</span><span>{w}</span>
                    </div>
                  ))}
                </div>
              )}
              <button
                onClick={handleConfirm}
                disabled={status === 'saving'}
                className="mt-3 w-full py-2 rounded-lg text-sm font-medium bg-green-600 text-white hover:bg-green-700 disabled:opacity-40"
              >
                {status === 'saving' ? 'Saving…' : 'Confirm & Save'}
              </button>
            </div>
          )}

          {/* Error */}
          {status === 'error' && error && (
            <div className="text-red-600 text-xs bg-red-50 rounded p-2">{error}</div>
          )}
        </>
      )}

      {isSaved && parsed && (
        <div className="text-xs text-gray-500 space-y-0.5">
          <div>Centre: ({parsed.camera_world_xyz.map(v => v.toFixed(2)).join(', ')}) m</div>
          <div>Height (C[2]): {parsed.camera_world_xyz[2].toFixed(2)} m</div>
        </div>
      )}
    </div>
  )
}

export default function CalibStep1_CamerasAndFiles({ onNext }) {
  const { cameras, addCamera, removeCamera, updateCamera } = useStore()
  const [showModal, setShowModal] = useState(false)
  // Only ask for name — height is derived from calibration (C[2])
  const [form, setForm] = useState({ name: '' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  async function handleAddCamera() {
    if (!form.name.trim()) return
    setSaving(true)
    setError(null)
    try {
      const cam = await createCamera({
        name: form.name.trim(),
        heightMeters: 0,  // will be overwritten by C[2] after calibration
        position: { x: 0, y: 0 },
      })
      addCamera({
        id: cam.id,
        name: cam.name,
        heightMeters: 0,
        position: { x: 0, y: 0 },
        calibrationMethod: null,
        calibrationStatus: null,
        cameraWorldXYZ: null,
      })
      setForm({ name: '' })
      setShowModal(false)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  function handleCalibrated(camId, patch) {
    updateCamera(camId, patch)
  }

  const allCalibrated = cameras.length > 0 && cameras.every(c => c.calibrationMethod === 'calibration_files')

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">
      <h2 className="text-xl font-bold text-gray-800 mb-1">Camera Setup & Calibration Files</h2>
      <p className="text-gray-500 text-sm mb-6">
        Register each camera and upload its intrinsic + extrinsic XML files.
        Camera height and world position are computed automatically as C&nbsp;=&nbsp;−R<sup>T</sup>·t.
      </p>

      {/* Camera list */}
      <div className="space-y-4 mb-6">
        {cameras.map(cam => (
          <CameraCard
            key={cam.id}
            cam={cam}
            onRemove={id => removeCamera(id)}
            onCalibrate={handleCalibrated}
          />
        ))}
        {cameras.length === 0 && (
          <div className="text-center text-gray-400 text-sm py-10 border-2 border-dashed border-gray-200 rounded-xl">
            No cameras yet. Add your first camera below.
          </div>
        )}
      </div>

      {/* Add camera */}
      <button
        onClick={() => { setShowModal(true); setError(null) }}
        className="w-full py-3 rounded-xl border-2 border-dashed border-blue-300 text-blue-600 hover:bg-blue-50 text-sm font-medium mb-6"
      >
        + Add Camera
      </button>

      {/* Navigation */}
      <button
        disabled={!allCalibrated}
        onClick={() => onNext && onNext()}
        className="w-full py-3 rounded-lg font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {allCalibrated
          ? 'Next: World Map Bounds →'
          : `Calibrate all cameras to continue (${cameras.filter(c => c.calibrationMethod === 'calibration_files').length}/${cameras.length} done)`
        }
      </button>

      {/* Add camera modal — name only, no height */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-xl p-6 w-80">
            <h3 className="font-semibold text-gray-800 mb-4">Add Camera</h3>
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-600 mb-1">Camera Name</label>
              <input
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                onKeyDown={e => e.key === 'Enter' && handleAddCamera()}
                className="w-full border rounded px-3 py-2 text-sm"
                placeholder="e.g. Entrance Camera"
                autoFocus
              />
              <p className="text-xs text-gray-400 mt-1">
                Height is derived automatically from the calibration files (C[2] component).
              </p>
            </div>
            {error && <div className="text-red-600 text-xs mb-3">{error}</div>}
            <div className="flex gap-3">
              <button
                onClick={() => setShowModal(false)}
                className="flex-1 py-2 rounded-lg border text-sm text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                disabled={!form.name.trim() || saving}
                onClick={handleAddCamera}
                className="flex-1 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-40"
              >
                {saving ? 'Adding…' : 'Add'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
