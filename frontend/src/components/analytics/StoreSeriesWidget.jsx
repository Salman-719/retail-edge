import React, { useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import { getStoreSeries } from '../../api'
import { useAnalyticsQuery } from './useAnalyticsQuery'
import WidgetFrame from './WidgetFrame'
import { DataTable } from './widgetParts'
import { toCsv, downloadCsv } from '../../lib/csv'
import { formatDuration, formatNumber } from '../../lib/format'

const METRICS = [
  { key: 'total_visits', label: 'Visits', kind: 'num' },
  { key: 'unique_visitors', label: 'Unique visitors', kind: 'num' },
  { key: 'avg_visit_duration_ms', label: 'Avg duration', kind: 'dur' },
  { key: 'median_visit_duration_ms', label: 'Median duration', kind: 'dur' },
  { key: 'peak_occupancy', label: 'Peak occupancy', kind: 'num' },
  { key: 'dead_period_count', label: 'Dead periods', kind: 'num' },
]

export default function StoreSeriesWidget({ slug, from, to, granularity }) {
  const [view, setView] = useState('line')
  const [metricKey, setMetricKey] = useState('total_visits')
  const { data, loading, error } = useAnalyticsQuery(
    () => getStoreSeries(slug, { from, to, granularity }),
    [slug, from, to, granularity],
  )

  const rows = data?.rows || []
  const metric = METRICS.find((m) => m.key === metricKey)
  const fmt = (v) => (metric.kind === 'dur' ? formatDuration(v) : formatNumber(v))

  function exportCsv() {
    const cols = [{ key: 'bucket_start', label: 'date' }, ...METRICS.map((m) => ({ key: m.key, label: m.label })), { key: 'is_complete', label: 'is_complete' }]
    downloadCsv(`store-series_${from}_${to}.csv`, toCsv(rows, cols))
  }

  const chartData = rows.map((r) => ({ bucket_start: r.bucket_start, value: r[metricKey] }))
  const ChartEl = view === 'bar' ? BarChart : view === 'area' ? AreaChart : LineChart

  return (
    <WidgetFrame
      title="Store Traffic Over Time"
      subtitle={data ? `Grain: ${data.grain}` : undefined}
      views={[{ key: 'line', label: 'Line' }, { key: 'bar', label: 'Bar' }, { key: 'area', label: 'Area' }, { key: 'table', label: 'Table' }]}
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
          rowKey={(r) => r.bucket_start}
          columns={[
            { key: 'bucket_start', label: 'Date' },
            ...METRICS.map((m) => ({ key: m.key, label: m.label, align: 'right', render: (r) => (m.kind === 'dur' ? formatDuration(r[m.key]) : formatNumber(r[m.key])) })),
          ]}
          rows={rows}
        />
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <ChartEl data={chartData} margin={{ top: 4, right: 24, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="bucket_start" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              formatter={(v) => [fmt(v), metric.label]}
            />
            {view === 'bar' && <Bar dataKey="value" fill="#3b82f6" radius={[4, 4, 0, 0]} />}
            {view === 'area' && <Area type="monotone" dataKey="value" stroke="#3b82f6" fill="#bfdbfe" />}
            {view === 'line' && <Line type="monotone" dataKey="value" stroke="#3b82f6" strokeWidth={2} dot={false} />}
          </ChartEl>
        </ResponsiveContainer>
      )}
    </WidgetFrame>
  )
}
