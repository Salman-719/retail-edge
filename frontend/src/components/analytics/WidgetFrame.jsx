import React from 'react'
import { Download } from 'lucide-react'

// Uniform widget chrome: title, optional view toggle (chart/table/...), CSV button,
// and the standard loading / error / empty states. Widgets pass their own content.
export default function WidgetFrame({
  title,
  subtitle,
  views,            // [{ key, label }] — omit/<=1 to hide the toggle
  view,
  onView,
  onExport,
  loading,
  error,
  isEmpty,
  emptyLabel = 'No data for this range yet',
  extraControls,
  children,
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <div className="flex items-start justify-between mb-4 gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">{title}</h2>
          {subtitle && <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {extraControls}
          {views && views.length > 1 && (
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              {views.map((v) => (
                <button
                  key={v.key}
                  onClick={() => onView(v.key)}
                  className={`px-2.5 py-1 text-xs transition-colors ${
                    view === v.key
                      ? 'bg-blue-600 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>
          )}
          <button
            onClick={onExport}
            disabled={isEmpty || loading || !!error}
            title="Export CSV"
            className="px-2.5 py-1 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 flex items-center gap-1"
          >
            <Download size={13} /> CSV
          </button>
        </div>
      </div>

      {loading ? (
        <div className="skeleton h-56 w-full rounded-lg" />
      ) : error ? (
        <div className="flex items-center justify-center h-40 text-sm text-red-600 bg-red-50 rounded-lg border border-red-100">
          Failed to load — {error?.response?.data?.detail?.error || error?.message || 'request error'}
        </div>
      ) : isEmpty ? (
        <div className="flex items-center justify-center h-40 text-sm text-gray-400 bg-gray-50 rounded-lg">
          {emptyLabel}
        </div>
      ) : (
        children
      )}
    </div>
  )
}
