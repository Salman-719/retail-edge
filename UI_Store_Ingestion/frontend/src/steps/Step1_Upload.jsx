import React, { useState, useRef } from 'react'
import useStore from '../store'
import { uploadFloorplan } from '../api'

export default function Step1_Upload() {
  const { setFloorPlan, setStep } = useStore()
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)
  const [info, setInfo] = useState(null)
  const inputRef = useRef()

  const handleFile = async (file) => {
    if (!file) return
    const ext = file.name.split('.').pop().toLowerCase()
    if (!['png', 'jpg', 'jpeg', 'pdf'].includes(ext)) {
      setError('Only PNG, JPG, or PDF files are accepted.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await uploadFloorplan(file)
      setFloorPlan({ floorPlanUrl: data.url, floorPlanWidth: data.width, floorPlanHeight: data.height })
      setInfo({ width: data.width, height: data.height, notice: data.notice })
      setPreview(data.url + '?t=' + Date.now())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    handleFile(file)
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h3 className="text-xl font-semibold mb-2 text-gray-800">Upload Floor Plan</h3>
      <p className="text-gray-500 mb-6 text-sm">Upload a PNG, JPG, or PDF floor plan image. PDFs are automatically converted to PNG.</p>

      <div
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-blue-300 bg-white'}`}
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input ref={inputRef} type="file" accept=".png,.jpg,.jpeg,.pdf" className="hidden" onChange={e => handleFile(e.target.files[0])} />
        <div className="text-5xl mb-4">🗺️</div>
        {loading ? (
          <p className="text-blue-600 font-medium">Uploading and processing...</p>
        ) : (
          <>
            <p className="text-gray-700 font-medium">Drag & drop your floor plan here</p>
            <p className="text-gray-400 text-sm mt-1">or click to browse</p>
            <p className="text-xs text-gray-400 mt-3">Accepted formats: PNG, JPG, PDF</p>
          </>
        )}
      </div>

      {error && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>
      )}

      {info && (
        <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
          {info.notice && <p className="text-yellow-700 text-sm mb-2">⚠️ {info.notice}</p>}
          <p className="text-green-700 text-sm font-medium">✓ Floor plan loaded successfully</p>
          <p className="text-gray-600 text-sm mt-1">Dimensions: {info.width} × {info.height} px</p>
        </div>
      )}

      {preview && (
        <div className="mt-6">
          <p className="text-sm font-medium text-gray-600 mb-2">Preview:</p>
          <img src={preview} alt="Floor plan preview" className="max-w-full max-h-64 border rounded-lg shadow object-contain" />
        </div>
      )}

      <div className="mt-8 flex justify-end">
        <button
          onClick={() => setStep(2)}
          disabled={!info}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-700 transition"
        >
          Next: Set Scale →
        </button>
      </div>
    </div>
  )
}
