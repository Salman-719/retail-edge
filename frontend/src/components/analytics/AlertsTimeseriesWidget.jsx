import React, { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { getAlertTimeseries } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatNumber } from '../../lib/format'

// Alert counts are additive (D7) → bucket+stack by type, honoring the shared bar.
const TYPE_COLORS = {
  staff_absence: '#f59e0b',
  queue_buildup: '#3b82f6',
  camera_offline: '#ef4444',
  camera_degraded: '#8b5cf6',
}

export default function AlertsTimeseriesWidget({ slug, from, to, granularity }) {
  const [view, setView] = useState('chart')
  const { data, loading, error } = useAnalyticsQuery(
    () => getAlertTimeseries(slug, { from, to, granularity }),
    [slug, from, to, granularity],
  )
  const rows = data?.rows || []

  // Pivot to one record per bucket, a column per alert type (sum severities).
  const types = [...new Set(rows.map((r) => r.type))]
  const byBucket = {}
  for (const r of rows) {
    byBucket[r.bucket_start] ??= { bucket_start: r.bucket_start }
    byBucket[r.bucket_start][r.type] = (byBucket[r.bucket_start][r.type] || 0) + r.count
  }
  const pivot = Object.values(byBucket)

  function exportCsv() {
    downloadCsv(`alerts-over-time_${from}_${to}.csv`, toCsv(rows, [
      { key: 'bucket_start', label: 'date' },
      { key: 'type', label: 'type' },
      { key: 'severity', label: 'severity' },
      { key: 'count', label: 'count' },
    ]))
  }

  return (
    <WidgetFrame
      title="Alerts Over Time"
      subtitle={data ? `Grain: ${data.grain}` : undefined}
      views={[{ key: 'chart', label: 'Chart' }, { key: 'table', label: 'Table' }]}
      view={view} onView={setView}
      onExport={exportCsv}
      loading={loading} error={error} isEmpty={!rows.length}
    >
      {view === 'table' ? (
        <DataTable
          rowKey={(r, i) => `${r.bucket_start}-${r.type}-${r.severity}-${i}`}
          columns={[
            { key: 'bucket_start', label: 'Date' },
            { key: 'type', label: 'Type' },
            { key: 'severity', label: 'Severity' },
            { key: 'count', label: 'Count', align: 'right', render: (r) => formatNumber(r.count) },
          ]}
          rows={rows}
        />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={pivot} margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="bucket_start" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
            <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
            {types.map((t) => (
              <Bar key={t} dataKey={t} stackId="a" fill={TYPE_COLORS[t] || '#6b7280'} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </WidgetFrame>
  )
}
