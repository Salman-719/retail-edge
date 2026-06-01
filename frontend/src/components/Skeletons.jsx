import React from 'react'

export function TableSkeleton({ rows = 6, cols = 5 }) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl overflow-hidden shadow-sm">
      {/* fake header */}
      <div className="bg-gray-50 border-b border-gray-200 flex gap-4 px-4 py-3">
        {Array.from({ length: cols }).map((_, i) => (
          <div key={i} className="skeleton h-3 flex-1" style={{ maxWidth: i === 0 ? 120 : undefined }} />
        ))}
      </div>
      {/* fake rows */}
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className={`flex gap-4 px-4 py-3.5 ${r % 2 === 1 ? 'bg-gray-50/50' : ''} border-b border-gray-100 last:border-0`}>
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="skeleton h-3 flex-1" style={{ maxWidth: c === 0 ? 160 : undefined, opacity: c >= 3 ? 0.6 : 1 }} />
          ))}
        </div>
      ))}
    </div>
  )
}

export function CardSkeleton({ count = 3 }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-100 rounded-2xl overflow-hidden shadow-sm">
          <div className="skeleton h-20" style={{ borderRadius: 0 }} />
          <div className="px-5 pt-8 pb-4 space-y-2">
            <div className="skeleton h-4 w-3/4" />
            <div className="skeleton h-3 w-1/2" />
            <div className="skeleton h-3 w-1/3 mt-1" />
          </div>
          <div className="border-t border-gray-100 grid grid-cols-3 divide-x divide-gray-100">
            {[0, 1, 2].map(j => (
              <div key={j} className="py-3 flex flex-col items-center gap-1">
                <div className="skeleton h-4 w-6" />
                <div className="skeleton h-2.5 w-10" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function StatsSkeleton({ count = 4 }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm space-y-2">
          <div className="skeleton h-3 w-20" />
          <div className="skeleton h-7 w-14" />
        </div>
      ))}
    </div>
  )
}

export function FormSkeleton({ rows = 4 }) {
  return (
    <div className="space-y-5 max-w-2xl">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="bg-white border border-gray-100 rounded-xl shadow-sm p-6 space-y-4" style={{ borderTop: '4px solid #e5e7eb' }}>
          <div className="skeleton h-5 w-40" />
          {[0, 1, 2].map(j => (
            <div key={j} className="flex items-center justify-between py-3 border-b border-gray-50 last:border-0">
              <div className="space-y-1.5">
                <div className="skeleton h-3 w-32" />
                <div className="skeleton h-2.5 w-48" />
              </div>
              <div className="skeleton h-8 w-24" />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
