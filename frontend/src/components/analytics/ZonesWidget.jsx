import React, { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { getZoneAnalytics } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatDuration, formatNumber } from '../../lib/format'

const METRICS = [
  { key: 'unique_visitors', label: 'Unique visitors', kind: 'num' },
  { key: 'total_transitions', label: 'Transitions', kind: 'num' },
  { key: 'avg_dwell_ms', label: 'Avg dwell', kind: 'dur' },
  { key: 'median_dwell_ms', label: 'Median dwell', kind: 'dur' },
  { key: 'passthrough_count', label: 'Pass-through', kind: 'num' },
  { key: 'engagement_count', label: 'Engagement', kind: 'num' },
]

const COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899', '#84cc16']

export default function ZonesWidget({ slug, from, to, granularity, zoneIds }) {
  const [view, setView] = useState('bar')
  const [metricKey, setMetricKey] = useState('unique_visitors')
  const zoneCsv = zoneIds.length ? zoneIds.join(',') : undefined
  const { data, loading, error } = useAnalyticsQuery(
    () => getZoneAnalytics(slug, { from, to, granularity, zone_ids: zoneCsv }),
    [slug, from, to, granularity, zoneCsv],
  )

  const rows = data?.rows || []
  const metric = METRICS.find((m) => m.key === metricKey)

  // Pivot to one row per bucket, a column per zone, for grouped bars.
  const zoneNames = [...new Set(rows.map((r) => r.zone_name))]
  const byBucket = {}
  for (const r of rows) {
    byBucket[r.bucket_start] ??= { bucket_start: r.bucket_start }
    byBucket[r.bucket_start][r.zone_name] = r[metricKey]
  }
  const pivot = Object.values(byBucket)

  function exportCsv() {
    const cols = [
      { key: 'zone_name', label: 'zone' }, { key: 'bucket_start', label: 'date' },
      ...METRICS.map((m) => ({ key: m.key, label: m.label })),
      { key: 'is_complete', label: 'is_complete' },
    ]
    downloadCsv(`zones_${from}_${to}.csv`, toCsv(rows, cols))
  }

  return (
    <WidgetFrame
      title="Zone Comparison"
      subtitle={data ? `Grain: ${data.grain}` : undefined}
      views={[{ key: 'bar', label: 'Bar' }, { key: 'table', label: 'Table' }]}
      view={view} onView={setView}
      onExport={exportCsv}
      loading={loading} error={error} isEmpty={!rows.length}
      extraControls={
        <select
          value={metricKey} onChange={(e) => setMetricKey(e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1 text-xs text-gray-700"
        >
          {METRICS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </select>
      }
    >
      {view === 'table' ? (
        <DataTable
          rowKey={(r, i) => `${r.zone_id}-${r.bucket_start}-${i}`}
          columns={[
            { key: 'zone_name', label: 'Zone' },
            { key: 'bucket_start', label: 'Date' },
            ...METRICS.map((m) => ({ key: m.key, label: m.label, align: 'right', render: (r) => (m.kind === 'dur' ? formatDuration(r[m.key]) : formatNumber(r[m.key])) })),
          ]}
          rows={rows}
        />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={pivot} margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="bucket_start" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              formatter={(v) => (metric.kind === 'dur' ? formatDuration(v) : formatNumber(v))}
            />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            {zoneNames.map((z, i) => (
              <Bar key={z} dataKey={z} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </WidgetFrame>
  )
}
