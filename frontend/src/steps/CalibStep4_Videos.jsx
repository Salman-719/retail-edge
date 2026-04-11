/**
 * CalibStep4_Videos — Method 2 Step 4
 *
 * Upload one video per camera. Thin wrapper over the Step5_Videos logic
 * but uses onBack / onNext callback props instead of setStep().
 */
import React, { useState, useRef } from 'react'
import useStore from '../store'
import { uploadVideo } from '../api'

function VideoCard({ camera, onUploaded }) {
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef()

  const handleFile = async (file) => {
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      const data = await uploadVideo(camera.id, file)
      onUploaded(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const done = !!camera.videoDuration

  return (
    <div className={`border rounded-xl p-4 bg-white shadow-sm ${done ? 'border-green-300' : 'border-gray-200'}`}>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h4 className="font-semibold text-gray-800">{camera.name}</h4>
          {camera.cameraWorldXYZ ? (
            <p className="text-xs text-gray-400">
              World position: ({camera.cameraWorldXYZ.map(v => v.toFixed(2)).join(', ')}) m
            </p>
          ) : (
            <p className="text-xs text-gray-400">{camera.heightMeters}m height</p>
          )}
        </div>
        {done && <span className="text-xs font-medium text-green-700 bg-green-100 px-2 py-1 rounded-full">✓ Ready</span>}
      </div>

      {done ? (
        <div className="text-sm text-gray-600 bg-gray-50 rounded-lg p-3">
          <p>Duration: {camera.videoDuration}s · FPS: {camera.videoFps} · {camera.videoWidth}×{camera.videoHeight}</p>
          <button onClick={() => inputRef.current?.click()} className="mt-2 text-xs text-blue-600 hover:underline">Replace video</button>
        </div>
      ) : (
        <div
          className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer ${dragging ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-blue-300'}`}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => { e.preventDefault(); setDragging(false); handleFile(e.dataTransfer.files[0]) }}
          onClick={() => inputRef.current?.click()}
        >
          {loading
            ? <p className="text-blue-600 text-sm">Uploading...</p>
            : <>
                <p className="text-gray-500 text-sm">Drop video or click to browse</p>
                <p className="text-xs text-gray-400 mt-1">MP4, AVI, MOV, MKV</p>
              </>
          }
        </div>
      )}

      <input ref={inputRef} type="file" accept=".mp4,.avi,.mov,.mkv" className="hidden"
        onChange={e => handleFile(e.target.files[0])} />
      {error && <p className="text-red-600 text-xs mt-2">{error}</p>}
    </div>
  )
}

export default function CalibStep4_Videos({ onBack, onNext }) {
  const { cameras, updateCamera } = useStore()
  const allDone = cameras.length > 0 && cameras.every(c => c.videoDuration)

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">
      <h2 className="text-xl font-bold text-gray-800 mb-1">Upload Camera Videos</h2>
      <p className="text-gray-500 text-sm mb-6">Upload a video file for each registered camera.</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        {cameras.map(cam => (
          <VideoCard
            key={cam.id}
            camera={cam}
            onUploaded={(data) => updateCamera(cam.id, {
              videoPath: data.videoPath,
              videoDuration: data.duration,
              videoFps: data.fps,
              videoWidth: data.width,
              videoHeight: data.height,
            })}
          />
        ))}
        {cameras.length === 0 && (
          <div className="col-span-2 text-center text-gray-400 text-sm py-10 border-2 border-dashed border-gray-200 rounded-xl">
            No cameras registered.
          </div>
        )}
      </div>

      <div className="flex gap-3">
        <button onClick={onBack} className="flex-1 py-3 rounded-lg border border-gray-300 text-gray-600 text-sm font-medium hover:bg-gray-50">
          ← Back
        </button>
        <button
          onClick={() => onNext && onNext()}
          disabled={!allDone}
          className="flex-1 py-3 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {allDone ? 'Next: Save Configuration →' : `Upload all videos to continue (${cameras.filter(c => c.videoDuration).length}/${cameras.length} done)`}
        </button>
      </div>
    </div>
  )
}
